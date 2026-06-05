import asyncio
import logging
import os
import json
from dotenv import load_dotenv
from pathlib import Path
import pandas as pd
from openai import AsyncOpenAI  # Fornito per lo Structured Output di OpenAI

# Playwright & Crawl4AI
from playwright.async_api import async_playwright

# Modelli del tuo ecosistema
from model.enums.statoLoginEnum import LoginStatus
from model.po.portalePo import Portale
from model.dto.bandoDto import Bando

# Servizi esterni e l'Orchestratore Ibrido configurato prima
from service.crawl4ai.esecutoreLoginService import EsecutoreLoginService
from service.crawl4ai.estrattoreBandiService import EstrazioneDatiService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

logger = logging.getLogger(__name__)

load_dotenv()

EXCEL_PATH  = Path("user e password per Operations.xlsx")
OPENAI_KEY  = os.environ.get("OPENAI_API_KEY", "")
CONCORRENZA = 3


class scraper:

    def __init__(self):
        if not OPENAI_KEY:
            raise EnvironmentError("Variabile OPENAI_API_KEY non impostata")
        
        # 1. Inizializziamo il client Async unico di OpenAI
        self.llm_client = AsyncOpenAI(api_key=OPENAI_KEY)
        
        # 2. Iniettiamo il client o la chiave nei rispettivi servizi
        self._esecutore = EsecutoreLoginService(OPENAI_KEY)
        self._estrattore_ibrido_service = EstrazioneDatiService(llm_client=self.llm_client)

    async def main(self):
        portali = self._carica_portali()
        logger.info("Portali caricati: %d", len(portali))

        risultati = []
        for i in range(0, len(portali), CONCORRENZA):
            batch = portali[i : i + CONCORRENZA]
            batch_risultati = await asyncio.gather(
                *[self._processa_portale(p) for p in batch]
            )
            risultati.extend(batch_risultati)
            logger.info("Completati %d / %d", min(i + CONCORRENZA, len(portali)), len(portali))

        self._stampa_riepilogo(risultati)
        
        # --- AGGIUNTA: SALVATAGGIO DEI BANDI SU FILE EXCEL ---
        self._salva_bandi_su_excel(risultati)
        
        return risultati
    

    async def _processa_portale(self, portale: Portale):
        # 1. LOGIN intelligente
        risultato_login = await self._esecutore.esegui_login(portale)

        if not risultato_login.is_success:
            logger.warning("[%s] Login fallito: %s", portale.url, risultato_login.status.value)
            return {"portale": portale.url, "login": risultato_login.status.value, "bandi": []}

        # 2. SCRAPING + ESTRAZIONE IBRIDA
        bandi_estratti: list[Bando] = await self._scrapa_e_estrai_bandi(portale, risultato_login.cookies_path)

        # --- AGGIUNTA: COUT / STAMPA DEI BANDI SU TERMINALE ---
        if bandi_estratti:
            print("\n" + "#" * 60)
            print(f" 🎯 BANDI ESTRATTI CON SUCCESSO DA: {portale.url}")
            print("#" * 60)
            for idx, bando in enumerate(bandi_estratti, 1):
                print(f" [{idx}] TITOLO:    {bando.titolo}")
                print(f"     SCADENZA:  {bando.scadenza or 'N/D'}")
                print(f"     IMPORTO:   {bando.importo or 'N/D'}")
                print(f"     URL DETT:  {bando.url_dettaglio or 'N/D'}")
                print("-" * 50)
            print("#" * 60 + "\n")
        else:
            print(f"\n ⚠️  Nessun bando estratto dal portale: {portale.url}\n")
        # ------------------------------------------------------

        # Trasformiamo i DTO Pydantic in dizionari semplici per il report finale
        bandi_dict = [b.model_dump() for b in bandi_estratti]

        return {
            "portale": portale.url, 
            "login": risultato_login.status.value, 
            "bandi": bandi_dict,
            "conteggio_bandi": len(bandi_dict)
        }

    async def _scrapa_e_estrai_bandi(self, portale: Portale, cookies_path: str) -> list[Bando]:
        """Esegue il fetch della pagina tramite Playwright e avvia l'estrazione ibrida dei dati."""
        cookies = []
        if cookies_path:
            try:
                cookies = json.loads(Path(cookies_path).read_text())
            except Exception as e:
                logger.warning("[%s] Cookie non caricabili: %s", portale.url, e)

        html_contenuto = ""
        
        # --- FASE 1: Scaricamento DOM con Playwright ---
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                if cookies:
                    await context.add_cookies(cookies)
                
                page = await context.new_page()
                logger.info("[%s] Navigazione verso la pagina dei bandi...", portale.url)
                
                # Usiamo 'networkidle' o 'domcontentloaded' a seconda di quanta JS asincrona usa il portale
                await page.goto(portale.url, timeout=45_000, wait_until="domcontentloaded")
                
                # Piccolo wait opzionale se il portale renderizza i dati via AJAX dopo il DOM
                await asyncio.sleep(2) 
                
                html_contenuto = await page.content()
                await browser.close()
            except Exception as e:
                logger.error("[%s] Errore Playwright durante il fetch della pagina: %s", portale.url, e)
                return []

        if not html_contenuto:
            logger.warning("[%s] Contenuto HTML vuoto, impossibile procedere all'estrazione.", portale.url)
            return []

        # --- FASE 2: Estrazione Dati Ibrida (CSS -> LLM Discovery -> Fallback) ---
        try:
            # Ricaviamo un id stringa e l'url base dal portale PO. 
            # Se portale.id non è una stringa, usiamo l'url pulito come chiave identificativa del file di configurazione
            portale_id = str(getattr(portale, 'id', portale.url.split("//")[-1].replace("/", "_")))
            url_base = portale.url # o un attributo specifico tipo portale.url_base se presente
            
            bandi = await self._estrattore_ibrido_service.estrai_bandi(
                html=html_contenuto, 
                portale_id=portale_id, 
                url_base=url_base
            )
            return bandi
        except Exception as e:
            logger.error("[%s] Errore critico nel servizio di estrazione dati: %s", portale.url, e)
            return []

    def _carica_portali(self) -> list[Portale]:
        df = pd.read_excel(EXCEL_PATH, header=4)
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
        portali = []

        logger.info("Colonne trovate nell'Excel: %s", df.columns.tolist())

        for _, row in df.iterrows():
            try:
                portali.append(Portale.from_dataframe_row(row.to_dict()))
            except Exception as exc:
                logger.warning("Riga dell'Excel saltata per errore di validazione: %s", exc)
        return [p for p in portali if p.is_active]

    def _stampa_riepilogo(self, risultati):
        totale   = len(risultati)
        successi = sum(1 for r in risultati if r and r.get("login") in ("success", "skipped_cookie"))
        totale_bandi = sum(len(r.get("bandi", [])) for r in risultati if r)
        
        logger.info("=" * 60)
        logger.info("RILASCIO OPERAZIONI DI SCRAPING COMPLETATO")
        logger.info("Totale Portali Processati: %d", totale)
        logger.info("Login Effettuati con Successo: %d", successi)
        logger.info("Login Falliti: %d", totale - successi)
        logger.info("Totale Bandi Complessivi Estratti: %d", totale_bandi)
        logger.info("=" * 60)


    def _salva_bandi_su_excel(self, risultati):
        """Prende tutti i risultati in memoria e li scrive in un unico file Excel."""
        logger.info("Generazione file Excel di riepilogo bandi...")
        
        righe_bando = []
        
        for r in risultati:
            if not r:
                continue
            url_portale = r.get("portale", "Sconosciuto")
            stato_login = r.get("login", "Sconosciuto")
            
            # Se il login è fallito o non ci sono bandi, creiamo comunque una riga di log
            if not r.get("bandi"):
                righe_bando.append({
                    "Portale": url_portale,
                    "Stato Login": stato_login,
                    "Titolo Bando": "Nessun bando estratto o login fallito",
                    "Scadenza": "-",
                    "Importo": "-",
                    "Categoria": "-",
                    "URL Dettaglio": "-"
                })
            else:
                # Se ci sono bandi, creiamo una riga per ciascun bando trovato
                for bando in r["bandi"]:
                    righe_bando.append({
                        "Portale": url_portale,
                        "Stato Login": stato_login,
                        "Titolo Bando": bando.get("titolo"),
                        "Scadenza": bando.get("scadenza", "-"),
                        "Importo": bando.get("importo", "-"),
                        "Categoria": bando.get("categoria", "-"),
                        "URL Dettaglio": bando.get("url_dettaglio", "-")
                    })
        
        # Trasformiamo in DataFrame e salviamo
        df_output = pd.DataFrame(righe_bando)
        
        output_filename = "bandi_estratti_totale.xlsx"
        try:
            df_output.to_excel(output_filename, index=False)
            logger.info("= " * 25)
            logger.info(f"💾 FILE SALVATO CON SUCCESSO: {output_filename}")
            logger.info("= " * 25)
        except Exception as e:
            logger.error(f"Errore durante il salvataggio del file Excel finale: {e}")