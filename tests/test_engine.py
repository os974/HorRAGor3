"""GraphEngine : contrat AgentEngine, robustesse jamais-de-500, sources."""

import sys
import types

import pytest
from langgraph.errors import GraphRecursionError

from src import trace
from src.config import settings
from src.contracts.schemas import ChatRequest, TraceStep
from src.engine import FALLBACK_ANSWER, GraphEngine, _langfuse_callbacks


@pytest.fixture(autouse=True)
def _isole_le_monitoring(monkeypatch, tmp_path):
    """Neutralise Langfuse (clés vides) et détourne le journal des runs."""
    monkeypatch.setattr(settings, "langfuse_public_key", "")
    monkeypatch.setattr(settings, "langfuse_secret_key", "")
    _langfuse_callbacks.cache_clear()
    monkeypatch.setattr(trace, "_LOG_PATH", tmp_path / "traces.jsonl")
    yield
    _langfuse_callbacks.cache_clear()


class FakeGraph:
    """Double du graphe compilé : renvoie un résultat fixe ou lève."""

    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def invoke(self, inputs, config):
        if self._error:
            raise self._error
        return self._result


async def test_run_transforme_le_state_en_reponse():
    """story → answer, path conservé, trace embarquée."""
    engine = GraphEngine(graph=FakeGraph({"story": "récit", "path": ["rag", "narration"]}))
    resp = await engine.run(ChatRequest(message="q"))
    assert resp.answer == "récit"
    assert resp.path == ["rag", "narration"]


async def test_recursion_donne_le_repli_gothique():
    """Limite de récursion → réponse de repli, jamais d'exception."""
    engine = GraphEngine(graph=FakeGraph(error=GraphRecursionError("boucle")))
    resp = await engine.run(ChatRequest(message="q"))
    assert resp.answer == FALLBACK_ANSWER


async def test_panne_technique_donne_le_repli():
    """Toute exception du graphe → repli assumé (pas de 500 pour le Front)."""
    engine = GraphEngine(graph=FakeGraph(error=RuntimeError("kaboom")))
    resp = await engine.run(ChatRequest(message="q"))
    assert resp.answer == FALLBACK_ANSWER


async def test_story_vide_donne_le_repli():
    """Un graphe qui termine sans récit → repli plutôt que réponse vide."""
    engine = GraphEngine(graph=FakeGraph({"story": "  ", "path": ["rag"]}))
    resp = await engine.run(ChatRequest(message="q"))
    assert resp.answer == FALLBACK_ANSWER


def test_sources_derivees_de_la_trace():
    """Seuls les kinds « source » comptent, uniques, ordre préservé."""
    events = [
        TraceStep(kind="node", name="rag"),
        TraceStep(kind="faiss", name="validate_film"),
        TraceStep(kind="sql", name="get_metadata"),
        TraceStep(kind="faiss", name="validate_film"),
        TraceStep(kind="router", name="should_scrape_or_narrate"),
    ]
    assert GraphEngine._sources_from(events) == ["validate_film", "get_metadata"]


def test_langfuse_desactive_sans_cles():
    """Fail-open : pas de clés → pas de callbacks, l'app vit sa vie."""
    assert _langfuse_callbacks() == ()


def _with_keys(monkeypatch):
    """Clés Langfuse renseignées (le monitoring est censé s'activer)."""
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-lf-test")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-lf-test")


def test_langfuse_active_avec_cles(monkeypatch):
    """Clés présentes → le client est initialisé et le handler branché."""
    _with_keys(monkeypatch)
    clients = []
    fake_sdk = types.ModuleType("langfuse")
    fake_sdk.Langfuse = lambda **kwargs: clients.append(kwargs)
    fake_integration = types.ModuleType("langfuse.langchain")
    fake_integration.CallbackHandler = lambda: "handler"
    monkeypatch.setitem(sys.modules, "langfuse", fake_sdk)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", fake_integration)

    assert _langfuse_callbacks() == ("handler",)
    assert clients[0]["public_key"] == "pk-lf-test"


def test_langfuse_fail_open_si_le_sdk_plante(monkeypatch):
    """Clés présentes mais SDK inutilisable → aucun callback, jamais d'erreur."""
    _with_keys(monkeypatch)
    monkeypatch.setitem(sys.modules, "langfuse", None)  # import → ImportError

    assert _langfuse_callbacks() == ()


async def test_config_invoke_sans_monitoring():
    """Sans Langfuse, la config ne contient que la limite de récursion."""
    config = GraphEngine._invoke_config(ChatRequest(message="q"))
    assert "callbacks" not in config
    assert config["recursion_limit"] > 0
