"""Serveur FastAPI (Uvicorn) : la porte d'entrée du backend multi-agent.

Lancement (depuis la racine) :
    uv run uvicorn src.main:app --reload

Endpoints :
    - ``GET /health`` : vitalité (CI, Docker HEALTHCHECK, Uptime Kuma) ;
    - ``GET /metrics`` : métriques Prometheus (règle observabilité : chaque
      service naît instrumenté) ;
    - ``POST /chat`` : l'unique porte métier — ChatRequest → graphe → ChatResponse.

Le ``lifespan`` charge l'index FAISS UNE fois au démarrage (routage de titres
instantané, en RAM) avec dégradation propre s'il est absent.
"""

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator

from src.config import settings
from src.contracts.interfaces import AgentEngine
from src.contracts.schemas import ChatRequest, ChatResponse
from src.data.faiss_index import TitleIndex
from src.engine import get_engine
from src.logging_conf import setup_logging
from src.tools.rag_tool import set_index

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
        index = TitleIndex.load()
        set_index(index)
        logger.info("Index FAISS chargé : {} titres en RAM", len(index))
    else:
        logger.warning(
            "Index FAISS absent ({}) : validate_film sera indisponible "
            "(copier celui de HorRAGor2 ou le reconstruire)",
            settings.faiss_index_dir,
        )
    yield


app = FastAPI(title="HorRAGor3 API", version="0.1.0", lifespan=lifespan)

# CORS : le Front Streamlit vit sur un autre port ; sans cela le navigateur
# bloquerait ses appels. (Phase G : restreindre à l'URL réelle du Front.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# /metrics Prometheus dès la naissance du service (règle observabilité) :
# latences, comptes et statuts par route, prêts pour la stack de la Phase G.
Instrumentator().instrument(app).expose(app)

EngineDep = Annotated[AgentEngine, Depends(get_engine)]


@app.get("/health")
async def health() -> dict[str, str]:
    """Vérifie que l'API répond.

    Returns:
        ``{"status": "ok"}`` — consommé par la CI, Docker et Uptime Kuma.
    """
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, engine: EngineDep) -> ChatResponse:
    """Délègue la question au moteur multi-agent.

    Args:
        req: Message utilisateur et identifiant de session.
        engine: Le moteur injecté (GraphEngine, ou fake dans les tests).

    Returns:
        La réponse complète (récit gothique, parcours, sources, trace).
    """
    logger.info("POST /chat [{}] : {!r}", req.session_id, req.message[:80])
    return await engine.run(req)
