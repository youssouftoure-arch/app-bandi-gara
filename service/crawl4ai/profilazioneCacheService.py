"""Cache profilazione: persiste su JSON URL sezione bandi e selettori CSS."""

import json
import logging
import os


class ProfilazioneCacheService:
    def __init__(self, cache_file_path: str, logger: logging.Logger = None):
        self.cache_file_path = cache_file_path
        self._logger = logger or logging.getLogger(__name__)

    def carica(self) -> dict:
        """Legge la cache delle profilazioni da file JSON."""
        if not os.path.exists(self.cache_file_path) or os.path.getsize(self.cache_file_path) == 0:
            return {}

        try:
            with open(self.cache_file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self._logger.warning("Impossibile leggere il file di cache JSON: %s", e)
            return {}

    def salva(self, cache_data: dict):
        """Salva la cache delle profilazioni su file JSON."""
        try:
            os.makedirs(os.path.dirname(self.cache_file_path), exist_ok=True)
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self._logger.error("Impossibile scrivere il file di cache JSON: %s", e)
