# Plan HorRAGor3 — Multi-Agent LangGraph (Partie 3)

## Contexte

HorRAGor est un chatbot conversationnel spécialisé dans l'univers de l'horreur, développé en 3 parties :
- **HorRAGor1** (couche Données) : base de données des œuvres d'horreur — *(exploration en cours)*
- **HorRAGor2** (couche Intelligence v2) : agent ReAct monolithique unique (FAISS + recherche web) — *(exploration en cours)*
- **HorRAGor3** (ce projet) : casser le monolithe en **système multi-agent peer-to-peer sous LangGraph**

Problèmes du monolithe identifiés dans le brief : saturation du contexte (prompt drowning), conflits décisionnels, affaiblissement de la plume narrative noyée dans les logs techniques.

Brief : `docs/HorRAGor BOT Partie 3.pdf` (Antony Schutz — DEV IA, Simplon).

## Exigences du brief (PDF)

### Les 3 agents (aucun manager central — chaîne directe)
1. **Agent RAG (Chercheur Local)** : premier point de contact, interroge FAISS pour le lore, corrige les approximations de l'utilisateur
2. **Agent Scraper (Enquêteur Web)** : déclenché **conditionnellement** par le routeur si la base locale est insuffisante ; creuse le web pour anecdotes/détails manquants
3. **Agent Narration (Écrivain Gothique)** : isolé de la plomberie technique (context trimming), reçoit uniquement la synthèse et l'emballe dans une atmosphère terrifiante

Flux : `START → rag_node → [routeur: should_scrape_or_narrate] → (narration | scraper → narration) → END`

### Arborescence imposée par le brief
```
horRAGor-project/
├── data/faiss_index/        # Index vectoriel local
├── app_frontend.py          # Interface Streamlit
└── src/
    ├── main.py              # Serveur FastAPI (Uvicorn)
    ├── config.py            # Config LLM (Ollama) et chemins
    ├── models/state.py      # Le State (mémoire commune)
    ├── tools/
    │   ├── rag_tool.py      # Recherche FAISS
    │   └── scraper_tool.py  # Recherche Web
    └── graph/
        ├── nodes.py         # Nœuds : rag_node, scraper_node, narration_node
        ├── router.py        # Arêtes conditionnelles (retournent un str)
        └── pipeline.py      # StateGraph : add_node/add_edge/add_conditional_edges → app = workflow.compile()
```

### Règles d'or LangGraph (du brief)
- **nodes.py** : chaque nœud = fonction pure `(state: AgentState) -> dict` de modifications à fusionner ; les nœuds ne savent pas qui précède/suit
- **router.py** : fonctions de routage qui lisent le state et retournent **uniquement un str** (prochaine destination) ; testables unitairement sans lancer le pipeline
- **pipeline.py** : point de vérité de la topologie ; se termine par `app = workflow.compile()` importé par FastAPI

### Monitoring — Langfuse
- Auto-hébergé : `git clone langfuse` + `docker compose up -d` → UI sur `http://localhost:3000`
- Compte local + projet → clés `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST`
- `CallbackHandler` passé via `config={"callbacks": [langfuse_handler]}` à `agent.invoke(inputs, config=config)`
- Analyse attendue : consommation tokens, latence par nœud, tracé des appels d'outils, arbre de décisions du graphe

### Épilogue MLOps (Grand Final)
- **Microservices Docker isolés** en réseau privé étanche :
  - Couche Données (HorRAGor1) : BDD derrière sa propre API dédiée, **strictement inaccessible de l'extérieur**
  - Couche Intelligence (Parties 2 & 3) : FastAPI multi-agent conteneurisée, parle à l'API de données via réseau privé, **auth Refresh Tokens** vers l'IHM, monitorée par Langfuse
  - Couche Présentation : Streamlit conteneurisé isolé, communication chiffrée vers l'API d'IA
- **CI/CD complet** + tests unitaires **≥ 80 %** (deux API + UI)
- **Loguru** pour la journalisation bout en bout
- **Prometheus + Grafana + Uptime Kuma** (télémétrie des 3 composants) + **Langfuse** (agent)
- **Doc Sphinx** : doc auto des API, schémas relationnels BDD, cartographie du graphe multi-agent
- **GitHub Issues** : ticket pour chaque anomalie/comportement déviant

## Existant réutilisable

