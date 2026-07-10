"""Enrichissement TMDB (mocké) et configuration Loguru."""

import logging

from loguru import logger

from src.data import tmdb
from src.logging_conf import setup_logging


class FakeResponse:
    """Double de la réponse httpx.get de TMDB."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def test_get_credits_extrait_realisateur_et_casting(monkeypatch):
    """Le réalisateur sort du crew, le casting est plafonné et sans None."""
    payload = {
        "crew": [
            {"name": "Monteur", "job": "Editor"},
            {"name": "Ari Aster", "job": "Director"},
        ],
        "cast": [{"name": f"Acteur {i}"} for i in range(8)],
    }
    monkeypatch.setattr(tmdb.httpx, "get", lambda *a, **k: FakeResponse(payload))

    credits = tmdb.get_credits(493922, top_cast=5)

    assert credits["director"] == "Ari Aster"
    assert len(credits["cast"]) == 5


def test_get_credits_sans_realisateur(monkeypatch):
    """Crew sans Director → director None, pas d'exception."""
    monkeypatch.setattr(tmdb.httpx, "get", lambda *a, **k: FakeResponse({"cast": []}))
    assert tmdb.get_credits(1) == {"director": None, "cast": []}


def test_setup_logging_intercepte_la_stdlib():
    """Les logs stdlib (uvicorn...) sont re-routés vers Loguru."""
    setup_logging()
    captured: list[str] = []
    handler_id = logger.add(lambda message: captured.append(str(message)), level="WARNING")
    try:
        logging.getLogger("uvicorn.error").warning("ping-stdlib")
    finally:
        logger.remove(handler_id)
    assert any("ping-stdlib" in line for line in captured)


def test_setup_logging_idempotent():
    """Deux appels ne dupliquent pas les sorties (remove avant add)."""
    setup_logging()
    setup_logging()  # ne doit pas lever ni empiler les sinks
