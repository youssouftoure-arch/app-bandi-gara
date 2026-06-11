"""Servizio legacy di lettura Excel portali con normalizzazione base degli URL."""

import pandas as pd
from model.po.portalePo import Portale


class EstrazioneDati:
    def __init__(self):
        pass   

    # --- Caricamento dal file xlsx ---
    @staticmethod
    def carica_portali(path: str) -> list[Portale]:
        # Carica l'Excel impostando l'intestazione alla riga 5 (indice 4)
        df = pd.read_excel(
            path,
            header=4,
            usecols=["N°", "Cliente", "Gruppo", "Link HTTP", "USER", "PSW", "NOTE"],
            dtype={
                "N°": int,
                "USER": str,
                "PSW": str,
                "Link HTTP": str
            }
        )

        # Pulizia base delle colonne
        df.columns = df.columns.str.strip()
        df = df.dropna(subset=["Link HTTP", "USER", "PSW"])  # righe incomplete scartate
        
        df["Link HTTP"] = df["Link HTTP"].str.strip()
        df["NOTE"] = df["NOTE"].fillna("")

        # --- FIX 1: Normalizzazione URL (Aggiunta protocollo https:// se mancante) ---
        def normalizza_url(url: str) -> str:
            if not url:
                return url
            # Se l'URL non inizia con http:// o https://, aggiungiamo https:// di default
            if not url.startswith(("http://", "https://")):
                return f"https://{url}"
            return url

        df["Link HTTP"] = df["Link HTTP"].apply(normalizza_url)
        # -----------------------------------------------------------------------------

        return [
            Portale(
                numero=row["N°"],
                cliente=row["Cliente"],
                gruppo=row["Gruppo"],
                url=row["Link HTTP"],
                username=row["USER"],
                password=row["PSW"],
                note=row["NOTE"]
            )
            for _, row in df.iterrows()
        ]
