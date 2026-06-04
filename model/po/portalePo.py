from dataclasses import dataclass
from typing import Optional

# --- Dataclass che rappresenta un portale ---
@dataclass
class Portale:
    numero: int
    cliente: str
    gruppo: str
    url: str
    username: str
    password: str
    note: Optional[str] = None