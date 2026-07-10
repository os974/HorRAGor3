"""Auth JWT : login, verrou des routes métier, refresh, expiration."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import src.main as main
from src.auth import _create_token
from src.config import settings
from src.contracts.schemas import ChatRequest, ChatResponse
from src.engine import get_engine


class FakeEngine:
    """Moteur factice : la route /chat répond sans graphe ni LLM."""

    async def run(self, req: ChatRequest) -> ChatResponse:
        return ChatResponse(answer="bouh")


@pytest.fixture
def client(monkeypatch):
    """TestClient avec auth configurée (compte démo) et moteur factice."""
    monkeypatch.setattr(settings, "jwt_secret", "secret-de-test")
    monkeypatch.setattr(settings, "app_username", "demo")
    monkeypatch.setattr(settings, "app_password", "abracadabra")
    monkeypatch.setattr(main.TitleIndex, "exists", classmethod(lambda cls, d=None: False))
    main.app.dependency_overrides[get_engine] = lambda: FakeEngine()
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def _login(client) -> dict:
    """Raccourci : login du compte démo, renvoie la paire de jetons."""
    resp = client.post("/auth/login", json={"username": "demo", "password": "abracadabra"})
    assert resp.status_code == 200
    return resp.json()


def test_login_emet_la_paire(client):
    """Identifiants valides → access + refresh."""
    tokens = _login(client)
    assert tokens["access_token"] and tokens["refresh_token"]
    assert tokens["token_type"] == "bearer"


def test_login_refuse_les_mauvais_identifiants(client):
    """Mauvais mot de passe → 401, sans fuite d'information."""
    resp = client.post("/auth/login", json={"username": "demo", "password": "faux"})
    assert resp.status_code == 401


def test_login_non_configure(client, monkeypatch):
    """JWT_SECRET absent → 503 explicite (auth non configurée)."""
    monkeypatch.setattr(settings, "jwt_secret", "")
    resp = client.post("/auth/login", json={"username": "demo", "password": "abracadabra"})
    assert resp.status_code == 503


def test_chat_verrouille_sans_jeton(client):
    """Le brief : les échanges avec l'IHM sont verrouillés — 401 sans Bearer."""
    resp = client.post("/chat", json={"message": "bouh"})
    assert resp.status_code == 401


def test_chat_refuse_un_jeton_bidon(client):
    """Jeton forgé/altéré → 401."""
    resp = client.post(
        "/chat", json={"message": "bouh"}, headers={"Authorization": "Bearer n.importe.quoi"}
    )
    assert resp.status_code == 401


def test_chat_accepte_un_access_valide(client):
    """Le porteur d'un access token valide passe la porte."""
    tokens = _login(client)
    resp = client.post(
        "/chat",
        json={"message": "bouh"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["answer"] == "bouh"


def test_refresh_renouvelle_la_paire(client):
    """Le refresh token émet une paire neuve, utilisable sur /chat."""
    tokens = _login(client)
    resp = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    new_access = resp.json()["access_token"]
    chat = client.post(
        "/chat", json={"message": "re"}, headers={"Authorization": f"Bearer {new_access}"}
    )
    assert chat.status_code == 200


def test_un_refresh_ne_passe_pas_en_access(client):
    """Contrôle du type : un refresh token présenté sur /chat → 401."""
    tokens = _login(client)
    resp = client.post(
        "/chat",
        json={"message": "bouh"},
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
    )
    assert resp.status_code == 401


def test_un_access_ne_passe_pas_en_refresh(client):
    """Et l'inverse : un access token sur /auth/refresh → 401."""
    tokens = _login(client)
    resp = client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401


def test_jeton_expire(client):
    """Un access token périmé → 401 « jeton expiré »."""
    expired = _create_token("demo", "access", timedelta(seconds=-1))
    resp = client.post(
        "/chat", json={"message": "bouh"}, headers={"Authorization": f"Bearer {expired}"}
    )
    assert resp.status_code == 401
    assert "expiré" in resp.json()["detail"]
