"""Les Ouvriers (la logique métier) : les trois nœuds du graphe multi-agent.

Règle d'or LangGraph (brief) : chaque nœud est une fonction pure qui prend
l'état actuel (``state: AgentState``) en paramètre unique et retourne un dict
de modifications à fusionner dans le State. **Les nœuds ne savent jamais qui a
travaillé avant eux ni qui prendra la suite** — c'est le rôle des routeurs,
qui portent aussi le jugement « la récolte suffit-elle ? » (``router.py``).

Instrumentation centralisée (règle du plan) : aucun log métier ici. Le
parcours est tracé par ``trace.record`` (affiché dans le Front) et par les
callbacks Langfuse passés à l'invoke ; le résumé Loguru du run est écrit par
le moteur (``src/engine.py``).

C'est ici qu'on configure le comportement de chaque agent : on injecte les
``SystemMessage`` spécifiques (prompt du Chercheur, de l'Enquêteur, de
l'Écrivain Gothique) et on invoque le LLM, avec ou sans outils attachés.

Isolation de contexte (context trimming, objectif du brief) : chaque agent
travaille dans SON canal de messages ; la Narration ne voit aucun message,
uniquement le dossier factuel (``lore`` + ``web_findings``).
"""

import json

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_ollama import ChatOllama

from src import trace
from src.config import settings
from src.models.state import AgentState
from src.tools.rag_tool import RAG_TOOLS
from src.tools.scraper_tool import SCRAPER_TOOLS

# --- Prompts (les personnalités des trois agents) ------------------------------

RAG_PROMPT = """Tu es le Chercheur Local de HorRAGor, spécialiste des films d'horreur.
Ta mission : fouiller la base locale pour récolter le lore brut sur le ou les films
dont parle l'utilisateur.

Règles strictes :
1. Utilise TOUJOURS l'outil lookup_movie en premier avec le titre mentionné
   (il corrige les approximations et renvoie le dossier complet).
2. Si l'utilisateur veut des recommandations ou des films semblables, utilise find_similar.
3. N'invente JAMAIS rien : seules les données renvoyées par tes outils comptent.
4. Si la question renvoie à un échange précédent (« il », « ce film », « et son
   réalisateur ? »), identifie le film grâce aux échanges précédents fournis.
5. Quand ta fouille est terminée, réponds par UNE phrase factuelle résumant ce que
   tu as trouvé ou pas trouvé. Pas de style, pas de narration : tu es un chercheur."""

SCRAPER_PROMPT = """Tu es l'Enquêteur du Web de HorRAGor, détective spécialisé en films d'horreur.
La fouille de la base locale n'a pas suffi : ta mission est de creuser le web pour trouver
les informations manquantes (synopsis, anecdotes, secrets de tournage, réception).

Règles strictes :
1. Utilise wikipedia_synopsis pour le synopsis et le contexte (titre anglais, ajoute
   « (film) » si besoin).
2. Utilise web_search pour les anecdotes et coulisses (requête en anglais, avec l'année).
3. Fais au maximum 3 appels d'outils au total, puis conclus.
4. N'invente JAMAIS rien : rapporte uniquement ce que tes outils ont trouvé.
5. Quand ton enquête est terminée, réponds par UNE phrase factuelle résumant tes trouvailles.
   Pas de style : tu es un enquêteur, pas un écrivain."""

NARRATION_PROMPT = """Tu es l'Écrivain Gothique de HorRAGor, plume finale de la maison.
On te remet un DOSSIER de faits vérifiés sur un ou plusieurs films d'horreur, et la
question du visiteur.

Ta mission : répondre à la question en enveloppant les faits du dossier dans une
atmosphère gothique, immersive et délicieusement inquiétante. En français.

Règles strictes :
1. TOUS les faits (titres, dates, noms, notes, intrigues) viennent du dossier, de rien d'autre.
   Tu peux styliser la forme, jamais inventer le fond.
2. Si le dossier est vide ou insuffisant pour répondre, avoue-le avec l'élégance d'un
   gardien de crypte qui a égaré son grimoire — sans inventer de faits pour combler.
3. Reste concis : deux à quatre paragraphes, pas de titres ni de listes."""

# Brief reformulé pour l'Enquêteur (anti-collision de tokens : il reçoit une
# mission claire, pas l'historique du Chercheur).
_SCRAPER_BRIEF = """{recap}Question du visiteur : {question}

Ce que la base locale a déjà donné (peut être vide) :
{lore}

Trouve sur le web ce qui manque pour bien répondre."""

