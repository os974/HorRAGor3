"""API Données : la base encapsulée derrière sa propre API dédiée (brief, couche 1).

Rôle dans le cluster : SEUL composant applicatif à connaître ``DATABASE_URL``
(le conteneur ``db``, avec un rôle en lecture seule ; Supabase en dev).
Conteneurisée dans le réseau privé Docker étanche — aucun port publié, aucune
requête entrante depuis l'extérieur : seule l'API IA lui parle, via
:class:`~src.data.http_repository.HttpFilmRepository`.

Lancement local (dev, hors Docker) :
    uv run uvicorn services.data_api.main:app --port 8100

Endpoints :
    - ``GET /health`` : vitalité (Docker HEALTHCHECK, Uptime Kuma) ;
    - ``GET /metrics`` : métriques Prometheus (règle observabilité) ;
    - ``GET /films/{id}`` : le lore brut d'un film (movies+genres+ratings) ;
    - ``GET /films/{id}/similar?k=`` : recommandations pgvector.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator

from src.contracts.interfaces import FilmRepository
from src.contracts.schemas import FilmMetadata, FilmRef
from src.data.repository import SupabaseFilmRepository
from src.logging_conf import setup_logging

# Un seul flux de logs Loguru, comme partout (règle : journalisation bout en bout).
setup_logging()


@lru_cache(maxsize=1)
def _repository() -> SupabaseFilmRepository:
    """Construit le repository une seule fois (connexion paresseuse).

    Returns:
        Le repository singleton branché sur ``DATABASE_URL``.
    """
    return SupabaseFilmRepository()


def get_repository() -> FilmRepository:
    """Fournit le repository aux routes (surchargé par les tests).

    Returns:
        L'implémentation de FilmRepository active.
    """
    return _repository()


app = FastAPI(title="HorRAGor3 — API Données", version="0.1.0")

# /metrics dès la naissance du service (règle observabilité, cible Prometheus).
Instrumentator().instrument(app).expose(app)

RepoDep = Annotated[FilmRepository, Depends(get_repository)]


@app.get("/health")
async def health() -> dict[str, str]:
    """Vérifie que l'API Données répond.

    Returns:
        ``{"status": "ok"}`` — consommé par Docker et Uptime Kuma.
    """
    return {"status": "ok"}


@app.get("/films/{film_id}", response_model=FilmMetadata)
async def film_metadata(film_id: int, repo: RepoDep) -> FilmMetadata:
    """Renvoie le lore brut d'un film (la seule source autorisée pour ces faits).

    Args:
        film_id: Identifiant interne (issu de la validation FAISS côté IA).
        repo: Le repository injecté.

    Returns:
        Les métadonnées complètes (réalisateur/casting restent vides ici :
        l'enrichissement TMDB est du ressort de la couche IA).

    Raises:
        HTTPException: 404 si le film n'existe pas ; 503 si la base est
            injoignable (l'appelant dégradera, contrat « jamais planter »).
    """
    try:
        metadata = repo.get_metadata(film_id)
    except Exception:  # noqa: BLE001 — la panne de la base ne doit pas fuiter en 500 brut
        logger.exception("Base injoignable (get_metadata id={})", film_id)
        raise HTTPException(status_code=503, detail="base de données injoignable") from None
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"film {film_id} inconnu")
    return metadata


@app.get("/films/{film_id}/similar", response_model=list[FilmRef])
async def similar_films(
    film_id: int,
    repo: RepoDep,
    k: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[FilmRef]:
    """Recommande les k films les plus proches sémantiquement (pgvector).

    Args:
        film_id: Film de référence.
        repo: Le repository injecté.
        k: Nombre de recommandations (1 à 20).

    Returns:
        Les voisins sémantiques ; liste vide si le film n'a pas d'embedding.

    Raises:
        HTTPException: 503 si la base est injoignable.
    """
    try:
        return repo.recommend_similar(film_id, k)
    except Exception:  # noqa: BLE001
        logger.exception("Base injoignable (recommend_similar id={})", film_id)
        raise HTTPException(status_code=503, detail="base de données injoignable") from None
