"""TitleIndex : recherche cosinus et persistance, sans Ollama (vecteurs fournis)."""

from sqlalchemy import create_engine, text

from scripts import build_faiss
from src.data import faiss_index
from src.data.faiss_index import TitleIndex, normalize_title


def _fake_embed(texts, workers, chunk_size):
    """Embeddings factices : un vecteur 3D déterministe par titre normalisé."""
    return [[float(len(t)), float(t.count("e")), 1.0] for t in texts]


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


def test_build_from_pairs_embedde_les_titres_normalises(monkeypatch):
    """Les titres sont embeddés normalisés ; l'index garde les titres d'origine."""
    seen: list[str] = []

    def recording_embed(texts, workers, chunk_size):
        seen.extend(texts)
        return _fake_embed(texts, workers, chunk_size)

    monkeypatch.setattr(faiss_index, "embed_texts_concurrent", recording_embed)

    index = TitleIndex.build_from_pairs([(1, "  Alien "), ("2", "Hereditary")])

    assert seen == ["alien", "hereditary"]
    assert len(index) == 2
    assert index.ids == [1, 2]
    assert index.titles == ["  Alien ", "Hereditary"]


def test_build_faiss_reconstruit_l_index_depuis_la_base(monkeypatch, tmp_path):
    """Le script lit movies (titres vides exclus, limite respectée) et persiste l'index."""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("create table movies (id integer primary key, title text)"))
        conn.execute(
            text("insert into movies values (3, 'Mara'), (1, 'Alien'), (2, NULL), (4, 'It')")
        )
    monkeypatch.setattr(build_faiss, "get_engine", lambda: engine)
    monkeypatch.setattr(faiss_index, "embed_texts_concurrent", _fake_embed)
    try:
        build_faiss.main(["--limit", "2", "--out", str(tmp_path)])
    finally:
        engine.dispose()

    reloaded = TitleIndex.load(str(tmp_path))
    assert reloaded.ids == [1, 3]  # trié par id, NULL exclu, limite à 2
    assert reloaded.titles == ["Alien", "Mara"]
