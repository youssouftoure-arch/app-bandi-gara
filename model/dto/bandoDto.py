from typing import Optional
from pydantic import BaseModel, Field
from urllib.parse import urljoin

class Bando(BaseModel):
    titolo: str = Field(..., description="Titolo del bando di gara")
    committente: Optional[str] = Field(None, description="Ente, Azienda o Stazione Appaltante")
    descrizione: Optional[str] = Field(None, description="Descrizione o estratto del bando")
    scadenza: Optional[str] = Field(None, description="Data di scadenza del bando (es. GG/MM/AAAA)")
    importo: Optional[str] = Field(None, description="Importo o valore stimato")
    categoria: Optional[str] = Field(None, description="Categoria merceologica")
    url_dettaglio: Optional[str] = Field(None, description="URL del dettaglio del bando")

    @classmethod
    def normalizza_url(cls, url_estratto: Optional[str], url_base: str) -> Optional[str]:
        """Risolve il bug di 'successundefined' e pulisce i link relativi."""
        if not url_estratto or "undefined" in url_estratto.lower() or "success" in url_estratto.lower():
            # Se il link è corrotto, restituiamo direttamente l'URL della pagina elenco per poter verificare a mano
            return url_base
        return urljoin(url_base, url_estratto.strip())