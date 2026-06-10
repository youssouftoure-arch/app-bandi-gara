import threading
import time
import asyncio
import os
from flask import jsonify
from view.scraperView import ScraperViewInterface
from service.crawl4ai.scraperService import scraper
from dao.bandoDao import BandoDao

class ScraperPresenter:
    def __init__(self, view: ScraperViewInterface, bando_dao: BandoDao = None):
        self.view = view
        self.bando_dao = bando_dao or BandoDao()
        
        # Stato condiviso thread-safe
        self._stato_lock = threading.Lock()
        self._scraper_stato = {
            "in_corso": False, 
            "ultimo_aggiornamento": None,
            "metriche_finali": None
        }

    def avvia_scraping(self):
        with self._stato_lock:
            if self._scraper_stato["in_corso"]:
                return self.view.show_avvio_error("Scraping già in corso...")

        threading.Thread(target=self._esegui_scraping_background, daemon=True).start()
        return self.view.show_avvio_success("Ciclo di scraping avviato tramite Blueprint!")

    def ottieni_stato(self):
        with self._stato_lock:
            stato_copia = self._scraper_stato.copy()
        return self.view.show_stato(
            in_corso=stato_copia["in_corso"],
            ultimo_aggiornamento=stato_copia["ultimo_aggiornamento"],
            metriche=stato_copia["metriche_finali"]
        )

    def ottieni_dati(self):
        if not self.bando_dao.excel_path.exists():
            return jsonify({"status": "empty", "data": [], "message": "Nessun dato ancora estratto."})
            
        try:
            dati = self.bando_dao.carica_dati_bandi()
            return self.view.show_dati(dati)
        except Exception as e:
            return self.view.show_error(str(e), 500)

    def _esegui_scraping_background(self):
        with self._stato_lock:
            self._scraper_stato["in_corso"] = True
            self._scraper_stato["metriche_finali"] = None
        
        start_time = time.time()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # 1. Eseguiamo il ciclo sui 14 portali attivi visti nei log
            risultati_raw = loop.run_until_complete(scraper().main())
            loop.close()
            
            elapsed_time = time.time() - start_time
            minuti = int(elapsed_time // 60)
            secondi = int(elapsed_time % 60)
            tempo_str = f"{minuti}m {secondi}s" if minuti > 0 else f"{secondi}s"

            # main() ritorna {"risultati": [...], "metriche": {...}} — estraiamo la lista
            lista_risultati = risultati_raw.get("risultati", []) if isinstance(risultati_raw, dict) else []

            successi = 0
            totale_bandi = 0
            for r in lista_risultati:
                if isinstance(r, dict):
                    stato_str = str(r.get("login", "")).lower()
                    if "success" in stato_str or "skipped_cookie" in stato_str:
                        successi += 1
                    totale_bandi += len(r.get("bandi", []))

            totale_portali = len(lista_risultati)

            metriche = {
                "totale_portali": totale_portali,
                "login_ok": successi,
                "login_ko": totale_portali - successi,
                "totale_bandi": totale_bandi,
                "tempo_impiegato": tempo_str,
                "file_excel": str(self.bando_dao.excel_path)
            }

            # 4. REQUISITO: Se i bandi estratti oggi sono 0, forziamo la pulizia
            if totale_bandi == 0:
                print("[Presenter] Rilevati 0 bandi totali. Forzo l'azzeramento della tabella dei dati.")
                # Se il tuo DAO ha un metodo per ripulire i dati correnti in memoria o svuotare l'excel:
                if hasattr(self.bando_dao, 'svuota_dati_correnti'):
                    self.bando_dao.svuota_dati_correnti()
                elif hasattr(self.bando_dao, 'salva_bandi'):
                    # Sovrascrive l'Excel/DB con una lista vuota per pulire la tabella sul frontend
                    self.bando_dao.salva_bandi([])

            # 5. Aggiorniamo lo stato globale letto da /api/stato
            with self._stato_lock:
                self._scraper_stato["metriche_finali"] = metriche
                # Questo sblocca la data aggiornandola al 2026-06-10 attuale dei log!
                self._scraper_stato["ultimo_aggiornamento"] = time.strftime("%Y-%m-%d %H:%M:%S")
                
        except Exception as e:
            print(f"Errore nello scraping in background: {e}")
        finally:
            with self._stato_lock:
                self._scraper_stato["in_corso"] = False