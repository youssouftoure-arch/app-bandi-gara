"""Enum dei livelli di confidenza restituiti dal classificatore LLM."""

from enum import Enum

class Confidence(str, Enum):
    HIGH = "HIGH"
    LOW  = "LOW"
