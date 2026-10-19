"""API Données avec un repository factice : contrat HTTP de la couche Données."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from services.data_api import main as data_api
from services.data_api.main import app, get_repository
from src import auth
from src.auth import require_access
from src.config import settings
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


@pytest.fixture
def client():
    """TestClient : repository factice peuplé d'Hereditary, appelant authentifié.

    L'authentification a ses propres tests ci-dessous ; ici, le jeton relayé
    par l'API IA est réputé valide.
    """
    fake = FakeRepository(
        metadata=FilmMetadata(id=41, title="Hereditary", release_year=2018),
        similar=[FilmRef(id=1, title="Mara"), FilmRef(id=2, title="The Unknown")],
    )
    app.dependency_overrides[get_repository] = lambda: fake
    app.dependency_overrides[require_access] = lambda: "testeur"
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_sonde_aussi_la_base(client, monkeypatch):
    """Le pouls de la couche Données, base comprise (Docker, Uptime Kuma)."""
    monkeypatch.setattr(data_api, "database_ok", lambda: True)
    assert client.get("/health").json() == {"status": "ok", "db": "ok"}


def test_health_base_injoignable_donne_503(client, monkeypatch):
    """Base muette → 503 explicite : la sonde Kuma de la chaîne passe au rouge."""
    monkeypatch.setattr(data_api, "database_ok", lambda: False)
    resp = client.get("/health")
    assert resp.status_code == 503 and resp.json()["db"] == "injoignable"


def test_database_ok_ne_leve_jamais(monkeypatch):
    """Moteur introuvable (DATABASE_URL absente) → False, jamais d'exception."""

    def boom():
        raise RuntimeError("DATABASE_URL non défini")

    monkeypatch.setattr(data_api, "get_engine", boom)
    assert data_api.database_ok() is False


def test_films_exige_le_jeton_de_l_utilisateur(monkeypatch):
    """Sans jeton relayé → 401 ; avec l'access token d'un compte → 200."""
    monkeypatch.setattr(settings, "jwt_secret", "s" * 32)  # longueur HS256 recommandée
    fake = FakeRepository(metadata=FilmMetadata(id=41, title="Hereditary"))
    app.dependency_overrides[get_repository] = lambda: fake
    try:
        with TestClient(app) as client:
            assert client.get("/films/41").status_code == 401
            token = auth._create_token("olivier", "access", timedelta(minutes=5))
            resp = client.get("/films/41", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()


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
    app.dependency_overrides[require_access] = lambda: "testeur"
    try:
        with TestClient(app) as client:
            assert client.get("/films/41").status_code == 503
            assert client.get("/films/41/similar").status_code == 503
    finally:
        app.dependency_overrides.clear()
