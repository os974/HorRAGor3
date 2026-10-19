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

    async def run(self, req: ChatRequest, user: str = "anonyme") -> ChatResponse:
        """Traite une requête de chat de bout en bout.

        Args:
            req: Message utilisateur et identifiant de session.
            user: Le compte authentifié : la mémoire de la conversation et les
                traces lui sont rattachées.

        Returns:
            La réponse complète (narration, sources, parcours, trace).
        """
        ...


class FilmRepository(Protocol):
    """Accès aux données films.

    Deux implémentations interchangeables : :class:`~src.data.repository.SqlFilmRepository`
    (SQL direct, mode dev et API Données) et
    :class:`~src.data.http_repository.HttpFilmRepository` (client de l'API
    Données, couche IA en cluster). Les outils des agents s'appuient sur cette
    interface : ils n'écrivent jamais de SQL eux-mêmes (règle de sécurité
    héritée de la Partie 2). La validation floue des titres n'en fait pas
    partie : c'est le rôle de l'index FAISS (:func:`src.tools.rag_tool.validate_film`).
    """

    def get_metadata(self, film_id: int) -> FilmMetadata | None:
        """Récupère les métadonnées complètes d'un film.

        Args:
            film_id: Identifiant interne du film.

        Returns:
            Les métadonnées (champs manquants laissés à None/vides), ou None
            si l'identifiant est inconnu.
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
