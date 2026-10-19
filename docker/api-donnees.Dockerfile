# Couche Données : la base encapsulée derrière son API dédiée.
# SEUL conteneur à recevoir DATABASE_URL ; aucun port publié — uniquement
# joignable via le réseau privé data_net (internal) par l'API IA.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/
COPY services/ services/

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["uv", "run", "--no-sync", "python", "-c", \
       "import httpx; httpx.get('http://localhost:8100/health', timeout=3).raise_for_status()"]

CMD ["uv", "run", "--no-sync", "uvicorn", "services.data_api.main:app", "--host", "0.0.0.0", "--port", "8100"]
