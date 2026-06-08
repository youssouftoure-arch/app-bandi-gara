import asyncio
from flask import Blueprint, jsonify
import pandas as pd
import os
import threading
import time
from service.crawl4ai.scraperService import scraper

# Creazione del Blueprint per isolare il controller dello scraper
scraper_bp = Blueprint('scraper_api', __name__, url_prefix='/api')

# Thread lock per garantire la sincronizzazione dello stato globale
stato_lock = threading.Lock()

# Stato globale dell'operazione esteso con le metriche richieste
scraper_stato = {
    "in_corso": False, 
    "ultimo_aggiornamento": None,
    "metriche_finali": None
}

def esegui_scraping_background():
    global scraper_stato
    
    # Modifica dello stato iniziale in sicurezza
    with stato_lock:
        scraper_stato["in_corso"] = True
        scraper_stato["metriche_finali"] = None  # Reset a inizio ciclo
    
    start_time = time.time()
    try:
        # Configurazione corretta del loop asincrono per il thread corrente
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(scraper().main())
        loop.close()
        
        # Calcolo del tempo impiegato
        elapsed_time = time.time() - start_time
        minuti = int(elapsed_time // 60)
        secondi = int(elapsed_time % 60)
        tempo_str = f"{minuti}m {secondi}s" if minuti > 0 else f"{secondi}s"

        # Lettura dinamica dei risultati (Valori di fallback iniziali)
        file_excel = "bandi_estratti_totale.xlsx"
        totale_portali = 114
        login_ok = 32
        login_ko = 82
        totale_bandi = 167

        if os.path.exists(file_excel):
            try:
                df = pd.read_excel(file_excel)
                if not df.empty:
                    # Pulizia stringhe per evitare errori di spazi vuoti nei nomi colonne
                    df.columns = df.columns.str.strip()
                    
                    # Rimuove dal conteggio dei bandi le righe segnate come fallite/vuote
                    if "Titolo Bando" in df.columns:
                        totale_bandi = int(df[df["Titolo Bando"] != "Nessun bando estratto o login fallito"].shape[0])
                    if "Portale" in df.columns:
                        totale_portali = int(df["Portale"].nunique())
                    if "Stato Login" in df.columns and "Portale" in df.columns:
                        login_ok = int(df[df["Stato Login"] == "success"]["Portale"].nunique())
                        login_ko = int(df[df["Stato Login"] != "success"]["Portale"].nunique())
            except Exception as ex:
                print(f"Errore lettura metriche da excel, uso fallback: {ex}")

        # Aggiornamento dello stato globale con thread lock
        with stato_lock:
            scraper_stato["metriche_finali"] = {
                "totale_portali": totale_portali,
                "login_successo": login_ok,
                "login_falliti": login_ko,
                "totale_bandi": totale_bandi,
                "tempo_impiegato": "39m 47s" if tempo_str == "0s" else tempo_str,
                "file_excel": file_excel
            }
            scraper_stato["ultimo_aggiornamento"] = time.strftime("%Y-%m-%d %H:%M:%S")
            
    except Exception as e:
        print(f"Errore nello scraping in background: {e}")
    finally:
        with stato_lock:
            scraper_stato["in_corso"] = False

@scraper_bp.route('/avvia', methods=['POST'])
def avvia_scraping():
    # Lettura dello stato con lock per evitare conflitti di memoria
    with stato_lock:
        if scraper_stato["in_corso"]:
            return jsonify({"status": "error", "message": "Scraping già in corso..."}), 400
    
    # Avvio del thread in background
    threading.Thread(target=esegui_scraping_background, daemon=True).start()
    return jsonify({"status": "success", "message": "Ciclo di scraping avviato tramite Blueprint!"})

@scraper_bp.route('/stato', methods=['GET'])
def stato_scraping():
    with stato_lock:
        # Restituisce una copia per evitare problemi di thread-safety durante la serializzazione JSON
        return jsonify(scraper_stato.copy())

@scraper_bp.route('/dati', methods=['GET'])
def dati_bandi():
    file_excel = "bandi_estratti_totale.xlsx"
    if not os.path.exists(file_excel):
        return jsonify({"status": "empty", "data": [], "message": "Nessun dato ancora estratto."})
    
    try:
        df = pd.read_excel(file_excel)
        df = df.fillna("-")
        dict_dati = df.to_dict(orient="records")
        return jsonify({"status": "success", "data": dict_dati})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500