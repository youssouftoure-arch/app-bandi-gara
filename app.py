import asyncio
from service.crawl4ai.scraperService import scraper


asyncio.run(scraper().main())