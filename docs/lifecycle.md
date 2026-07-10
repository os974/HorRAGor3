# Lifecycle — le livre du projet HorRAGor3

Ce document suit le **cycle de vie complet d'une requête** à travers le système,
fichier par fichier, dans l'ordre du flux réel — pas dans l'ordre d'écriture du
code. Chaque étape suit le format constant : **Fichier — Entrées — Sorties — ce
qui s'y passe et pourquoi**. Il est tenu au fil de l'eau (règle de travail du
projet) : à la fin, il doit se lire comme un livre qui permet de comprendre
HorRAGor3 sans ouvrir le code.

## Vue d'ensemble du flux

```
Utilisateur (navigateur)
   │ question en français
   ▼
app_frontend.py (Streamlit)                     [Phase D — à venir]
   │ POST /chat {message, session_id}
   ▼
src/main.py (FastAPI)                           [Phase D — à venir]
   │ ChatRequest → AgentEngine.run()
   ▼
src/graph/pipeline.py (graphe compilé)
   │ State initial {question}
   ▼
rag_node ⇄ rag_tools (fouille locale)
   │ state.lore, state.is_complete
   ▼
router: should_scrape_or_narrate
   │ "narration" si le lore suffit, sinon "scraper"
   ├─────────────► scraper_node ⇄ scraper_tools
   │                  │ state.web_findings
   ▼                  ▼
narration_node (plume gothique, sans outils)
   │ state.story
   ▼
ChatResponse {answer, sources, path, trace} → Front → Utilisateur
```

---

## Chapitre 0 — Les fondations transverses (Phase A)

Ces fichiers ne sont pas des étapes du flux : ils sont utilisés par **toutes**
les étapes. Ils se lisent en premier car tout le reste s'appuie dessus.

### `pyproject.toml`
- **Entrées** : —
- **Sorties** : l'environnement (`uv sync` → `.venv/`), les règles ruff/pytest.
- **Ce qui s'y passe** : déclare les dépendances (LangGraph, FastAPI, Streamlit,
  FAISS, ddgs, Langfuse v3 épinglé, Loguru…). Projet « application » non packagé
  (`package = false`) : on lance depuis la racine et on importe en `src.*`,
  conformément à l'arborescence du brief. La règle ruff `T201` interdit les
  `print()` (règle observabilité : Loguru partout).

### `src/config.py`
- **Entrées** : le fichier `.env` à la racine (secrets) + les défauts codés ici.
- **Sorties** : l'objet unique `settings`, importé partout.
- **Ce qui s'y passe** : pydantic-settings valide et type tous les réglages —
  connexion Supabase, modèles Ollama (`qwen2.5:7b`, `nomic-embed-text` 768d),
  chemins FAISS, clés Langfuse (vides = monitoring désactivé, fail-open),
  température de la Narration (0.7, seule créative). Une seule source de
  vérité : aucun `os.environ` en dur ailleurs dans le code.

### `src/logging_conf.py`
- **Entrées** : `settings.log_level`.
- **Sorties** : logs lisibles sur stderr + `logs/app.jsonl` (JSON, pour la
  stack de monitoring de la Phase G).
- **Ce qui s'y passe** : configure Loguru une seule fois (`setup_logging()`)
  et intercepte les logs stdlib (uvicorn, fastapi) via `InterceptHandler` pour
  n'avoir qu'un seul flux de logs. Appelé au démarrage de l'API et du Front.

### `src/contracts/schemas.py`
- **Entrées** : — (définitions pures).
- **Sorties** : les modèles Pydantic `ChatRequest`, `ChatResponse`, `FilmRef`,
  `FilmMetadata`, `TraceStep`.
- **Ce qui s'y passe** : fige la forme JSON échangée entre Front et API (et le
  schéma OpenAPI généré). Nouveauté Partie 3 : `ChatResponse.path` liste les
  agents traversés (ex. `["rag", "scraper", "narration"]`) pour rendre le
  parcours du graphe visible côté Front.

### `src/contracts/interfaces.py`
- **Entrées** : les schémas ci-dessus.
- **Sorties** : les Protocols `AgentEngine` et `FilmRepository`.
- **Ce qui s'y passe** : l'API ne connaîtra que `AgentEngine.run(ChatRequest)
  → ChatResponse` — on branche un mock dans les tests puis le vrai graphe sans
  toucher à l'API. `FilmRepository` garantit que les outils n'écrivent jamais
  de SQL eux-mêmes.

