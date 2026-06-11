"""Parser risposta vision: trasforma JSON LLM in ClassificationResult tipizzato."""

import json
import logging

from model.dto.classificazioneLoginDto import ClassificationResult
from model.enums.confidenzaEnum import Confidence
from model.enums.statoPaginaEnum import PageState


def parse_classification_response(raw_text: str, model: str, logger: logging.Logger = None) -> ClassificationResult:
    active_logger = logger or logging.getLogger(__name__)
    cleaned = raw_text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        active_logger.warning("JSON non valido dal modello %s: %r", model, raw_text)
        return ClassificationResult(
            state=PageState.UNKNOWN,
            confidence=Confidence.LOW,
            notes="JSON non valido nella risposta",
            used_model=model,
            raw_json={},
        )

    state_value = data.get("state", "unknown")
    try:
        state = PageState(state_value)
    except ValueError:
        active_logger.warning("State sconosciuto: %r", state_value)
        state = PageState.UNKNOWN

    confidence_value = data.get("confidence", "LOW")
    try:
        confidence = Confidence(confidence_value)
    except ValueError:
        confidence = Confidence.LOW

    return ClassificationResult(
        state=PageState(state) if state in PageState._value2member_map_ else PageState.UNKNOWN,
        confidence=Confidence(confidence) if confidence in Confidence._value2member_map_ else Confidence.LOW,
        notes=str(data.get("notes", ""))[:200],
        used_model=model,
        raw_json=data,
    )
