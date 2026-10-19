"""Fixtures partagées : isolation des fabriques en cache entre les tests.

Les outils obtiennent l'index FAISS et le repository par des fabriques
``lru_cache`` ; on vide ces caches autour de chaque test pour éviter toute
pollution croisée.
"""

import pytest

from src.tools import rag_tool


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Vide les caches des fabriques de rag_tool avant et après chaque test."""
    rag_tool.get_index.cache_clear()
    rag_tool.get_repository.cache_clear()
    yield
    rag_tool.get_index.cache_clear()
    rag_tool.get_repository.cache_clear()
