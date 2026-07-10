"""Forme des données échangées entre Front, API et graphe (modèles Pydantic).

Contrat partagé repris de HorRAGor2 : le Front et l'API parlent exactement la
même structure JSON, et FastAPI génère le schéma OpenAPI à partir de ces
classes. Nouveauté Partie 3 : :attr:`ChatResponse.path` expose le parcours des
agents dans le graphe (RAG seul, ou RAG puis Scraper, puis Narration).

⚠️ Schémas partagés : ne pas modifier sans adapter le Front ET l'API.
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Requête envoyée par le Front à l'API (``POST /chat``).

    Attributes:
        message: Question de l'utilisateur.
        session_id: Identifiant de conversation — sert aussi d'ID de
            corrélation logs ↔ traces Langfuse (règle observabilité).
    """

    message: str
    session_id: str = "default"


class FilmRef(BaseModel):
    """Référence minimale d'un film (sortie du routeur FAISS ou d'une reco).

    Attributes:
        id: Identifiant interne (aligné entre FAISS, SQL et pgvector).
        title: Titre du film.
    """

    id: int
    title: str


class FilmMetadata(BaseModel):
    """Métadonnées complètes d'un film (connecteur SQL + enrichissement TMDB).

    Tous les champs hors identité sont optionnels pour rester tolérant aux
    données incomplètes du golden data de HorRAGor1.

    Attributes:
        id: Identifiant interne.
        title: Titre du film.
        tmdb_id: Identifiant TMDB (sert à enrichir réalisateur/casting).
        director: Réalisateur — absent de la base, enrichi via TMDB.
        release_year: Année de sortie (dérivée de ``movies.release_date``).
        genres: Genres (jointure ``movie_genres``).
        rating: Note 0-10 (table ``ratings``).
        cast: Casting principal — enrichi via TMDB.
        synopsis: Synopsis (``movies.overview``).
    """

    id: int
    title: str
    tmdb_id: int | None = None
    director: str | None = None
    release_year: int | None = None
    genres: list[str] = Field(default_factory=list)
    rating: float | None = None
    cast: list[str] = Field(default_factory=list)
    synopsis: str | None = None


class TraceStep(BaseModel):
    """Une étape du raisonnement (pour l'expander « Raisonnement » du Front).

    Attributes:
        kind: Type d'étape — "node" | "tool" | "router" | "verdict".
        name: Nom du nœud, de l'outil ou de l'événement.
        detail: Arguments, extrait du résultat ou raison de la décision.
    """

    kind: str
    name: str
    detail: str = ""


class ChatResponse(BaseModel):
    """Réponse renvoyée par l'API au Front.

    Attributes:
        answer: Réponse finale (narration gothique).
        sources: Outils/données ayant fondé la réponse (traçabilité
            anti-hallucination).
        path: Parcours des agents dans le graphe, dans l'ordre d'exécution
            (ex. ``["rag", "scraper", "narration"]``) — spécifique Partie 3.
        trace: Étapes détaillées du raisonnement.
    """

    answer: str
    sources: list[str] = Field(default_factory=list)
    path: list[str] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
