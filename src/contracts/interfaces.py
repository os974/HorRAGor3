"""Interfaces (contrats de comportement) entre les briques.

Des ``Protocol`` plutôt que des classes abstraites : duck typing statique,
une classe est compatible si elle a les bonnes méthodes, sans héritage.
L'API dépend de l'abstraction :class:`AgentEngine`, jamais du graphe concret —
on branche un mock dans les tests, puis le vrai graphe multi-agent, sans
toucher au code de l'API (pattern validé sur HorRAGor2).
"""

from typing import Protocol

from src.contracts.schemas import ChatRequest, ChatResponse, FilmMetadata, FilmRef


class AgentEngine(Protocol):
    """Ce que l'API appelle pour obtenir une réponse (mock ou graphe réel)."""

    async def run(self, req: ChatRequest) -> ChatResponse:
        """Traite une requête de chat de bout en bout.

        Args:
            req: Message utilisateur et identifiant de session.

        Returns:
            La réponse complète (narration, sources, parcours, trace).
        """
        ...


class FilmRepository(Protocol):
    """Accès aux données films (implémenté par Supabase + FAISS).

    Les outils des agents s'appuient sur cette interface : ils n'écrivent
    jamais de SQL eux-mêmes (règle de sécurité héritée de la Partie 2).
    """

    def validate_film(self, title: str) -> FilmRef | None:
        """Valide un titre approximatif contre l'index FAISS.

        Args:
            title: Titre saisi par l'utilisateur, fautes tolérées.

        Returns:
            Le film le plus proche, ou None sous le seuil de similarité.
        """
        ...

    def get_metadata(self, film_id: int) -> FilmMetadata:
        """Récupère les métadonnées complètes d'un film.

        Args:
            film_id: Identifiant interne du film.

        Returns:
            Les métadonnées (champs manquants laissés à None/vides).
        """
        ...

    def recommend_similar(self, film_id: int, k: int = 5) -> list[FilmRef]:
        """Recommande des films similaires via pgvector.

        Args:
            film_id: Film de référence.
            k: Nombre de recommandations.

        Returns:
            Les k films les plus proches sémantiquement.
        """
        ...
