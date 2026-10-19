"""L'API FastAPI avec un moteur factice : contrat HTTP sans LLM ni FAISS."""

import pytest
from fastapi.testclient import TestClient
from loguru import logger

import src.main as main
from src.auth import require_access
from src.contracts.schemas import ChatRequest, ChatResponse
from src.engine import get_engine


class FakeEngine:
    """Double d'AgentEngine : réponse fixe, instantanée."""

    async def run(self, req: ChatRequest, user: str = "anonyme") -> ChatResponse:
        return ChatResponse(
            answer=f"BOUH:{req.message}",
            path=["rag", "narration"],
            sources=["validate_film"],
        )


@pytest.fixture
def client(monkeypatch):
    """TestClient : index FAISS absent, moteur factice, auth court-circuitée.

    L'auth JWT a ses propres tests (test_auth.py) ; ici on teste le contrat
    HTTP des routes métier, visiteur déjà authentifié.
    """
    monkeypatch.setattr(main.TitleIndex, "exists", classmethod(lambda cls, d=None: False))
    main.app.dependency_overrides[get_engine] = lambda: FakeEngine()
    main.app.dependency_overrides[require_access] = lambda: "testeur"
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def test_health(client):
    """Le pouls du serveur (CI, Docker, Uptime Kuma)."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_metrics_prometheus_expose(client):
    """/metrics naît avec le service (règle observabilité)."""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "http_request" in resp.text


def test_chat_delegue_au_moteur(client):
    """POST /chat → le contrat ChatResponse, moteur interchangeable."""
    resp = client.post("/chat", json={"message": "Alien ?", "session_id": "t"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "BOUH:Alien ?"
    assert body["path"] == ["rag", "narration"]


def test_chat_pose_les_ids_de_correlation_dans_les_logs(client):
    """Chaque ligne de log de /chat porte session_id et request_id (champ extra)."""
    records: list[dict] = []
    handler_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        client.post("/chat", json={"message": "Alien ?", "session_id": "conv-42"})
    finally:
        logger.remove(handler_id)
    chat_logs = [r for r in records if "POST /chat" in r["message"]]
    assert chat_logs
    assert chat_logs[0]["extra"]["session_id"] == "conv-42"
    assert len(chat_logs[0]["extra"]["request_id"]) == 8


def test_chat_valide_la_requete(client):
    """Requête sans message → 422 (validation Pydantic automatique)."""
    assert client.post("/chat", json={}).status_code == 422
