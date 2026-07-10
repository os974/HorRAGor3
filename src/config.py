"""Configuration centrale du projet (source unique de vérité).

Charge les réglages depuis ``.env`` via pydantic-settings : typage + validation
automatiques, aucun secret en dur dans le code. Un seul objet :data:`settings`
est instancié au chargement du module et importé partout.

Stratégie secrets vs réglages (héritée de HorRAGor2) :
    - SECRETS (clés, URLs privées) : valeur uniquement dans ``.env``, défaut vide ici.
    - RÉGLAGES non sensibles (ports, modèles, chemins) : défaut ici ; le ``.env``
      ne sert qu'à surcharger.

Règle observabilité du projet : pas de ``os.environ[...] = ...`` en dur (le snippet
Langfuse du brief PDF le fait — à ne pas reproduire) ; tout passe par ce module.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Racine du projet : src/config.py -> parents[1] = racine du dépôt.
# Ancrer .env à la racine le rend lisible quel que soit le dossier de lancement.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Réglages typés de l'application, chargés depuis ``.env``.

    Attributes:
        database_url: Connection string PostgreSQL Supabase (secret, accès principal
            à la base relationnelle de HorRAGor1 via SQLAlchemy).
        supabase_url: URL API REST Supabase (secret, optionnel).
        supabase_key: Clé API Supabase (secret, optionnel).
        tmdb_token: Token TMDB v4 pour enrichir réalisateur/casting (secret,
            optionnel — si vide, l'enrichissement est ignoré sans erreur).
        tmdb_base_url: Base de l'API TMDB.
        api_host: Hôte d'écoute du serveur FastAPI.
        api_port: Port d'écoute du serveur FastAPI.
        api_base_url: URL de l'API telle que vue par le Front Streamlit.
        ollama_base_url: Instance Ollama locale (LLM + embeddings).
        llm_model: LLM des agents (tool-calling). ``qwen2.5:7b`` : tool_calls
            structurés fiables sur Ollama (validé sur HorRAGor2).
        narration_temperature: Température du seul agent Narration — la plume
            gothique a besoin de créativité, les agents RAG/Scraper restent à 0.
        embedding_model: Modèle d'embeddings Ollama (``nomic-embed-text``).
        embedding_dim: Dimension des vecteurs. DOIT correspondre à la colonne
            pgvector ``vector(768)`` ET à l'index FAISS — la changer impose de
            tout ré-embedder.
        data_api_url: URL de l'API Données du cluster. Si définie, la couche IA
            passe par HttpFilmRepository (jamais d'accès direct à la base —
            exigence de l'épilogue) ; vide = accès direct Supabase (mode dev).
        titles_db_path: Repli hors-ligne pour les titres : SQLite de HorRAGor1.
        faiss_index_dir: Dossier de persistance de l'index FAISS (gitignoré),
            ``data/faiss_index`` conformément à l'arborescence du brief.
        faiss_score_threshold: Seuil cosinus sous lequel un titre est inconnu.
        jwt_secret: Secret de signature des JWT (secret ; vide = auth
            inutilisable, /auth/login répond 503).
        app_username: Compte de démonstration de l'IHM (secret).
        app_password: Mot de passe du compte démo (secret).
        access_token_minutes: Durée de vie du jeton d'accès (défaut 15 min).
        refresh_token_days: Durée de vie du jeton de renouvellement (7 j).
        langfuse_public_key: Clé publique Langfuse (secret ; vide = désactivé).
        langfuse_secret_key: Clé secrète Langfuse (secret ; vide = désactivé).
        langfuse_host: URL du serveur Langfuse self-hosted.
        log_level: Niveau minimal des logs Loguru.
    """

    # extra="ignore" : on tolère des variables .env non listées ici sans planter.
    model_config = SettingsConfigDict(env_file=_PROJECT_ROOT / ".env", extra="ignore")

    # --- Supabase : SECRETS (confinés au backend) ---
    database_url: str = ""
    supabase_url: str = ""
    supabase_key: str = ""

    # --- TMDB : enrichissement réalisateur/casting ---
    tmdb_token: str = ""
    tmdb_base_url: str = "https://api.themoviedb.org/3"

    # --- API ---
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_base_url: str = "http://127.0.0.1:8000"

    # --- Modèles : stack 100 % locale via Ollama (aucune clé API) ---
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:7b"
    narration_temperature: float = 0.7
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    # --- API Données (cluster) : si définie, l'IA ne parle plus jamais à la base ---
    # Ex. http://api-donnees:8100 dans le compose ; vide = accès direct Supabase (dev).
    data_api_url: str = ""

    # --- FAISS (validation de titres, index repris de HorRAGor2) ---
    titles_db_path: str = "../HorRAGor1/data/horragor.db"
    faiss_index_dir: str = "data/faiss_index"
    faiss_score_threshold: float = 0.75

    # --- Auth JWT (brief : refresh tokens IHM ↔ API IA) : SECRETS ---
    jwt_secret: str = ""
    app_username: str = ""
    app_password: str = ""
    access_token_minutes: int = 15
    refresh_token_days: int = 7

    # --- Langfuse (Phase E) : fail-open si clés absentes ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    # --- Logging ---
    log_level: str = "INFO"

    @property
    def langfuse_enabled(self) -> bool:
        """Indique si le monitoring Langfuse doit être activé.

        Returns:
            True si les deux clés Langfuse sont renseignées dans ``.env``.
        """
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


# Instancié une fois au chargement du module : importer `settings` suffit partout.
settings = Settings()
