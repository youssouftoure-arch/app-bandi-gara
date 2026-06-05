"""
LoginClassifier
---------------
Usa GPT-4o-mini (vision) per classificare lo stato di una pagina web.
Fallback automatico a GPT-4o se confidence == LOW o errore.

Stati riconosciuti:
    - standard_form   : form login classico (username + password)
    - oauth_sso       : pulsanti OAuth / SAML / "Accedi con..."
    - captcha_present : CAPTCHA visibile (reCAPTCHA, Turnstile, immagini)
    - mfa_otp         : schermata OTP / codice di verifica
    - logged_in       : utente già autenticato, dashboard visibile
    - error_page      : errore credenziali o pagina di errore
    - unknown         : nessuna categoria riconosciuta con certezza
"""

import base64
import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from openai import AsyncOpenAI

from model.dto.classificazioneLoginDto import ClassificationResult
from model.enums.confidenzaEnum import Confidence
from model.enums.statoLoginEnum import LoginStatus
from promptDiSistema.classificatoreLogin import SYSTEM_PROMPT

logger = logging.getLogger(__name__)







# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class LoginClassifier:
    """
    Classifica lo stato di una pagina tramite screenshot + vision LLM.

    Uso:
        classifier = LoginClassifier(api_key="sk-...")
        result = await classifier.classify(screenshot_path="path/to/shot.png")
    """

    MODEL_PRIMARY  = "gpt-4o-mini"
    MODEL_FALLBACK = "gpt-4o"

    def __init__(self, api_key: str):
        self._client = AsyncOpenAI(api_key=api_key)

    # ------------------------------------------------------------------
    # Metodo pubblico principale
    # ------------------------------------------------------------------

    async def classify(self, screenshot_path: str | Path, *, force_premium: bool = False, ) -> ClassificationResult:
        """
        Classifica la pagina a partire da uno screenshot su disco.

        Args:
            screenshot_path : percorso al file PNG/JPEG dello screenshot.
            force_premium   : salta mini e usa direttamente GPT-4o.

        Returns:
            ClassificationResult con stato, confidence e modello usato.
        """
        screenshot_b64 = self._encode_image(screenshot_path)
        model = self.MODEL_FALLBACK if force_premium else self.MODEL_PRIMARY

        result = await self._call_vision(screenshot_b64, model)

        # Fallback automatico se confidence bassa o errore con il modello mini
        if (
            not force_premium
            and result.confidence == Confidence.LOW
        ):
            logger.info(
                "Confidence LOW con %s — fallback a %s",
                self.MODEL_PRIMARY,
                self.MODEL_FALLBACK,
            )
            result = await self._call_vision(screenshot_b64, self.MODEL_FALLBACK)

        return result

    # ------------------------------------------------------------------
    # Metodo per classificare da bytes (es. screenshot Playwright in-memory)
    # ------------------------------------------------------------------

    async def classify_bytes(
        self,
        screenshot_bytes: bytes,
        *,
        force_premium: bool = False,
    ) -> ClassificationResult:
        """
        Come classify(), ma accetta i bytes dello screenshot direttamente
        (utile con Playwright: screenshot_bytes = await page.screenshot()).
        """
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
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

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _call_vision(
        self,
        screenshot_b64: str,
        model: str,
    ) -> ClassificationResult:
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
                                "type":  "image_url",
                                "image_url": {
                                    "url":    f"data:image/png;base64,{screenshot_b64}",
                                    "detail": "low",   # "low" = ~85 token, sufficiente per classificazione
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
            # In caso di errore API, restituiamo unknown con LOW
            return ClassificationResult(
                state=LoginStatus.UNKNOWN,
                confidence=Confidence.LOW,
                notes=f"Errore API: {exc}",
                used_model=model,
                raw_json={},
            )

    def _parse_response(self, raw_text: str, model: str) -> ClassificationResult:
        """Parsa la risposta JSON del modello."""
        # Pulizia difensiva: rimuove eventuali backtick markdown
        cleaned = raw_text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("JSON non valido dal modello %s: %r", model, raw_text)
            return ClassificationResult(
                state=LoginStatus.UNKNOWN,
                confidence=Confidence.LOW,
                notes="JSON non valido nella risposta",
                used_model=model,
                raw_json={},
            )

        # Normalizzazione valori
        state_value = data.get("state", "unknown")
        try:
            state = LoginStatus(state_value)
        except ValueError:
            logger.warning("State sconosciuto: %r", state_value)
            state = LoginStatus.UNKNOWN

        confidence_value = data.get("confidence", "LOW")
        try:
            confidence = Confidence(confidence_value)
        except ValueError:
            confidence = Confidence.LOW

        return ClassificationResult(
            state=LoginStatus(state) if state in LoginStatus._value2member_map_ else LoginStatus.UNKNOWN,
            confidence=Confidence(confidence) if confidence in Confidence._value2member_map_ else Confidence.LOW,
            notes=str(data.get("notes", ""))[:200],
            used_model=model,
            raw_json=data,
        )

    @staticmethod
    def _encode_image(path: str | Path) -> str:
        """Legge un'immagine da disco e la converte in base64."""
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")