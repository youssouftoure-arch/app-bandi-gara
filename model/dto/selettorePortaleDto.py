from pydantic import BaseModel, Field
from typing import Dict

class ConfigSelettori(BaseModel):
    contenitore_bando: str = Field(..., description="Selettore CSS per la card/riga del bando")
    titolo: str = Field(..., description="Selettore CSS relativo per il titolo")
    descrizione: str = Field(..., description="Selettore CSS relativo per la descrizione")
    scadenza: str = Field(..., description="Selettore CSS relativo per la scadenza")
    importo: str = Field(..., description="Selettore CSS relativo per l'importo")
    categoria: str = Field(..., description="Selettore CSS relativo per la categoria")
    url_dettaglio: str = Field(..., description="Selettore CSS relativo per l'URL di dettaglio")

class PortaleConfigSchema(BaseModel):
    portale_id: str
    url_base: str
    scoperto_il: str
    affidabile: bool
    selettori: ConfigSelettori
    ultimo_test: str
    bandi_estratti_ultimo_test: int