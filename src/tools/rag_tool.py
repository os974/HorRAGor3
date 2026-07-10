"""Outil natif de l'Agent RAG (Chercheur Local) : fouille FAISS + SQL + pgvector.

Regroupe les fonctions data de la Partie 2 derrière un contrat unique, pensé
pour un agent LLM : **aucune fonction publique ne lève jamais d'exception** —
en cas d'erreur (Ollama éteint, base injoignable...), on renvoie None/[] et on
journalise. C'est le nœud RAG qui jugera si sa récolte est suffisante ; un
outil qui plante ne doit pas faire s'effondrer le graphe.

Trois capacités :
    - :func:`validate_film` — FAISS : titre approximatif → film confirmé (id) ;
    - :func:`query_movie_metadata` — SQL : lore brut (année, genres, note,
      synopsis) + enrichissement TMDB best-effort (réalisateur, casting) ;
    - :func:`find_similar_horror_movies` — pgvector : recommandations.

Singletons injectables (``set_index`` / ``set_repository``) : l'API injecte
les vrais au démarrage, les tests injectent des fakes.
"""

from loguru import logger

from src import trace
from src.config import settings
from src.contracts.interfaces import FilmRepository
from src.contracts.schemas import FilmMetadata, FilmRef
from src.data import tmdb
from src.data.embed import embed_text
from src.data.faiss_index import TitleIndex, normalize_title
from src.data.repository import SupabaseFilmRepository

_index: TitleIndex | None = None
_repository: FilmRepository | None = None


def set_index(index: TitleIndex) -> None:
    """Injecte l'index FAISS déjà chargé (au démarrage de l'API, ou un fake en test).

    Args:
        index: Index des titres prêt à la recherche.
    """
    global _index
    _index = index


def set_repository(repository: FilmRepository) -> None:
    """Injecte le repository SQL (au démarrage de l'API, ou un fake en test).

    Args:
        repository: Implémentation de FilmRepository.
    """
    global _repository
    _repository = repository


def _get_index() -> TitleIndex:
    """Renvoie l'index injecté, ou le charge paresseusement depuis le disque.

    Returns:
        L'index FAISS des titres.
    """
    global _index
    if _index is None:
        _index = TitleIndex.load()
    return _index


def _get_repository() -> FilmRepository:
    """Renvoie le repository injecté, ou en crée un (connexion paresseuse).

    Returns:
        Le repository films.
    """
    global _repository
    if _repository is None:
        _repository = SupabaseFilmRepository()
    return _repository


def validate_film(title: str) -> FilmRef | None:
    """Valide un titre approximatif contre l'index FAISS (titre → id).

    S'exécute en premier : confirme qu'un film existe et renvoie son id AVANT
    toute action coûteuse (SQL, scraping). Corrige les approximations de
    l'utilisateur (rôle du Chercheur Local dans le brief).

    Args:
        title: Titre saisi par l'utilisateur, fautes/casse tolérées.

    Returns:
        Le film le plus proche si le score cosinus atteint le seuil
        (``settings.faiss_score_threshold``), sinon None. None aussi en cas
        d'erreur technique (jamais d'exception).
    """
    try:
        index = _get_index()
        trace.record("embed", "embed_text", f"{settings.embedding_model} : {title!r} → vecteur")
        vector = embed_text(normalize_title(title))
        results = index.search_vector(vector, k=1)
    except Exception as exc:  # noqa: BLE001 — contrat "jamais d'exception" pour l'agent
        logger.warning("validate_film({!r}) en échec technique : {}", title, exc)
        trace.record("faiss", "validate_film", f"{title!r} → erreur technique")
        return None
    if not results:
        trace.record("faiss", "validate_film", f"{title!r} → aucun résultat")
        return None
    score, film_id, matched_title = results[0]
    if score < settings.faiss_score_threshold:
        trace.record(
            "faiss",
            "validate_film",
            f"{title!r} → rejeté (cosinus {score:.2f} < seuil {settings.faiss_score_threshold})",
        )
        return None
    trace.record(
        "faiss",
        "validate_film",
        f"{title!r} → id={film_id} {matched_title!r} (cosinus {score:.2f})",
    )
    return FilmRef(id=film_id, title=matched_title)


def query_movie_metadata(film_id: int) -> FilmMetadata | None:
    """Récupère le lore brut d'un film : la SEULE source autorisée pour ces faits.

    Enrichit réalisateur/casting via TMDB si un token est configuré et que le
    film a un ``tmdb_id`` — best-effort : un échec réseau ne casse rien, les
    faits de la base restent intacts.

    Args:
        film_id: Identifiant interne (issu de :func:`validate_film`).

    Returns:
        Les métadonnées complètes, ou None si le film n'existe pas ou en cas
        d'erreur technique (jamais d'exception).
    """
    try:
        metadata = _get_repository().get_metadata(film_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("query_movie_metadata({}) en échec technique : {}", film_id, exc)
        trace.record("sql", "get_metadata", f"id={film_id} → erreur technique")
        return None
    if metadata is None:
        return None
    if settings.tmdb_token and metadata.tmdb_id:
        try:
            credits = tmdb.get_credits(metadata.tmdb_id)
            metadata = metadata.model_copy(update=credits)
        except Exception:  # noqa: BLE001 — enrichissement optionnel, on dégrade en silence
            trace.record("tmdb", "get_credits", f"tmdb_id={metadata.tmdb_id} → indisponible")
    return metadata


def find_similar_horror_movies(film_id: int, k: int = 5) -> list[FilmRef]:
    """Recommande les k films les plus proches sémantiquement (pgvector).

    Similarité de CONTENU (synopsis), pas de titre : c'est pgvector, pas FAISS.

    Args:
        film_id: Film de référence.
        k: Nombre de recommandations.

    Returns:
        Les k plus proches voisins ; [] si le film n'a pas d'embedding ou en
        cas d'erreur technique (jamais d'exception — ex. repli SQLite sans
        pgvector).
    """
    try:
        return _get_repository().recommend_similar(film_id, k)
    except Exception as exc:  # noqa: BLE001
        logger.warning("find_similar_horror_movies({}) en échec technique : {}", film_id, exc)
        trace.record("pgvector", "recommend_similar", f"id={film_id} → erreur technique")
        return []
