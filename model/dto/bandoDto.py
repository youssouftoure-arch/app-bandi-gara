from typing import Optional
from pydantic import BaseModel, Field, field_validator
from urllib.parse import urljoin

class Bando(BaseModel):
    titolo: str = Field(..., description="Titolo del bando di gara")
    descrizione: Optional[str] = Field(None, description="Descrizione o estratto del bando")
    scadenza: Optional[str] = Field(None, description="Data di scadenza del bando")
    importo: Optional[str] = Field(None, description="Importo o valore stimato")
    categoria: Optional[str] = Field(None, description="Categoria merceologica o CPV")
    url_dettaglio: Optional[str] = Field(None, description="URL del dettaglio del bando")

    @classmethod
    def normalizza_url(cls, url_estratto: Optional[str], url_base: str) -> Optional[str]:
        """Normalizza l'URL gestendo sia casi relativi che assoluti."""
        if not url_estratto:
            return None
        return urljoin(url_base, url_estratto.strip())