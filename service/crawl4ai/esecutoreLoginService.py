"""Esecutore login: orchestra browser, classificazione pagina, form fill e retry."""

import asyncio
import logging
from pathlib import Path

from playwright.async_api import BrowserContext, async_playwright

from model.dto.risultatoLoginDto import LoginResult
from model.enums.statoLoginEnum import LoginStatus
from model.enums.statoPaginaEnum import PageState
from model.po.portalePo import Portale
from service.crawl4ai.browserFactory import BrowserFactory
from service.crawl4ai.classificatoreLoginService import LoginClassifier
from service.crawl4ai.estrattoreSelettoriService import EstrattoreSelettoriService
from service.crawl4ai.formFillerService import FormFillerService
from service.crawl4ai.sessioneLoginService import COOKIES_DIR, SessioneLoginService

logger = logging.getLogger(__name__)

TIMEOUT_NAV = 30_000
TIMEOUT_PORT = 90


class EsecutoreLoginService:

    MAX_RETRY = 2

    def __init__(self, openai_api_key: str, cookies_dir: Path = COOKIES_DIR):
        self._classificatore = LoginClassifier(openai_api_key)
        self._estrattore = EstrattoreSelettoriService(openai_api_key)
        self._cookies_dir = cookies_dir
        self._sessione_service = SessioneLoginService(cookies_dir, logger)

    async def esegui_login(self, portale: Portale) -> LoginResult:
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
            browser, context = await BrowserFactory.create_browser_and_context(p, headless=True)
            try:
                return await self._login_con_retry(portale, context)
            finally:
                await browser.close()

    async def _login_con_retry(self, portale: Portale, context: BrowserContext) -> LoginResult:
        import random

        ultimo_errore = None

        for tentativo in range(1, self.MAX_RETRY + 1):
            try:
                if tentativo > 1:
                    tempo_attesa = random.uniform(2.0, 5.0) * (tentativo - 1)
                    logger.info("[%s] Attesa di %.2f secondi prima del tentativo %d...", portale.url, tempo_attesa, tentativo)
                    await asyncio.sleep(tempo_attesa)

                logger.info("[%s] Avvio tentativo di login %d/%d", portale.url, tentativo, self.MAX_RETRY)
                result = await self._tenta_login(portale, context)
                result.retry_count = tentativo - 1

                if result.is_success:
                    return result

                ultimo_errore = result
                logger.warning("[%s] Tentativo %d non andato a buon fine. Stato: %s", portale.url, tentativo, result.status.value)

            except Exception as exc:
                logger.error("[%s] Errore critico al tentativo %d: %s", portale.url, tentativo, exc)
                ultimo_errore = LoginResult(
                    portal_id=str(portale.numero),
                    url=portale.url,
                    status=LoginStatus.FAILED_ERROR,
                    error_message=str(exc),
                    retry_count=tentativo,
                )

        logger.error("[%s] Tutti i %d tentativi di login sono falliti.", portale.url, self.MAX_RETRY)
        return ultimo_errore

    async def _tenta_login(self, portale: Portale, context: BrowserContext) -> LoginResult:
        import random

        page = await context.new_page()

        try:
            await page.goto(portale.url, timeout=TIMEOUT_NAV, wait_until="load")
        except Exception:
            await page.goto(portale.url, timeout=TIMEOUT_NAV, wait_until="domcontentloaded")

        await asyncio.sleep(random.uniform(1.0, 2.0))

        screenshot = await page.screenshot()
        classificazione = await self._classificatore.classify_bytes(screenshot)

        logger.info(
            "[%s] Stato pagina: %s (confidence=%s, model=%s)",
            portale.url,
            classificazione.state,
            classificazione.confidence,
            classificazione.used_model,
        )

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

        html = await page.content()
        selettori = await self._estrattore.estrai(portale, html)

        if not selettori:
            return LoginResult(portal_id=str(portale.numero), url=portale.url,
                               status=LoginStatus.FAILED_ERROR,
                               error_message="Selettori non trovati nel DOM")

        u_sel = selettori.get("username")
        p_sel = selettori.get("password")
        s_sel = selettori.get("submit")

        try:
            await FormFillerService.fill_and_submit(
                page=page,
                u_sel=u_sel,
                p_sel=p_sel,
                s_sel=s_sel,
                username=portale.username,
                password=portale.password,
                portale_url=portale.url,
            )
        except Exception as e:
            return LoginResult(portal_id=str(portale.numero), url=portale.url,
                               status=LoginStatus.FAILED_ERROR, error_message=f"Errore interazione form: {str(e)}")

        try:
            await page.wait_for_load_state("load", timeout=TIMEOUT_NAV)
            await asyncio.sleep(random.uniform(1.5, 3.0))
        except Exception:
            await page.wait_for_load_state("domcontentloaded", timeout=TIMEOUT_NAV)

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
        return await self._sessione_service.salva_sessione(portale, page, classificazione, selettori)
