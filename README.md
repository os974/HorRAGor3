# HorRAGor3 — HorRAGor BOT Partie 3

Système **multi-agent peer-to-peer** sous LangGraph : l'agent conversationnel horreur
de HorRAGor2 (monolithe ReAct) est éclaté en trois agents spécialisés qui partagent
un `State` commun, sans manager central :

1. **Agent RAG (Chercheur Local)** — fouille FAISS/SQL/pgvector
2. **Agent Scraper (Enquêteur du Web)** — déclenché seulement si la base locale est insuffisante
3. **Agent Narration (Écrivain Gothique)** — reçoit la synthèse, rend l'atmosphère terrifiante

Flux : `START → rag → [routeur] → (narration | scraper → narration) → END`

## Documentation

- **Brief** : `docs/HorRAGor BOT Partie 3.pdf`
- **Plan directeur** (phases A→G, règles de travail) : [docs/plan-horragor3.md](docs/plan-horragor3.md)
- **Lifecycle** (le « livre du projet », tenu au fil de l'eau) : [docs/lifecycle.md](docs/lifecycle.md)
- **Lire la console et les logs** (guide pour non-initiés) : [docs/lire-la-console-et-les-logs.md](docs/lire-la-console-et-les-logs.md)

## Prérequis

- [uv](https://docs.astral.sh/uv/), Python ≥ 3.12
- [Ollama](https://ollama.com) avec `ollama pull qwen2.5:7b` et `ollama pull nomic-embed-text`
- Un `.env` rempli d'après `.env.example` (Supabase ; Langfuse optionnel)
- Monitoring (optionnel) : Langfuse self-hosted — `git clone https://github.com/langfuse/langfuse && cd langfuse && docker compose up -d`, compte local sur `http://localhost:3000`, clés dans `.env`. Sans clés, l'app tourne à l'identique (fail-open).
- L'index FAISS dans `data/faiss_index/` (copié depuis HorRAGor2, ou reconstruit)

## Installation

```bash
uv sync
cp .env.example .env   # puis remplir les secrets
```

## Lancement

```bash
# Terminal 1 — l'API (charge l'index FAISS au démarrage)
uv run uvicorn src.main:app --reload

# Terminal 2 — le front
uv run streamlit run app_frontend.py
```

Endpoints : `GET /health`, `GET /metrics` (Prometheus), `POST /auth/login`, `POST /auth/refresh`, `POST /chat` (JWT requis).

## Lancement en cluster (Docker)

```bash
./scripts/gen_certs.sh     # une fois : CA locale + certificat TLS
./scripts/dump_supabase.sh # une fois : dump de la base (POSTGRES_* requis dans .env)
docker compose up -d --build
```

Puis ouvre **https://horragor.localhost** (accepte le certificat de la CA locale,
ou importe `certs/ca.pem` dans le navigateur) et connecte-toi avec
`APP_USERNAME`/`APP_PASSWORD` du `.env`. Architecture : Traefik (443, seul port
publié) → Streamlit → API IA (JWT) → réseau privé étanche → API Données →
Postgres + pgvector (conteneur, réseau interne dédié). Ollama reste sur l'hôte.

Monitoring 360° (interfaces sur la boucle locale uniquement) :

| Outil | URL | Rôle |
|---|---|---|
| Langfuse | http://localhost:3000 | traces de l'agent (nœuds, tokens, latences, outils) |
| Uptime Kuma | http://localhost:3001 | disponibilité des 3 couches et des outils |
| Grafana | http://localhost:3002 | dashboard « HorRAGor3 — les 3 couches » |
| Prometheus | http://localhost:9090 | métriques brutes (APIs + Traefik) |

Au premier lancement, créer les sondes Uptime Kuma :
`uv run --with uptime-kuma-api==1.2.1 python scripts/setup_uptime_kuma.py`.

## Documentation (Sphinx)

```bash
uv run --group docs sphinx-build -W -b html docs/sphinx docs/sphinx/_build/html
```

Doc automatique des deux API (endpoints générés depuis OpenAPI), schémas
relationnels (MCD/MLD/MPD), cartographie du graphe générée depuis
`src/graph/pipeline.py`, et le livre du projet (`docs/lifecycle.md`).

## Tests

```bash
uv run pytest --cov=src    # 83 tests hermétiques (ni Ollama, ni réseau), verrou à 80 %
uv run ruff check . && uv run ruff format --check .
```

La CI GitHub Actions rejoue exactement ces commandes à chaque push/PR sur `main`.

## État d'avancement

- [x] Phase A — Socle (config, contracts, trace, logging Loguru, index FAISS)
- [x] Phase B — Outils natifs (rag_tool : FAISS+SQL+pgvector ; scraper_tool : Wikipédia+DuckDuckGo)
- [x] Phase C — Graphe multi-agent (state multi-canaux, 3 nœuds, routeurs purs, pipeline compilé)
- [x] Phase D — API FastAPI (/health, /metrics, /chat) + front Streamlit (parcours des agents)
- [x] Phase E — Monitoring Langfuse (self-hosted Docker, CallbackHandler v3 fail-open, traces par session)
- [x] Phase F — Tests (83 tests hermétiques, 92 % de couverture) + CI GitHub Actions
- [ ] Phase G — Épilogue MLOps
  - [x] G1 — API Données dédiée (la base encapsulée, réseau privé)
  - [x] G2 — Authentification par Refresh Tokens (JWT access/refresh)
  - [x] G3 — Cluster Docker 3 couches (Traefik + TLS vérifié, réseau interne étanche)
  - [ ] BDD conteneurisée (Postgres + pgvector dans le cluster)
  - [ ] Monitoring 360° (Langfuse intégré, Prometheus, Grafana, Uptime Kuma)
  - [ ] Documentation Sphinx (2 API, schémas relationnels, carte du graphe)
  - [ ] CD (images GHCR + doc sur GitHub Pages)
  - [ ] GitHub Issues (un ticket par anomalie)