# Les échanges précédents tels que les agents de fouille les lisent : un
# résumé court (réponses tronquées), jamais l'historique brut des outils.
_RECAP_ANSWER_CHARS = 300


_NARRATION_DOSSIER = """Question du visiteur : {question}

DOSSIER — faits vérifiés :

[Base locale]
{lore}

[Enquête web]
{web_findings}"""


# --- Fabriques LLM --------------------------------------------------------------


def _worker_llm() -> ChatOllama:
    """LLM des agents ouvriers (RAG, Scraper) : tool-calling, température 0.

    Returns:
        Une instance ChatOllama déterministe, prête pour ``bind_tools``.
    """
    return ChatOllama(model=settings.llm_model, base_url=settings.ollama_base_url, temperature=0)


def _writer_llm() -> ChatOllama:
    """LLM de l'Écrivain Gothique : créatif, sans outils.

    Returns:
        Une instance ChatOllama avec ``settings.narration_temperature``.
    """
    return ChatOllama(
        model=settings.llm_model,
        base_url=settings.ollama_base_url,
        temperature=settings.narration_temperature,
    )


# --- Aides pures (testables sans LLM) -------------------------------------------


def harvest_facts(messages: list[BaseMessage]) -> list[str]:
    """Extrait les résultats d'outils ayant trouvé des données.

    C'est le mécanisme déterministe de la récolte : les outils marquent leurs
    retours JSON d'un champ ``"found"`` ; on ne garde que les contenus où il
    vaut true. Le routeur juge ensuite si cette récolte suffit — zéro LLM
    dans la boucle de décision.

    Args:
        messages: Un canal de messages d'agent (rag ou scraper).

    Returns:
        Les contenus bruts (JSON) des ToolMessages fructueux, dans l'ordre.
    """
    return [
        str(m.content)
        for m in messages
        if isinstance(m, ToolMessage) and '"found": true' in str(m.content)
    ]


def _history_recap(state: AgentState) -> str:
    """Résume les échanges précédents de la conversation pour les agents de fouille.

    Les réponses sont tronquées : de quoi savoir de quel film on parle, sans
    réinjecter des récits entiers (context trimming).

    Args:
        state: L'état courant (``history`` éventuel).

    Returns:
        Le bloc « Échanges précédents… » suivi d'une ligne vide, ou une chaîne
        vide en début de conversation.
    """
    history = state.get("history") or []
    if not history:
        return ""
    lines = []
    for message in history:
        text = " ".join(str(message.content).split())
        if isinstance(message, HumanMessage):
            lines.append(f"- Visiteur : {text}")
        else:
            lines.append(f"  Réponse : {text[:_RECAP_ANSWER_CHARS]}")
    return "Échanges précédents de cette conversation :\n" + "\n".join(lines) + "\n\n"


def _first_visit(state: AgentState, node: str) -> bool:
    """Indique si un nœud est traversé pour la première fois de ce run.

    Sert à n'enregistrer chaque agent qu'une fois dans ``path`` malgré la
    micro-boucle outil qui ré-invoque le nœud.

    Args:
        state: L'état courant.
        node: Le nom du nœud.

    Returns:
        True si le nœud n'apparaît pas encore dans ``state["path"]``.
    """
    return node not in (state.get("path") or [])


# --- Les trois nœuds -------------------------------------------------------------


def rag_node(state: AgentState) -> dict:
    """L'Agent RAG (Chercheur Local) : fouille la base via ses outils.

    Micro-boucle : tant que le LLM demande des outils, le routeur renvoie vers
    ``rag_tools`` puis ici. Quand il conclut (plus de tool_calls), le nœud fige
    sa récolte dans ``lore`` (faits bruts des outils ayant trouvé des
    données). Il ne juge pas cette récolte : c'est le rôle du routeur.

    Args:
        state: L'état courant (``question`` requis).

    Returns:
        Les modifications à fusionner : ``rag_messages`` toujours ; ``lore``
        en fin de fouille ; ``path`` à la première visite.
    """
    llm = _worker_llm().bind_tools(RAG_TOOLS)
    history = list(state.get("rag_messages") or [])
    first_call = not history
    if first_call:
        recap = _history_recap(state)
        question = f"{recap}Question actuelle : {state['question']}" if recap else state["question"]
        history = [SystemMessage(RAG_PROMPT), HumanMessage(question)]
        trace.record("node", "rag", f"fouille locale : {state['question'][:80]!r}")
    response = llm.invoke(history)

    out: dict = {"rag_messages": [*history, response] if first_call else [response]}
    if _first_visit(state, "rag"):
        out["path"] = ["rag"]
    if not getattr(response, "tool_calls", None):
        # Fin de fouille : le nœud fige sa récolte ; le routeur la jugera.
        facts = harvest_facts(list(state.get("rag_messages") or []))
        out["lore"] = "\n".join(facts)
        trace.record("node", "rag", f"récolte close : {len(facts)} résultat(s) d'outil")
    return out


