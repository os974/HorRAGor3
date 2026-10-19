# Couche Présentation : le front Streamlit, isolé dans son conteneur.
# Parle à l'API IA exclusivement en HTTPS via Traefik (SSL_CERT_FILE pointe
# vers notre CA locale : le certificat est VÉRIFIÉ, pas de verify=False).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/
COPY app_frontend.py ./

# /_stcore/health : l'endpoint de santé natif de Streamlit (cible Uptime Kuma).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["uv", "run", "--no-sync", "python", "-c", \
       "import httpx; httpx.get('http://localhost:8501/_stcore/health', timeout=3).raise_for_status()"]

CMD ["uv", "run", "--no-sync", "streamlit", "run", "app_frontend.py", \
     "--server.address", "0.0.0.0", "--server.port", "8501", "--server.headless", "true"]
