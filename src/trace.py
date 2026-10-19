"""Trace fine du raisonnement multi-agent (mécanisme repris de HorRAGor2).

Un ``ContextVar`` porte la liste d'événements du run courant : n'importe quelle
fonction profonde (nœud, outil, routeur) appelle :func:`record` pour s'y
ajouter, sans faire transiter un collecteur dans toutes les signatures — et
sans violer la pureté des nœuds (ce module ne dépend que de config/contracts).

``asyncio.to_thread`` (utilisé pour exécuter le graphe synchrone depuis
FastAPI) propage le contexte au thread : les sous-appels y sont bien capturés.

Complémentarité avec le reste de l'observabilité :
    - Loguru (``logging_conf``) = logs applicatifs continus ;
    - Langfuse (Phase E) = traces LLM détaillées côté serveur ;
    - ce module = le résumé du parcours renvoyé au Front dans ``ChatResponse``.
"""

import contextvars
import json
from datetime import UTC, datetime

from loguru import logger

from src.config import _PROJECT_ROOT
from src.contracts.schemas import ChatResponse, TraceStep

_events: contextvars.ContextVar[list[TraceStep] | None] = contextvars.ContextVar(
    "trace_events", default=None
)
_LOG_PATH = _PROJECT_ROOT / "logs" / "traces.jsonl"


def begin() -> list[TraceStep]:
    """Démarre une nouvelle trace (début d'un run).

    Returns:
        La liste collectrice, vide, dans laquelle :func:`record` accumulera
        les étapes du run courant.
    """
    events: list[TraceStep] = []
    _events.set(events)
    return events


def record(kind: str, name: str, detail: str = "") -> None:
    """Ajoute une étape à la trace courante.

    No-op hors d'un run (ex. scripts offline) : aucune fonction n'a besoin de
    savoir si une trace est active.

    Args:
        kind: Type d'étape — "node" | "router" pour le graphe, ou la source
            interrogée : "embed" | "faiss" | "sql" | "pgvector" | "tmdb" |
            "wikipedia" | "ddg".
        name: Nom du nœud, de l'outil ou de l'événement.
        detail: Contexte libre, tronqué à 300 caractères.
    """
    events = _events.get()
    if events is not None:
        events.append(TraceStep(kind=kind, name=name, detail=str(detail)[:300]))


def log_trace(question: str, response: ChatResponse, session_id: str = "") -> None:
    """Persiste un run complet (1 ligne JSON) dans ``logs/traces.jsonl``.

    Best-effort : le logging ne doit jamais casser la réponse (fail-open,
    règle observabilité du projet).

    Args:
        question: Message utilisateur du run.
        response: Réponse complète renvoyée au Front.
        session_id: Conversation d'origine (corrélation avec Loguru et Langfuse).
    """
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record_obj = {
            "ts": datetime.now(UTC).isoformat(),
            "session_id": session_id,
            "question": question,
            "answer": response.answer,
            "path": response.path,
            "sources": response.sources,
            "trace": [step.model_dump() for step in response.trace],
        }
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record_obj, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        logger.warning("Écriture de logs/traces.jsonl impossible (run non persisté)")
