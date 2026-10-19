"""Engine SQLAlchemy partagé vers la base PostgreSQL + pgvector. Repris de HorRAGor2.

En cluster : le conteneur ``db`` du réseau privé (seule l'API Données s'y
connecte). En dev hors cluster : Supabase. Engine unique mis en cache :
SQLAlchemy gère un pool de connexions, on ne le recrée pas à chaque requête.
``pool_pre_ping`` revalide la connexion avant usage (un pooler distant peut
fermer les connexions inactives).

Repli hors-ligne possible : ``DATABASE_URL=sqlite:///../HorRAGor1/data/horragor.db``
— le schéma est identique, seule la reco pgvector devient indisponible.
"""

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from src.config import settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Renvoie l'engine partagé vers la base configurée.

    Returns:
        L'engine SQLAlchemy (pool de connexions, pre-ping activé).

    Raises:
        RuntimeError: Si ``DATABASE_URL`` n'est pas renseigné dans ``.env``.
    """
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL non défini : renseignez-le dans .env "
            "(connection string Supabase postgresql+psycopg://..., "
            "ou repli local sqlite:///../HorRAGor1/data/horragor.db)."
        )
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)
