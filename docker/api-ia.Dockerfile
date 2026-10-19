# Couche Intelligence : l'API FastAPI hébergeant le graphe multi-agent.
# Réseaux : data_net (API Données) + front_net (Traefik) ; Ollama et Langfuse
# restent sur l'hôte (host-gateway). L'index FAISS est monté en volume RO.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dépendances d'abord (cache Docker : elles changent moins que le code).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/

# Le HEALTHCHECK du brief MLOps : Docker et Uptime Kuma sondent /health.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["uv", "run", "--no-sync", "python", "-c", \
       "import httpx; httpx.get('http://localhost:8000/health', timeout=3).raise_for_status()"]

CMD ["uv", "run", "--no-sync", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
