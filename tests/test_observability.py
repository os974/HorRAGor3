"""Une trace Langfuse par requête métier : middleware fail-open, sans réseau."""

import sys
import types
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import observability
from src.config import settings
from src.observability import LangfuseRequestMiddleware, tag_current_trace


class FakeSpan:
    """Span factice : mémorise ses mises à jour."""

    def __init__(self):
        self.updates: list[dict] = []
        self.trace_updates: list[dict] = []

    def update(self, **kwargs):
        self.updates.append(kwargs)

    def update_trace(self, **kwargs):
        self.trace_updates.append(kwargs)


class FakeClient:
    """Client Langfuse factice : une span par requête, attributs de trace notés."""

    def __init__(self, fail=False):
        self.spans: list[tuple[str, FakeSpan]] = []
        self.current_trace: list[dict] = []
        self._fail = fail

    @contextmanager
    def start_as_current_span(self, name, input=None):
        if self._fail:
            raise RuntimeError("Langfuse en panne")
        span = FakeSpan()
        self.spans.append((name, span))
        yield span

    def update_current_trace(self, **kwargs):
        self.current_trace.append(kwargs)


def _app(monkeypatch, client) -> TestClient:
    """Mini-API instrumentée, avec le client Langfuse factice injecté."""
    monkeypatch.setattr(observability, "langfuse_client", lambda: client)
    app = FastAPI()
    app.add_middleware(LangfuseRequestMiddleware, service="api-test")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/films/{film_id}")
    async def film(film_id: int):
        tag_current_trace(user_id="olivier")
        return {"id": film_id}

    @app.get("/boom")
    async def boom():
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="base injoignable")

    return TestClient(app)


def test_chaque_requete_metier_ouvre_une_trace(monkeypatch):
    """Requête métier → une span « méthode route », statut et service consignés."""
    client = FakeClient()
    http = _app(monkeypatch, client)

    assert http.get("/films/41").status_code == 200

    name, span = client.spans[0]
    assert name == "GET /films/41"
    assert span.updates[0]["output"] == {"status_code": 200}
    assert span.trace_updates[0]["tags"] == ["api-test"]
    assert client.current_trace == [{"user_id": "olivier"}]  # rattachée au compte


def test_sondes_non_tracees(monkeypatch):
    """/health (sondes Docker, Kuma) n'encombre pas Langfuse."""
    client = FakeClient()
    http = _app(monkeypatch, client)

    assert http.get("/health").status_code == 200
    assert client.spans == []


def test_erreur_serveur_marquee(monkeypatch):
    """Statut 5xx → span au niveau ERROR."""
    client = FakeClient()
    http = _app(monkeypatch, client)

    assert http.get("/boom").status_code == 503
    assert client.spans[0][1].updates[0]["level"] == "ERROR"


def test_langfuse_en_panne_ne_casse_rien(monkeypatch):
    """Fail-open : la span ne s'ouvre pas, la requête aboutit quand même."""
    http = _app(monkeypatch, FakeClient(fail=True))

    assert http.get("/films/41").status_code == 200


def test_sans_langfuse_tout_passe(monkeypatch):
    """Clés absentes (conftest) → aucun client, middleware transparent."""
    http = _app(monkeypatch, None)

    assert http.get("/films/41").json() == {"id": 41}


def test_client_cree_avec_les_cles(monkeypatch):
    """Clés présentes → client initialisé depuis settings."""
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-lf-test")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-lf-test")
    created = []
    fake_sdk = types.ModuleType("langfuse")
    fake_sdk.Langfuse = lambda **kwargs: created.append(kwargs) or "client"
    monkeypatch.setitem(sys.modules, "langfuse", fake_sdk)

    assert observability.langfuse_client() == "client"
    assert created[0]["public_key"] == "pk-lf-test"


def test_client_absent_si_sdk_inutilisable(monkeypatch):
    """Clés présentes mais SDK cassé → None, jamais d'erreur."""
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-lf-test")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-lf-test")
    monkeypatch.setitem(sys.modules, "langfuse", None)

    assert observability.langfuse_client() is None
