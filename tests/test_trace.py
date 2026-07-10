"""Trace ContextVar : collecte par run, no-op hors run, persistance best-effort."""

import json

from src import trace
from src.contracts.schemas import ChatResponse


def test_record_collecte_pendant_un_run():
    """begin() ouvre la collecte ; record() y ajoute des étapes tronquées."""
    events = trace.begin()
    trace.record("node", "rag", "x" * 500)
    assert len(events) == 1
    assert events[0].kind == "node"
    assert len(events[0].detail) == 300  # tronqué


def test_record_no_op_hors_run():
    """Sans begin() (scripts offline), record() ne fait rien et ne casse rien."""
    trace._events.set(None)
    trace.record("node", "rag", "perdu")  # ne doit pas lever


def test_log_trace_ecrit_une_ligne_json(monkeypatch, tmp_path):
    """Chaque run persiste 1 ligne JSON complète dans traces.jsonl."""
    log_file = tmp_path / "traces.jsonl"
    monkeypatch.setattr(trace, "_LOG_PATH", log_file)
    response = ChatResponse(answer="récit", path=["rag", "narration"])

    trace.log_trace("question ?", response)

    record = json.loads(log_file.read_text().strip())
    assert record["question"] == "question ?"
    assert record["path"] == ["rag", "narration"]


def test_log_trace_best_effort(monkeypatch, tmp_path):
    """Chemin inécrivable → warning, jamais d'exception (fail-open)."""
    monkeypatch.setattr(trace, "_LOG_PATH", tmp_path)  # un dossier : open() échoue
    trace.log_trace("q", ChatResponse(answer="a"))  # ne doit pas lever
