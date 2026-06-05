"""
service/crawl4ai/esecutoreLoginService.py
-----------------------------------------
Playwright + compilazione form + gestione stati post-submit + cookie manager
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, Page, BrowserContext

from model.dto.risultatoLoginDto import LoginResult
from model.enums.statoLoginEnum import LoginStatus
from model.enums.statoPaginaEnum import PageState
from model.po.portalePo import Portale
from service.crawl4ai.classificatoreLoginService import LoginClassifier 
from service.crawl4ai.estrattoreSelettoriService import EstrattoreSelettoriService

logger = logging.getLogger(__name__)

COOKIES_DIR = Path("sessioni")


class EsecutoreLoginService:

    TIMEOUT_MS    = 15_000
    MAX_RETRY     = 2

    def __init__(self, openai_api_key: str, cookies_dir: Path = COOKIES_DIR):
        self._classificatore = LoginClassifier(openai_api_key)
        self._estrattore     = EstrattoreSelettoriService(openai_api_key)
        self._cookies_dir    = cookies_dir
        self._cookies_dir.mkdir(exist_ok=True)

    async def esegui_login(self, portale: Portale) -> LoginResult:
        """Entry point principale. Gestisce cookie reuse e login fresco."""

        # ── Livello 0: cookie reuse ──────────────────────────────────────
        if portale.has_valid_session and portale.cookies_path:
            logger.info("[%s] Sessione cookie valida — skip login", portale.url)
            return LoginResult(
                portal_id=str(portale.numero),
                url=portale.url,
                status=LoginStatus.SKIPPED_COOKIE,
                session_valid=True,
                cookies_path=portale.cookies_path,
            )

        # ── Portali che richiedono intervento manuale ────────────────────
        if portale.needs_manual_intervention:
            logger.warning("[%s] Richiede intervento manuale", portale.url)
            return LoginResult(
                portal_id=str(portale.numero),
                url=portale.url,
                status=LoginStatus.FAILED_MANUAL,
                error_message=f"login_type={portale.login_type} mfa={portale.mfa_type} captcha={portale.captcha_type}",
            )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            try:
                result = await self._login_con_retry(portale, context)
            finally:
                await browser.close()

        return result

    # ------------------------------------------------------------------

    async def _login_con_retry(self, portale: Portale, context: BrowserContext) -> LoginResult:
        ultimo_errore = None
        for tentativo in range(1, self.MAX_RETRY + 1):
            try:
                result = await self._tenta_login(portale, context)
                result.retry_count = tentativo - 1
                if result.is_success:
                    return result
                ultimo_errore = result
            except Exception as exc:
                logger.error("[%s] Tentativo %d fallito: %s", portale.url, tentativo, exc)
                ultimo_errore = LoginResult(
                    portal_id=str(portale.numero),
                    url=portale.url,
                    status=LoginStatus.FAILED_ERROR,
                    error_message=str(exc),
                    retry_count=tentativo,
                )
        return ultimo_errore

    async def _tenta_login(self, portale: Portale, context: BrowserContext) -> LoginResult:
        page = await context.new_page()

        # 1. Naviga alla pagina di login
        await page.goto(portale.url, timeout=self.TIMEOUT_MS)
        await page.wait_for_load_state("domcontentloaded")

        # 2. Screenshot + classificazione vision
        screenshot = await page.screenshot()
        classificazione = await self._classificatore.classify_bytes(screenshot)

        logger.info("[%s] Stato pagina: %s (confidence=%s, model=%s)",
                    portale.url, classificazione.state, classificazione.confidence, classificazione.used_model)

        # 3. Gestione stati non-standard
        if classificazione.state == PageState.LOGGED_IN:
            return await self._salva_sessione(portale, page, classificazione)

        if classificazione.state == PageState.CAPTCHA_PRESENT:
            portale.captcha_type = "unknown"
            return LoginResult(
                portal_id=str(portale.numero), url=portale.url,
                status=LoginStatus.FAILED_CAPTCHA,
                page_state=classificazione.state,
                vision_model=classificazione.used_model,
                vision_notes=classificazione.notes,
            )

        if classificazione.state == PageState.OAUTH_SSO:
            portale.login_type = "oauth"
            portale.requires_manual = True
            return LoginResult(
                portal_id=str(portale.numero), url=portale.url,
                status=LoginStatus.FAILED_MANUAL,
                page_state=classificazione.state,
                error_message="OAuth/SSO rilevato — richiede intervento manuale",
            )

        if classificazione.state not in (PageState.STANDARD_FORM, PageState.UNKNOWN):
            return LoginResult(
                portal_id=str(portale.numero), url=portale.url,
                status=LoginStatus.FAILED_ERROR,
                page_state=classificazione.state,
                error_message=f"Stato inatteso: {classificazione.state}",
            )

        # 4. Estrai selettori dal DOM
        html = await page.content()
        selettori = await self._estrattore.estrai(portale, html)

        if not selettori:
            return LoginResult(
                portal_id=str(portale.numero), url=portale.url,
                status=LoginStatus.FAILED_ERROR,
                error_message="Selettori non trovati nel DOM",
            )

        # 5. Compila e invia il form
        await page.fill(selettori["username_selector"], portale.username)
        await page.fill(selettori["password_selector"], portale.password)
        await page.click(selettori["submit_selector"])
        await page.wait_for_load_state("domcontentloaded", timeout=self.TIMEOUT_MS)

        # 6. Classifica lo stato post-submit
        screenshot_post = await page.screenshot()
        stato_post = await self._classificatore.classify_bytes(screenshot_post)

        logger.info("[%s] Stato post-submit: %s", portale.url, stato_post.state)

        if stato_post.state == PageState.LOGGED_IN:
            return await self._salva_sessione(portale, page, stato_post, selettori)

        if stato_post.state == PageState.MFA_OTP:
            portale.mfa_type = "unknown"
            # Hook MFA — gestito da MFAHandler (prossimo step)
            return LoginResult(
                portal_id=str(portale.numero), url=portale.url,
                status=LoginStatus.FAILED_MFA,
                page_state=stato_post.state,
                mfa_triggered=True,
                vision_model=stato_post.used_model,
            )

        if stato_post.state == PageState.ERROR_PAGE:
            return LoginResult(
                portal_id=str(portale.numero), url=portale.url,
                status=LoginStatus.FAILED_CREDS,
                page_state=stato_post.state,
                vision_notes=stato_post.notes,
            )

        if stato_post.state == PageState.CAPTCHA_PRESENT:
            return LoginResult(
                portal_id=str(portale.numero), url=portale.url,
                status=LoginStatus.FAILED_CAPTCHA,
                page_state=stato_post.state,
            )

        # Stato ambiguo — trattalo come errore
        return LoginResult(
            portal_id=str(portale.numero), url=portale.url,
            status=LoginStatus.FAILED_ERROR,
            page_state=stato_post.state,
            error_message=f"Stato post-submit ambiguo: {stato_post.state}",
        )

    async def _salva_sessione(self, portale: Portale, page: Page, classificazione, selettori=None) -> LoginResult:
        """Serializza i cookie e aggiorna il portale."""
        cookies = await page.context.cookies()
        path = self._cookies_dir / f"{portale.numero}_{portale.cliente}.json"
        path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))

        portale.cookies_path  = str(path)
        portale.last_login_ok = datetime.now(timezone.utc)
        if selettori:
            portale.selectors_cached = selettori

        logger.info("[%s] Login OK — cookie salvati in %s", portale.url, path)

        return LoginResult(
            portal_id=str(portale.numero),
            url=portale.url,
            status=LoginStatus.SUCCESS,
            session_valid=True,
            cookies_path=str(path),
            page_state=classificazione.state,
            vision_model=classificazione.used_model,
            selectors_used=selettori,
        )
