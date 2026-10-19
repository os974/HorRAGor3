"""Outil du Chercheur : contrat « jamais d'exception » et wrappers @tool."""

from src.config import settings
from src.contracts.schemas import FilmMetadata, FilmRef
from src.tools import rag_tool


class FakeIndex:
    """Double du TitleIndex : renvoie des voisins préparés."""

    def __init__(self, results):
        self._results = results

    def search_vector(self, vector, k=1):
        return self._results


class FakeRepository:
    """Double du repository : métadonnées et recommandations préparées."""

    def __init__(self, metadata=None, similar=None, error=None):
        self._metadata = metadata
        self._similar = similar or []
        self._error = error

    def get_metadata(self, film_id):
        if self._error:
            raise self._error
        return self._metadata

    def recommend_similar(self, film_id, k=5):
        if self._error:
            raise self._error
        return self._similar


def _use_repository(monkeypatch, repository):
    """Remplace la fabrique du repository par un fake."""
    monkeypatch.setattr(rag_tool, "get_repository", lambda: repository)


def _use_index(monkeypatch, results):
    """Installe un faux index + un faux embedding (pas d'Ollama)."""
    monkeypatch.setattr(rag_tool, "get_index", lambda: FakeIndex(results))
    monkeypatch.setattr(rag_tool, "embed_text", lambda text: [0.0, 1.0])


def test_validate_film_confirme_au_dessus_du_seuil(monkeypatch):
    """Score ≥ seuil → FilmRef avec l'id et le titre canonique."""
    _use_index(monkeypatch, [(0.99, 41, "Hereditary")])
    ref = rag_tool.validate_film("hereditary")
    assert ref == FilmRef(id=41, title="Hereditary")


def test_validate_film_rejette_sous_le_seuil(monkeypatch):
    """Score < seuil → None (le routeur enverra l'Enquêteur)."""
    _use_index(monkeypatch, [(settings.faiss_score_threshold - 0.1, 7, "HER")])
    assert rag_tool.validate_film("heriditary") is None


def test_validate_film_sans_resultat(monkeypatch):
    """Index vide → None, pas d'exception."""
    _use_index(monkeypatch, [])
    assert rag_tool.validate_film("zzz") is None


def test_validate_film_jamais_d_exception(monkeypatch):
    """Panne d'embedding (Ollama éteint) → None + log, jamais d'exception."""
    monkeypatch.setattr(rag_tool, "get_index", lambda: FakeIndex([]))

    def boom(text):
        raise ConnectionError("Ollama éteint")

    monkeypatch.setattr(rag_tool, "embed_text", boom)
    assert rag_tool.validate_film("Alien") is None


def test_query_metadata_delegue_au_repository(monkeypatch):
    """Le lore vient du repository ; sans token TMDB, pas d'enrichissement."""
    meta = FilmMetadata(id=41, title="Hereditary", release_year=2018)
    _use_repository(monkeypatch, FakeRepository(metadata=meta))
    monkeypatch.setattr(settings, "tmdb_token", "")
    assert rag_tool.query_movie_metadata(41) == meta


def test_query_metadata_enrichissement_tmdb_best_effort(monkeypatch):
    """TMDB en panne → les faits de la base restent intacts."""
    meta = FilmMetadata(id=41, title="Hereditary", tmdb_id=99)
    _use_repository(monkeypatch, FakeRepository(metadata=meta))
    monkeypatch.setattr(settings, "tmdb_token", "tok")

    def boom(tmdb_id, top_cast=5):
        raise ConnectionError("TMDB down")

    monkeypatch.setattr(rag_tool.tmdb, "get_credits", boom)
    out = rag_tool.query_movie_metadata(41)
    assert out.title == "Hereditary" and out.director is None


def test_query_metadata_jamais_d_exception(monkeypatch):
    """Base injoignable → None, pas d'exception."""
    _use_repository(monkeypatch, FakeRepository(error=RuntimeError("DB down")))
    assert rag_tool.query_movie_metadata(41) is None


def test_find_similar_degrade_en_liste_vide(monkeypatch):
    """pgvector indisponible (ex. repli SQLite) → []."""
    _use_repository(monkeypatch, FakeRepository(error=RuntimeError("no pgvector")))
    assert rag_tool.find_similar_horror_movies(41) == []


def test_wrapper_lookup_movie_found_true(monkeypatch):
    """Le @tool compose validate → metadata et marque "found": true."""
    _use_index(monkeypatch, [(0.99, 41, "Hereditary")])
    _use_repository(
        monkeypatch,
        FakeRepository(metadata=FilmMetadata(id=41, title="Hereditary", release_year=2018)),
    )
    monkeypatch.setattr(settings, "tmdb_token", "")
    out = rag_tool.lookup_movie.invoke({"title": "hereditary"})
    assert '"found": true' in out and "2018" in out


def test_wrapper_lookup_movie_found_false(monkeypatch):
    """Titre inconnu → "found": false avec une raison lisible."""
    _use_index(monkeypatch, [])
    out = rag_tool.lookup_movie.invoke({"title": "zzz"})
    assert '"found": false' in out


def test_wrapper_find_similar(monkeypatch):
    """Recommandations trouvées → "found": true et titres listés."""
    _use_index(monkeypatch, [(0.99, 42, "Midsommar")])
    _use_repository(monkeypatch, FakeRepository(similar=[FilmRef(id=1, title="Mara")]))
    out = rag_tool.find_similar.invoke({"title": "Midsommar"})
    assert '"found": true' in out and "Mara" in out


def test_wrapper_find_similar_sans_reco(monkeypatch):
    """Aucune recommandation → "found": false."""
    _use_index(monkeypatch, [(0.99, 42, "Midsommar")])
    _use_repository(monkeypatch, FakeRepository(similar=[]))
    out = rag_tool.find_similar.invoke({"title": "Midsommar"})
    assert '"found": false' in out
