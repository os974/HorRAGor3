"""Fixtures partagées : isolation des fabriques en cache entre les tests.

Les outils obtiennent l'index FAISS et le repository par des fabriques
``lru_cache`` ; on vide ces caches autour de chaque test pour éviter toute
pollution croisée. Langfuse est neutralisé partout : le ``.env`` local peut
contenir de vraies clés, et les tests restent hermétiques (aucune trace
envoyée).
"""

import pytest

from src import observability
from src.config import settings
from src.tools import rag_tool

# Les fabriques d'origine : un test peut les remplacer par des fakes
# (monkeypatch), leurs caches se vident quand même.
_CACHED_FACTORIES = (
    rag_tool.get_index,
    rag_tool.get_repository,
    observability.langfuse_client,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Vide les caches des fabriques avant et après chaque test."""
    for factory in _CACHED_FACTORIES:
        factory.cache_clear()
    yield
    for factory in _CACHED_FACTORIES:
        factory.cache_clear()


@pytest.fixture(autouse=True)
def _langfuse_neutralise(monkeypatch):
    """Clés Langfuse vides : aucun test n'émet de trace."""
    monkeypatch.setattr(settings, "langfuse_public_key", "")
    monkeypatch.setattr(settings, "langfuse_secret_key", "")
