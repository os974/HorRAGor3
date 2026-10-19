"""Client HTTP de l'API Données : même contrat que le repository SQL."""

import httpx
import pytest

from src.config import settings
from src.data import http_repository
from src.data.http_repository import HttpFilmRepository
from src.tools import rag_tool


class FakeResponse:
    """Double de la réponse httpx.get."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erreur", request=None, response=None)


def test_get_metadata_valide_le_contrat(monkeypatch):
    """200 → FilmMetadata revalidé côté client (tout écart au contrat détecté)."""
    monkeypatch.setattr(
        http_repository.httpx,
        "get",
        lambda url, **k: FakeResponse(200, {"id": 41, "title": "Hereditary"}),
    )
    repo = HttpFilmRepository(base_url="http://api-donnees:8100")
    meta = repo.get_metadata(41)
    assert meta.title == "Hereditary"


def test_get_metadata_404_devient_none(monkeypatch):
    """404 de l'API Données → None (même sémantique que le repository SQL)."""
    monkeypatch.setattr(http_repository.httpx, "get", lambda url, **k: FakeResponse(404))
    repo = HttpFilmRepository(base_url="http://api-donnees:8100")
    assert repo.get_metadata(999) is None


def test_recommend_similar(monkeypatch):
    """La liste JSON devient des FilmRef typés ; k transmis en query."""
    seen = {}

    def fake_get(url, params=None, **kwargs):
        seen["url"], seen["params"] = url, params
        return FakeResponse(200, [{"id": 1, "title": "Mara"}])

    monkeypatch.setattr(http_repository.httpx, "get", fake_get)
    repo = HttpFilmRepository(base_url="http://api-donnees:8100")
    similar = repo.recommend_similar(41, k=3)
    assert [s.title for s in similar] == ["Mara"]
    assert seen["params"] == {"k": 3} and "/films/41/similar" in seen["url"]


def test_erreur_serveur_remonte(monkeypatch):
    """503 → exception httpx : c'est rag_tool qui applique le « jamais d'exception »."""
    monkeypatch.setattr(http_repository.httpx, "get", lambda url, **k: FakeResponse(503))
    repo = HttpFilmRepository(base_url="http://api-donnees:8100")
    with pytest.raises(httpx.HTTPStatusError):
        repo.get_metadata(41)
    # Et la couche outils, elle, dégrade sans lever :
    monkeypatch.setattr(rag_tool, "get_repository", lambda: repo)
    assert rag_tool.query_movie_metadata(41) is None


def test_rag_tool_choisit_le_repo_selon_la_config(monkeypatch):
    """data_api_url définie → client HTTP ; vide → accès SQL direct."""
    monkeypatch.setattr(settings, "data_api_url", "http://api-donnees:8100")
    assert isinstance(rag_tool.get_repository(), HttpFilmRepository)
