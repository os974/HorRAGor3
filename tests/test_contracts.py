"""Contrats Pydantic : défauts et forme du JSON échangé Front/API."""

from src.contracts.schemas import ChatRequest, ChatResponse, FilmMetadata, FilmRef, TraceStep


def test_chat_request_session_par_defaut():
    """Sans session explicite, la conversation est "default"."""
    req = ChatRequest(message="bouh")
    assert req.session_id == "default"


def test_chat_response_defauts_vides():
    """Une réponse minimale reste valide (listes vides, pas de None)."""
    resp = ChatResponse(answer="récit")
    assert resp.sources == []
    assert resp.path == []
    assert resp.trace == []


def test_film_metadata_tolere_les_champs_manquants():
    """Le golden data est incomplet : tout sauf l'identité est optionnel."""
    meta = FilmMetadata(id=1, title="Alien")
    assert meta.director is None
    assert meta.genres == []
    assert meta.cast == []


def test_round_trip_json():
    """Sérialisation → validation : le contrat est stable."""
    resp = ChatResponse(
        answer="a",
        path=["rag", "narration"],
        trace=[TraceStep(kind="node", name="rag")],
    )
    again = ChatResponse.model_validate(resp.model_dump())
    assert again == resp
    assert FilmRef(id=3, title="Mara").model_dump() == {"id": 3, "title": "Mara"}
