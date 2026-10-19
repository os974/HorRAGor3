"""Le moteur : pont entre le contrat de l'API et le graphe multi-agent.

Implémente :class:`~src.contracts.interfaces.AgentEngine` au-dessus de l'``app``
compilé par ``graph/pipeline.py``. L'API ne connaît que l'abstraction : on
branche ce moteur (ou un fake dans les tests) sans toucher aux routes.

Robustesse (pattern HorRAGor2) : ``run`` ne lève JAMAIS — récursion excessive
ou panne technique → réponse de repli assumée, jamais de 500 pour le Front.
Le graphe est synchrone : on l'exécute via ``asyncio.to_thread`` pour ne pas
geler la boucle d'événements FastAPI (le ContextVar de trace se propage).

Mémoire de session : chaque conversation est un ``thread_id`` du checkpointer,
préfixé par le compte utilisateur — un visiteur ne peut jamais reprendre la
conversation d'un autre, même en devinant son ``session_id``.
"""

import asyncio
from functools import lru_cache

from langchain_core.messages import RemoveMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from loguru import logger

from src import trace
from src.config import settings
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

    async def run(self, req: ChatRequest, user: str = "anonyme") -> ChatResponse:
        """Traite une question de bout en bout (jamais d'exception).

        Args:
            req: La requête du Front (message + session_id).
            user: Le compte authentifié (extrait du jeton par l'API).

        Returns:
            La réponse complète : récit, parcours des agents, sources, trace.
        """
        events = trace.begin()
        try:
            result = await asyncio.to_thread(
                self._graph.invoke,
                self._turn_input(req.message),
                self._invoke_config(req, user),
            )
            answer = (result.get("story") or "").strip() or FALLBACK_ANSWER
            response = ChatResponse(
                answer=answer,
                path=result.get("path") or [],
                sources=self._sources_from(events),
                trace=events,
            )
            # Instrumentation centralisée : les nœuds restent purs, le résumé
            # métier du run est journalisé ici, une fois le graphe terminé.
            logger.info(
                "Graphe : {} (lore {} car., web {} car., récit {} car.)",
                " → ".join(response.path),
                len(result.get("lore") or ""),
                len(result.get("web_findings") or ""),
                len(answer),
            )
        except GraphRecursionError:
            logger.warning("Graphe interrompu : limite de récursion ({})", RECURSION_LIMIT)
            trace.record("node", "engine", "limite de récursion atteinte")
            response = ChatResponse(answer=FALLBACK_ANSWER, trace=events)
        except Exception:  # noqa: BLE001 — jamais de 500 pour le Front
            logger.exception("Échec technique du graphe")
            trace.record("node", "engine", "échec technique")
            response = ChatResponse(answer=FALLBACK_ANSWER, trace=events)
        trace.log_trace(req.message, response, req.session_id)
        return response

    @staticmethod
    def _turn_input(question: str) -> dict:
        """Entrée d'un tour : la question, et les cases de travail remises à zéro.

        Avec la mémoire de session, le State d'une conversation persiste d'une
        question à l'autre : on vide les canaux des agents et le dossier du
        tour précédent pour que chaque agent reparte d'un contexte propre
        (context trimming). Seul ``history`` traverse les tours.

        Args:
            question: La nouvelle question du visiteur.

        Returns:
            Le dict d'entrée du graphe.
        """
        return {
            "question": question,
            "rag_messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
            "scraper_messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
            "lore": "",
            "web_findings": "",
            "story": "",
            "path": [],
        }

    @staticmethod
    def _invoke_config(req: ChatRequest, user: str = "anonyme") -> dict:
        """Construit la config d'invocation du graphe.

        Mémoire de session : ``thread_id`` = compte + ``session_id``. Monitoring
        Langfuse (Phase E) : si les clés sont configurées, le
        ``CallbackHandler`` est passé via ``config={"callbacks": [...]}`` (le
        mécanisme exact du brief), avec la conversation et le compte pour
        regrouper les traces et mesurer les tokens par utilisateur.

        Args:
            req: La requête courante.
            user: Le compte authentifié.

        Returns:
            La config LangGraph (limite de récursion, conversation, callbacks).
        """
        config: dict = {
            "recursion_limit": RECURSION_LIMIT,
            "configurable": {"thread_id": f"{user}:{req.session_id}"},
        }
        callbacks = _langfuse_callbacks()
        if callbacks:
            config["callbacks"] = list(callbacks)
            config["metadata"] = {
                "langfuse_session_id": req.session_id,
                "langfuse_user_id": user,
            }
        return config

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
def _langfuse_callbacks() -> tuple:
    """Construit le CallbackHandler Langfuse une seule fois (fail-open).

    Règle observabilité du projet : l'application fonctionne à l'identique
    sans Langfuse — clés absentes ou serveur éteint → tuple vide, zéro bruit
    dans le run. SDK v3 : l'import vit dans ``langfuse.langchain`` (le snippet
    v2 du brief n'est plus valide) et les clés sont passées au client
    explicitement depuis ``settings`` (pas de ``os.environ`` en dur).

    Returns:
        ``(handler,)`` si Langfuse est configuré et joignable, sinon ``()``.
    """
    if not settings.langfuse_enabled:
        logger.info("Langfuse désactivé (clés absentes du .env)")
        return ()
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler

        # Initialise le client global du SDK v3 avec nos réglages typés.
        Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        handler = CallbackHandler()
        logger.info("Langfuse activé → {}", settings.langfuse_host)
        return (handler,)
    except Exception:  # noqa: BLE001 — le monitoring ne doit jamais bloquer le métier
        logger.warning("Langfuse indisponible : monitoring désactivé (fail-open)")
        return ()


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
