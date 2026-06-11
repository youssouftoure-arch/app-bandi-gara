"""Configurazione scraper: costanti, dotenv e setup logging condiviso."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv


LOG_FILE_PATH = "scraper_activity.log"
CACHE_FILE_PATH = os.path.join("config", "profiler_cache.json")
EXCEL_PATH = Path("user e password per Operations.xlsx")
CONCORRENZA = 3


def configura_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        logger.addHandler(console_handler)

        file_handler = logging.FileHandler(LOG_FILE_PATH, mode="a", encoding="utf-8")
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)


load_dotenv()

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
