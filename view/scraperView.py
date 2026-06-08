from abc import ABC, abstractmethod
from flask import jsonify, Response

class ScraperViewInterface(ABC):
    @abstractmethod
    def show_stato(self, in_corso: bool, ultimo_aggiornamento: str, metriche: dict) -> any:
        pass

    @abstractmethod
    def show_dati(self, dati: list) -> any:
        pass

    @abstractmethod
    def show_avvio_success(self, messaggio: str) -> any:
        pass

    @abstractmethod
    def show_avvio_error(self, messaggio: str) -> any:
        pass

    @abstractmethod
    def show_error(self, messaggio: str, status_code: int) -> any:
        pass


class FlaskScraperView(ScraperViewInterface):
    def show_stato(self, in_corso: bool, ultimo_aggiornamento: str, metriche: dict) -> Response:
        return jsonify({
            "in_corso": in_corso,
            "ultimo_aggiornamento": ultimo_aggiornamento,
            "metriche_finali": metriche
        })

    def show_dati(self, dati: list) -> Response:
        return jsonify({
            "status": "success",
            "data": dati
        })

    def show_avvio_success(self, messaggio: str) -> Response:
        return jsonify({
            "status": "success",
            "message": messaggio
        })

    def show_avvio_error(self, messaggio: str) -> tuple[Response, int]:
        return jsonify({
            "status": "error",
            "message": messaggio
        }), 400

    def show_error(self, messaggio: str, status_code: int = 500) -> tuple[Response, int]:
        return jsonify({
            "status": "error",
            "message": messaggio
        }), status_code
