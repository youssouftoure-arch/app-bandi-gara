import logging
from typing import Optional
from bs4 import BeautifulSoup
from model.dto.bandoDto import Bando

logger = logging.getLogger(__name__)

class EstrattoreCssService:
    @staticmethod
    def estrai_con_selettori(html: str, selettori: dict, url_base: str) -> list[Bando]:
        """Estrae i bandi in modo deterministico usando i selettori CSS."""
        soup = BeautifulSoup(html, 'html.parser')
        bandi_estratti = []

        # BUG FIX 3: guard su selettore contenitore vuoto (causava "Expected a selector at position 0")
        contenitore_sel = selettori.get("contenitore_bando", "")
        if not contenitore_sel or not contenitore_sel.strip():
            logger.warning("Selettore contenitore_bando vuoto o assente — skip estrazione CSS.")
            return []

        contenitori = soup.select(contenitore_sel)
        logger.info(f"Trovati {len(contenitori)} elementi con il selettore contenitore.")

        for nodo in contenitori:
            try:
                def _testo_o_none(selector_key: str) -> Optional[str]:
                    sel = selettori.get(selector_key, "")
                    if not sel or not sel.strip():
                        return None
                    el = nodo.select_one(sel)
                    return el.get_text(strip=True) if el else None

                # Gestione URL (href)
                url_relativo = None
                sel_url = selettori.get("url_dettaglio", "")
                if sel_url and sel_url.strip():
                    el_url = nodo.select_one(sel_url)
                    if el_url:
                        url_relativo = el_url.get('href')

                titolo = _testo_o_none("titolo")
                if not titolo:
                    continue

                bando = Bando(
                    titolo=titolo,
                    descrizione=_testo_o_none("descrizione"),
                    scadenza=_testo_o_none("scadenza"),
                    importo=_testo_o_none("importo"),
                    categoria=_testo_o_none("categoria"),
                    url_dettaglio=Bando.normalizza_url(url_relativo, url_base)
                )
                bandi_estratti.append(bando)
            except Exception as e:
                logger.error(f"Errore durante il parsing del singolo bando CSS: {e}")
                continue

        return bandi_estratti