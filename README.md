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

Endpoints : `GET /health`, `GET /metrics` (Prometheus), `POST /chat`.

## État d'avancement

- [x] Phase A — Socle (config, contracts, trace, logging Loguru, index FAISS)
- [x] Phase B — Outils natifs (rag_tool : FAISS+SQL+pgvector ; scraper_tool : Wikipédia+DuckDuckGo)
- [x] Phase C — Graphe multi-agent (state multi-canaux, 3 nœuds, routeurs purs, pipeline compilé)
- [x] Phase D — API FastAPI (/health, /metrics, /chat) + front Streamlit (parcours des agents)
- [x] Phase E — Monitoring Langfuse (self-hosted Docker, CallbackHandler v3 fail-open, traces par session)
- [ ] Phase F — Tests (≥ 80 %) + CI
- [ ] Phase G — Épilogue MLOps (Docker, JWT, Prometheus/Grafana/Uptime Kuma, Sphinx)
