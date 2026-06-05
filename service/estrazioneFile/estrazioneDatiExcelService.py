import pandas as pd
from model.po.portalePo import Portale


class EstrazioneDati:
    def __init__(self):
        pass   

     # --- Caricamento dal file xlsx ---
    def carica_portali(path: str) -> list[Portale]:
        df = pd.read_excel(
            path,
            usecols=["N°", "Cliente", "Gruppo", "Link HTTP", "USER", "PSW", "NOTE"],
            dtype={
                "N°": int,
                "USER": str,
                "PSW": str,
                "Link HTTP": str
            }
        )

        # Pulizia base
        df.columns = df.columns.str.strip()
        df = df.dropna(subset=["Link HTTP", "USER", "PSW"])  # righe incomplete scartate
        df["Link HTTP"] = df["Link HTTP"].str.strip()
        df["NOTE"] = df["NOTE"].fillna("")

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