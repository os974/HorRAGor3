"""Routeurs purs : states forgés, zéro LLM (règle d'or du brief)."""

from types import SimpleNamespace

from src.graph.router import (
    should_continue_rag,
    should_continue_scraper,
    should_scrape_or_narrate,
)

AI_TOOLS = SimpleNamespace(tool_calls=[{"name": "lookup_movie"}])
AI_FINAL = SimpleNamespace(tool_calls=None)


def test_narrate_quand_recolte_complete():
    """Récolte jugée suffisante → directement chez l'Écrivain."""
    assert should_scrape_or_narrate({"is_complete": True}) == "narration"


def test_scrape_quand_recolte_insuffisante():
    """Récolte insuffisante → déroutage vers l'Enquêteur."""
    assert should_scrape_or_narrate({"is_complete": False}) == "scraper"


def test_scrape_par_prudence_sur_state_vide():
    """State sans jugement → prudence : on enquête."""
    assert should_scrape_or_narrate({}) == "scraper"


def test_micro_boucle_rag_vers_outils():
    """Le Chercheur demande un outil → micro-boucle rag_tools."""
    assert should_continue_rag({"rag_messages": [AI_TOOLS]}) == "rag_tools"


def test_rag_delegue_au_carrefour_strategique():
    """Fouille close → le carrefour should_scrape_or_narrate décide."""
    assert should_continue_rag({"rag_messages": [AI_FINAL], "is_complete": True}) == "narration"
    assert should_continue_rag({"rag_messages": [AI_FINAL], "is_complete": False}) == "scraper"


def test_micro_boucle_scraper():
    """L'Enquêteur demande un outil → scraper_tools, sinon → narration."""
    assert should_continue_scraper({"scraper_messages": [AI_TOOLS]}) == "scraper_tools"
    assert should_continue_scraper({"scraper_messages": [AI_FINAL]}) == "narration"
