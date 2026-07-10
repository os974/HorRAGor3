"""Outil de l'Enquêteur : Wikipédia et DuckDuckGo mockés, contrat sans exception."""

import httpx

from src.tools import scraper_tool


class FakeResponse:
    """Double de la réponse httpx."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_wikipedia_renvoie_l_extrait(monkeypatch):
    """Page trouvée → l'extrait brut."""
    monkeypatch.setattr(
        scraper_tool.httpx,
        "get",
        lambda *a, **k: FakeResponse(200, {"extract": "Un film terrifiant."}),
    )
    assert scraper_tool.scrape_detailed_synopsis("Hereditary") == "Un film terrifiant."


def test_wikipedia_page_absente(monkeypatch):
    """404 → message explicite, restituable tel quel par l'agent."""
    monkeypatch.setattr(scraper_tool.httpx, "get", lambda *a, **k: FakeResponse(404))
    assert "Aucune page" in scraper_tool.scrape_detailed_synopsis("zzz")


def test_wikipedia_homonymie(monkeypatch):
    """Page d'homonymie → on demande de préciser, sans deviner."""
    monkeypatch.setattr(
        scraper_tool.httpx,
        "get",
        lambda *a, **k: FakeResponse(200, {"type": "disambiguation"}),
    )
    assert "homonymie" in scraper_tool.scrape_detailed_synopsis("It")


def test_wikipedia_erreur_reseau(monkeypatch):
    """Réseau coupé → message d'erreur, jamais d'exception."""

    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(scraper_tool.httpx, "get", boom)
    assert "Impossible de contacter" in scraper_tool.scrape_detailed_synopsis("Alien")


class FakeDDGS:
    """Double du client ddgs (context manager)."""

    def __init__(self, results=None, error=None):
        self._results = results or []
        self._error = error

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def text(self, query, max_results=5):
        if self._error:
            raise self._error
        return self._results


def test_search_web_normalise_les_resultats(monkeypatch):
    """Les clés ddgs (href/body) deviennent url/snippet."""
    monkeypatch.setattr(
        scraper_tool,
        "DDGS",
        FakeDDGS([{"title": "Trivia", "href": "http://x", "body": "anecdote"}]),
    )
    results = scraper_tool.search_web("Hereditary trivia")
    assert results == [{"title": "Trivia", "url": "http://x", "snippet": "anecdote"}]


def test_search_web_jamais_d_exception(monkeypatch):
    """Panne réseau → [] + log, jamais d'exception."""
    monkeypatch.setattr(scraper_tool, "DDGS", FakeDDGS(error=ConnectionError("offline")))
    assert scraper_tool.search_web("q") == []


def test_wrapper_wikipedia_marque_found(monkeypatch):
    """Extrait réel → found true ; échec → found false."""
    monkeypatch.setattr(
        scraper_tool.httpx, "get", lambda *a, **k: FakeResponse(200, {"extract": "Peur."})
    )
    assert '"found": true' in scraper_tool.wikipedia_synopsis.invoke({"title": "Alien"})

    monkeypatch.setattr(scraper_tool.httpx, "get", lambda *a, **k: FakeResponse(404))
    assert '"found": false' in scraper_tool.wikipedia_synopsis.invoke({"title": "zzz"})


def test_wrapper_web_search_marque_found(monkeypatch):
    """Résultats → found true ; rien → found false."""
    monkeypatch.setattr(scraper_tool, "DDGS", FakeDDGS([{"title": "t", "href": "u", "body": "s"}]))
    assert '"found": true' in scraper_tool.web_search.invoke({"query": "q"})

    monkeypatch.setattr(scraper_tool, "DDGS", FakeDDGS([]))
    assert '"found": false' in scraper_tool.web_search.invoke({"query": "q"})
