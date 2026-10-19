"""Le graphe compilé avec des nœuds injectés : routage réel, zéro LLM."""

from langchain_core.messages import AIMessage

from src.graph import pipeline
from src.graph.pipeline import app, build_graph


def _fake_rag(lore: str):
    """Fabrique un faux Chercheur qui conclut immédiatement avec ce lore."""

    def rag(state: dict) -> dict:
        return {
            "rag_messages": [AIMessage(content="fouille close")],
            "lore": lore,
            "path": ["rag"],
        }

    return rag


def _fake_scraper(state: dict) -> dict:
    """Faux Enquêteur : une trouvaille, sans outil."""
    return {
        "scraper_messages": [AIMessage(content="enquête close")],
        "web_findings": "trouvaille web",
        "path": ["scraper"],
    }


def _fake_narration(state: dict) -> dict:
    """Fausse plume : renvoie un récit fixe."""
    return {"story": "récit gothique", "path": ["narration"]}


def test_chemin_court_quand_le_lore_suffit():
    """Récolte complète → rag → narration, sans détour par le web."""
    graph = build_graph(
        rag=_fake_rag("lore local"), scraper=_fake_scraper, narration=_fake_narration
    )
    result = graph.invoke({"question": "Parle-moi d'Alien"})
    assert result["path"] == ["rag", "narration"]
    assert result["story"] == "récit gothique"


def test_detour_par_l_enqueteur_quand_le_lore_manque():
    """Récolte insuffisante → rag → scraper → narration."""
    graph = build_graph(rag=_fake_rag(""), scraper=_fake_scraper, narration=_fake_narration)
    result = graph.invoke({"question": "Film inconnu ?"})
    assert result["path"] == ["rag", "scraper", "narration"]
    assert result["web_findings"] == "trouvaille web"


def test_detour_quand_la_question_exige_le_web():
    """Film connu mais anecdotes demandées → le routeur envoie l'Enquêteur."""
    graph = build_graph(
        rag=_fake_rag("lore local"), scraper=_fake_scraper, narration=_fake_narration
    )
    result = graph.invoke({"question": "Des anecdotes de tournage d'Alien ?"})
    assert result["path"] == ["rag", "scraper", "narration"]


def test_le_livrable_du_brief_est_compile():
    """`app = workflow.compile()` expose bien la topologie du brief."""
    assert isinstance(pipeline.workflow, pipeline.StateGraph)
    node_names = set(app.get_graph().nodes.keys())
    assert {"rag", "rag_tools", "scraper", "scraper_tools", "narration"} <= node_names
