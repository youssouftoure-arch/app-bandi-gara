# Usa l'immagine ufficiale di Playwright che ha già tutti i browser e le dipendenze di sistema pronte
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

# Imposta la cartella di lavoro all'interno del container
WORKDIR /app

# Copia il file dei requisiti e installa le dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutto il resto del codice del tuo progetto nel container
COPY . .

# Comando per avviare il tuo script (sostituisci "main.py" con il nome del tuo file)
CMD ["python", "app.py"]