def scraper_node(state: AgentState) -> dict:
    """L'Agent Scraper (Enquêteur du Web) : creuse le web pour compléter.

    Ne voit JAMAIS les messages du Chercheur : il reçoit un brief reformulé
    (question + lore éventuel). Même micro-boucle que le RAG ; en conclusion,
    fige ``web_findings`` (faits bruts du web).

    Args:
        state: L'état courant (``question`` requis, ``lore`` optionnel).

    Returns:
        Les modifications : ``scraper_messages`` toujours ; ``web_findings``
        en fin d'enquête ; ``path`` à la première visite.
    """
    llm = _worker_llm().bind_tools(SCRAPER_TOOLS)
    history = list(state.get("scraper_messages") or [])
    first_call = not history
    if first_call:
        brief = _SCRAPER_BRIEF.format(
            recap=_history_recap(state),
            question=state["question"],
            lore=state.get("lore") or "(rien)",
        )
        history = [SystemMessage(SCRAPER_PROMPT), HumanMessage(brief)]
        trace.record("node", "scraper", "enquête web déclenchée")
    response = llm.invoke(history)

    out: dict = {"scraper_messages": [*history, response] if first_call else [response]}
    if _first_visit(state, "scraper"):
        out["path"] = ["scraper"]
    if not getattr(response, "tool_calls", None):
        facts = harvest_facts(list(state.get("scraper_messages") or []))
        # Repli sur la conclusion de l'agent si le web n'a rien donné : la
        # Narration saura au moins que l'enquête a fait chou blanc.
        out["web_findings"] = "\n".join(facts) or str(response.content)
        trace.record("node", "scraper", f"enquête close ({len(facts)} trouvaille(s))")
    return out


def narration_node(state: AgentState) -> dict:
    """L'Agent de Narration (Écrivain Gothique) : la plume finale.

    Isolé de toute la plomberie (context trimming du brief) : PAS d'outils,
    PAS d'historique — uniquement le dossier factuel. Température créative.
    Dernier nœud du tour, il consigne l'échange dans la mémoire de session.

    Args:
        state: L'état courant (``question``, ``lore``, ``web_findings``).

    Returns:
        Les modifications : ``story``, ``path`` et l'échange du tour pour
        ``history`` (question du visiteur, récit rendu).
    """
    dossier = _NARRATION_DOSSIER.format(
        question=state["question"],
        lore=_pretty_facts(state.get("lore")) or "(néant)",
        web_findings=_pretty_facts(state.get("web_findings")) or "(pas d'enquête web)",
    )
    trace.record("node", "narration", f"dossier de {len(dossier)} car. transmis à la plume")
    response = _writer_llm().invoke([SystemMessage(NARRATION_PROMPT), HumanMessage(dossier)])
    story = str(response.content)
    return {
        "story": story,
        "path": ["narration"],
        "history": [HumanMessage(state["question"]), AIMessage(story)],
    }


def _pretty_facts(raw: str | None) -> str:
    """Aère les faits JSON pour le dossier de la Narration.

    Les contenus d'outils sont du JSON compact ; on le ré-indente légèrement
    pour aider le LLM écrivain à s'y retrouver (sans en changer le fond).

    Args:
        raw: Lignes JSON concaténées, ou None.

    Returns:
        Une version lisible (ou chaîne vide si rien).
    """
    if not raw:
        return ""
    lines = []
    for line in raw.splitlines():
        try:
            data = json.loads(line)
            data.pop("found", None)
            lines.append(json.dumps(data, ensure_ascii=False, indent=1))
        except (json.JSONDecodeError, AttributeError):
            lines.append(line)
    return "\n".join(lines)
