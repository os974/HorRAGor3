# Couche Données : la base encapsulée derrière son API dédiée.
# Seul conteneur applicatif à détenir des identifiants de base ; aucun port
# publié, joignable uniquement via data_net (internal) par l'API IA.
FROM ghcr.io/astral-sh/uv:0.9.30-python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/
COPY services/ services/

RUN useradd --system --create-home --uid 1001 app \
 && mkdir -p logs && chown app logs
USER 1001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", \
       "import httpx; httpx.get('http://localhost:8100/health', timeout=3).raise_for_status()"]

CMD ["/app/.venv/bin/uvicorn", "services.data_api.main:app", "--host", "0.0.0.0", "--port", "8100"]
