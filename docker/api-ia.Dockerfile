# Couche Intelligence : l'API FastAPI hébergeant le graphe multi-agent.
# Réseaux : ia_net (Traefik, sortie web, Ollama sur l'hôte) + data_net (API
# Données). L'index FAISS est monté en volume RO. Processus non root.
FROM ghcr.io/astral-sh/uv:0.9.30-python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dépendances d'abord (cache Docker : elles changent moins que le code).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/

# Utilisateur dédié ; seuls les journaux (logs/) sont accessibles en écriture.
RUN useradd --system --create-home --uid 1001 app \
 && mkdir -p logs && chown app logs
USER 1001

# Le HEALTHCHECK du brief MLOps : Docker et Uptime Kuma sondent /health.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", \
       "import httpx; httpx.get('http://localhost:8000/health', timeout=3).raise_for_status()"]

CMD ["/app/.venv/bin/uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
