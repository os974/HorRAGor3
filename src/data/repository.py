"""Connecteur SQL sécurisé : fonctions Python typées au-dessus de la base.

RÈGLE D'OR (héritée de la Partie 2) : le LLM ne génère JAMAIS de SQL. Toutes
les requêtes vivent ici, **paramétrées** (pas d'injection possible), et
renvoient des objets typés (:class:`~src.contracts.schemas.FilmMetadata`).

Mapping vers le schéma réel de HorRAGor1 :
    - année ← ``movies.release_date`` ;
    - genres ← jointure ``movie_genres``/``genres`` ;
    - rating ← table ``ratings`` (0-10 : imdb prioritaire, sinon tmdb) ;
    - synopsis ← ``movies.overview`` ;
    - réalisateur/casting : absents de la base → enrichis via TMDB (côté outil).
"""

from datetime import date

from sqlalchemy import Engine, text

from src import trace
from src.contracts.schemas import FilmMetadata, FilmRef
from src.data.db import get_engine


def _year_from(value) -> int | None:
    """Extrait l'année d'une date (Postgres) ou d'une chaîne ISO (SQLite).

    Args:
        value: ``date``, chaîne "YYYY-MM-DD", ou None.

    Returns:
        L'année, ou None si indéterminable.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value.year
    head = str(value)[:4]
    return int(head) if head.isdigit() else None


def _pick_rating(rows: list[tuple[str, float | None]]) -> float | None:
    """Choisit une note 0-10 parmi les sources (imdb puis tmdb).

    Rotten Tomatoes est en 0-100, donc ignoré ici.

    Args:
        rows: Couples (source, score) de la table ``ratings``.

    Returns:
        La note retenue, ou None.
    """
    scores = {src: score for src, score in rows}
    for source in ("imdb", "tmdb"):
        if scores.get(source) is not None:
            return float(scores[source])
    return None


class SupabaseFilmRepository:
    """Implémentation SQL de :class:`~src.contracts.interfaces.FilmRepository`."""

    def __init__(self, engine: Engine | None = None):
        """Initialise le repository.

        Args:
            engine: Engine injectable (tests sur SQLite) ; par défaut l'engine
                partagé configuré par ``DATABASE_URL``.
        """
        self._engine = engine or get_engine()

    def get_metadata(self, film_id: int) -> FilmMetadata | None:
        """Récupère les métadonnées d'un film (movies + genres + ratings).

        Args:
            film_id: Identifiant interne du film.

        Returns:
            Les métadonnées, ou None si le film n'existe pas. Réalisateur et
            casting restent vides ici (enrichis via TMDB côté outil).
        """
        with self._engine.connect() as conn:
            movie = conn.execute(
                text(
                    "select id, tmdb_id, title, release_date, overview from movies where id = :id"
                ),
                {"id": film_id},
            ).first()
            if movie is None:
                trace.record("sql", "get_metadata", f"id={film_id} → introuvable")
                return None
            genres = [
                name
                for (name,) in conn.execute(
                    text(
                        "select g.name from genres g "
                        "join movie_genres mg on mg.genre_id = g.id "
                        "where mg.movie_id = :id order by g.name"
                    ),
                    {"id": film_id},
                ).all()
            ]
            rating = _pick_rating(
                conn.execute(
                    text("select source, score from ratings where movie_id = :id"),
                    {"id": film_id},
                ).all()
            )
        trace.record(
            "sql",
            "get_metadata",
            f"movies+genres+ratings id={film_id} → {movie.title!r}, {len(genres)} genres, "
            f"note={rating}",
        )
        return FilmMetadata(
            id=movie.id,
            tmdb_id=movie.tmdb_id,
            title=movie.title,
            release_year=_year_from(movie.release_date),
            genres=genres,
            rating=rating,
            synopsis=movie.overview,
        )

    def validate_film(self, title: str) -> FilmRef | None:
        """Non implémenté ici : la validation floue est le rôle de FAISS.

        Args:
            title: Titre à valider.

        Raises:
            NotImplementedError: Toujours — utiliser
                :func:`src.tools.rag_tool.validate_film`.
        """
        raise NotImplementedError("Utiliser src.tools.rag_tool.validate_film.")

    def recommend_similar(self, film_id: int, k: int = 5) -> list[FilmRef]:
        """Renvoie les k films les plus proches par similarité cosinus (pgvector).

        Le vecteur du film graine reste côté base (sous-requête) : pas de
        transfert. ``<=>`` est la distance cosinus pgvector.

        Args:
            film_id: Film de référence.
            k: Nombre de recommandations.

        Returns:
            Les k plus proches voisins, ou [] si le film n'a pas d'embedding.
        """
        with self._engine.connect() as conn:
            if (
                conn.execute(
                    text("select 1 from movie_embeddings where movie_id = :id"),
                    {"id": film_id},
                ).first()
                is None
            ):
                trace.record("pgvector", "recommend_similar", f"id={film_id} → pas d'embedding")
                return []
            rows = conn.execute(
                text(
                    "select m.id, m.title "
                    "from movie_embeddings e join movies m on m.id = e.movie_id "
                    "where e.movie_id <> :id "
                    "order by e.embedding <=> "
                    "(select embedding from movie_embeddings where movie_id = :id) "
                    "limit :k"
                ),
                {"id": film_id, "k": k},
            ).all()
        trace.record(
            "pgvector",
            "recommend_similar",
            f"voisins de id={film_id} (cosinus <=>) → {len(rows)} film(s)",
        )
        return [FilmRef(id=r.id, title=r.title) for r in rows]
