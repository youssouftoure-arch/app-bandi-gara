import pandas as pd
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class BandoDao:
    def __init__(self, excel_path: Path = Path("bandi_estratti_totale.xlsx")):
        self.excel_path = excel_path

    def carica_dati_bandi(self) -> list[dict]:
        if not self.excel_path.exists():
            return []
        try:
            df = pd.read_excel(self.excel_path)
            df = df.fillna("-")
            return df.to_dict(orient="records")
        except Exception as e:
            logger.error("Errore lettura dati bandi da Excel: %s", e)
            raise e

    def leggi_metriche(self, fallback_totale_portali=114, fallback_login_ok=32, fallback_login_ko=82, fallback_totale_bandi=167) -> dict:
        totale_portali = fallback_totale_portali
        login_ok = fallback_login_ok
        login_ko = fallback_login_ko
        totale_bandi = fallback_totale_bandi

        if self.excel_path.exists():
            try:
                df = pd.read_excel(self.excel_path)
                if not df.empty:
                    df.columns = df.columns.str.strip()
                    if "Titolo Bando" in df.columns:
                        totale_bandi = int(df[df["Titolo Bando"] != "Nessun bando estratto o login fallito"].shape[0])
                    if "Portale" in df.columns:
                        totale_portali = int(df["Portale"].nunique())
                    if "Stato Login" in df.columns and "Portale" in df.columns:
                        login_ok = int(df[df["Stato Login"] == "success"]["Portale"].nunique())
                        login_ko = int(df[df["Stato Login"] != "success"]["Portale"].nunique())
            except Exception as ex:
                logger.error("Errore lettura metriche da excel, uso fallback: %s", ex)

        return {
            "totale_portali": totale_portali,
            "login_successo": login_ok,
            "login_falliti": login_ko,
            "totale_bandi": totale_bandi
        }

    def salva_bandi_su_excel(self, risultati: list) -> bool:
        logger.info("Generazione file Excel di riepilogo bandi...")
        righe = []
        
        lista_valori = list(risultati.values()) if isinstance(risultati, dict) else risultati

        for r in lista_valori:
            if not r or not isinstance(r, dict):
                continue
                
            url_portale = r.get("portale", "Sconosciuto")
            stato_login = r.get("login", "Sconosciuto")
            if hasattr(stato_login, "value"):
                stato_login = stato_login.value
                
            committente_fallback = self.estrai_committente_da_url(url_portale)
            bandi = r.get("bandi", [])
            
            if not bandi:
                righe.append({
                    "Portale": url_portale, 
                    "Stato Login": stato_login,
                    "Committente": committente_fallback,
                    "Titolo Bando": "Nessun bando estratto o login fallito",
                    "Scadenza": "-", 
                    "Importo": "-", 
                    "Categoria": "-",
                    "Descrizione": "-", 
                    "URL Dettaglio": "-",
                })
            else:
                for bando in bandi:
                    if hasattr(bando, "model_dump"):
                        bando_dict = bando.model_dump()
                    elif hasattr(bando, "dict"):
                        bando_dict = bando.dict()
                    elif isinstance(bando, dict):
                        bando_dict = bando
                    else:
                        bando_dict = {
                            "committente": getattr(bando, "committente", None),
                            "titolo": getattr(bando, "titolo", "-"),
                            "scadenza": getattr(bando, "scadenza", "-"),
                            "importo": getattr(bando, "importo", "-"),
                            "categoria": getattr(bando, "categoria", "-"),
                            "descrizione": getattr(bando, "descrizione", "-"),
                            "url_dettaglio": getattr(bando, "url_dettaglio", "-"),
                        }

                    scadenza_bando = bando_dict.get("scadenza", "-")
                    if "2025" in str(scadenza_bando):
                        continue

                    url_dettaglio = bando_dict.get("url_dettaglio") or "-"
                    if "undefined" in str(url_dettaglio).lower() or str(url_dettaglio).strip() == "-":
                        url_dettaglio = url_portale 

                    committente_finale = bando_dict.get("committente") or committente_fallback

                    righe.append({
                        "Portale":       url_portale,
                        "Stato Login":   stato_login,
                        "Committente":   str(committente_finale).upper(),
                        "Titolo Bando":  bando_dict.get("titolo") or "-",
                        "Scadenza":      scadenza_bando,
                        "Importo":       bando_dict.get("importo") or "-",
                        "Categoria":     bando_dict.get("categoria") or "-",
                        "Descrizione":   bando_dict.get("descrizione") or "-",
                        "URL Dettaglio": url_dettaglio,
                    })
                    
        if not righe:
            logger.warning("Nessun dato raccolto. Generazione file Excel annullata.")
            return False

        df_output = pd.DataFrame(righe)
        try:
            df_output.to_excel(self.excel_path, index=False)
            logger.info("= " * 25)
            logger.info("💾 FILE SALVATO CON SUCCESSO: %s", self.excel_path)
            logger.info("= " * 25)
            return True
        except Exception as e:
            logger.error("Errore salvataggio Excel: %s", e)
            return False

    @staticmethod
    def estrai_committente_da_url(url: str) -> str:
        try:
            dominio = urlparse(url).netloc.lower()
            for sub in ['www.', 'acquisti.', 'portale.', 'portalefornitori.', 'fornitori.', 'eprocurement.']:
                dominio = dominio.replace(sub, '')
            nome = dominio.split('.')[0]
            return nome.upper()
        except Exception:
            return "SCONOSCIUTO"
