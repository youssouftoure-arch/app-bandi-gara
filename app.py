"""Entry point Flask: crea l'app, registra il blueprint API e serve la home."""

from flask import Flask, render_template
from controller.indexController import scraper_bp

app = Flask(__name__)

# Registriamo il Blueprint importato dalla cartella controllers
app.register_blueprint(scraper_bp)

@app.route('/')
def index():
    # Unica rotta principale dell'applicazione
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
