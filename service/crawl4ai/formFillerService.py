import asyncio
import logging
import random
from playwright.async_api import Page, Frame, errors  # <--- Aggiunto errors di Playwright

logger = logging.getLogger(__name__)

class FormFillerService:
    @staticmethod
    async def fill_and_submit(
        page: Page, 
        u_sel: str, 
        p_sel: str, 
        s_sel: str, 
        username: str, 
        password: str, 
        portale_url: str
    ) -> bool:
        # Ricerca nei frame
        target_context = page
        is_iframe = False

        # --- OTTIMIZZAZIONE TIMEOUT: Alzato a 5000ms per dare tempo agli iFrame lenti ---
        try:
            if u_sel:
                await page.wait_for_selector(u_sel, state="visible", timeout=5000)
        except Exception:
            logger.info("[%s] Selettore non visibile sulla pagina principale, cerco negli iFrame...", portale_url)
            for frame in page.frames:
                if frame != page:
                    try:
                        if u_sel and await frame.locator(u_sel).count() > 0:
                            target_context = frame
                            is_iframe = True
                            logger.info("[%s] 🎯 Form di login individuato all'interno dell'iFrame: %s", portale_url, frame.name or frame.url)
                            break
                    except Exception:
                        continue

        try:
            # --- 1. Gestione Username & Fallback Robustezza ---
            try:
                username_input = target_context.locator(u_sel).first
                await username_input.wait_for(state="visible", timeout=6000) # Alzato da 5000
                await username_input.click()
            except Exception:
                logger.warning("[%s] Selettore username primario fallito o mutato. Avvio fallback generico...", portale_url)
                username_input = target_context.locator("input[type='text'], input[type='email'], input[name*='user'], input[name*='login']").first
                await username_input.wait_for(state="visible", timeout=6000) # Alzato da 4000
                await username_input.click()

            await username_input.fill("")
            await username_input.press_sequentially(username, delay=random.randint(40, 120))
            await asyncio.sleep(random.uniform(0.4, 0.9))

            # --- 2. Gestione Password & Fallback Robustezza ---
            try:
                password_input = target_context.locator(p_sel).first
                await password_input.wait_for(state="visible", timeout=6000) # Alzato da 4000
                await password_input.click()
            except Exception:
                logger.warning("[%s] Selettore password primario fallito. Avvio fallback generico...", portale_url)
                password_input = target_context.locator("input[type='password'], input[name*='pass']").first
                await password_input.wait_for(state="visible", timeout=6000) # Alzato da 4000
                await password_input.click()

            await password_input.fill("")
            await password_input.press_sequentially(password, delay=random.randint(40, 120))
            await asyncio.sleep(random.uniform(0.6, 1.3))

            # --- 3. Gestione Submit / Invio Form robusto ---
            submit_button = await FormFillerService._trova_submit(target_context, s_sel)
            try:
                await submit_button.wait_for(state="visible", timeout=5000) # Alzato da 4000
                await submit_button.click()
                # Aspettiamo un attimo che la navigazione inizi prima di ritornare True
                await page.wait_for_timeout(1500)
            except Exception:
                logger.warning("[%s] Click standard sul submit fallito. Tento click forzato o via JS...", portale_url)
                try:
                    await submit_button.click(force=True)
                    await page.wait_for_timeout(1500)
                except Exception:
                    # Protezione contro il TargetClosedError inserendo un try-except specifico di Playwright
                    try:
                        logger.info("[%s] Tento l'invio disperato tramite tasto INVIO sulla password...", portale_url)
                        await password_input.press("Enter")
                        # Diamo tempo al browser di processare l'invio prima che il chiamante distrugga la pagina
                        await page.wait_for_timeout(2000)
                    except errors.TargetClosedError:
                        logger.warning("[%s] Il browser si è chiuso anticipatamente durante la pressione di Enter, ma proseguiamo.", portale_url)
                    except Exception as press_ex:
                        logger.warning("[%s] Errore generico sulla pressione di Enter: %s", portale_url, press_ex)
            
            return True
            
        except Exception as e:
            logger.error("[%s] Errore critico durante l'interazione con i campi (iFrame=%s): %s", portale_url, is_iframe, e)
            raise e

    @staticmethod
    async def _trova_submit(target_context, s_sel):
        login_keywords = ["accedi", "login", "sign in", "entra", "accesso", "invia", "conferma"]

        if not s_sel:
            return target_context.locator("button[type='submit'], input[type='submit'], button:has-text('Accedi')").first

        locator_tutti = target_context.locator(s_sel)
        try:
            count = await locator_tutti.count()
        except Exception:
            count = 0

        if count <= 1:
            return locator_tutti.first

        for keyword in login_keywords:
            candidato = target_context.locator(s_sel).filter(has_text=keyword)
            try:
                if await candidato.count() == 1:
                    logger.info("Submit disambiguato per testo '%s'", keyword)
                    return candidato.first
            except Exception:
                continue

        logger.warning("Impossibile disambiguare il submit con %d elementi — uso .first", count)
        return locator_tutti.first