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
TIMEOUT_NAV  = 30_000
TIMEOUT_PORT = 90


class EsecutoreLoginService:

    MAX_RETRY = 2

    def __init__(self, openai_api_key: str, cookies_dir: Path = COOKIES_DIR):
        self._classificatore = LoginClassifier(openai_api_key)
        self._estrattore     = EstrattoreSelettoriService(openai_api_key)
        self._cookies_dir    = cookies_dir
        self._cookies_dir.mkdir(exist_ok=True)

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
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-sandbox"
                ]
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="it-IT",
                timezone_id="Europe/Rome",
                accept_downloads=True
            )
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)
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

        html = await page.content()
        selettori = await self._estrattore.estrai(portale, html)

        if not selettori:
            return LoginResult(portal_id=str(portale.numero), url=portale.url,
                               status=LoginStatus.FAILED_ERROR,
                               error_message="Selettori non trovati nel DOM")

        # FIX ALLINEAMENTO CHIAVI: allineati con il nuovo prompt dei selettori
        u_sel = selettori.get("username")
        p_sel = selettori.get("password")
        s_sel = selettori.get("submit")

        # Ricerca nei frame
        target_context = page
        is_iframe = False

        try:
            if u_sel:
                await page.wait_for_selector(u_sel, state="visible", timeout=3000)
        except Exception:
            logger.info("[%s] Selettore non visibile sulla pagina principale, cerco negli iFrame...", portale.url)
            for frame in page.frames:
                if frame != page:
                    try:
                        if u_sel and await frame.locator(u_sel).count() > 0:
                            target_context = frame
                            is_iframe = True
                            logger.info("[%s] 🎯 Form di login individuato all'interno dell'iFrame: %s", portale.url, frame.name or frame.url)
                            break
                    except Exception:
                        continue

        try:
            # --- 1. Gestione Username & Fallback Robustezza ---
            try:
                username_input = target_context.locator(u_sel).first
                await username_input.wait_for(state="visible", timeout=5000)
                await username_input.click()
            except Exception:
                logger.warning("[%s] Selettore username primario fallito o mutato. Avvio fallback generico...", portale.url)
                username_input = target_context.locator("input[type='text'], input[type='email'], input[name*='user'], input[name*='login']").first
                await username_input.wait_for(state="visible", timeout=4000)
                await username_input.click()

            await username_input.fill("")
            await username_input.press_sequentially(portale.username, delay=random.randint(40, 120))
            await asyncio.sleep(random.uniform(0.4, 0.9))

            # --- 2. Gestione Password & Fallback Robustezza ---
            try:
                password_input = target_context.locator(p_sel).first
                await password_input.wait_for(state="visible", timeout=4000)
                await password_input.click()
            except Exception:
                logger.warning("[%s] Selettore password primario fallito. Avvio fallback generico...", portale.url)
                password_input = target_context.locator("input[type='password'], input[name*='pass']").first
                await password_input.wait_for(state="visible", timeout=4000)
                await password_input.click()

            await password_input.fill("")
            await password_input.press_sequentially(portale.password, delay=random.randint(40, 120))
            await asyncio.sleep(random.uniform(0.6, 1.3))

            # --- 3. Gestione Submit / Invio Form robusto ---
            submit_button = await self._trova_submit(target_context, s_sel)
            try:
                await submit_button.wait_for(state="visible", timeout=4000)
                await submit_button.click()
            except Exception:
                logger.warning("[%s] Click standard sul submit fallito. Tento click forzato o via JS...", portale.url)
                try:
                    await submit_button.click(force=True)
                except Exception:
                    # Se anche il forzato fallisce, cerchiamo un pulsante col testo o inviamo via Enter
                    await password_input.press("Enter")

        except Exception as e:
            logger.error("[%s] Errore durante l'interazione con i campi (iFrame=%s): %s", portale.url, is_iframe, e)
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
                               status=LoginStatus.FAILED_CAPTCHA, page_state=classificazione.state)

        return LoginResult(portal_id=str(portale.numero), url=portale.url,
                           status=LoginStatus.FAILED_ERROR, page_state=stato_post.state,
                           error_message=f"Stato post-submit ambiguo: {stato_post.state}")

    async def _trova_submit(self, target_context, s_sel):
        # Parole chiave che identificano un bottone di login (in ordine di priorità)
        login_keywords = ["accedi", "login", "sign in", "entra", "accesso", "invia", "conferma"]

        if not s_sel:
            # Fallback immediato se l'LLM non ha estratto un selettore valido per il submit
            return target_context.locator("button[type='submit'], input[type='submit'], button:has-text('Accedi')").first

        locator_tutti = target_context.locator(s_sel)
        try:
            count = await locator_tutti.count()
        except Exception:
            count = 0

        if count <= 1:
            return locator_tutti.first

        # Prova a trovare il bottone giusto filtrando per testo
        for keyword in login_keywords:
            candidato = target_context.locator(s_sel).filter(has_text=keyword)
            try:
                if await candidato.count() == 1:
                    logger.info("Submit disambiguato per testo '%s'", keyword)
                    return candidato.first
            except Exception:
                continue

        # Fallback se non si riesce a disambiguare
        logger.warning("Impossibile disambiguare il submit con %d elementi — uso .first", count)
        return locator_tutti.first

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