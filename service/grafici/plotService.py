import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

class AnalyticsService:
    def __init__(self, excel_path: str = "bandi_estratti_totale.xlsx"):
        self.excel_path = Path(excel_path)

    def ottieni_dati_dashboard(self) -> dict:
        """
        Legge il file Excel di output dei bandi estratti ed elabora le metriche per la dashboard.
        """
        if not self.excel_path.exists():
            logger.warning(f"File Excel di output {self.excel_path} non trovato per le analytics.")
            return {
                "errore": True,
                "messaggio": f"Il file di riepilogo dei bandi non è ancora stato generato dallo scraper.",
                "totale_bandi": 0,
                "portali_scansionati": 0,
                "grafico_portali": {"labels": [], "conteggi": []},
                "ultimi_bandi": []
            }

        try:
            # Carichiamo i dati dei bandi estratti
            df = pd.read_excel(self.excel_path, sheet_name=0)
            
            if df.empty:
                return {
                    "errore": False,
                    "totale_bandi": 0,
                    "portali_scansionati": 0,
                    "grafico_portali": {"labels": [], "conteggi": []},
                    "ultimi_bandi": []
                }

            # Rimuoviamo gli spazi vuoti accidentali dai nomi delle colonne per sicurezza
            df.columns = df.columns.str.strip()

            # 1. Calcolo KPI Generici (Escludendo i messaggi di login fallito se presenti)
            col_titolo = "Titolo Bando" if "Titolo Bando" in df.columns else "titolo"
            col_portale = "Portale" if "Portale" in df.columns else "portale"
            col_importo = "Importo" if "Importo" in df.columns else "importo"
            col_scadenza = "Scadenza" if "Scadenza" in df.columns else "scadenza"

            # Filtriamo via le righe segnaposto di errore per avere i conteggi puliti dei veri bandi
            df_veri_bandi = df[df[col_titolo] != "Nessun bando estratto o login fallito"] if col_titolo in df.columns else df
            totale_bandi = int(df_veri_bandi.shape[0])
            portali_unici = int(df[col_portale].nunique()) if col_portale in df.columns else 0

            # 2. Elaborazione dati per il Grafico a Barre (Distribuzione per Portale)
            grafico_portali = {"labels": [], "conteggi": []}
            if col_portale in df.columns and totale_bandi > 0:
                conteggio = df_veri_bandi[col_portale].value_counts()
                
                # Pulizia dei domini lunghi per le etichette dell'asse X del grafico
                grafico_portali["labels"] = [
                    str(url).replace("https://", "").replace("http://", "").split('/')[0] 
                    for url in conteggio.index if pd.notna(url)
                ]
                grafico_portali["conteggi"] = [int(v) for v in conteggio.values]

            # 3. Estrazione dei ultimi 10 bandi (Allineati al template HTML 'titolo', 'importo', 'scadenza')
            ultimi_bandi = []
            if totale_bandi > 0:
                # Prendiamo i primi 10 record reali (escludendo i falliti)
                df_sub = df_veri_bandi.head(10).copy()
                
                for _, row in df_sub.iterrows():
                    t = row[col_titolo] if col_titolo in df_sub.columns else None
                    val_titolo = str(t).strip() if pd.notna(t) and str(t).strip() != "" else "Senza Titolo"
                    
                    i = row[col_importo] if col_importo in df_sub.columns else None
                    val_importo = str(i).strip() if pd.notna(i) and str(i).strip() != "" else "-"
                    
                    s = row[col_scadenza] if col_scadenza in df_sub.columns else None
                    if pd.notna(s):
                        if isinstance(s, pd.Timestamp):
                            val_scadenza = s.strftime('%d/%m/%Y %H:%M')
                        else:
                            val_scadenza = str(s).strip()
                    else:
                        val_scadenza = "-"
                    
                    ultimi_bandi.append({
                        "titolo": val_titolo,
                        "importo": val_importo,
                        "scadenza": val_scadenza
                    })

            return {
                "errore": False,
                "totale_bandi": totale_bandi,
                "portali_scansionati": portali_unici,
                "grafico_portali": grafico_portali,
                "ultimi_bandi": ultimi_bandi
            }

        except Exception as e:
            logger.error(f"Errore durante l'elaborazione dei grafici: {e}")
            return {
                "errore": True,
                "messaggio": f"Errore interno durante l'analisi dell'Excel: {str(e)}",
                "totale_bandi": 0,
                "portali_scansionati": 0,
                "grafico_portali": {"labels": [], "conteggi": []},
                "ultimi_bandi": []
            }