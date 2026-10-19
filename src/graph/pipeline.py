"""L'Ingénieur Système (le câblage) : point de vérité de la topologie du réseau.

C'est l'atelier d'assemblage final : on lie les ouvriers (``nodes.py``) et les
aiguilleurs (``router.py``) autour du cahier des charges commun (``state.py``)
via les trois méthodes clés du brief :

1. ``workflow.add_node()`` — enregistrer les fonctions de nodes.py ;
2. ``workflow.add_edge()`` — tracer les autoroutes directes ;
3. ``workflow.add_conditional_edges()`` — greffer les aiguilleurs aux carrefours.

Topologie peer-to-peer (aucun manager central) :

    START → rag ⇄ rag_tools
              └─[should_scrape_or_narrate]─┬─→ narration → END
                                           └─→ scraper ⇄ scraper_tools
                                                  └─→ narration → END

Les nœuds et outils sont **injectables** dans :func:`build_workflow` (pattern
du module MultiAgent) : les tests câblent de faux agents via
:func:`build_graph` et vérifient le routage sans appeler le moindre LLM.

Le livrable du brief : ce fichier se termine par ``app = workflow.compile(...)``,
l'objet final importé par FastAPI pour propulser le backend. Le checkpointer
passé à la compilation donne au graphe sa mémoire de session : chaque
conversation (``thread_id``) retrouve son State d'une question à l'autre.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from src.graph import router
from src.graph.nodes import narration_node, rag_node, scraper_node
from src.models.state import AgentState
from src.tools.rag_tool import RAG_TOOLS
from src.tools.scraper_tool import SCRAPER_TOOLS


def build_workflow(
    rag=rag_node,
    scraper=scraper_node,
    narration=narration_node,
    rag_tools=None,
    scraper_tools=None,
) -> StateGraph:
    """Assemble le StateGraph multi-agent (non compilé).

    Args:
        rag: Nœud du Chercheur Local (injectable pour les tests).
        scraper: Nœud de l'Enquêteur du Web (injectable).
        narration: Nœud de l'Écrivain Gothique (injectable).
        rag_tools: Nœud outil du RAG ; par défaut un ToolNode branché sur le
            canal ``rag_messages``.
        scraper_tools: Nœud outil du Scraper ; par défaut un ToolNode branché
            sur le canal ``scraper_messages``.

    Returns:
        Le ``StateGraph`` câblé, à compiler par ``workflow.compile()``.
    """
    # Chaque ToolNode lit/écrit le canal de messages de SON agent : l'isolation
    # de contexte est garantie jusque dans l'exécution des outils.
    rag_tools = rag_tools or ToolNode(RAG_TOOLS, messages_key="rag_messages")
    scraper_tools = scraper_tools or ToolNode(SCRAPER_TOOLS, messages_key="scraper_messages")

    workflow = StateGraph(AgentState)

    # 1. Les ouvriers.
    workflow.add_node("rag", rag)
    workflow.add_node("rag_tools", rag_tools)
    workflow.add_node("scraper", scraper)
    workflow.add_node("scraper_tools", scraper_tools)
    workflow.add_node("narration", narration)

    # 2. Les autoroutes directes.
    workflow.add_edge(START, "rag")  # l'Agent RAG s'allume toujours en premier
    workflow.add_edge("rag_tools", "rag")  # micro-boucle outil du Chercheur
    workflow.add_edge("scraper_tools", "scraper")  # micro-boucle de l'Enquêteur
    workflow.add_edge("narration", END)  # la plume ferme toujours la marche

    # 3. Les aiguilleurs aux carrefours stratégiques.
    workflow.add_conditional_edges(
        "rag",
        router.should_continue_rag,
        {"rag_tools": "rag_tools", "scraper": "scraper", "narration": "narration"},
    )
    workflow.add_conditional_edges(
        "scraper",
        router.should_continue_scraper,
        {"scraper_tools": "scraper_tools", "narration": "narration"},
    )

    return workflow


def build_graph(**nodes) -> CompiledStateGraph:
    """Assemble et compile un graphe aux nœuds injectés (tests).

    Args:
        **nodes: Nœuds de remplacement, mêmes noms que :func:`build_workflow`.

    Returns:
        Le graphe compilé, prêt à ``invoke``/``stream``.
    """
    return build_workflow(**nodes).compile()


# Le livrable : l'objet final, propre et prêt à l'emploi, importé par FastAPI.
# Le checkpointer en mémoire garde le State de chaque conversation (thread_id).
workflow = build_workflow()
app = workflow.compile(checkpointer=InMemorySaver())
