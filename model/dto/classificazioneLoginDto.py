from dataclasses import dataclass
from model.enums.statoPaginaEnum import PageState
from model.enums.confidenzaEnum import Confidence

@dataclass
class ClassificationResult:
    state:       PageState
    confidence:  Confidence
    notes:       str
    used_model:  str        # quale modello ha risposto
    raw_json:    dict       # payload grezzo dal modello