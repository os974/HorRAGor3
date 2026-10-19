"""Les Aiguilleurs (la logique décisionnelle) : les arêtes conditionnelles.

Règle d'or LangGraph (brief) : une fonction de routage examine l'état actuel
et sa SEULE responsabilité est de renvoyer une chaîne de caractères — la
prochaine destination. Aucune écriture dans le State, aucun appel LLM.

C'est ici que vivent les **règles logiques** du réseau (brief, p. 3) : « le
message de l'agent RAG contient-il assez d'informations ? Si oui, renvoie
"narration", sinon "scraper" ». Le nœud RAG se contente de récolter
(``lore``) ; le routeur juge cette récolte et aiguille.

Isoler ces fonctions permet de tester l'intelligence algorithmique du réseau
de manière unitaire, sans lancer le pipeline (states forgés à la main).
"""

from typing import Literal

from src import trace
from src.models.state import AgentState

# Indices (déterministes) d'une demande d'informations que la base locale ne
# possède PAS : elle stocke métadonnées et synopsis, jamais les coulisses.
# Une question qui contient l'un de ces mots exige l'Enquêteur du Web, même
# si le film est trouvé localement.
_WEB_ONLY_HINTS = (
    "anecdote",
    "coulisse",
    "tournage",
    "making of",
    "making-of",
    "behind the scenes",
    "trivia",
    "secret",
    "réception",
    "interview",
)


def wants_web_details(question: str) -> bool:
    """Détecte une demande d'informations hors du périmètre de la base locale.

    La base (HorRAGor1) contient métadonnées et synopsis — pas les anecdotes,
    coulisses de tournage ou la réception critique. Pour ces demandes, la
    récolte locale n'est JAMAIS suffisante : l'Enquêteur doit partir, même si
    le film est connu. Détection par mots-clés : déterministe et testable.

    Args:
        question: La question brute de l'utilisateur.

    Returns:
        True si la question réclame des informations que seul le web possède.
    """
    q = question.lower()
    return any(hint in q for hint in _WEB_ONLY_HINTS)


def should_scrape_or_narrate(state: AgentState) -> Literal["scraper", "narration"]:
    """L'aiguillage stratégique du brief : la récolte locale suffit-elle ?

    Deux critères, tous deux déterministes (zéro LLM dans la décision) :
    le Chercheur a récolté des faits (``lore`` non vide : au moins un outil a
    marqué ``"found": true``), ET la question ne réclame pas d'informations
    hors du périmètre local (:func:`wants_web_details`). Si oui → directement
    chez l'Écrivain ; sinon → on déroute le flux vers l'Enquêteur du Web.

    Args:
        state: L'état courant (``question`` et ``lore``).

    Returns:
        "narration" si la récolte locale est suffisante, sinon "scraper".
    """
    has_lore = bool(state.get("lore"))
    needs_web = wants_web_details(state.get("question") or "")
    destination = "narration" if has_lore and not needs_web else "scraper"
    if not has_lore:
        reason = "récolte locale vide"
    elif needs_web:
        reason = "détails web exigés par la question"
    else:
        reason = "récolte locale suffisante"
    trace.record("router", "should_scrape_or_narrate", f"{reason} → {destination}")
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
