from typing import Optional
from pydantic import BaseModel, Field, field_validator
from urllib.parse import urljoin
from datetime import datetime
import re

class Bando(BaseModel):
    titolo: str = Field(..., description="Titolo del bando di gara")
    committente: Optional[str] = Field(None, description="Ente, Azienda o Stazione Appaltante")
    descrizione: Optional[str] = Field(None, description="Descrizione o estratto del bando")
    scadenza: Optional[str] = Field(None, description="Data di scadenza del bando (es. GG/MM/AAAA)")
    importo: Optional[str] = Field(None, description="Importo o valore stimato")
    categoria: Optional[str] = Field(None, description="Categoria merceologica")
    url_dettaglio: Optional[str] = Field(None, description="URL del dettaglio del bando")

    @field_validator('scadenza')
    @classmethod
    def verifica_scadenza_futura(cls, v: Optional[str]) -> Optional[str]:
        if not v or v == "-":
            return v
        
        try:
            # Estrae la data (GG/MM/AAAA) ignorando l'orario se presente
            match = re.search(r'(\d{2})/(\d{2})/(\d{4})', v)
            if match:
                data_str = match.group(0)
                data_bando = datetime.strptime(data_str, "%d/%m/%Y")
                
                # Se la scadenza è passata (antecedente a oggi), scartiamo o solleviamo errore
                if data_bando.date() < datetime.now().date():
                    raise ValueError(f"Bando scaduto il {data_str}, riga ignorata.")
            return v
        except ValueError as e:
            # Sollevando l'errore, Pydantic invalida questa riga e lo scraper la salta
            raise e
        except Exception:
            return v # Nel dubbio non blocchiamo l'esecuzione

    @classmethod
    def normalizza_url(cls, url_estratto: Optional[str], url_base: str) -> Optional[str]:
        """Risolve il bug di 'successundefined' e pulisce i link relativi."""
        if not url_estratto or "undefined" in url_estratto.lower() or "success" in url_estratto.lower():
            # Se il link è corrotto, restituiamo direttamente l'URL della pagina elenco per poter verificare a mano
            return url_base
        return urljoin(url_base, url_estratto.strip())