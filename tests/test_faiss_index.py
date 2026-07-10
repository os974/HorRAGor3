"""TitleIndex : recherche cosinus et persistance, sans Ollama (vecteurs fournis)."""

from src.data.faiss_index import TitleIndex, normalize_title


def _small_index() -> TitleIndex:
    """Index jouet : 3 titres en dimension 3."""
    vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.7, 0.7, 0.0]]
    return TitleIndex.from_vectors(vectors, ids=[1, 2, 3], titles=["Alien", "Mara", "It"])


def test_normalize_title():
    """Casse et espaces de bord neutralisés."""
    assert normalize_title("  HEREDITARY ") == "hereditary"


def test_search_vector_trouve_le_plus_proche():
    """Le voisin exact sort avec un score cosinus de 1."""
    index = _small_index()
    score, film_id, title = index.search_vector([1.0, 0.0, 0.0], k=1)[0]
    assert (film_id, title) == (1, "Alien")
    assert score == 1.0


def test_search_vector_k_voisins():
    """k=2 → deux voisins, du plus proche au plus lointain."""
    results = _small_index().search_vector([0.7, 0.7, 0.0], k=2)
    assert len(results) == 2
    assert results[0][2] == "It"


def test_len_et_persistance(tmp_path):
    """save → exists → load : l'index survit au disque, intact."""
    index = _small_index()
    assert len(index) == 3
    assert not TitleIndex.exists(str(tmp_path))

    index.save(str(tmp_path))
    assert TitleIndex.exists(str(tmp_path))

    reloaded = TitleIndex.load(str(tmp_path))
    assert len(reloaded) == 3
    assert reloaded.titles == ["Alien", "Mara", "It"]
    assert reloaded.search_vector([0.0, 1.0, 0.0], k=1)[0][2] == "Mara"
