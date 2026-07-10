"""Enrichissement via l'API TMDB : réalisateur + casting. Repris de HorRAGor2.

Le brief Partie 2 demandait réalisateur/casting dans les métadonnées, mais la
base ne les contient pas ; chaque film a en revanche son ``tmdb_id``. Token v4
(Bearer) confiné au backend via ``settings.tmdb_token``.
"""

import httpx

from src import trace
from src.config import settings


def get_credits(tmdb_id: int, top_cast: int = 5) -> dict:
    """Récupère réalisateur et casting d'un film TMDB.

    Donnée faisant autorité (0 % hallucination). En cas de problème réseau,
    l'appelant décide (enrichissement best-effort dans ``rag_tool``).

    Args:
        tmdb_id: Identifiant TMDB du film.
        top_cast: Nombre d'acteurs principaux retenus.

    Returns:
        ``{"director": str | None, "cast": list[str]}``.

    Raises:
        httpx.HTTPError: Erreur réseau ou statut HTTP d'échec.
    """
    resp = httpx.get(
        f"{settings.tmdb_base_url}/movie/{tmdb_id}/credits",
        headers={"Authorization": f"Bearer {settings.tmdb_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    director = next(
        (c.get("name") for c in data.get("crew", []) if c.get("job") == "Director"),
        None,
    )
    cast = [c.get("name") for c in data.get("cast", [])[:top_cast] if c.get("name")]
    trace.record(
        "tmdb", "get_credits", f"tmdb_id={tmdb_id} → réalisateur={director}, {len(cast)} acteurs"
    )
    return {"director": director, "cast": cast}
