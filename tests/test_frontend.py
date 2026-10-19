"""L'UI Streamlit via st.testing.AppTest : la porte, le login, le chat (mocké)."""

import json

import httpx
from streamlit.testing.v1 import AppTest

APP = "app_frontend.py"


class FakeResponse:
    """Double de la réponse httpx.post consommée par le front."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erreur", request=None, response=None)


def _fake_api(
    monkeypatch,
    *,
    login_ok=True,
    answer="Récit des ténèbres.",
    stale_access=False,
    refresh_ok=True,
):
    """Détourne httpx.post : /auth/login, /auth/refresh et /chat sont simulés.

    ``stale_access`` : le premier access token (« acc ») est expiré → 401 sur
    /chat ; ``refresh_ok`` : le refresh token est encore accepté ou non.
    """

    def fake_post(url, json=None, headers=None, timeout=None):
        if url.endswith("/auth/login"):
            if not login_ok:
                return FakeResponse(401)
            return FakeResponse(
                200, {"access_token": "acc", "refresh_token": "ref", "token_type": "bearer"}
            )
        if url.endswith("/auth/refresh"):
            if not refresh_ok:
                return FakeResponse(401)
            return FakeResponse(
                200, {"access_token": "acc2", "refresh_token": "ref2", "token_type": "bearer"}
            )
        if url.endswith("/chat"):
            if stale_access and headers["Authorization"] == "Bearer acc":
                return FakeResponse(401)
            return FakeResponse(
                200,
                {
                    "answer": answer,
                    "path": ["rag", "narration"],
                    "sources": ["validate_film"],
                    "trace": [{"kind": "node", "name": "rag", "detail": "fouille"}],
                },
            )
        raise AssertionError(f"URL inattendue : {url}")

    monkeypatch.setattr(httpx, "post", fake_post)


def test_porte_close_sans_session():
    """Sans jetons : le formulaire est là, le chat est inaccessible."""
    at = AppTest.from_file(APP).run()
    assert any("Connecte-toi" in str(info.value) for info in at.info)
    assert not at.chat_input  # st.stop() a coupé avant le chat


def test_login_reussi_ouvre_le_manoir(monkeypatch):
    """Identifiants valides → jetons en session, le chat apparaît."""
    _fake_api(monkeypatch)
    at = AppTest.from_file(APP).run()
    at.text_input[0].set_value("olivier")
    at.text_input[1].set_value("sésame")
    at.button[0].set_value(True).run()  # submit du formulaire

    assert at.session_state["access_token"] == "acc"
    assert len(at.chat_input) == 1  # la porte est ouverte


def test_login_refuse(monkeypatch):
    """Mauvais identifiants → erreur affichée, porte toujours close."""
    _fake_api(monkeypatch, login_ok=False)
    at = AppTest.from_file(APP).run()
    at.text_input[0].set_value("olivier")
    at.text_input[1].set_value("faux")
    at.button[0].set_value(True).run()

    assert "access_token" not in at.session_state
    assert any("invalides" in str(err.value) for err in at.error)


def test_chat_affiche_recit_et_parcours(monkeypatch):
    """Une question → le récit, le parcours des agents et les coulisses."""
    _fake_api(monkeypatch)
    at = AppTest.from_file(APP)
    at.session_state["access_token"] = "acc"
    at.session_state["refresh_token"] = "ref"
    at.run()
    at.chat_input[0].set_value("Parle-moi d'Alien").run(timeout=10)

    rendered = json.dumps(
        [msg["content"] for msg in at.session_state["messages"]], ensure_ascii=False
    )
    assert "Récit des ténèbres." in rendered
    meta = at.session_state["messages"][-1]
    assert meta["path"] == ["rag", "narration"]
    assert meta["sources"] == ["validate_film"]


def _ask_with_session(monkeypatch, **api) -> AppTest:
    """Session ouverte (acc/ref), une question posée, l'app rejouée."""
    _fake_api(monkeypatch, **api)
    at = AppTest.from_file(APP)
    at.session_state["access_token"] = "acc"
    at.session_state["refresh_token"] = "ref"
    at.run()
    at.chat_input[0].set_value("Parle-moi d'Alien").run(timeout=10)
    return at


def test_access_expire_prolonge_la_session_en_silence(monkeypatch):
    """401 sur /chat → UN refresh, la paire est remplacée et la question rejouée."""
    at = _ask_with_session(monkeypatch, stale_access=True)

    assert at.session_state["access_token"] == "acc2"
    assert at.session_state["refresh_token"] == "ref2"
    assert at.session_state["messages"][-1]["content"] == "Récit des ténèbres."


def test_refresh_refuse_demande_une_reconnexion(monkeypatch):
    """Access expiré ET refresh refusé (révoqué/expiré) → message de reconnexion."""
    at = _ask_with_session(monkeypatch, stale_access=True, refresh_ok=False)

    assert "session expirée" in at.session_state["messages"][-1]["content"]


def test_deconnexion_purge_la_session(monkeypatch):
    """Le bouton de déconnexion efface jetons et historique."""
    _fake_api(monkeypatch)
    at = AppTest.from_file(APP)
    at.session_state["access_token"] = "acc"
    at.session_state["refresh_token"] = "ref"
    at.session_state["messages"] = [{"role": "user", "content": "bouh"}]
    at.run()
    at.button[0].set_value(True).run()  # « Se déconnecter »

    assert "access_token" not in at.session_state
    assert "messages" not in at.session_state or not at.session_state["messages"]
