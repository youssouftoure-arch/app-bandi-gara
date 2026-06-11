"""Report scraper: formatta durata, successo login e riepiloghi console/log."""

import logging

from model.dto.bandoDto import Bando


def stato_login_success(stato_login) -> bool:
    stato_str = str(stato_login).lower() if stato_login else ""
    return "success" in stato_str or "skipped_cookie" in stato_str


def formatta_durata(tempo_totale: float) -> str:
    minuti = int(tempo_totale // 60)
    secondi = int(tempo_totale % 60)
    return f"{minuti}m {secondi}s" if minuti > 0 else f"{secondi}s"


def stampa_bandi(url_portale: str, bandi: list[Bando]):
    print("\n" + "#" * 60)
    print(f" BANDI ESTRATTI CON SUCCESSO DA: {url_portale}")
    print("#" * 60)
    for idx, bando in enumerate(bandi, 1):
        print(f" [{idx}] TITOLO:    {bando.titolo}")
        print(f"     SCADENZA:  {bando.scadenza or 'N/D'}")
        print(f"     IMPORTO:   {bando.importo or 'N/D'}")
        print(f"     URL DETT:  {bando.url_dettaglio or 'N/D'}")
        print("-" * 50)
    print("#" * 60 + "\n")


def stampa_riepilogo(risultati, tempo_totale: float, logger: logging.Logger):
    lista_valori = list(risultati.values()) if isinstance(risultati, dict) else risultati
    totale = len(lista_valori)
    successi = 0
    totale_bandi = 0

    for r in lista_valori:
        if not r or not isinstance(r, dict):
            continue
        if stato_login_success(r.get("login")):
            successi += 1
        bandi = r.get("bandi", [])
        if isinstance(bandi, list):
            totale_bandi += len(bandi)

    logger.info("=" * 60)
    logger.info("RILASCIO OPERAZIONI DI SCRAPING COMPLETATO")
    logger.info("Totale Portali Processati:         %d", totale)
    logger.info("Login Effettuati con Successo:     %d", successi)
    logger.info("Login Falliti:                     %d", totale - successi)
    logger.info("Totale Bandi Complessivi Estratti: %d", totale_bandi)
    logger.info("Tempo Totale Impiegato:            %s", formatta_durata(tempo_totale))
    logger.info("=" * 60)
