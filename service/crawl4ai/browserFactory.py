import logging
from playwright.async_api import Playwright, BrowserContext

logger = logging.getLogger(__name__)

class BrowserFactory:
    @staticmethod
    async def create_browser_and_context(
        p: Playwright, 
        headless: bool = True, 
        viewport: dict = None, 
        user_agent: str = None
    ) -> tuple[any, BrowserContext]:
        logger.info("Avvio browser Chromium...")
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox"
            ]
        )
        
        vp = viewport or {"width": 1920, "height": 1080}
        ua = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        
        context = await browser.new_context(
            viewport=vp,
            user_agent=ua,
            locale="it-IT",
            timezone_id="Europe/Rome",
            accept_downloads=True
        )
        
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)
        
        return browser, context
