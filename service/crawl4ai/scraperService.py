import asyncio
from crawl4ai import AsyncWebCrawler



class scraper:
    def __init__(self):
        pass

    async def main():
        #creazione dell'istanza del crawler (scraper)
        async with AsyncWebCrawler() as crawler:

            risultato= await crawler.arun(url="https://www.acquistinretepa.it/opencms/opencms/vetrina_bandi.html?filter=AB")

            return risultato.markdown