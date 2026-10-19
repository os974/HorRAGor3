"""Reducers du State : parcours par tour et fenêtre glissante de la mémoire."""

from langchain_core.messages import AIMessage, HumanMessage

from src.models.state import MEMORY_EXCHANGES, extend_path, keep_recent_exchanges


def test_extend_path_ajoute_les_noeuds():
    """Chaque nœud traversé s'ajoute au parcours du tour."""
    assert extend_path(["rag"], ["narration"]) == ["rag", "narration"]
    assert extend_path(None, ["rag"]) == ["rag"]


def test_extend_path_liste_vide_ouvre_un_nouveau_tour():
    """Une liste vide (entrée d'un tour) remet le parcours à zéro."""
    assert extend_path(["rag", "scraper", "narration"], []) == []


def test_keep_recent_exchanges_garde_la_fenetre():
    """Au-delà de MEMORY_EXCHANGES échanges, les plus anciens sont oubliés."""
    history: list = []
    for i in range(MEMORY_EXCHANGES + 2):
        history = keep_recent_exchanges(
            history, [HumanMessage(f"question {i}"), AIMessage(f"récit {i}")]
        )
    assert len(history) == 2 * MEMORY_EXCHANGES
    assert history[0].content == "question 2"
    assert history[-1].content == f"récit {MEMORY_EXCHANGES + 1}"
