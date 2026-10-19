"""Le State : la mémoire commune que les agents se passent en relais (brief).

Choix structurant — **un canal de messages PAR agent** (``rag_messages``,
``scraper_messages``) plutôt qu'un historique unique : c'est l'isolation de
contexte (*context trimming*) demandée par le brief. Chaque agent ne voit que
sa propre micro-conversation ; la Narration ne reçoit AUCUN message, seulement
le dossier synthétique (``lore`` + ``web_findings``). Bénéfices : pas de
collision de tokens entre agents, pas de paresse de génération, et un Écrivain
Gothique jamais noyé dans les logs techniques.

Reducers :
    - ``add_messages`` : les nouveaux messages s'AJOUTENT (micro-boucle outil) ;
    - ``operator.add`` sur ``path`` : chaque nœud traversé s'enregistre.

Les autres clés sont écrasées à chaque écriture (comportement par défaut) :
ce sont des « cases » du dossier que chaque agent remplit une fois.
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


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
        path: Nœuds traversés dans l'ordre (ex. ["rag", "scraper",
            "narration"]) — renvoyé au Front via ``ChatResponse.path``.
    """

    question: str
    rag_messages: Annotated[list, add_messages]
    scraper_messages: Annotated[list, add_messages]
    lore: str
    web_findings: str
    story: str
    path: Annotated[list[str], operator.add]
