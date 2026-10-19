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
- **Documentation technique en ligne** (Sphinx) : https://os974.github.io/HorRAGor3/
- **Plan directeur** (phases A→G, règles de travail) : [docs/plan-horragor3.md](docs/plan-horragor3.md)
- **Lifecycle** (le « livre du projet », tenu au fil de l'eau) : [docs/lifecycle.md](docs/lifecycle.md)
- **Lire la console et les logs** (guide pour non-initiés) : [docs/lire-la-console-et-les-logs.md](docs/lire-la-console-et-les-logs.md)

## Prérequis

- [uv](https://docs.astral.sh/uv/), Python ≥ 3.12
- [Ollama](https://ollama.com) avec `ollama pull qwen2.5:7b` et `ollama pull nomic-embed-text`
- Un `.env` rempli d'après `.env.example`
- L'index FAISS dans `data/faiss_index/` (gitignoré, ~100 Mo) : copié depuis
  `../HorRAGor2/faiss_index/`, ou reconstruit depuis la base (Ollama et
  `DATABASE_URL` requis, quelques minutes) :
  `uv run python -m scripts.build_faiss`
- Docker avec Compose ≥ 2.20 (cluster et monitoring ; le compose utilise `include:`)

Hors cluster (mode dev), l'API lit la base directement via `DATABASE_URL`
(Supabase). Langfuse est optionnel (sans clés, l'app tourne à l'identique,
fail-open). Il peut être lancé seul avec
`docker compose up -d langfuse-web langfuse-worker` (le worker ingère les
traces) ; Compose lisant tout le fichier, les variables exigées du cluster
doivent alors être renseignées dans le `.env`.

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

# Optionnel — l'API Données, comme en cluster (puis DATA_API_URL=http://127.0.0.1:8100 dans le .env)
uv run uvicorn services.data_api.main:app --port 8100
```

Endpoints de l'API IA : `GET /health`, `GET /metrics` (Prometheus), `POST /auth/login`,
`POST /auth/refresh`, `POST /chat` (JWT requis). API Données : `GET /films/{id}`,
`GET /films/{id}/similar`, `/health`, `/metrics`.

## Lancement en cluster (Docker)

```bash
./scripts/gen_certs.sh     # une fois : CA locale + certificat TLS
./scripts/dump_supabase.sh # une fois : dump de la base source (lit DATABASE_URL)
docker compose up -d --build
docker compose ps          # les 15 conteneurs doivent être « healthy »
```

Arrêt : `docker compose down` (les volumes, donc la base et les traces, sont
conservés ; `docker compose down -v` les supprime).

Les images des 3 couches sont aussi publiées par le CD, publiques :
`docker pull ghcr.io/os974/horragor3-{api-ia,api-donnees,frontend}:latest`
(tags `latest` et `sha-<commit>`). Le compose, lui, les construit localement.

Le `.env` doit aussi contenir les secrets du cluster (`POSTGRES_*`, `JWT_SECRET`,
`APP_*`, `LANGFUSE_*`, `GRAFANA_ADMIN_PASSWORD`, `KUMA_*` — voir `.env.example`).

Puis ouvre **https://horragor.localhost** (accepte le certificat de la CA locale,
ou importe `certs/ca.pem` dans le navigateur) et connecte-toi avec
`APP_USERNAME`/`APP_PASSWORD` du `.env`. Architecture : Traefik (127.0.0.1:443,
seul port applicatif publié) → Streamlit → API IA (JWT) → réseau privé étanche →
API Données → Postgres + pgvector (conteneur, réseau interne dédié). Ollama reste
sur l'hôte (GPU) : le service `ollama-relay` l'expose aux conteneurs sur la seule
passerelle Docker (`172.17.0.1`), jamais sur le réseau local.

Monitoring 360° (interfaces sur la boucle locale uniquement) :

| Outil | URL | Rôle | Connexion |
|---|---|---|---|
| Langfuse | http://localhost:3000 | traces de l'agent (nœuds, tokens, latences, outils), par conversation | `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` |
| Uptime Kuma | http://localhost:3001 | disponibilité des 3 couches et des outils | `KUMA_ADMIN_USER` / `KUMA_ADMIN_PASSWORD` |
| Grafana | http://localhost:3002 | dashboard « HorRAGor3 — les 3 couches » | `admin` / `GRAFANA_ADMIN_PASSWORD` |
| Prometheus | http://localhost:9090 | métriques brutes (APIs + Traefik) | — |

Au premier lancement, créer les sondes Uptime Kuma :
`uv run --env-file .env --with uptime-kuma-api==1.2.1 python scripts/setup_uptime_kuma.py`.

## Documentation (Sphinx)

En ligne (publiée par le CD à chaque merge sur `main`) : https://os974.github.io/HorRAGor3/

```bash
uv run --group docs sphinx-build -W -b html docs/sphinx docs/sphinx/_build/html
```

Doc automatique des deux API (endpoints générés depuis OpenAPI), schémas
relationnels (MCD/MLD/MPD), cartographie du graphe générée depuis
`src/graph/pipeline.py` avec une page par agent, le livre du projet
(`docs/lifecycle.md`) et le guide de la console.

## Tests

```bash
uv run pytest --cov        # 123 tests hermétiques (ni Ollama, ni réseau), verrou à 80 %
uv run ruff check . && uv run ruff format --check .
```

CI/CD GitHub Actions :
- `ci.yml` (chaque PR, et appelée par `cd.yml` sur `main`) : ruff, shellcheck,
  pytest avec 80 % de couverture **par périmètre** (API IA, API Données, UI) ;
- `cd.yml` : images des 3 couches construites à chaque PR, poussées sur GHCR
  et doc Sphinx publiée sur GitHub Pages après merge sur `main`, **seulement si
  la CI est verte**.

## État d'avancement

- [x] Phase A — Socle (config, contracts, trace, logging Loguru, index FAISS)
- [x] Phase B — Outils natifs (rag_tool : FAISS+SQL+pgvector ; scraper_tool : Wikipédia+DuckDuckGo)
- [x] Phase C — Graphe multi-agent (state multi-canaux, 3 nœuds, routeurs purs, pipeline compilé)
- [x] Phase D — API FastAPI (/health, /metrics, /chat) + front Streamlit (parcours des agents)
- [x] Phase E — Monitoring Langfuse (self-hosted Docker, CallbackHandler v3 fail-open, traces par session)
- [x] Phase F — Tests (83 tests hermétiques, 92 % de couverture) + CI GitHub Actions
- [x] Phase G — Épilogue MLOps
  - [x] G1 — API Données dédiée (la base encapsulée, réseau privé)
  - [x] G2 — Authentification par Refresh Tokens (JWT access/refresh, révocation sur rejeu)
  - [x] G3 — Cluster Docker 3 couches (Traefik + TLS vérifié, réseaux internes, durcissement)
  - [x] BDD conteneurisée (Postgres + pgvector dans le cluster, rôle en lecture seule)
  - [x] Monitoring 360° (Langfuse intégré, Prometheus, Grafana, Uptime Kuma)
  - [x] Documentation Sphinx (2 API, schémas relationnels, carte du graphe)
  - [x] CI/CD (images publiques sur GHCR, doc en ligne : https://os974.github.io/HorRAGor3/)
  - [x] GitHub Issues (formulaires + un ticket archivé par anomalie : https://github.com/os974/HorRAGor3/issues)
  - [x] Récit de bout en bout en conteneurs (relais Ollama, traces dans le Langfuse intégré)
- [x] Vérification finale contre la lettre du brief (tickets #22–#25, livre ch. 17) : règle de
  suffisance dans `router.py`, `app = workflow.compile()`, corrélation par conversation, Loguru
  de bout en bout, index FAISS reproductible, analyse Langfuse chiffrée
