import pandas as pd
import logging
from pathlib import Path
from model.po.portalePo import Portale

logger = logging.getLogger(__name__)

class PortaleDao:
    def __init__(self, excel_path: Path = Path("user e password per Operations.xlsx")):
        self.excel_path = excel_path

    def carica_portali(self) -> list[Portale]:
        if not self.excel_path.exists():
            logger.error("File excel portali non trovato: %s", self.excel_path)
            return []
        
        df = pd.read_excel(self.excel_path, header=4)
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
        
        portali = []
        logger.info("Colonne trovate nell'Excel (riga 5): %s", df.columns.tolist())
        
        for _, row in df.iterrows():
            if row.isnull().all():
                continue
                
            try:
                portali.append(Portale.from_dataframe_row(row.to_dict()))
            except Exception as exc:
                logger.warning("Riga dell'Excel saltata per errore di validazione: %s", exc)
                
        return [p for p in portali if p.is_active]
