"""Les Aiguilleurs (la logique décisionnelle) : les arêtes conditionnelles.

Règle d'or LangGraph (brief) : une fonction de routage examine l'état actuel
et sa SEULE responsabilité est de renvoyer une chaîne de caractères — la
prochaine destination. Aucune écriture dans le State, aucun appel LLM :
« le nœud juge, le routeur aiguille ».

Isoler ces fonctions permet de tester l'intelligence algorithmique du réseau
de manière unitaire, sans lancer le pipeline (states forgés à la main).
"""

from typing import Literal

from src import trace
from src.models.state import AgentState


def should_scrape_or_narrate(state: AgentState) -> Literal["scraper", "narration"]:
    """L'aiguillage stratégique du brief : la récolte locale suffit-elle ?

    Lit ``is_complete``, posé par le nœud RAG (jugement déterministe sur les
    résultats d'outils). Si oui → directement chez l'Écrivain ; sinon → on
    déroute le flux vers l'Enquêteur du Web.

    Args:
        state: L'état courant.

    Returns:
        "narration" si la récolte locale est suffisante, sinon "scraper".
    """
    destination = "narration" if state.get("is_complete") else "scraper"
    trace.record(
        "router",
        "should_scrape_or_narrate",
        f"is_complete={bool(state.get('is_complete'))} → {destination}",
    )
    return destination


def should_continue_rag(state: AgentState) -> Literal["rag_tools", "scraper", "narration"]:
    """Micro-boucle du Chercheur, puis passage de relais.

    Si le dernier message du canal RAG contient des tool_calls, l'agent veut
    utiliser ses outils → "rag_tools". Sinon sa fouille est close et on
    délègue l'aiguillage stratégique à :func:`should_scrape_or_narrate`.

    Args:
        state: L'état courant (``rag_messages`` non vide à ce stade).

    Returns:
        "rag_tools", "scraper" ou "narration".
    """
    last = (state.get("rag_messages") or [None])[-1]
    if getattr(last, "tool_calls", None):
        return "rag_tools"
    return should_scrape_or_narrate(state)


def should_continue_scraper(state: AgentState) -> Literal["scraper_tools", "narration"]:
    """Micro-boucle de l'Enquêteur, puis relais vers la plume.

    Args:
        state: L'état courant (``scraper_messages`` non vide à ce stade).

    Returns:
        "scraper_tools" si l'agent demande un outil, sinon "narration".
    """
    last = (state.get("scraper_messages") or [None])[-1]
    if getattr(last, "tool_calls", None):
        return "scraper_tools"
    return "narration"
