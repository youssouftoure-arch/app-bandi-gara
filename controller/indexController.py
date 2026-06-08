from flask import Blueprint
from view.scraperView import FlaskScraperView
from presenter.scraperPresenter import ScraperPresenter

# Creazione del Blueprint per isolare il controller dello scraper
scraper_bp = Blueprint('scraper_api', __name__, url_prefix='/api')

# Istanziazione del View e del Presenter secondo il pattern MVP
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