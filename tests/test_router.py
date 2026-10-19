"""Routeurs purs : states forgés, zéro LLM (règle d'or du brief)."""

from types import SimpleNamespace

from src.graph.router import (
    should_continue_rag,
    should_continue_scraper,
    should_scrape_or_narrate,
    wants_web_details,
)

AI_TOOLS = SimpleNamespace(tool_calls=[{"name": "lookup_movie"}])
AI_FINAL = SimpleNamespace(tool_calls=None)
LORE = '{"found": true, "title": "Alien"}'


def test_narrate_quand_recolte_suffisante():
    """Lore présent et question locale → directement chez l'Écrivain."""
    state = {"question": "Parle-moi d'Alien", "lore": LORE}
    assert should_scrape_or_narrate(state) == "narration"


def test_scrape_quand_recolte_vide():
    """Aucun fait récolté → déroutage vers l'Enquêteur."""
    assert should_scrape_or_narrate({"question": "Film inconnu ?", "lore": ""}) == "scraper"


def test_scrape_quand_la_question_exige_le_web():
    """Anecdotes demandées → l'Enquêteur part, même si le film est connu."""
    state = {"question": "Des anecdotes de tournage d'Alien ?", "lore": LORE}
    assert should_scrape_or_narrate(state) == "scraper"


def test_scrape_par_prudence_sur_state_vide():
    """State sans récolte → prudence : on enquête."""
    assert should_scrape_or_narrate({}) == "scraper"


def test_wants_web_details_detecte_les_demandes_hors_base():
    """Anecdotes/coulisses/trivia → la base locale ne suffira jamais."""
    for question in (
        "Des anecdotes de tournage du film Weapons ?",
        "Raconte les secrets de tournage de The Thing",
        "Behind the scenes trivia about Hereditary",
        "Le making of d'Alien",
    ):
        assert wants_web_details(question), question


def test_wants_web_details_laisse_passer_les_questions_locales():
    """Métadonnées, synopsis, recommandations : la base locale suffit."""
    for question in (
        "Parle-moi du film Hereditary",
        "Des films semblables à Midsommar ?",
        "Quelle est l'année de sortie d'Alien ?",
    ):
        assert not wants_web_details(question), question


def test_micro_boucle_rag_vers_outils():
    """Le Chercheur demande un outil → micro-boucle rag_tools."""
    assert should_continue_rag({"rag_messages": [AI_TOOLS]}) == "rag_tools"


def test_rag_delegue_au_carrefour_strategique():
    """Fouille close → le carrefour should_scrape_or_narrate décide."""
    base = {"rag_messages": [AI_FINAL], "question": "Parle-moi d'Alien"}
    assert should_continue_rag({**base, "lore": LORE}) == "narration"
    assert should_continue_rag({**base, "lore": ""}) == "scraper"


def test_micro_boucle_scraper():
    """L'Enquêteur demande un outil → scraper_tools, sinon → narration."""
    assert should_continue_scraper({"scraper_messages": [AI_TOOLS]}) == "scraper_tools"
    assert should_continue_scraper({"scraper_messages": [AI_FINAL]}) == "narration"
