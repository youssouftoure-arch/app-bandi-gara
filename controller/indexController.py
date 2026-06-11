"""Controller Flask: espone endpoint API, download Excel e dashboard grafica."""

from flask import Blueprint, render_template, send_file, jsonify
import os
from view.scraperView import FlaskScraperView
from presenter.scraperPresenter import ScraperPresenter
from service.grafici.plotService import AnalyticsService

# Creazione del Blueprint per isolare il controller dello scraper
scraper_bp = Blueprint('scraper_api', __name__, url_prefix='/api')

# Istanziazione del View e del Presenter secondo il pattern MVP
analytics_service = AnalyticsService()
view = FlaskScraperView()
presenter = ScraperPresenter(view)

@scraper_bp.route('/avvia', methods=['POST'])
def avvia_scraping():
    """Avvia il ciclo di scraping in background."""
    return presenter.avvia_scraping()

@scraper_bp.route('/stato', methods=['GET'])
def stato_scraping():
    """Ritorna lo stato corrente del processo di scraping."""
    return presenter.ottieni_stato()

@scraper_bp.route('/dati', methods=['GET'])
def dati_bandi():
    """Ritorna i dati estratti dei bandi."""
    return presenter.ottieni_dati()

@scraper_bp.route('/scarica-excel', methods=['GET'])
def scarica_excel():
    file_excel = "bandi_estratti_totale.xlsx"
    
    # Controlla se il file esiste davvero sul server
    if not os.path.exists(file_excel):
        return jsonify({"status": "error", "message": "Il file Excel non è ancora stato generato."}), 404
    
    try:
        # Invia il file in modo sicuro permettendo il download al browser
        return send_file(
            file_excel,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="bandi_estratti.xlsx"  # Nome che l'utente vedrà al momento del download
        )
    except Exception as e:
        return jsonify({"status": "error", "message": f"Errore durante il download: {str(e)}"}), 500
    

@scraper_bp.route('/dashboard')
def mostra_dashboard():
    """
    Renderizza la pagina web contenente i grafici e le metriche di riepilogo.
    """
    dati_dashboard = analytics_service.ottieni_dati_dashboard()
    
    # Renderizza un template HTML passando i dati elaborati dal service
    return render_template('dashboard.html', dati=dati_dashboard)
