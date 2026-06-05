"""
service/crawl4ai/esecutoreLoginService.py
"""

import asyncio
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

COOKIES_DIR  = Path("sessioni")
TIMEOUT_NAV  = 30_000   # navigazione pagina
TIMEOUT_PORT = 90       # timeout globale per portale (secondi)


class EsecutoreLoginService:

    MAX_RETRY = 2

    def __init__(self, openai_api_key: str, cookies_dir: Path = COOKIES_DIR):
        self._classificatore = LoginClassifier(openai_api_key)
        self._estrattore     = EstrattoreSelettoriService(openai_api_key)
        self._cookies_dir    = cookies_dir
        self._cookies_dir.mkdir(exist_ok=True)

    async def esegui_login(self, portale: Portale) -> LoginResult:
        # Livello 0: cookie reuse
        if portale.has_valid_session and portale.cookies_path:
            logger.info("[%s] Sessione cookie valida — skip login", portale.url)
            return LoginResult(
                portal_id=str(portale.numero), url=portale.url,
                status=LoginStatus.SKIPPED_COOKIE,
                session_valid=True, cookies_path=portale.cookies_path,
            )

        if portale.needs_manual_intervention:
            logger.warning("[%s] Richiede intervento manuale", portale.url)
            return LoginResult(
                portal_id=str(portale.numero), url=portale.url,
                status=LoginStatus.FAILED_MANUAL,
                error_message=f"login_type={portale.login_type} mfa={portale.mfa_type}",
            )

        try:
            return await asyncio.wait_for(
                self._login_con_browser(portale),
                timeout=TIMEOUT_PORT,
            )
        except asyncio.TimeoutError:
            logger.error("[%s] Timeout globale %ds — portale saltato", portale.url, TIMEOUT_PORT)
            return LoginResult(
                portal_id=str(portale.numero), url=portale.url,
                status=LoginStatus.FAILED_ERROR,
                error_message=f"Timeout globale {TIMEOUT_PORT}s",
            )

    async def _login_con_browser(self, portale: Portale) -> LoginResult:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            try:
                return await self._login_con_retry(portale, context)
            finally:
                await browser.close()

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
                    portal_id=str(portale.numero), url=portale.url,
                    status=LoginStatus.FAILED_ERROR,
                    error_message=str(exc), retry_count=tentativo,
                )
        return ultimo_errore

    async def _tenta_login(self, portale: Portale, context: BrowserContext) -> LoginResult:
        page = await context.new_page()

        await page.goto(portale.url, timeout=TIMEOUT_NAV, wait_until="domcontentloaded")

        screenshot = await page.screenshot()
        classificazione = await self._classificatore.classify_bytes(screenshot)

        logger.info("[%s] Stato pagina: %s (confidence=%s, model=%s)",
                    portale.url, classificazione.state, classificazione.confidence, classificazione.used_model)

        if classificazione.state == PageState.LOGGED_IN:
            return await self._salva_sessione(portale, page, classificazione)

        if classificazione.state == PageState.CAPTCHA_PRESENT:
            portale.captcha_type = "unknown"
            return LoginResult(portal_id=str(portale.numero), url=portale.url,
                               status=LoginStatus.FAILED_CAPTCHA, page_state=classificazione.state)

        if classificazione.state == PageState.OAUTH_SSO:
            portale.login_type = "oauth"
            portale.requires_manual = True
            return LoginResult(portal_id=str(portale.numero), url=portale.url,
                               status=LoginStatus.FAILED_MANUAL, page_state=classificazione.state)

        # Estrai selettori
        html = await page.content()
        selettori = await self._estrattore.estrai(portale, html)

        if not selettori:
            return LoginResult(portal_id=str(portale.numero), url=portale.url,
                               status=LoginStatus.FAILED_ERROR,
                               error_message="Selettori non trovati nel DOM")

        # Prima di fill, aspetta che il campo sia visibile
        await page.wait_for_selector(selettori["username_selector"], state="visible", timeout=10_000)
        await page.fill(selettori["username_selector"], portale.username, timeout=10_000)
        
        # Compila form con timeout espliciti su ogni azione
        await page.fill(selettori["username_selector"], portale.username, timeout=10_000)
        await page.fill(selettori["password_selector"], portale.password, timeout=10_000)
        await page.click(selettori["submit_selector"], timeout=10_000)
        await page.wait_for_load_state("domcontentloaded", timeout=TIMEOUT_NAV)

        # Classifica post-submit
        screenshot_post = await page.screenshot()
        stato_post = await self._classificatore.classify_bytes(screenshot_post)

        logger.info("[%s] Stato post-submit: %s", portale.url, stato_post.state)

        if stato_post.state == PageState.LOGGED_IN:
            return await self._salva_sessione(portale, page, stato_post, selettori)

        if stato_post.state == PageState.MFA_OTP:
            portale.mfa_type = "unknown"
            return LoginResult(portal_id=str(portale.numero), url=portale.url,
                               status=LoginStatus.FAILED_MFA, mfa_triggered=True,
                               page_state=stato_post.state)

        if stato_post.state == PageState.ERROR_PAGE:
            return LoginResult(portal_id=str(portale.numero), url=portale.url,
                               status=LoginStatus.FAILED_CREDS, page_state=stato_post.state)

        if stato_post.state == PageState.CAPTCHA_PRESENT:
            return LoginResult(portal_id=str(portale.numero), url=portale.url,
                               status=LoginStatus.FAILED_CAPTCHA, page_state=stato_post.state)

        return LoginResult(portal_id=str(portale.numero), url=portale.url,
                           status=LoginStatus.FAILED_ERROR, page_state=stato_post.state,
                           error_message=f"Stato post-submit ambiguo: {stato_post.state}")

    async def _salva_sessione(self, portale, page, classificazione, selettori=None) -> LoginResult:
        cookies = await page.context.cookies()
        path = self._cookies_dir / f"{portale.numero}_{portale.cliente}.json"
        path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
        portale.cookies_path  = str(path)
        portale.last_login_ok = datetime.now(timezone.utc)
        if selettori:
            portale.selectors_cached = selettori
        logger.info("[%s] Login OK — cookie salvati in %s", portale.url, path)
        return LoginResult(
            portal_id=str(portale.numero), url=portale.url,
            status=LoginStatus.SUCCESS, session_valid=True,
            cookies_path=str(path), page_state=classificazione.state,
            vision_model=classificazione.used_model, selectors_used=selettori,
        )