### `src/trace.py`
- **Entrées** : appels `record(kind, name, detail)` depuis n'importe quelle
  profondeur du code pendant un run.
- **Sorties** : la liste d'étapes insérée dans `ChatResponse.trace` +
  l'historique `logs/traces.jsonl` (1 ligne JSON par run).
- **Ce qui s'y passe** : un `ContextVar` collecte les événements du run courant
  sans faire transiter un collecteur dans les signatures — les nœuds du graphe
  restent des fonctions pures. Repris de HorRAGor2, enrichi du `path`.

### `data/faiss_index/` (titles.index + titles_map.json)
- **Entrées** : construit dans HorRAGor2 à partir des 33 961 titres de la base
  HorRAGor1 (embeddings `nomic-embed-text`, IndexFlatIP cosinus).
- **Sorties** : la validation titre → id utilisée par l'agent RAG.
- **Ce qui s'y passe** : copié tel quel depuis HorRAGor2 (gitignoré, 101 Mo).
  ⚠️ Les ids doivent rester alignés avec la base : si HorRAGor1 recharge ses
  données, reconstruire l'index.

---

## Chapitre 1 — Les outils natifs (Phase B)

Les outils sont les **mains** des agents : des fonctions Python pures que les
nœuds du graphe exposeront au LLM (Phase C). Contrat commun, pensé pour un
agent : **aucune fonction publique ne lève jamais d'exception** — erreur
technique → None/[]/message explicite + log Loguru + trace. Un outil qui
plante ne fait pas s'effondrer le graphe ; c'est le routeur qui décidera de
la suite (ex. récolte locale vide → Scraper).

