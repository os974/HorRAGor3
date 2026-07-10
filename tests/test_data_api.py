"""API Données avec un repository factice : contrat HTTP de la couche Données."""

import pytest
from fastapi.testclient import TestClient

from services.data_api.main import app, get_repository
from src.contracts.schemas import FilmMetadata, FilmRef


class FakeRepository:
    """Double du repository : données préparées ou panne simulée."""

    def __init__(self, metadata=None, similar=None, error=None):
        self._metadata = metadata
        self._similar = similar or []
        self._error = error

    def get_metadata(self, film_id):
        if self._error:
            raise self._error
        return self._metadata if film_id == 41 else None

    def recommend_similar(self, film_id, k=5):
        if self._error:
            raise self._error
        return self._similar[:k]

    def validate_film(self, title):
        raise NotImplementedError


@pytest.fixture
def client():
    """TestClient avec un repository factice peuplé d'Hereditary."""
    fake = FakeRepository(
        metadata=FilmMetadata(id=41, title="Hereditary", release_year=2018),
        similar=[FilmRef(id=1, title="Mara"), FilmRef(id=2, title="The Unknown")],
    )
    app.dependency_overrides[get_repository] = lambda: fake
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health(client):
    """Le pouls de la couche Données (Docker, Uptime Kuma)."""
    assert client.get("/health").json() == {"status": "ok"}


def test_metrics_prometheus(client):
    """/metrics naît avec le service (règle observabilité)."""
    resp = client.get("/metrics")
    assert resp.status_code == 200 and "http_request" in resp.text


def test_film_metadata_trouve(client):
    """GET /films/{id} → le lore brut, validé contre le contrat."""
    resp = client.get("/films/41")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Hereditary" and body["release_year"] == 2018


def test_film_metadata_inconnu(client):
    """Film absent → 404 explicite (le client HTTP en fera un None)."""
    assert client.get("/films/999").status_code == 404


def test_similar_films(client):
    """GET /films/{id}/similar → les voisins pgvector, k respecté."""
    resp = client.get("/films/41/similar", params={"k": 1})
    assert resp.status_code == 200
    assert resp.json() == [{"id": 1, "title": "Mara"}]


def test_similar_k_borne(client):
    """k hors bornes (1..20) → 422 (validation FastAPI)."""
    assert client.get("/films/41/similar", params={"k": 0}).status_code == 422
    assert client.get("/films/41/similar", params={"k": 21}).status_code == 422


def test_base_injoignable_donne_503():
    """Panne de la base → 503 propre, jamais un 500 brut."""
    app.dependency_overrides[get_repository] = lambda: FakeRepository(error=RuntimeError("DB down"))
    try:
        with TestClient(app) as client:
            assert client.get("/films/41").status_code == 503
            assert client.get("/films/41/similar").status_code == 503
    finally:
        app.dependency_overrides.clear()
