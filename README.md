# App Bandi Gara 🚀

Applicazione per lo scraping e l'analisi dei bandi di gara basata su Python e `Crawl4AI`.

## Prerequisiti

L'applicazione è interamente containerizzata. Per eseguirla, l'unico requisito richiesto sulla macchina è **Docker** (e **Docker Desktop** se si utilizza Windows o macOS).

## Come iniziare (Ambiente di Sviluppo)

### 1. Clona la repository

```bash
git clone <URL_DELLA_TUA_REPO_QUI>
cd "app bandi gara"
```

### 2. Costruisci l'immagine Docker

Da eseguire solo la prima volta oppure quando viene modificato il file `requirements.txt`.

```bash
docker build -t app-bandi-gara .
```

### 3. Avvia l'applicazione in modalità sviluppo

#### Windows (PowerShell)

```powershell
docker run --rm -v "${PWD}:/app" app-bandi-gara
```

#### Linux / macOS (Terminale) o Git Bash

```bash
docker run --rm -v "$(pwd):/app" app-bandi-gara
```

## Sviluppo

Grazie ai volumi Docker (`-v`), qualsiasi modifica apportata ai file `.py` sul computer locale verrà immediatamente riflessa all'interno del container, senza necessità di ricostruire l'immagine Docker.
