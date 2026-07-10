"""Fixtures partagées : isolation des singletons entre les tests.

Les outils utilisent des singletons injectables (index FAISS, repository) ;
on les remet à zéro autour de chaque test pour éviter toute pollution croisée.
"""

import pytest

from src.tools import rag_tool


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Réinitialise les singletons de rag_tool avant et après chaque test."""
    rag_tool._index = None
    rag_tool._repository = None
    yield
    rag_tool._index = None
    rag_tool._repository = None