### `src/data/` — la plomberie sous les outils (reprise de HorRAGor2)
- **Entrées** : `settings` (Ollama, DATABASE_URL, chemins FAISS).
- **Sorties** : primitives typées utilisées par les outils.
- **Ce qui s'y passe** : `embed.py` (vecteurs via Ollama `/api/embed`, garde-fou
  sur la dimension 768), `faiss_index.py` (classe `TitleIndex`, IndexFlatIP
  cosinus, recherche sans embedding → testable sans Ollama), `db.py` (engine
  SQLAlchemy unique, Supabase ou repli `sqlite:///../HorRAGor1/...`),
  `repository.py` (SQL paramétré — le LLM n'écrit JAMAIS de SQL), `tmdb.py`
  (réalisateur/casting, absents de la base). Les agents n'accèdent jamais à
  cette couche directement : toujours via les outils.

### `src/tools/rag_tool.py` — l'outil de l'Agent RAG (Chercheur Local)
- **Entrées** : un titre approximatif, puis un `film_id` confirmé.
- **Sorties** : `FilmRef` (validation), `FilmMetadata` (lore brut : année,
  genres, note, synopsis, réalisateur/casting via TMDB), `list[FilmRef]`
  (recommandations pgvector).
- **Ce qui s'y passe** : `validate_film` embedde le titre et interroge FAISS —
  score ≥ 0.75 = film confirmé avec son id ; la casse est normalisée, mais une
  faute de frappe tombe sous le seuil → None (c'est voulu : le routeur enverra
  alors enquêter le Scraper). `query_movie_metadata` va chercher le lore en SQL
  avec cet id (seule source autorisée pour les faits — 0 hallucination) et
  enrichit réalisateur/casting via TMDB en best-effort. `find_similar_horror_movies`
  interroge pgvector (contenu des synopsis, pas les titres). Singletons
  injectables (`set_index`/`set_repository`) : l'API injecte les vrais au
  démarrage, les tests des fakes.

### `src/tools/scraper_tool.py` — l'outil de l'Agent Scraper (Enquêteur du Web)
- **Entrées** : un titre (Wikipédia) ou une requête libre (DuckDuckGo).
- **Sorties** : un extrait encyclopédique (str), ou une liste de
  `{"title", "url", "snippet"}`.
- **Ce qui s'y passe** : `scrape_detailed_synopsis` appelle l'API REST
  Wikipédia (résumé d'article, gestion des homonymies, User-Agent ASCII
  obligatoire). `search_web` interroge DuckDuckGo via `ddgs` (métamoteur sans
  clé API) pour les anecdotes hors Wikipédia — ex. la page trivia IMDb d'un
  film. Les messages d'erreur sont rédigés pour être restitués tels quels par
  l'agent (« Aucune page Wikipédia trouvée pour... »).

---

## Chapitre 2 — Le graphe multi-agent (Phase C)

Le cœur du brief : trois agents en chaîne directe, sans manager central.
Une requête y entre comme une `question` et en ressort comme une `story`.

### `src/models/state.py` — le cahier des charges commun
- **Entrées** : les écritures de chaque nœud (dicts fusionnés par LangGraph).
- **Sorties** : la mémoire commune typée (`AgentState`).
- **Ce qui s'y passe** : choix structurant — **un canal de messages PAR agent**
  (`rag_messages`, `scraper_messages`) au lieu d'un historique unique. C'est
  l'isolation de contexte du brief : chaque agent ne voit que sa propre
  micro-conversation, la Narration ne voit aucun message. Les autres cases du
  dossier : `lore` (faits locaux), `is_complete` (jugement du RAG),
  `web_findings` (faits web), `story` (récit final), `path` (nœuds traversés,
  reducer `operator.add`).

### `src/graph/nodes.py` — les Ouvriers (la logique métier)
- **Entrées** : `state` (paramètre unique, règle d'or du brief).
- **Sorties** : un dict de modifications à fusionner — jamais d'effet de bord.
- **Ce qui s'y passe** : les trois personnalités vivent ici (prompts
  SystemMessage). `rag_node` (température 0, outils `RAG_TOOLS`) fouille en
  micro-boucle puis **juge sa récolte de façon déterministe** : `is_complete`
  = au moins un outil a marqué `"found": true` — aucun LLM dans la décision
  de routage. `scraper_node` reçoit un brief reformulé (question + lore),
  jamais l'historique du Chercheur (anti-collision de tokens). Il fige ses
  `web_findings` (faits bruts du web). `narration_node` (température 0.7,
  AUCUN outil) reçoit un dossier synthétique — question + lore + web_findings
  — et rien d'autre : l'Écrivain Gothique n'a jamais vu un log technique.
  Les nœuds ignorent qui précède et qui suit.

### `src/graph/router.py` — les Aiguilleurs (la logique décisionnelle)
- **Entrées** : `state` (lecture seule).
- **Sorties** : un `str` — la prochaine destination, rien d'autre.
- **Ce qui s'y passe** : `should_scrape_or_narrate` (le carrefour stratégique
  du brief) lit `is_complete` : true → "narration", false → "scraper" (et
  prudence par défaut : state vide → "scraper"). `should_continue_rag` et
  `should_continue_scraper` gèrent les micro-boucles outil (`tool_calls`
  présents → nœud outil). Fonctions pures : testées avec des states forgés,
  sans lancer le pipeline ni le moindre LLM.

### `src/graph/pipeline.py` — l'Ingénieur Système (le câblage)
- **Entrées** : nœuds + routeurs (injectables pour les tests).
- **Sorties** : `app = workflow.compile()` — le livrable importé par FastAPI.
- **Ce qui s'y passe** : le point de vérité de la topologie, via les trois
  méthodes du brief : `add_node` (5 nœuds : rag, rag_tools, scraper,
  scraper_tools, narration), `add_edge` (START→rag ; micro-boucles
  outil→agent ; narration→END), `add_conditional_edges` (les aiguilleurs aux
  deux carrefours). Chaque `ToolNode` est branché sur le canal de messages de
  SON agent (`messages_key`) : l'isolation tient jusque dans l'exécution des
  outils.

**Vu en conditions réelles** (qwen2.5:7b local) : « Parle-moi du film
Hereditary » → `[rag, narration]` en ~18 s ; « anecdotes du film 'Heriditary' »
(faute de frappe) → lookup sous le seuil FAISS → `[rag, scraper, narration]`
en ~26 s, l'Enquêteur rapportant les anecdotes réelles (ScreenRant/IMDb) que
la plume gothique romance sans inventer.

---

*Chapitres suivants (au fil des phases) : API et Front (D), monitoring
Langfuse (E).*
