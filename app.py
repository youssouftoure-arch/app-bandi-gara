import asyncio
from crawl4ai import AsyncWebCrawler

async def main():
    #creazione dell'istanza del crawler (scraper)
    async with AsyncWebCrawler() as crawler:

        risultato= await crawler.arun(url="https://www.acquistinretepa.it/opencms/opencms/vetrina_bandi.html?filter=AB")

        print(risultato.markdown)


asyncio.run(main())