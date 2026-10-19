"""Aides pures de nodes.py : récolte déterministe, sans LLM."""

from langchain_core.messages import AIMessage, ToolMessage

from src.graph.nodes import _first_visit, _pretty_facts, harvest_facts


def test_harvest_facts_ne_garde_que_les_found_true():
    """Seuls les résultats d'outils marqués "found": true comptent."""
    messages = [
        AIMessage(content="je cherche"),
        ToolMessage(content='{"found": true, "title": "Hereditary"}', tool_call_id="1"),
        ToolMessage(content='{"found": false, "reason": "inconnu"}', tool_call_id="2"),
    ]
    assert harvest_facts(messages) == ['{"found": true, "title": "Hereditary"}']


def test_harvest_facts_vide_sans_tool_messages():
    """Aucun ToolMessage → récolte vide."""
    assert harvest_facts([AIMessage(content="rien")]) == []


def test_first_visit_selon_le_path():
    """Un nœud déjà dans path n'est pas une première visite."""
    assert _first_visit({"path": []}, "rag")
    assert _first_visit({}, "rag")
    assert not _first_visit({"path": ["rag"]}, "rag")


def test_pretty_facts_reindente_le_json_et_retire_found():
    """Le JSON compact des outils est aéré pour la plume, sans le marqueur."""
    out = _pretty_facts('{"found": true, "title": "Alien"}')
    assert "Alien" in out
    assert "found" not in out


def test_pretty_facts_tolere_le_texte_brut():
    """Une ligne non-JSON passe telle quelle ; None/vide → chaîne vide."""
    assert _pretty_facts("pas du json") == "pas du json"
    assert _pretty_facts(None) == ""
    assert _pretty_facts("") == ""
