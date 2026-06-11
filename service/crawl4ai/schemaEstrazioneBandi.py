"""Schemi Pydantic per output strutturati dell'LLM su elenco e dettagli bandi."""

from typing import Optional

from pydantic import BaseModel, Field

from model.dto.bandoDto import Bando


class ElencoBandiOutput(BaseModel):
    bandi: list[Bando] = Field(default_factory=list, description="Lista dei bandi di gara individuati nella pagina")


class DettagliBandoOutput(BaseModel):
    importo: Optional[str] = None
    scadenza: Optional[str] = None
    descrizione: Optional[str] = None
    categoria: Optional[str] = None
