"""Classificatore login: invia screenshot all'LLM vision e applica fallback premium."""

import base64
import logging
from pathlib import Path

from openai import AsyncOpenAI

from model.dto.classificazioneLoginDto import ClassificationResult
from model.enums.confidenzaEnum import Confidence
from model.enums.statoPaginaEnum import PageState
from promptDiSistema.classificatoreLogin import SYSTEM_PROMPT
from service.crawl4ai.classificazioneLoginParser import parse_classification_response

logger = logging.getLogger(__name__)


class LoginClassifier:
    """
    Classifica lo stato di una pagina tramite screenshot + vision LLM.
    """

    MODEL_PRIMARY = "gpt-4o-mini"
    MODEL_FALLBACK = "gpt-4o"

    def __init__(self, api_key: str):
        self._client = AsyncOpenAI(api_key=api_key)

    async def classify(self, screenshot_path: str | Path, *, force_premium: bool = False) -> ClassificationResult:
        """Classifica la pagina a partire da uno screenshot su disco."""
        screenshot_b64 = self._encode_image(screenshot_path)
        return await self._classify_b64(screenshot_b64, force_premium=force_premium)

    async def classify_bytes(self, screenshot_bytes: bytes, *, force_premium: bool = False) -> ClassificationResult:
        """Come classify(), ma accetta i bytes dello screenshot direttamente."""
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        return await self._classify_b64(screenshot_b64, force_premium=force_premium)

    async def _classify_b64(self, screenshot_b64: str, *, force_premium: bool = False) -> ClassificationResult:
        model = self.MODEL_FALLBACK if force_premium else self.MODEL_PRIMARY
        result = await self._call_vision(screenshot_b64, model)

        if not force_premium and result.confidence == Confidence.LOW:
            logger.info(
                "Confidence LOW con %s — fallback a %s",
                self.MODEL_PRIMARY,
                self.MODEL_FALLBACK,
            )
            result = await self._call_vision(screenshot_b64, self.MODEL_FALLBACK)

        return result

    async def _call_vision(self, screenshot_b64: str, model: str) -> ClassificationResult:
        """Esegue la chiamata OpenAI vision e parsa il JSON."""
        try:
            response = await self._client.chat.completions.create(
                model=model,
                max_tokens=256,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_b64}",
                                    "detail": "low",
                                },
                            },
                            {
                                "type": "text",
                                "text": "Classifica questa pagina secondo le istruzioni.",
                            },
                        ],
                    },
                ],
            )

            raw_text = response.choices[0].message.content or ""
            return self._parse_response(raw_text, model)

        except Exception as exc:
            logger.error("Errore chiamata vision [%s]: %s", model, exc)
            return ClassificationResult(
                state=PageState.UNKNOWN,
                confidence=Confidence.LOW,
                notes=f"Errore API: {exc}",
                used_model=model,
                raw_json={},
            )

    def _parse_response(self, raw_text: str, model: str) -> ClassificationResult:
        return parse_classification_response(raw_text, model, logger)

    @staticmethod
    def _encode_image(path: str | Path) -> str:
        """Legge un'immagine da disco e la converte in base64."""
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
