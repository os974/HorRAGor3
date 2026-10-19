"""Serveur FastAPI (Uvicorn) : la porte d'entrée du backend multi-agent.

Lancement (depuis la racine) :
    uv run uvicorn src.main:app --reload

Endpoints :
    - ``GET /health`` : vitalité (CI, Docker HEALTHCHECK, Uptime Kuma) ;
    - ``GET /metrics`` : métriques Prometheus (règle observabilité : chaque
      service naît instrumenté) — non routé en public dans le cluster ;
    - ``POST /auth/login`` et ``POST /auth/refresh`` : la paire de jetons
      (Refresh Tokens du brief, voir :mod:`src.auth`) ;
    - ``POST /chat`` : l'unique porte métier (JWT requis) — ChatRequest →
      graphe → ChatResponse.

Le ``lifespan`` charge l'index FAISS UNE fois au démarrage (routage de titres
instantané, en RAM) avec dégradation propre s'il est absent.
"""

from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator

from src.auth import bearer_token, forwarding_access_token, require_access
from src.auth import router as auth_router
from src.config import settings
from src.contracts.interfaces import AgentEngine
from src.contracts.schemas import ChatRequest, ChatResponse
from src.data.faiss_index import TitleIndex
from src.engine import get_engine
from src.logging_conf import setup_logging
from src.observability import LangfuseRequestMiddleware, tag_current_trace
from src.tools.rag_tool import get_index

# Un seul flux de logs pour toute l'app, uvicorn compris (règle : Loguru partout).
setup_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Charge l'index FAISS au démarrage (dégradation propre s'il manque).

    Args:
        _: L'application FastAPI (non utilisée).

    Yields:
        La main à l'application, index prêt en RAM.
    """
    if TitleIndex.exists():
        index = get_index()  # chargé une fois, gardé en cache pour tout le processus
        logger.info("Index FAISS chargé : {} titres en RAM", len(index))
    else:
        logger.warning(
            "Index FAISS absent ({}) : validate_film sera indisponible "
            "(le reconstruire : uv run python -m scripts.build_faiss)",
            settings.faiss_index_dir,
        )
    yield


# Pas de CORS : le navigateur n'appelle jamais l'API — c'est le serveur
# Streamlit (httpx, côté conteneur) qui lui parle.
app = FastAPI(title="HorRAGor3 API", version="1.0.0", lifespan=lifespan)

# /metrics Prometheus dès la naissance du service (règle observabilité) :
# latences, comptes et statuts par route, prêts pour la stack de la Phase G.
Instrumentator().instrument(app).expose(app)

# Une trace Langfuse par requête métier ; le graphe de /chat s'y imbrique.
app.add_middleware(LangfuseRequestMiddleware, service="api-ia")

# /auth/login et /auth/refresh (JWT access + refresh — exigence du brief).
app.include_router(auth_router)

EngineDep = Annotated[AgentEngine, Depends(get_engine)]
# L'identité vérifiée par le jeton d'accès (401 sinon) : verrouille les routes métier.
UserDep = Annotated[str, Depends(require_access)]
# Le jeton lui-même, relayé à l'API Données : toute la chaîne reste liée au compte.
TokenDep = Annotated[str, Depends(bearer_token)]


@app.get("/health")
async def health() -> dict[str, str]:
    """Vérifie que l'API répond.

    Returns:
        ``{"status": "ok"}`` — consommé par la CI, Docker et Uptime Kuma.
    """
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, engine: EngineDep, user: UserDep, token: TokenDep) -> ChatResponse:
    """Délègue la question au moteur multi-agent (route verrouillée par JWT).

    Corrélation : ``session_id`` (la conversation, fourni par le Front) et un
    ``request_id`` (cet appel) sont posés dans le contexte Loguru ; toutes les
    lignes de log du run, graphe compris, les portent.

    Args:
        req: Message utilisateur et identifiant de session.
        engine: Le moteur injecté (GraphEngine, ou fake dans les tests).
        user: L'identité extraite du jeton d'accès (401 si absent/invalide).
        token: Le jeton d'accès, relayé aux appels vers l'API Données.

    Returns:
        La réponse complète (récit gothique, parcours, sources, trace).
    """
    with (
        logger.contextualize(session_id=req.session_id, request_id=uuid4().hex[:8]),
        forwarding_access_token(token),
    ):
        logger.info("POST /chat [{}] par {} : {!r}", req.session_id, user, req.message[:80])
        response = await engine.run(req, user)
    tag_current_trace(
        user_id=user, session_id=req.session_id, input=req.message, output=response.answer
    )
    return response
