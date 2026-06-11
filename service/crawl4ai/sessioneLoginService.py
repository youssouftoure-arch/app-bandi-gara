"""Sessione login: salva cookie Playwright e aggiorna metadati sessione del portale."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from model.dto.risultatoLoginDto import LoginResult
from model.enums.statoLoginEnum import LoginStatus


COOKIES_DIR = Path("sessioni")


class SessioneLoginService:
    def __init__(self, cookies_dir: Path = COOKIES_DIR, logger: logging.Logger = None):
        self._cookies_dir = cookies_dir
        self._logger = logger or logging.getLogger(__name__)
        self._cookies_dir.mkdir(exist_ok=True)

    async def salva_sessione(self, portale, page, classificazione, selettori=None) -> LoginResult:
        cookies = await page.context.cookies()
        path = self._cookies_dir / f"{portale.numero}_{portale.cliente}.json"
        path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
        portale.cookies_path = str(path)
        portale.last_login_ok = datetime.now(timezone.utc)
        if selettori:
            portale.selectors_cached = selettori
        self._logger.info("[%s] Login OK — cookie salvati in %s", portale.url, path)
        return LoginResult(
            portal_id=str(portale.numero),
            url=portale.url,
            status=LoginStatus.SUCCESS,
            session_valid=True,
            cookies_path=str(path),
            page_state=classificazione.state,
            vision_model=classificazione.used_model,
            selectors_used=selettori,
        )