### MultiAgent (`/home/olivier/Bureau/Simplon/MultiAgent`) — la référence LangGraph
Projet de cours "IA Agentic" (DEVIA 25) avec un exercice multi-agent **peer-to-peer déjà implémenté** (Analyste SQL → Rédacteur tweet) qui mappe presque 1:1 sur HorRAGor3 :
- **`multiagent/state.py`** : `AgentState(TypedDict)` avec `messages: Annotated[Sequence[BaseMessage], operator.add]` (reducer)
- **`multiagent/nodes.py`** : nœuds `def x_node(state) -> dict` retournant `{"messages": [...]}` ; `tool_node = ToolNode(TOOLS)` ; briefs reformulés par agent (anti-collision de tokens)
- **`multiagent/graph.py`** : routeurs typés `-> Literal[...]` lisant `state["messages"][-1]` (pattern « le nœud juge, le routeur aiguille ») avec fallback sûr ; câblage `build_peer_graph()` : `add_edge(START, "analyst")` + `add_conditional_edges` + micro-boucle outil `add_edge("x_tools", "x")` + `workflow.compile()`. **Nœuds/outils injectables** dans `build_*graph(...)` → tests du routage sans LLM
- **`common/tool_calls.py`** : parsing tolérant des tool calls Ollama (`extract_json_object`, `coerce_tool_calls`) — indispensable avec petits modèles locaux
- **`common/llm.py`** : `ChatOllama` avec `qwen2.5-coder:7b`, `temperature=0`
- **`hitl/graph.py`** : checkpointing `MemorySaver()` + `interrupt_before` + `thread_id` (optionnel)
- **`docs/notes-de-session.md`** : théorie complète (State/reducer, conditional edges, peer-to-peer vs superviseur, pièges petits LLM)
- Versions : `langgraph 1.2.8`, `langchain-core 1.4.9`, `langchain-ollama 1.1.0`, `pydantic 2.13.4`, `pytest 9.1.1`, Python ≥ 3.13, gestion **uv**
- ⚠️ **Aucun monitoring/Langfuse dans ce dépôt** — la partie Langfuse est à concevoir depuis le brief

### HorRAGor1 (`/home/olivier/Bureau/Simplon/HorRAGor1`) — couche Données
Pipeline ETL multi-sources (TMDB, IMDB, Kaggle, Rotten Tomatoes/Selenium, Spark TF-IDF) → réconciliation MDM → dataset Gold → base relationnelle 3NF (6 tables). Géré avec **uv**, Python ≥ 3.12, SQLAlchemy 2.0, tests pytest, ruff. Pas d'API web (CLI + Prefect), pas de Docker.
- **Base peuplée** : `data/horragor.db` (SQLite, ~34 000 films d'horreur, 294k mots-clés) ; bascule SQLite/Supabase via `DATABASE_URL` (`src/horragor/db/database.py`)
- **ORM réutilisable** : `src/horragor/db/models.py` (movies, genres, movie_genres, ratings, movie_keywords, sources_metadata)
- **Dataset Gold dénormalisé** : `data/gold/horragor_gold.parquet` (synopsis, mots-clés, genres, scores multi-sources, consensus critiques) — matière première idéale pour l'index FAISS
- ⚠️ Pour l'épilogue MLOps : la BDD n'a **pas encore d'API dédiée** — elle sera à créer (exigence « couche Données derrière sa propre API, réseau privé Docker »)

### HorRAGor2 (`/home/olivier/Bureau/Simplon/HorRAGor2`) — le monolithe à casser
Agent ReAct LangGraph (déjà `langgraph>=1.2.4` !) avec nœud Juge anti-hallucination, API FastAPI async, front Streamlit découplé, 16 fichiers de tests, CI GitHub Actions (ruff + pytest). Pas de Docker. Modèles : **`qwen2.5:7b`** (agent + juge), **`nomic-embed-text`** 768d.
- **Config à reprendre** : `src/backend/config.py` (pydantic-settings, `.env`, URLs Ollama, seuil FAISS 0.75)
- **Index FAISS prêt** : `faiss_index/titles.index` (~104 Mo, 33 961 titres, IndexFlatIP cosinus) + `titles_map.json` + classe `TitleIndex` (`src/backend/data/faiss_index.py`). ⚠️ Il indexe **les titres seulement** (validation titre→id) ; le contenu sémantique passe par **pgvector sur Supabase** (`movie_embeddings`, HNSW)
- **Outils data purs réutilisables** (`src/backend/tools/`) : `faiss_tool.validate_film`, `sql_tool.query_movie_metadata`, `pgvector_tool.find_similar_horror_movies`, `temporal_tool.calculate_movie_age`, `wikipedia_tool.scrape_detailed_synopsis` (API REST Wikipédia via httpx — **pas un vrai moteur de recherche web**)
- **State existant** : `src/backend/agent/state.py` (`messages: Annotated[list, add_messages]`, `retries`, `verdict`)
- **Juge** : `src/backend/agent/judge.py` (`with_structured_output`, fail-open) — réutilisable en aval de la Narration
- **Front/API découplés** : contrat `AgentEngine.run(ChatRequest) -> ChatResponse` (`contracts/`), `deps.get_engine()` → on branche le graphe multi-agent sans toucher au front ; `trace.py` (ContextVar → `logs/traces.jsonl`) + expander « Raisonnement » dans Streamlit — parfait pour visualiser le parcours multi-agent
- **Export Mermaid** : `src/backend/agent/export_graph.py`
- Dépendances d'infra : Ollama local + Supabase (`DATABASE_URL`) ; repli titres SQLite : `../HorRAGor1/data/horragor.db`

## Décisions actées (avec l'utilisateur)

1. **Structure hybride** : arborescence du PDF pour la partie graphe (`src/graph/`, `src/models/state.py`, `src/tools/`, `src/config.py`, `src/main.py`, `app_frontend.py`) + acquis de HorRAGor2 (contracts Pydantic, trace, tests, CI)
2. **Scraper web** : Wikipédia (existant) **+ DuckDuckGo via la lib `ddgs`** (gratuit, sans clé — cohérent avec le 100 % local)
3. Gestion **uv**, Python 3.12+, mêmes modèles Ollama (`qwen2.5:7b`, `nomic-embed-text`)

## Règle de travail — docstrings Google style (prévision Sphinx)

Tous les fichiers Python sont documentés **au fil de l'eau** par docstrings **Google style** (`Args:` / `Returns:` / `Raises:`) : docstring de module en tête de fichier (rôle dans l'architecture) + docstring sur chaque fonction/classe publique, y compris nœuds, routeurs et outils du graphe. Côté Sphinx (Phase G) : `sphinx.ext.autodoc` + `sphinx.ext.napoleon` dans `conf.py`. Documenter dès l'écriture rend la doc Sphinx de l'épilogue quasi gratuite.

