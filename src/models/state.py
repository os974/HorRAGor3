"""Le State : la mémoire commune que les agents se passent en relais (brief).

Choix structurant — **un canal de messages PAR agent** (``rag_messages``,
``scraper_messages``) plutôt qu'un historique unique : c'est l'isolation de
contexte (*context trimming*) demandée par le brief. Chaque agent ne voit que
sa propre micro-conversation ; la Narration ne reçoit AUCUN message, seulement
le dossier synthétique (``lore`` + ``web_findings``). Bénéfices : pas de
collision de tokens entre agents, pas de paresse de génération, et un Écrivain
Gothique jamais noyé dans les logs techniques.

Mémoire de session : le graphe est compilé avec un checkpointer, et chaque
conversation (``thread_id`` = compte utilisateur + ``session_id``) retrouve
son State d'un tour à l'autre. Seul ``history`` est fait pour durer : à chaque
nouvelle question, le moteur remet à zéro les canaux des agents et les cases
du dossier, pour que le context trimming tienne sur toute la conversation.

Reducers :
    - ``add_messages`` : les nouveaux messages s'AJOUTENT (micro-boucle outil) ;
      ``RemoveMessage(id=REMOVE_ALL_MESSAGES)`` vide le canal en début de tour ;
    - :func:`extend_path` sur ``path`` : chaque nœud traversé s'enregistre, une
      liste vide ouvre un nouveau tour ;
    - :func:`keep_recent_exchanges` sur ``history`` : la fenêtre glissante des
      derniers échanges de la conversation.

Les autres clés sont écrasées à chaque écriture (comportement par défaut) :
ce sont des « cases » du dossier que chaque agent remplit une fois par tour.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# Échanges (question + réponse) gardés en mémoire par conversation : assez pour
# comprendre une relance (« et son réalisateur ? »), trop peu pour saturer.
MEMORY_EXCHANGES = 3


def extend_path(left: list[str] | None, right: list[str] | None) -> list[str]:
    """Reducer de ``path`` : ajoute les nœuds traversés, une liste vide remet à zéro.

    Args:
        left: Le parcours déjà enregistré.
        right: Les nœuds à ajouter, ou ``[]`` pour ouvrir un nouveau tour.

    Returns:
        Le parcours mis à jour.
    """
    if not right:
        return []
    return [*(left or []), *right]


def keep_recent_exchanges(
    left: list[BaseMessage] | None, right: list[BaseMessage] | None
) -> list[BaseMessage]:
    """Reducer de ``history`` : ajoute l'échange du tour, garde les plus récents.

    Args:
        left: L'historique déjà mémorisé.
        right: Les messages du tour (question du visiteur, puis récit).

    Returns:
        Les ``MEMORY_EXCHANGES`` derniers échanges (deux messages chacun).
    """
    return [*(left or []), *(right or [])][-2 * MEMORY_EXCHANGES :]


class AgentState(TypedDict, total=False):
    """Mémoire commune du graphe multi-agent.

    Attributes:
        question: La demande utilisateur brute (seule entrée obligatoire).
        rag_messages: Micro-conversation de l'Agent RAG (system, human,
            tool calls, tool results) — invisible aux autres agents.
        scraper_messages: Micro-conversation de l'Agent Scraper — idem.
        lore: Synthèse factuelle de la récolte locale (contenus bruts des
            outils FAISS/SQL/pgvector ayant trouvé des données). Jugée par le
            routeur ``should_scrape_or_narrate`` : vide, ou question qui
            réclame des infos hors du périmètre local (anecdotes, coulisses...
            cf. ``router.wants_web_details``) → l'Enquêteur du Web part.
        web_findings: Synthèse factuelle de l'enquête web (Scraper).
        story: La réponse finale de l'Écrivain Gothique.
        path: Nœuds traversés dans l'ordre pendant le tour (ex. ["rag",
            "scraper", "narration"]) — renvoyé au Front via ``ChatResponse.path``.
        history: Mémoire de la conversation : les derniers échanges (question
            du visiteur, récit rendu), conservés d'un tour à l'autre et lus
            par le Chercheur et l'Enquêteur pour comprendre les relances.
    """

    question: str
    rag_messages: Annotated[list, add_messages]
    scraper_messages: Annotated[list, add_messages]
    lore: str
    web_findings: str
    story: str
    path: Annotated[list[str], extend_path]
    history: Annotated[list[BaseMessage], keep_recent_exchanges]
