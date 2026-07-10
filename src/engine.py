"""Le moteur : pont entre le contrat de l'API et le graphe multi-agent.

Implémente :class:`~src.contracts.interfaces.AgentEngine` au-dessus de l'``app``
compilé par ``graph/pipeline.py``. L'API ne connaît que l'abstraction : on
branche ce moteur (ou un fake dans les tests) sans toucher aux routes.

Robustesse (pattern HorRAGor2) : ``run`` ne lève JAMAIS — récursion excessive
ou panne technique → réponse de repli assumée, jamais de 500 pour le Front.
Le graphe est synchrone : on l'exécute via ``asyncio.to_thread`` pour ne pas
geler la boucle d'événements FastAPI (le ContextVar de trace se propage).
"""

import asyncio
from functools import lru_cache

from langgraph.errors import GraphRecursionError
from loguru import logger

from src import trace
from src.contracts.interfaces import AgentEngine
from src.contracts.schemas import ChatRequest, ChatResponse
from src.graph import pipeline

# Garde-fou anti-boucle : suffisant pour rag (+outils) → scraper (+outils) → narration.
RECURSION_LIMIT = 25

# Repli gothique : on avoue l'échec avec le ton de la maison, sans inventer de faits.
FALLBACK_ANSWER = (
    "Les brumes se sont refermées sur mon grimoire : quelque chose s'est égaré "
    "dans les profondeurs du manoir. Repose ta question, âme courageuse — "
    "les esprits sont parfois capricieux."
)

# Les kinds de trace qui comptent comme « sources » de la réponse (traçabilité
# anti-hallucination côté Front).
_SOURCE_KINDS = {"faiss", "sql", "pgvector", "tmdb", "wikipedia", "ddg"}


class GraphEngine:
    """Moteur de production : exécute le graphe multi-agent compilé."""

    def __init__(self, graph=None):
        """Initialise le moteur.

        Args:
            graph: Graphe compilé injectable (tests) ; par défaut
                ``pipeline.app``, le livrable du brief.
        """
        self._graph = graph or pipeline.app

    async def run(self, req: ChatRequest) -> ChatResponse:
        """Traite une question de bout en bout (jamais d'exception).

        Args:
            req: La requête du Front (message + session_id).

        Returns:
            La réponse complète : récit, parcours des agents, sources, trace.
        """
        events = trace.begin()
        try:
            result = await asyncio.to_thread(
                self._graph.invoke,
                {"question": req.message},
                self._invoke_config(req),
            )
            answer = (result.get("story") or "").strip() or FALLBACK_ANSWER
            response = ChatResponse(
                answer=answer,
                path=result.get("path") or [],
                sources=self._sources_from(events),
                trace=events,
            )
        except GraphRecursionError:
            logger.warning("Graphe interrompu : limite de récursion ({})", RECURSION_LIMIT)
            trace.record("node", "engine", "limite de récursion atteinte")
            response = ChatResponse(answer=FALLBACK_ANSWER, trace=events)
        except Exception:  # noqa: BLE001 — jamais de 500 pour le Front
            logger.exception("Échec technique du graphe")
            trace.record("node", "engine", "échec technique")
            response = ChatResponse(answer=FALLBACK_ANSWER, trace=events)
        trace.log_trace(req.message, response)
        return response

    @staticmethod
    def _invoke_config(req: ChatRequest) -> dict:
        """Construit la config d'invocation du graphe.

        Point d'ancrage du monitoring : la Phase E y ajoutera le
        ``CallbackHandler`` Langfuse (``config={"callbacks": [...]}``),
        corrélé au ``session_id`` de la requête.

        Args:
            req: La requête courante.

        Returns:
            La config LangGraph (limite de récursion, callbacks à venir).
        """
        return {"recursion_limit": RECURSION_LIMIT}

    @staticmethod
    def _sources_from(events) -> list[str]:
        """Dérive la liste des sources depuis la trace du run.

        Args:
            events: Les TraceSteps collectés pendant le run.

        Returns:
            Les noms d'outils/sources uniques, dans l'ordre d'apparition.
        """
        seen: list[str] = []
        for step in events:
            if step.kind in _SOURCE_KINDS and step.name not in seen:
                seen.append(step.name)
        return seen


@lru_cache(maxsize=1)
def _engine() -> GraphEngine:
    """Construit le moteur une seule fois (lazy : au premier /chat).

    Returns:
        Le moteur singleton.
    """
    return GraphEngine()


def get_engine() -> AgentEngine:
    """Fournit le moteur aux routes FastAPI (surchargé par les tests).

    Returns:
        L'implémentation d'AgentEngine active.
    """
    return _engine()
