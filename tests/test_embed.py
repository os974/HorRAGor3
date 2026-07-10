"""Embeddings Ollama mockés : batch, repli legacy, garde-fou de dimension."""

import pytest

from src.config import settings
from src.data import embed


class FakeResponse:
    """Double de la réponse httpx.post."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_embed_texts_batch(monkeypatch):
    """L'endpoint moderne /api/embed renvoie un vecteur par texte."""
    monkeypatch.setattr(settings, "embedding_dim", 2)
    monkeypatch.setattr(
        embed.httpx,
        "post",
        lambda url, **k: FakeResponse(200, {"embeddings": [[1.0, 0.0], [0.0, 1.0]]}),
    )
    assert embed.embed_texts(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]


def test_embed_text_raccourci(monkeypatch):
    """embed_text = embed_texts d'un seul élément."""
    monkeypatch.setattr(settings, "embedding_dim", 2)
    monkeypatch.setattr(
        embed.httpx, "post", lambda url, **k: FakeResponse(200, {"embeddings": [[0.5, 0.5]]})
    )
    assert embed.embed_text("alien") == [0.5, 0.5]


def test_repli_legacy_sur_404(monkeypatch):
    """Vieille instance Ollama (404 sur /api/embed) → /api/embeddings un par un."""
    monkeypatch.setattr(settings, "embedding_dim", 2)

    def fake_post(url, **kwargs):
        if url.endswith("/api/embed"):
            return FakeResponse(404)
        return FakeResponse(200, {"embedding": [9.0, 9.0]})

    monkeypatch.setattr(embed.httpx, "post", fake_post)
    assert embed.embed_texts(["a", "b"]) == [[9.0, 9.0], [9.0, 9.0]]


def test_garde_fou_de_dimension(monkeypatch):
    """Une dimension inattendue doit lever : elle casserait FAISS et pgvector."""
    monkeypatch.setattr(settings, "embedding_dim", 768)
    monkeypatch.setattr(
        embed.httpx, "post", lambda url, **k: FakeResponse(200, {"embeddings": [[1.0, 2.0]]})
    )
    with pytest.raises(ValueError, match="Dimension"):
        embed.embed_texts(["a"])


def test_liste_vide():
    """Liste vide → liste vide, sans appel réseau."""
    assert embed.embed_texts([]) == []


def test_reponse_ollama_inattendue(monkeypatch):
    """Réponse sans champ embeddings → RuntimeError explicite."""
    monkeypatch.setattr(embed.httpx, "post", lambda url, **k: FakeResponse(200, {}))
    with pytest.raises(RuntimeError, match="inattendue"):
        embed.embed_texts(["a"])
