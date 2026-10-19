# Couche Présentation : le front Streamlit, isolé dans son conteneur.
# Son seul réseau (front_net, interne) ne mène qu'à Traefik : il parle à l'API
# IA exclusivement en HTTPS, certificat VÉRIFIÉ contre la CA locale
# (SSL_CERT_FILE), jamais en clair. Processus non root.
FROM ghcr.io/astral-sh/uv:0.9.30-python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/
COPY app_frontend.py ./

RUN useradd --system --create-home --uid 1001 app \
 && mkdir -p logs && chown app logs
USER 1001

# /_stcore/health : l'endpoint de santé natif de Streamlit (cible Uptime Kuma).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", \
       "import httpx; httpx.get('http://localhost:8501/_stcore/health', timeout=3).raise_for_status()"]

CMD ["/app/.venv/bin/streamlit", "run", "app_frontend.py", \
     "--server.address", "0.0.0.0", "--server.port", "8501", "--server.headless", "true", \
     "--browser.gatherUsageStats", "false"]
