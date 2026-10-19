"""Client HTTP de l'API Données : le FilmRepository de la couche IA en cluster.

Dans l'architecture cible du brief, l'API IA ne parle JAMAIS à la base :
elle communique exclusivement, via le réseau privé Docker, avec l'API Données
(``services/data_api``). Cette classe implémente le Protocol
:class:`~src.contracts.interfaces.FilmRepository` au-dessus de HTTP — le même
contrat que :class:`~src.data.repository.SqlFilmRepository`, donc
interchangeable sans toucher aux outils (``rag_tool`` choisit selon
``settings.data_api_url``).

Les erreurs réseau/HTTP remontent en exceptions httpx : c'est ``rag_tool``
qui applique le contrat « jamais d'exception » de la couche outils.
"""

import httpx

from src import trace
from src.config import settings
from src.contracts.schemas import FilmMetadata, FilmRef

_TIMEOUT = 15.0


class HttpFilmRepository:
    """FilmRepository au-dessus de l'API Données (réseau privé du cluster)."""

    def __init__(self, base_url: str | None = None):
        """Initialise le client.

        Args:
            base_url: URL de l'API Données ; par défaut ``settings.data_api_url``
                (ex. ``http://api-donnees:8100`` dans le cluster).
        """
        self._base_url = (base_url or settings.data_api_url).rstrip("/")

    def get_metadata(self, film_id: int) -> FilmMetadata | None:
        """Récupère le lore d'un film auprès de l'API Données.

        Args:
            film_id: Identifiant interne du film.

        Returns:
            Les métadonnées validées contre le contrat, ou None si 404.

        Raises:
            httpx.HTTPError: API Données injoignable ou en erreur (503...).
        """
        resp = httpx.get(f"{self._base_url}/films/{film_id}", timeout=_TIMEOUT)
        if resp.status_code == 404:
            trace.record("sql", "get_metadata", f"id={film_id} → introuvable (API Données)")
            return None
        resp.raise_for_status()
        trace.record("sql", "get_metadata", f"id={film_id} → via API Données")
        return FilmMetadata.model_validate(resp.json())

    def recommend_similar(self, film_id: int, k: int = 5) -> list[FilmRef]:
        """Demande les k voisins sémantiques à l'API Données.

        Args:
            film_id: Film de référence.
            k: Nombre de recommandations.

        Returns:
            Les voisins (liste vide si le film n'a pas d'embedding).

        Raises:
            httpx.HTTPError: API Données injoignable ou en erreur.
        """
        resp = httpx.get(
            f"{self._base_url}/films/{film_id}/similar",
            params={"k": k},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = [FilmRef.model_validate(item) for item in resp.json()]
        trace.record(
            "pgvector", "recommend_similar", f"id={film_id} → {len(results)} via API Données"
        )
        return results