## Règle de travail — implémenter en prévision du monitoring

Analyse de la stack du brief (Langfuse, Loguru, Prometheus, Grafana, Uptime Kuma) faite le 2026-07-09. Règles à respecter **pendant** le développement pour que l'intégration des outils (Phases E et G) soit triviale :

1. **Loguru dès la Phase A** (pas en Phase G) : zéro `print()` ; logger configuré une seule fois dans un module dédié, sink JSON (`serialize=True`), `InterceptHandler` pour capter les logs uvicorn/FastAPI
2. **Corrélation par IDs** : `request_id`/`session_id` générés à l'entrée API et propagés partout (`logger.bind(...)`, metadata Langfuse, `trace.py`) — un même ID croise logs ↔ traces
3. **Chaque service naît avec `/health` + `/metrics`** : `prometheus-fastapi-instrumentator` sur chaque FastAPI ; Streamlit expose nativement `/_stcore/health` (cible Uptime Kuma) ; `HEALTHCHECK` dans chaque Dockerfile
4. **Nœuds purs, instrumentation centralisée** : aucun appel Langfuse/Prometheus/logging métier dans `nodes.py`/`router.py` — tout passe par les callbacks à l'invoke et le point d'entrée API. Observabilité **optionnelle et fail-open** (l'app tourne sans Langfuse ; handler no-op si clés absentes)
5. **Noms stables = spans stables** : les noms de nœuds (`add_node("rag", ...)`) deviennent les spans Langfuse et labels Prometheus — les fixer définitivement dès `pipeline.py`
6. **⚠️ Langfuse SDK v3** : le snippet du PDF est en v2 (`from langfuse.callback import CallbackHandler`) ; en v3 : `from langfuse.langchain import CallbackHandler`, clés lues depuis l'env. Pinner la version. Self-hosted v3 = 6 conteneurs (web, worker, Postgres, ClickHouse, Redis, MinIO) : prévoir la RAM, TZ UTC, volumes persistants ClickHouse
7. **Plan de ports fixé d'avance** (collision Langfuse/Grafana, tous deux sur 3000 par défaut) : Langfuse 3000, Uptime Kuma 3001, Grafana 3002, API 8000, Streamlit 8501, Prometheus 9090
8. **Config 12-factor** : toutes les URLs/clés d'outillage via `config.py` (pydantic-settings + `.env`) — pas de `os.environ[...] = "..."` en dur comme dans le snippet du PDF
9. **Provisioning as code (Phase G)** : dashboards Grafana JSON + datasources YAML versionnés (`grafana/provisioning/`) ; réseaux Docker et noms de conteneurs fixés tôt (scrape configs et cibles Uptime Kuma stables)

## Règle de travail — lifecycle, le « livre du projet »

Tenir `docs/lifecycle.md` **au fil de l'eau** (pas à la fin) : le cycle de vie complet d'une requête, étape par étape dans l'ordre du flux réel, au format constant « **Fichier — Entrées — Sorties** — ce qui s'y passe et pourquoi » (ex. saisie utilisateur → `app_frontend.py` → `POST /chat` → `src/main.py` → `graph/pipeline.py` → `rag_node` → routeur → `scraper_node`/`narration_node` → réponse). Objectif : à la fin du projet, ce document se lit comme un livre qui permet de comprendre HorRAGor3 sans ouvrir le code. Intégré à la doc Sphinx en Phase G.

## Règle de travail — vérification plan vs brief

**Avant de commencer à coder** (au démarrage et au début de chaque phase) : confronter le plan au brief `docs/HorRAGor BOT Partie 3.pdf` pour identifier les points d'attention et éviter les hors-piste. Concrètement :
- Relire la section du brief correspondant à la phase à coder
- Lister les écarts entre brief, plan et ce qu'on s'apprête à faire ; tout écart doit être explicite et validé (ex. la structure hybride est un écart volontaire déjà acté)
- Le projet est un livrable pédagogique évalué sur la conformité au brief (arborescence, règles d'or LangGraph, Langfuse, épilogue MLOps) : une « meilleure » solution hors brief reste un hors-piste

## Étapes d'implémentation

### Étape 0 — Mise en mémoire (demande explicite de l'utilisateur) ✅ fait
- Règle de travail « vérifier plan vs brief avant de coder » enregistrée (`verifier-plan-vs-brief-avant-code.md`)
Sauvegarder ce plan dans la mémoire persistante (`~/.claude/projects/-home-olivier-Bureau-Simplon-HorRAGor3/memory/`) :
- `horragor3-plan.md` (type `project`) : synthèse du brief, phases, décisions actées
- `horragor-ecosysteme.md` (type `project`) : cartographie HorRAGor1/2/MultiAgent et chemins des briques réutilisables
- Mettre à jour `MEMORY.md` avec les pointeurs

### Phase A — Socle du projet
1. Initialiser le repo : `git init`, `uv init` (Python ≥ 3.12), `pyproject.toml` avec `langgraph`, `langchain-ollama`, `langchain-core`, `faiss-cpu`, `fastapi`, `uvicorn[standard]`, `streamlit`, `httpx`, `pydantic-settings`, `sqlalchemy`, `psycopg[binary]`, `pgvector`, `ddgs`, `langfuse` ; dev : `ruff`, `pytest`, `pytest-asyncio`
2. Créer l'arborescence hybride actée (voir Décisions) ; `.env.example` sur le modèle de HorRAGor2
3. Reprendre de HorRAGor2 : `config.py` (adapté : + clés Langfuse), `contracts/schemas.py` + `interfaces.py`, `trace.py`
4. Copier `faiss_index/` de HorRAGor2 vers `data/faiss_index/` (ou script de reconstruction `build_faiss.py` repris)

### Phase B — Les outils natifs (src/tools/)
5. `rag_tool.py` : regrouper les fonctions data de HorRAGor2 (`validate_film` FAISS, `query_movie_metadata` SQL, `find_similar_horror_movies` pgvector) — fonctions pures, jamais d'exception (`{"found": false}` / `[]`)
6. `scraper_tool.py` : `scrape_detailed_synopsis` (Wikipédia, repris) + nouvelle recherche DuckDuckGo (`ddgs`) pour anecdotes/détails — même contrat « ne lève jamais »

### Phase C — Le graphe multi-agent (cœur du brief)
7. `models/state.py` : `AgentState(TypedDict)` — `messages: Annotated[list, add_messages]` + champs métier explicites (`lore` : résultats RAG, `web_findings` : résultats scraper, `is_complete` : jugement du RAG, `story` : sortie narration) pour le context trimming
8. `graph/nodes.py` : `rag_node` (LLM + rag tools via micro-boucle `ToolNode`), `scraper_node` (LLM + scraper tools), `narration_node` (**sans outils**, prompt « Écrivain Gothique », ne reçoit que la synthèse — context trimming, pas tout l'historique) — signature unique `(state: AgentState) -> dict`, aucun nœud ne connaît ses voisins
9. `graph/router.py` : `should_scrape_or_narrate(state) -> Literal["scraper", "narration"]` (juge la complétude de la récolte locale) + routeurs de micro-boucle outils (`-> Literal["rag_tools", ...]`) — pattern MultiAgent « le nœud juge, le routeur aiguille », fallback sûr
10. `graph/pipeline.py` : câblage sur le modèle de `build_peer_graph` (MultiAgent) avec nœuds/outils **injectables** pour tester sans LLM :
    `START → rag → (rag_tools ⇄ rag) → [should_scrape_or_narrate] → scraper → (scraper_tools ⇄ scraper) → narration → END` ; se termine par `app = workflow.compile()`
11. Réutiliser `common/tool_calls.py` de MultiAgent (parsing tolérant des tool calls Ollama) si `qwen2.5:7b` dévie ; briefs reformulés par agent (anti-collision de tokens)

### Phase D — API + Front
12. `src/main.py` : FastAPI (lifespan chargeant FAISS, `GET /health`, `POST /chat`) sur le modèle de HorRAGor2 ; le graphe compilé branché derrière `get_engine()` (contrat `AgentEngine` inchangé)
13. `app_frontend.py` : Streamlit adapté de `src/front/streamlit/app.py` — afficher quel(s) agent(s) ont travaillé (trace du parcours du graphe)

### Phase E — Monitoring Langfuse (exigence explicite du PDF)
14. Déployer Langfuse self-hosted : `git clone https://github.com/langfuse/langfuse && docker compose up -d` → UI `http://localhost:3000`, créer compte local + projet → clés
15. Intégrer `CallbackHandler` : clés dans `.env`/`config.py`, passer `config={"callbacks": [langfuse_handler]}` à l'invoke du graphe — ⚠️ SDK v3 : `from langfuse.langchain import CallbackHandler` (le snippet du PDF est en v2), clés lues depuis l'env
16. Livrable d'analyse : tokens par nœud, latence par agent, tracé des tool calls, arbre de décision du routeur

### Phase F — Tests + CI
17. Tests unitaires : routeurs purs (sans LLM, states forgés), nœuds avec LLM mocké (injection dans `build_graph`), outils (HTTP mocké), API (FakeEngine comme HorRAGor2) — viser ≥ 80 % dès maintenant (exigence de l'épilogue)
18. CI GitHub Actions ruff + pytest (reprendre `.github/workflows/ci.yml` de HorRAGor2)

### Phase G — Épilogue MLOps (Grand Final, gros chantier séparé)
19. **API Données dédiée** (nouvelle — n'existe pas dans HorRAGor1) : petite FastAPI CRUD lecture devant la BDD, conteneurisée, réseau privé Docker uniquement
20. **Conteneurisation 3 couches** : `docker-compose.yml` avec réseau privé étanche (BDD + API données), API IA (seul port exposé, **auth JWT access + refresh tokens**), Streamlit isolé (HTTPS vers l'API IA)
21. **Observabilité** : Loguru bout en bout, Prometheus + Grafana + Uptime Kuma (télémétrie des 3 composants), Langfuse (agents)
22. **Gouvernance** : doc Sphinx (autodoc des 2 API, schéma relationnel — reprendre docs/merise de HorRAGor1 —, cartographie du graphe via l'export Mermaid), GitHub Issues pour chaque anomalie

## Vérification

- **Routage sans LLM** : pytest sur `router.py` avec des states forgés (lore complet → "narration" ; lore vide → "scraper")
- **Graphe bout en bout** : `app.invoke({"messages": [HumanMessage("Parle-moi de Hereditary")]})` → vérifier le chemin RAG→narration (film connu) vs RAG→scraper→narration (film obscur/absent de la base)
- **API** : `curl POST /chat` + `GET /health` ; front Streamlit conversationnel
- **Langfuse** : traces visibles sur `localhost:3000` avec l'arbre des nœuds et le coût par agent
- **Narration isolée** : vérifier dans les traces que `narration_node` ne reçoit que la synthèse (pas les logs d'outils bruts)
- Prérequis d'exécution : Ollama (`qwen2.5:7b`, `nomic-embed-text`), Supabase joignable (ou repli SQLite HorRAGor1), Docker pour Langfuse
