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
app_frontend.py (Streamlit) — un session_id par conversation
   │ POST /chat {message, session_id} + jeton JWT (HTTPS via Traefik en cluster)
   ▼
src/main.py (FastAPI) → src/engine.py (GraphEngine)
   │ ChatRequest → AgentEngine.run()
   ▼
src/graph/pipeline.py (app = workflow.compile())
   │ State initial {question}
   ▼
rag_node ⇄ rag_tools (fouille locale : FAISS, puis base via l'API Données)
   │ state.lore
   ▼
router: should_scrape_or_narrate (« la récolte suffit-elle ? »)
   │ "narration" si lore non vide et question locale, sinon "scraper"
   ├─────────────► scraper_node ⇄ scraper_tools
   │                  │ state.web_findings
   ▼                  ▼
narration_node (plume gothique, sans outils)
   │ state.story
   ▼
ChatResponse {answer, sources, path, trace} → Front → Utilisateur
```

En cluster, chaque flèche franchit un réseau Docker isolé : la topologie
finale (Traefik et TLS, JWT, API Données, Postgres conteneurisé) est au
chapitre 10, la stack d'observabilité au chapitre 11.

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
  `print()` (règle observabilité : Loguru partout). Version 1.0.0 ;
  `.python-version` épingle Python 3.12, comme la CI et les images.

### `src/config.py`
- **Entrées** : le fichier `.env` à la racine (secrets) + les défauts codés ici.
- **Sorties** : l'objet unique `settings`, importé partout.
- **Ce qui s'y passe** : pydantic-settings valide et type tous les réglages —
  URL de la base (Supabase en dev, Postgres du cluster pour la seule API
  Données), modèles Ollama (`qwen2.5:7b`, `nomic-embed-text` 768d),
  chemins FAISS, clés Langfuse (vides = monitoring désactivé, fail-open),
  température de la Narration (0.7, seule créative). Une seule source de
  vérité : aucun `os.environ` en dur ailleurs dans le code.

### `src/logging_conf.py`
- **Entrées** : `settings.log_level`.
- **Sorties** : logs lisibles sur stderr + `logs/app.jsonl` (JSON ; les
  identifiants de corrélation `session_id`/`request_id` y figurent dans
  `extra`). Ce fichier est prêt pour un agrégateur de logs mais aucun
  composant de la stack ne le collecte : en cluster, on lit
  `docker compose logs`.
- **Ce qui s'y passe** : configure Loguru une seule fois (`setup_logging()`)
  et intercepte les logs stdlib via `InterceptHandler` pour n'avoir qu'un seul
  flux de logs, chaque ligne signée par son vrai appelant. Les loggers
  d'uvicorn, configurés par le serveur avant l'import de l'app, sont
  explicitement rebranchés (chapitre 17). Appelé par les deux API et par le
  Front.

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
- **Ce qui s'y passe** : copié tel quel depuis HorRAGor2 (gitignoré, 101 Mo),
  ou reconstruit depuis la base par `uv run python -m scripts.build_faiss`
  (chapitre 17). ⚠️ Les ids doivent rester alignés avec la base : si HorRAGor1
  recharge ses données, reconstruire l'index.

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
  injectables (`set_index`/`set_repository`) : l'API injecte l'index FAISS au
  démarrage, le repository est construit au premier appel (client de l'API
  Données en cluster, SQL direct en dev), les tests injectent des fakes.

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
  dossier : `lore` (faits locaux, que le routeur juge), `web_findings` (faits
  web), `story` (récit final), `path` (nœuds traversés, reducer
  `operator.add`).

### `src/graph/nodes.py` — les Ouvriers (la logique métier)
- **Entrées** : `state` (paramètre unique, règle d'or du brief).
- **Sorties** : un dict de modifications à fusionner — jamais d'effet de bord.
- **Ce qui s'y passe** : les trois personnalités vivent ici (prompts
  SystemMessage). `rag_node` (température 0, outils `RAG_TOOLS`) fouille en
  micro-boucle puis **fige sa récolte** dans `lore` : les résultats d'outils
  marqués `"found": true` (`harvest_facts`). Il ne la juge pas : c'est le
  rôle du routeur. `scraper_node` reçoit un brief reformulé (question +
  lore), jamais l'historique du Chercheur (anti-collision de tokens). Il fige
  ses `web_findings` (faits bruts du web). `narration_node` (température 0.7,
  AUCUN outil) reçoit un dossier synthétique — question + lore + web_findings
  — et rien d'autre : l'Écrivain Gothique n'a jamais vu un log technique.
  Les nœuds ignorent qui précède et qui suit, et n'écrivent aucun log :
  l'instrumentation passe par la trace, les callbacks Langfuse et le moteur.
  *(Avant le chapitre 17, `rag_node` jugeait lui-même sa récolte dans un
  booléen `is_complete` que le routeur ne faisait que lire.)*

### `src/graph/router.py` — les Aiguilleurs (la logique décisionnelle)
- **Entrées** : `state` (lecture seule).
- **Sorties** : un `str` — la prochaine destination, rien d'autre.
- **Ce qui s'y passe** : `should_scrape_or_narrate` (le carrefour stratégique
  du brief) porte **la règle logique** que le brief y place : « le message de
  l'agent RAG contient-il assez d'informations ? ». Deux critères
  déterministes, aucun LLM : `lore` non vide **ET** une question qui ne
  réclame pas d'informations hors du périmètre local (`wants_web_details` :
  mots-clés anecdotes/coulisses/tournage... — la base n'a que métadonnées et
  synopsis, donc ces demandes envoient l'Enquêteur même si le film est
  connu). Oui → "narration", non → "scraper" ; state vide → "scraper" par
  prudence. La raison de la décision est inscrite dans la trace (« récolte
  locale vide », « détails web exigés par la question »…). `should_continue_rag` et
  `should_continue_scraper` gèrent les micro-boucles outil (`tool_calls`
  présents → nœud outil). Fonctions pures : testées avec des states forgés,
  sans lancer le pipeline ni le moindre LLM.

### `src/graph/pipeline.py` — l'Ingénieur Système (le câblage)
- **Entrées** : nœuds + routeurs (injectables pour les tests).
- **Sorties** : le fichier se termine par `workflow = build_workflow()` puis
  `app = workflow.compile()` — le livrable du brief, importé par FastAPI. Les
  tests passent par `build_graph(...)`, qui compile un graphe aux nœuds
  injectés.
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

## Chapitre 3 — L'API et le Front (Phase D)

La requête traverse maintenant tout le système, du navigateur au récit.

### `app_frontend.py` — la salle de lecture (Streamlit)
- **Entrées** : la question tapée dans `st.chat_input` ; l'historique de
  `st.session_state`.
- **Sorties** : `POST /chat` vers l'API ; l'affichage du récit, du **parcours
  des agents** (🔎 Chercheur → 🕵️ Enquêteur → 🖋️ Écrivain — la preuve visuelle
  du routage conditionnel), des sources, et l'expander « Dans les coulisses du
  manoir » (la trace complète).
- **Ce qui s'y passe** : découplage strict — aucune logique LLM/BDD, seulement
  un client HTTP qui revalide la réponse contre le contrat Pydantic partagé.
  Toute erreur API s'affiche en bulle, jamais de crash. Chaque conversation
  reçoit son `session_id` (uuid4, renouvelé par « Nouvelle conversation ») et
  le Front journalise via Loguru (chapitre 17). Lancement :
  `uv run streamlit run app_frontend.py`.

### `src/main.py` — la porte d'entrée (FastAPI/Uvicorn)
- **Entrées** : requêtes HTTP (`/health`, `/metrics`, `POST /chat`).
- **Sorties** : `ChatResponse` JSON ; métriques Prometheus ; logs Loguru.
- **Ce qui s'y passe** : `setup_logging()` unifie les logs (uvicorn compris) ;
  le `lifespan` charge l'index FAISS une fois en RAM (dégradation propre s'il
  manque) et l'injecte dans `rag_tool` ; `/metrics` est exposé dès la
  naissance (prometheus-fastapi-instrumentator — règle observabilité) ;
  `/chat` délègue au moteur via l'abstraction `AgentEngine` (inversion de
  dépendance : les tests injectent un fake) et pose `session_id` et un
  `request_id` dans le contexte Loguru (chapitre 17). Lancement :
  `uv run uvicorn src.main:app --reload`.

### `src/engine.py` — le pont contrat ↔ graphe (GraphEngine)
- **Entrées** : `ChatRequest` (message + session_id).
- **Sorties** : `ChatResponse` (récit, path, sources, trace) — **jamais
  d'exception** : récursion excessive ou panne → réponse de repli gothique,
  pas de 500.
- **Ce qui s'y passe** : `trace.begin()` ouvre la collecte ; le graphe
  synchrone s'exécute dans `asyncio.to_thread` (la boucle FastAPI ne gèle
  pas, le ContextVar se propage) ; `story` devient `answer`, `path` sort tel
  quel, les `sources` sont dérivées de la trace (kinds faiss/sql/pgvector/
  tmdb/wikipedia/ddg) ; `_invoke_config()` est le point d'ancrage du
  CallbackHandler Langfuse (branché au chapitre 4) ; une ligne Loguru résume
  le run (parcours, tailles du lore, des trouvailles web et du récit) ;
  `log_trace` archive le run dans `logs/traces.jsonl`.

**Vu en conditions réelles** : `.env` branché sur Supabase (métadonnées
enrichies TMDB : réalisateur/casting, et recommandations pgvector réelles) ;
`/health` ok, `/metrics` Prometheus actif, « Des films semblables à
Midsommar ? » → `[rag, narration]`, 7 étapes de trace, réponse gothique en
19 s ; Streamlit démarré, `/_stcore/health` = ok (sondé par Uptime Kuma depuis
le chapitre 11).

---

## Chapitre 4 — Le monitoring Langfuse (Phase E)

Langfuse est le « tableau de bord visuel » du registre de bord : chaque
question devient une **trace** consultable sur `http://localhost:3000`.

### La stack Langfuse (self-hosted)

*(État Phase E : instance hors du repo, lancée par `git clone` comme dans le
brief. Depuis le chapitre 11, Langfuse est intégré à la stack du projet,
sans port ClickHouse publié, avec ses clés provisionnées au démarrage.)*

- **Entrées** : les événements envoyés par le CallbackHandler de l'API.
- **Sorties** : l'UI d'analyse (arbre des décisions, tokens, latences, coûts).
- **Ce qui s'y passe** : `docker compose up -d` démarre 6 conteneurs — web
  (l'UI, port 3000), worker (ingestion), Postgres (comptes/projets),
  ClickHouse (le stockage analytique des traces), Redis (file d'attente),
  MinIO (blobs). ⚠️ Particularité locale : ClickHouse voulait publier le port
  hôte 9000, déjà pris par Portainer → `docker-compose.override.yml` le
  décale vers 9002 (les services internes n'en dépendent pas).

### `src/engine.py::_langfuse_callbacks()` — le branchement
- **Entrées** : `settings.langfuse_*` (clés du `.env` ; générées dans l'UI à
  ce stade, provisionnées depuis le chapitre 11).
- **Sorties** : le `CallbackHandler` passé au graphe via
  `config={"callbacks": [...]}` (le mécanisme exact du brief), plus
  `langfuse_session_id` pour regrouper les traces par conversation. *(Le
  Front n'envoyait alors que « default » : une seule session pour tous,
  corrigé au chapitre 17.)*
- **Ce qui s'y passe** : **fail-open** — clés absentes ou serveur éteint →
  tuple vide, l'application fonctionne à l'identique. SDK **v3** : l'import
  est `from langfuse.langchain import CallbackHandler` (le snippet v2 du
  brief n'est plus valide) et le client est initialisé explicitement depuis
  `settings` (pas de `os.environ` en dur). Piège rencontré : l'intégration
  exige le méta-paquet `langchain` en plus de `langchain-core` — ajouté aux
  dépendances.

### Ce qu'on lit dans une trace (vu en réel, question « anecdotes Heriditary »)
- L'arbre : `LangGraph` → CHAIN par nœud (`rag`, `scraper`, `narration`) et
  par **routeur** (`should_continue_rag`, `should_continue_scraper` — l'arbre
  de décisions du brief), TOOL par outil (`lookup_movie`,
  `wikipedia_synopsis`, `web_search`).
- Les 8 générations LLM avec **tokens entrée/sortie et latence chacune** —
  ex. la narration finale : 1 454 tokens in → 525 out en 13,5 s ; les
  décisions d'outils : ~25-40 tokens out en ~1 s.
- La preuve du **context trimming** : la génération de la narration ne
  contient que le dossier synthétique, pas les logs d'outils.

---

## Chapitre 5 — Les tests et la CI (Phase F)

Les tests ne sont pas une étape du flux : ils sont le **filet de sécurité**
sous chaque étape. 83 tests, ~92 % de couverture, exécution < 1 s.

- **Hermétiques par construction** : aucun test n'a besoin d'Ollama, de
  Supabase, du réseau ni de l'index FAISS. C'est le dividende des choix
  d'architecture : routeurs purs (states forgés à la main), nœuds testés avec
  un `FakeLLM` (monkeypatch des fabriques), graphe compilé avec des **nœuds
  injectés** (`build_graph(rag=faux_rag, ...)` — le routage réel se vérifie
  sans un seul appel IA), API testée avec un `FakeEngine` derrière
  l'abstraction `AgentEngine`, repository sur une SQLite en mémoire au même
  schéma, httpx/ddgs doublés.
- **Ce que les tests verrouillent** : les deux chemins du graphe (lore
  suffisant → narration directe ; insuffisant → détour Enquêteur), le
  jugement déterministe (`harvest_facts`, `wants_web_details`, routeur depuis
  le chapitre 17 — dont le cas
  « anecdotes d'un film connu → Enquêteur quand même »), le contrat
  « jamais d'exception » des outils (Ollama éteint, TMDB en panne, réseau
  coupé), le « jamais de 500 » du moteur (récursion, panne → repli gothique),
  le context trimming (la plume ne reçoit que system + dossier), et le
  garde-fou de dimension des embeddings.
- **CI** (`.github/workflows/ci.yml`) : à chaque push/PR sur main — ruff
  check + format, puis pytest avec `fail_under = 80` (l'exigence du brief est
  un verrou de build, pas une intention). *(État Phase F ; déclencheurs et
  périmètre élargis au chapitre 13.)*
- L'UI Streamlit (`app_frontend.py`) était alors hors mesure ; elle est testée
  depuis le chapitre 8 (`streamlit.testing.v1.AppTest`).

---

## Chapitre 6 — La couche Données encapsulée (Phase G1)

Premier acte de l'épilogue MLOps : la base n'est plus jamais touchée
directement par la couche IA.

### `services/data_api/main.py` — l'API Données (couche 1 du brief)
- **Entrées** : `GET /films/{id}`, `GET /films/{id}/similar?k=` (+ `/health`,
  `/metrics`) — appelées uniquement par l'API IA via le réseau privé.
- **Sorties** : `FilmMetadata` / `list[FilmRef]` (contrats partagés) ; 404 si
  film inconnu ; **503** propre si la base est injoignable (jamais de 500 brut).
- **Ce qui s'y passe** : c'est désormais le SEUL composant à connaître
  `DATABASE_URL` (Supabase encapsulé à ce stade ; décision révisée au
  chapitre 9 : la base elle-même rejoint le cluster). Réutilise `SqlFilmRepository` tel quel,
  Loguru, Instrumentator, repository injectable pour les tests. En cluster
  (G3), ce service n'aura **aucun port publié**.

### `src/data/http_repository.py` — le client côté IA
- **Entrées** : les appels de `rag_tool` (get_metadata, recommend_similar).
- **Sorties** : les mêmes objets typés que le repository SQL — contrat
  `FilmRepository` identique, revalidé par Pydantic à la réception.
- **Ce qui s'y passe** : le swap prévu depuis la Phase A paie : `rag_tool`
  choisit l'implémentation selon `DATA_API_URL` (définie → HTTP via le réseau
  privé ; vide → accès direct Supabase, mode dev). 404 → None (même
  sémantique), erreurs réseau → exceptions httpx, absorbées par le contrat
  « jamais d'exception » de la couche outils.

**Vu en réel** : API Données sur :8100 face à Supabase (film 41 = Hereditary
2018, similaires de Midsommar, 404 propre) ; puis API IA lancée avec
`DATA_API_URL=http://127.0.0.1:8100` → `/chat` complet, et la **preuve par
Prometheus** : les compteurs `http_requests_total{handler="/films/..."}` de
l'API Données ont enregistré les requêtes émises par le graphe.

### ⚠️ Incident — quota Supabase saturé (2026-09-03)

Le plan gratuit Supabase (500 Mo) a débordé brutalement (502 Mo) sans aucun
changement côté HorRAGor3 — le repository ne fait que des `SELECT`, les tests
sont hermétiques, la CI n'avait pas tourné. Cause réelle, trouvée par
diagnostic SQL (`pg_stat_user_tables`, `pg_indexes`) : **le projet Supabase
est partagé avec HorRAGor2** (même `DATABASE_URL`), et l'index pgvector
`movie_embeddings_hnsw` construit par `HorRAGor2/build_embeddings.py`
(768 dimensions, ~34k films) pesait **256 Mo à lui seul** — plus que la
donnée brute elle-même (437 Mo au total pour `movie_embeddings` sur 502 Mo de
base, soit 87 %). Correctif appliqué : `DROP INDEX CONCURRENTLY
movie_embeddings_hnsw` — aucune donnée touchée, `recommend_similar` reste
fonctionnel (scan séquentiel, non mesurable à cette échelle). Base repassée à
245 Mo. Point de vigilance pour la suite : un futur `uv run
horragor-reset-data` côté HorRAGor2 recréera cet index HNSW et remplira la
base à nouveau — à éviter sur ce plan gratuit, ou reconstruire l'index avec des
paramètres plus légers (`m`/`ef_construction` réduits) si la perf de
`recommend_similar` devient un jour un vrai problème.

---

## Chapitre 7 — Le verrou JWT access/refresh (Phase G2)

Le brief exige « un système d'authentification robuste par Refresh Tokens
pour verrouiller les échanges avec l'IHM ». Le flux d'une session :

### `src/auth.py` — la serrurerie
- **Entrées** : `POST /auth/login` (compte démo `APP_USERNAME`/`APP_PASSWORD`
  du `.env`) ; `POST /auth/refresh` (le jeton long).
- **Sorties** : une paire de JWT signés HS256 (`JWT_SECRET`) — **access**
  ~15 min (présenté en `Authorization: Bearer` à chaque `/chat` : s'il fuite,
  il expire vite) + **refresh** ~12 h (sert UNIQUEMENT à renouveler, avec
  rotation complète à chaque usage ; durée révisée au chapitre 10, avec la
  révocation des refresh rejoués).
- **Ce qui s'y passe** : chaque jeton porte son `type` — un refresh présenté
  sur `/chat` est refusé, un access sur `/auth/refresh` aussi. La dépendance
  `require_access` verrouille les routes métier (401 explicites : jeton
  requis / invalide / expiré). Auth non configurée → 503 propre.

### `app_frontend.py` — la porte du manoir
- **Entrées** : le formulaire « 🗝️ Entrée du manoir » (sidebar).
- **Sorties** : les jetons en `session_state` ; l'accès au chat.
- **Ce qui s'y passe** : porte close tant que non connecté (`st.stop()`).
  À chaque question, l'access token part en Bearer ; sur 401, le front tente
  UNE prolongation silencieuse via le refresh puis rejoue la requête — la
  session se prolonge sans que l'utilisateur ne s'en aperçoive, jusqu'à
  expiration du refresh (reconnexion demandée avec élégance).

**Vu en réel** : `/chat` sans jeton → 401 ; mauvais mot de passe → 401 ;
login → paire de jetons ; `/chat` avec Bearer → 200 et récit complet.
10 tests couvrent la serrurerie (types croisés, expiration, non configurée) ;
13 après la révocation des refresh rejoués (chapitre 10).

---

## Chapitre 8 — Le cluster Docker (Phase G3)

Le voyage d'une requête traverse désormais des conteneurs isolés :

```
navigateur ── https://horragor.localhost ──> traefik (443, SEUL port publié)
   ├──> frontend (Streamlit, conteneur isolé)
   │       │ https://api.horragor.localhost (TLS VÉRIFIÉ contre notre CA)
   │       ▼
   └──> api-ia (JWT) ──data_net (internal, étanche)──> api-donnees ──> Supabase
              └──host-gateway──> Ollama (hôte) · Langfuse (hôte:3000) · web
```
*(État à ce chapitre : la base rejoint le cluster au chapitre 9, Langfuse au
chapitre 11, et la topologie est durcie au chapitre 10.)*

### `scripts/gen_certs.sh` + `traefik/`
- **Entrées** : openssl (une fois).
- **Sorties** : `certs/` (gitignoré) — une CA locale + le certificat du
  cluster (SAN `horragor.localhost`, `api.horragor.localhost`), servi par
  Traefik (`traefik/dynamic.yml`).
- **Ce qui s'y passe** : la « communication chiffrée » du brief, sans
  compromis : le front vérifie le certificat contre la CA montée
  (`SSL_CERT_FILE=/certs/ca.pem`, honoré nativement par httpx) — pas de
  `verify=False`.

### `docker-compose.yml` — la topologie du cluster
- **Entrées** : le `.env` racine (substitution des `${VAR}`).
- **Sorties** : 4 services — traefik, frontend, api-ia, api-donnees.
- **Ce qui s'y passe** : `data_net` est **internal** (le réseau privé étanche
  du brief : api-donnees n'a AUCUN port publié, seul api-ia l'atteint) ;
  api-donnees possède une seconde patte réseau pour joindre Supabase
  (supprimée au chapitre 9, quand la base rejoint le cluster) ;
  **ségrégation des secrets** : `DATABASE_URL` n'est fourni qu'à api-donnees,
  api-ia ne reçoit que `DATA_API_URL` ; Ollama et Langfuse restent sur l'hôte
  (`host-gateway` ; Langfuse est intégré au chapitre 11) ; l'index FAISS est monté en volume RO (jamais dans
  l'image) ; Traefik résout `api.horragor.localhost` en interne (alias
  réseau) et route le navigateur vers le front. Chaque Dockerfile embarque
  un `HEALTHCHECK` (sondes Docker + Uptime Kuma).

### Les tests de l'UI (`tests/test_frontend.py`)
- `streamlit.testing.v1.AppTest` pilote le vrai script Streamlit, httpx
  mocké : porte close sans session, login réussi/refusé, chat complet (récit
  + parcours + sources), déconnexion. `app_frontend.py` entre dans la
  couverture — l'exigence « les deux API **et l'UI** » est complète.

### ⚠️ Pièges rencontrés
- **« client version 1.24 is too old »** (#2) : Traefik ne découvrait aucun
  service ; Docker Engine ≥ 28 exige l'API ≥ 1.44, que l'ancien client de
  Traefik ne négociait pas. Correctif : `traefik:v3` +
  `DOCKER_API_VERSION=1.44`.
- **504 vers l'API IA** (#3) : api-ia a deux pattes réseau et Traefik
  choisissait parfois l'IP de `data_net`, qu'il ne peut pas joindre.
  Correctif : `--providers.docker.network=horragor3_front_net`.
- Les deux correctifs sont devenus sans objet au chapitre 10, quand le
  routage est passé en fichier : plus de socket Docker, et chaque service est
  visé par son nom sur le réseau partagé.

**Vu en réel** : les deux pièges ci-dessus sont apparus au premier démarrage
du cluster. La vérification complète de la topologie (TLS vérifié, seul le 443
publié, login puis `/chat`, `api-donnees` injoignable) a été faite une fois la
base intégrée : elle est consignée au chapitre 9.

---

## Chapitre 9 — La base souveraine (BDD conteneurisée)

Relecture du brief : « La base de données doit être encapsulée derrière sa
propre API dédiée. **L'ensemble** doit être conteneurisé au sein d'un réseau
privé Docker étanche », pour une « infrastructure **souveraine** ». Garder
Supabase (un service cloud) derrière l'API laissait la base elle-même hors du
cluster : elle y entre désormais.

```
api-ia ──data_net (internal)──> api-donnees ──db_net (internal)──> db (Postgres + pgvector)
```

### `scripts/dump_supabase.sh` — l'extraction
- **Entrées** : `DATABASE_URL` du `.env` (Supabase, ou `SOURCE_DATABASE_URL`).
- **Sorties** : `data/db_init/horragor.dump` (format custom, ~79 Mo, gitignoré).
- **Ce qui s'y passe** : `pg_dump` du schéma `public` exécuté DANS l'image du
  service db (`pgvector/pgvector:0.8.0-pg17`) — le serveur Supabase est en
  PostgreSQL 17.6, le client de l'hôte en 16 : passer par le conteneur aligne
  les versions. L'URL transite par l'environnement du conteneur, jamais en
  argument visible. `--no-owner --no-privileges` : aucun rôle Supabase importé.

### `docker/db-init/01-restore.sh` — la restauration au premier démarrage
- **Entrées** : le dump monté en lecture seule (`/dump`).
- **Sorties** : la base peuplée dans le volume nommé `db_data`.
- **Ce qui s'y passe** : `CREATE EXTENSION vector` (absente d'un dump limité au
  schéma), restauration en `--exit-on-error` après avoir retiré de la table des
  matières l'entrée `SCHEMA public` (déjà présente dans une base neuve), puis
  **recréation de l'index HNSW** `movie_embeddings_hnsw` supprimé sur Supabase
  pour cause de quota (chapitre 6) : en local, aucune limite ne s'y oppose.

### `docker-compose.yml` — le service `db`
- Image épinglée `pgvector/pgvector:0.8.0-pg17`, **aucun port publié**,
  identifiants `POSTGRES_*` du `.env` fournis uniquement à db et api-donnees.
- Réseau dédié `db_net` (internal) : seule l'API Données y a une patte —
  l'API IA ne peut même pas résoudre le nom `db`. `egress_net` est supprimé :
  la couche Données n'a plus aucune sortie internet.
- Healthcheck `pg_isready -h 127.0.0.1` : pendant la restauration, le serveur
  temporaire n'écoute que sur le socket Unix, donc « healthy » seulement une
  fois la base prête ; `api-donnees` attend cette condition (`depends_on`).
- Le code applicatif n'a pas changé d'une ligne : `SqlFilmRepository`
  parle du SQL standard et `<=>` (pgvector) — seul `DATABASE_URL` diffère.

**Vu en réel** (2026-10-19) : dump en 40 s ; restauration + index HNSW en 35 s
(33 961 films, 31 284 embeddings) ; depuis api-ia, `GET /films/41` → Hereditary,
`/films/41/similar` → voisins cosinus servis par l'index HNSW (`EXPLAIN` :
*Index Scan using movie_embeddings_hnsw*), id inconnu → 404 ; api-donnees →
internet : bloqué ; api-ia → db : nom introuvable ; depuis l'hôte, seul le 443
répond (front HTTPS 200, certificat vérifié contre la CA locale ; login → jeton,
`/chat` sans jeton → 401).

⚠️ **Anomalie découverte** (détaillée au chapitre 10) : `/chat` en cluster renvoie le repli gothique —
Ollama, sur l'hôte, n'écoute que sur `127.0.0.1:11434` et refuse les connexions
venues des conteneurs (`host.docker.internal` → *Connection refused*). Le
cluster n'avait donc jamais servi un récit de bout en bout. Résolu au
chapitre 16 (relais vers la seule passerelle Docker).

---

## Chapitre 10 — Le durcissement du cluster (revue de sécurité)

Une revue de sécurité du cluster a relevé des écarts entre ce que le brief
exige et ce que la topologie **garantit**. Chaque correctif retire du code
ou une capacité plutôt que d'en ajouter.

### `docker-compose.yml` — la topologie qui impose les règles
```
navigateur ──127.0.0.1:443──> traefik:8443 ──front_net (internal)──> frontend
frontend ──front_net──> traefik (alias api.horragor.localhost:8443) ──ia_net──> api-ia
api-ia ──data_net (internal)──> api-donnees ──db_net (internal)──> db
```
- **Le chiffrement UI → IA est imposé par le réseau** : le front n'est que sur
  `front_net` (interne), où seul Traefik l'attend. `http://api-ia:8000` lui
  est inaccessible, tout comme internet (télémétrie Streamlit coupée aussi :
  `--browser.gatherUsageStats false`).
- **443 lié à 127.0.0.1** : les ports publiés par Docker contournent le
  pare-feu de l'hôte ; seule la machine elle-même atteint le cluster.
- **Moindre privilège** : ancre YAML `x-hardening` (`no-new-privileges`,
  `cap_drop: ALL`) sur tous les services. Les trois images applicatives
  tournent sous l'uid 1001 (seul `logs/` est inscriptible) et lancent
  directement les binaires du venv. Traefik écoute sur 8443 (aucun besoin du
  privilège de port bas) et ne garde que `DAC_READ_SEARCH` pour lire la clé
  du certificat ; Postgres garde le strict nécessaire à son entrypoint.
- `depends_on: condition: service_healthy` sur toute la chaîne (db →
  api-donnees → api-ia → frontend) ; secrets d'auth exigés (`${VAR:?}`).
- Images épinglées : `traefik:v3.7.15`, `uv:0.9.30-python3.12-bookworm-slim`.

### `traefik/dynamic.yml` — le routage déclaré en fichier
- **Plus de socket Docker** : même monté en lecture seule, il donnait au seul
  composant exposé l'équivalent de root sur l'hôte. Les deux routes fixes
  (front, API) sont déclarées dans le fichier, les labels disparaissent.
- La route publique de l'API exclut `/metrics`, `/docs`, `/redoc` et
  `/openapi.json` (404) : la métrologie se lit sur le réseau privé.

### `scripts/gen_certs.sh` — une CA qui ne peut signer que *.localhost
- `nameConstraints=critical,permitted;DNS:localhost` : même importée dans un
  navigateur, la CA ne peut pas servir à usurper un autre site. Seuls
  `cluster.pem`/`cluster.key` sont montés dans Traefik — la clé de la CA ne
  quitte plus l'hôte. (Anciens certificats conservés dans
  `certs/backup-2026-10-19/` ; réimporter `certs/ca.pem` si le navigateur
  faisait confiance à l'ancienne CA.)

### `src/auth.py` — la révocation des refresh rejoués
- Chaque refresh porte un `jti` ; le registre en mémoire ne garde que le
  dernier émis par sujet. Un refresh déjà consommé qui revient (vol
  présumé) → 401 « jeton révoqué » **et** révocation de la session entière.
- Refresh ramené à 12 h (les jetons vivent dans la session Streamlit, qui
  meurt avec l'onglet) ; claims `exp`/`sub`/`type` (+ `jti`) exigés ;
  identifiants comparés en temps constant (`hmac.compare_digest`) ; secret
  absent → 503 propre, jamais de 500.
- `src/main.py` : middleware CORS supprimé — le navigateur n'appelle jamais
  l'API, c'est le serveur Streamlit qui le fait.

### `docker/db-init/01-restore.sh` — un rôle en lecture seule
- L'API Données se connecte avec `horragor_ro` : `SELECT` seulement,
  `default_transaction_read_only = on`, `statement_timeout = 30s`. Le
  superutilisateur ne sort jamais du conteneur db.

**Vu en réel** (2026-10-19) : 5 services *healthy* ; seul `127.0.0.1:443`
publié ; front HTTPS 200 ; `/metrics`, `/docs`, `/openapi.json` → 404 en
public ; rejeu d'un refresh consommé → 401, puis le refresh légitime suivant
aussi → 401 (session révoquée) ; front → `api-ia:8000` en clair : bloqué ;
front → internet : bloqué ; front → API via Traefik en TLS vérifié : 200 ;
uid 1001 pour front/api-ia/api-donnees ; rôle `horragor_ro` : `DELETE` refusé
(*read-only transaction*) ; recommandations pgvector servies par l'API Données.

---

## Chapitre 11 — Le monitoring à 360° (Phase G)

Le brief : « monitoré à 360° en temps réel via une stack Docker unifiant
Prometheus, Grafana, Uptime Kuma (pour la télémétrie des 3 composants) et
Langfuse (pour l'agent) ». Tout démarre avec le même `docker compose up -d`.

```
api-ia ─────langfuse_ingest──> langfuse-web ──langfuse_net (internal)──> postgres · clickhouse · redis · minio · worker
prometheus ──ia_net/data_net──> api-ia:8000 · api-donnees:8100 · traefik:8082   (/metrics)
grafana ──obs_net──> prometheus            uptime-kuma ──(une patte par réseau)──> 10 sondes
UIs : 127.0.0.1 → Langfuse :3000 · Kuma :3001 · Grafana :3002 · Prometheus :9090
```

### `monitoring/langfuse/compose.yml` — Langfuse dans la stack (`include:`)
- **Entrées** : les secrets `LANGFUSE_*` du `.env` ; les traces envoyées par le
  CallbackHandler d'api-ia (`LANGFUSE_HOST=http://langfuse-web:3000`).
- **Sorties** : l'UI d'analyse sur `127.0.0.1:3000`.
- **Ce qui s'y passe** : les 6 conteneurs du compose officiel v3, versions
  épinglées (`3.210.0`, ClickHouse 26.6, Redis 7.4, Postgres 17), entrailles
  sur un réseau **interne** sans aucun port publié, télémétrie coupée.
  **Init headless** (`LANGFUSE_INIT_*`) : organisation, projet `HorRAGor3`,
  ses clés (celles du `.env` : l'application n'a rien à changer) et compte
  admin sont provisionnés au premier démarrage — zéro clic.
- ⚠️ Piège rencontré : Next.js écoute sur `$HOSTNAME`, que Docker remplit avec
  l'id du conteneur → une seule de ses deux pattes réseau répond, l'UI publiée
  restait muette malgré « Ready ». Correctif : `HOSTNAME=0.0.0.0`.
- L'ancienne instance hors repo a été arrêtée (volumes conservés).

### `monitoring/prometheus/prometheus.yml` — la télémétrie des 3 composants
- `api-ia` (couche Intelligence) et `api-donnees` (couche Données) : le
  `/metrics` de `prometheus-fastapi-instrumentator`, présent depuis la
  Phase A (règle « chaque service naît instrumenté ») ;
- `traefik` (couche Présentation) : Streamlit n'expose pas de `/metrics`, on
  mesure donc le trafic qui la sert (`traefik_service_*{service="front@file"}`,
  activé par `--metrics.prometheus` sur l'entrée interne `:8082`).
- Les cibles sont jointes par les réseaux privés ; `/metrics` n'est pas routé
  en public (chapitre 10).

### `monitoring/grafana/provisioning/` — dashboards as code
- Datasource Prometheus + dashboard **« HorRAGor3 — les 3 couches »** :
  disponibilité des cibles, débit et latence p95 par couche, taux de 5xx,
  `/chat` (débit + latence de l'agent), refus d'authentification, appels à
  l'API Données. Lecture seule (`allowUiUpdates: false`) : la vérité est dans
  le repo. Rapports d'usage vers l'éditeur coupés.

### `scripts/setup_uptime_kuma.py` — les sondes, as code aussi
- Uptime Kuma n'a pas de provisioning par fichier : le script (idempotent,
  `uv run --env-file .env --with uptime-kuma-api`) crée le compte admin puis
  10 sondes (la 10ᵉ, Ollama via le relais, ajoutée au chapitre 16) — les
  deux **entrées publiques en TLS vérifié** (Kuma fait confiance à la CA
  locale via `NODE_EXTRA_CA_CERTS`), Streamlit, API IA, API Données, la
  **chaîne API → Postgres** (sonde à mot-clé : `/films/41` doit contenir
  « Hereditary »), Langfuse, Prometheus, Grafana.

**Vu en réel** (2026-10-19) : 14 conteneurs démarrés par une seule commande
(15 avec le relais Ollama du chapitre 16) ;
cibles Prometheus `api-ia`, `api-donnees`, `traefik`, `prometheus` toutes
**up** ; métriques `http_requests_total{job, handler, status}` et
`traefik_service_requests_total{service="front@file"|"api@file"}` présentes ;
dashboard provisionné dans le dossier HorRAGor3 ; Langfuse `/api/public/health`
200 et projet `HorRAGor3` provisionné, accessible avec les clés du `.env` ;
**9 sondes Uptime Kuma UP** (dont « keyword is found » sur la chaîne données).

---

## Chapitre 12 — La documentation Sphinx (gouvernance)

Le brief : « L'intégralité de cette usine logicielle doit être documentée
proprement via Sphinx [...] obligatoirement la doc automatique des API, les
schémas relationnels de la base de données, ainsi que la cartographie
complète de votre graphe multi-agent ».

### `docs/sphinx/conf.py` — une doc qui ne peut pas mentir
- **Entrées** : le code lui-même (`src/`, `services/`), les docstrings Google
  style écrites au fil de l'eau depuis la Phase A (règle de travail).
- **Sorties** : le site HTML (`docs/sphinx/_build/html`, gitignoré).
- **Ce qui s'y passe** : au démarrage de chaque construction (`builder-inited`),
  trois artefacts sont **générés depuis le code** dans `_generated/` :
  la carte Mermaid du graphe (`pipeline.app.get_graph().draw_mermaid()`), la
  table des endpoints de chaque API et sa spécification OpenAPI
  (`app.openapi()`, téléchargeable). Extensions : autodoc + napoleon
  (docstrings), viewcode (lien vers le source), myst-parser (pages Markdown,
  inclusion du livre et du plan), sphinxcontrib-mermaid ; thème furo.
  Dépendances isolées dans le groupe uv `docs` (absentes des images).
- ⚠️ Piège rencontré : LangGraph préfixe son Mermaid d'un front matter YAML
  (`---config---`) que MyST prenait pour les options de la directive
  (`JSONDecodeError`) — retiré à la génération.

### Les pages
- **Architecture** : chemin d'une question à travers les 3 couches et leurs
  réseaux, l'observabilité, et la table « exigence du brief → mise en œuvre ».
- **Cartographie du graphe** : le diagramme généré, le rôle de chaque nœud et
  routeur, puis l'autodoc du State, des nœuds, des routeurs et du câblage.
- **API IA / API Données** : endpoints (avec la protection JWT) + autodoc.
- **Schémas relationnels** : MCD et MLD repris de la merise de HorRAGor1,
  MPD **réel** extrait de la base du cluster (`information_schema`), qui
  montre `movie_embeddings` (`vector(768)`, ajoutée par HorRAGor2).
- **Le livre du projet** (ce document) et le plan directeur, inclus tels quels.
- Ajoutées au chapitre 17 : une page par agent (rôle, entrées et sorties du
  State, outils, mesures Langfuse) et le guide « Lire la console et les logs ».

**Vu en réel** (2026-10-19) : `sphinx-build -W` (avertissements = erreurs) sans
un seul avertissement ; les diagrammes Mermaid (graphe, MLD, MPD, les deux
schémas d'architecture) rendus en SVG dans Chrome headless ; endpoints des deux API et OpenAPI
téléchargeables présents ; autodoc de `rag_node`, `should_scrape_or_narrate`,
`validate_film`, `refresh`…

---

## Chapitre 13 — Le pipeline CI/CD

Le brief : « la mise en place d'un pipeline CI/CD complet ». Deux workflows
GitHub Actions se partagent le travail.

### `.github/workflows/ci.yml` — le garde-fou (Phase F, élargi en G)
- **Entrées** : chaque PR (y compris les PR empilées entre branches), et
  chaque merge sur `main` via un appel depuis cd.yml (`workflow_call`).
- **Ce qui s'y passe** : ruff (lint + format), shellcheck sur les scripts
  shell, puis `pytest --cov` : le périmètre vient du `pyproject.toml` (`src`,
  `services`, `app_frontend` — « les deux API et l'UI ») et `fail_under = 80`
  casse le build en dessous. Le seuil global pouvant masquer un périmètre
  faible, **chacun** (API IA, API Données, UI) est aussi vérifié à 80 %.

### `.github/workflows/cd.yml` — la livraison
- **Entrées** : PR vers `main` (vérification) ; merge sur `main` (livraison).
- **Sorties** : `ghcr.io/os974/horragor3-{api-ia,api-donnees,frontend}`
  (tags `sha-xxxxxxx` + `latest`), et le site Sphinx sur GitHub Pages.
- **Ce qui s'y passe** :
  - **la CI d'abord** : sur `main`, le job `ci` rejoue ci.yml et les jobs
    suivants en dépendent (`needs`) — une CI rouge ne publie **rien**. (Revue
    QA : sans ce lien, les deux workflows partaient en parallèle et une
    régression pouvait être poussée en `latest`.)
  - **images** (matrice des 3 Dockerfiles) : construites à chaque PR (un
    Dockerfile cassé bloque la PR), poussées seulement après merge, avec
    labels OCI et cache GitHub Actions ;
  - **docs** : `sphinx-build -W` à chaque PR (une docstring cassée bloque
    aussi) ; sur `main`, l'artefact part vers Pages ;
  - permissions minimales par job (`packages: write` pour les images,
    `pages`/`id-token` pour le seul déploiement).
- La doc se construit sans secret ni service : vérifié dans un clone vierge
  (ni `.env`, ni index FAISS, ni base).

**Vu en réel** (2026-10-19) : `actionlint` et `shellcheck` sans erreur ;
build Sphinx strict réussi dans un clone propre ; les 3 images construites
localement avec les mêmes Dockerfiles (cluster du chapitre 11) ; 118 tests,
couverture 94 % (API IA 94 %, API Données 95 %, UI 95 %) — la revue QA a
ajouté les tests du refresh silencieux côté UI et du fail-open Langfuse.

**Vu sur GitHub** (2026-10-19) : CI et CD en mode PR verts sur les PR de la
pile ; premier CD réel au merge de #15 dans `main` — 6 jobs verts (CI rejouée
en garde-fou, 3 images, doc, Pages) ; images `ghcr.io/os974/horragor3-*`
publiées en `latest` + `sha-<commit>` et **publiques** (téléchargeables sans
compte, visibilité héritée du dépôt) ; doc en ligne sur
https://os974.github.io/HorRAGor3/ (Pages activé en mode « GitHub Actions »).

⚠️ **Comportement déviant** (#19) : la branche de base n'ayant pas été
supprimée après le merge de #15, GitHub a recibé les PR empilées #16 à #18
sur `ci/cd-ghcr-pages` au lieu de `main` — `main` et la doc publiée ont
manqué les trois derniers commits. Rattrapé par la PR #20 vers `main`, qui
clôt #19. Leçon : dans une pile de PR, supprimer la branche de base après
**chaque** merge ; l'option « Automatically delete head branches » est
désormais activée sur le dépôt.

---

## Chapitre 14 — La traçabilité par GitHub Issues

Le brief : « chaque anomalie ou comportement déviant détecté devra faire
l'objet d'un ticket archivé dans vos GitHub Issues ».

### `.github/ISSUE_TEMPLATE/` — des tickets exploitables
- `config.yml` : pas de ticket libre, tout passe par un formulaire.
- **Anomalie** (un composant échoue) : couche concernée, constat,
  reproduction, attendu, preuves, puis cause et correctif à la résolution.
- **Comportement déviant** (le système tourne mais se trompe) : nature
  (routage, réponse de l'agent, isolation de contexte, sécurité,
  performance), question posée, observé/attendu, et le **`session_id`** —
  l'identifiant de corrélation qui relie la conversation à sa trace Langfuse
  et à ses logs Loguru (règle d'observabilité de la Phase A).

### Le registre des anomalies rencontrées
Chaque incident de ce livre devient un ticket, clos avec la référence de son
correctif : quota Supabase (ch. 6), Traefik API 1.44 et 504 (ch. 8), port
ClickHouse et méta-paquet `langchain` (ch. 4), Langfuse muet (ch. 11),
Mermaid/Sphinx (ch. 12), revue de sécurité (ch. 10), CD sans garde-fou
(ch. 13), Ollama injoignable depuis le cluster (ch. 9, résolu au ch. 16).

**Archivé** (2026-10-19) : tickets #1 à #10 sur
https://github.com/os974/HorRAGor3/issues, labellisés par nature
(`anomalie`, `comportement-déviant`, `sécurité`) et par couche (`données`,
`intelligence`, `cluster`, `observabilité`, `ci-cd`), chacun clos avec la
référence de son correctif. Puis #19, ouvert au premier passage du CD
(chapitre 13) et clos par la PR #20 ; enfin #22 à #25, les écarts de la
vérification finale (chapitre 17).

---

## Chapitre 15 — La clôture de la Phase G

Trois revues ont encadré l'épilogue, chacune appliquée avant de pousser :
sécurité (chapitre 10), qualité des tests et du pipeline (chapitre 13), et
une revue qualité finale. Cette dernière a surtout relevé des **textes rendus
faux par l'avancement** — le risque propre à un livre tenu au fil de l'eau :
- « l'unique port publié » : vrai pour l'application (`127.0.0.1:443`), mais
  les UIs d'observabilité publient aussi sur la boucle locale — reformulé ;
- README : installation de Langfuse par clone externe, `--cov=src`,
  « 83 tests », CI « sur push » — remis à jour ;
- `SUPABASE_URL`/`SUPABASE_KEY` : configuration morte (lue nulle part),
  supprimée ; Supabase n'est plus présenté comme « la » base mais comme la
  source du dump et l'accès direct en dev ;
- Uptime Kuma tournait hors de l'ancre de durcissement : il la rejoint, avec
  les trois seules capacités dont son entrypoint a besoin (`CHOWN`, `SETUID`,
  `SETGID` pour basculer sur l'uid 1001). Les six conteneurs Langfuse gardent
  la configuration officielle de l'éditeur, sur leur réseau interne ;
- healthchecks factorisés (ancre `x-healthcheck`), script Kuma sans
  dépendance implicite (`--env-file` au lieu de `python-dotenv`).

---

## Chapitre 16 — Le relais Ollama : le premier récit en conteneurs

Dernier écart fonctionnel (chapitre 9) : Ollama, service de l'hôte (GPU,
modèles de plusieurs Go), n'écoute que sur `127.0.0.1:11434`. Les conteneurs
l'appellent par `host.docker.internal`, c'est-à-dire la passerelle Docker
(`172.17.0.1`) — connexion refusée.

Trois voies écartées : écouter sur `0.0.0.0` (Ollama n'a pas
d'authentification : tout le réseau local en profiterait) ; lier Ollama à la
passerelle par un override systemd (casse `localhost:11434` pour les autres
projets) ; un relais systemd sur l'hôte (configuration hors du repo, non
reproductible).

### `docker-compose.yml` — le service `ollama-relay`
- **Entrées** : les appels LLM d'api-ia vers `host.docker.internal:11434`.
- **Sorties** : les mêmes requêtes, relayées vers `127.0.0.1:11434`.
- **Ce qui s'y passe** : un conteneur `alpine/socat` en `network_mode: host`
  (il voit la boucle locale de l'hôte) écoute **uniquement** sur l'IP de la
  passerelle Docker (`DOCKER_GATEWAY_IP`, `172.17.0.1` par défaut) — jamais
  sur le réseau local — et relaie vers Ollama. Utilisateur `nobody`,
  `cap_drop: ALL`, `no-new-privileges`. Ni sudo ni configuration de l'hôte :
  tout reste dans le repo, et `localhost:11434` reste intact.
- **Sonde dédiée** : la revue de sécurité l'avait noté, `/health` restait vert
  alors que chaque récit tombait sur le repli. Uptime Kuma sonde désormais le
  LLM par le même chemin qu'api-ia (« Intelligence — Ollama (via relais) »).

**Vu en réel** (2026-10-19) : `ss` montre le relais sur `172.17.0.1:11434`
seulement (Ollama reste sur `127.0.0.1`) ; à travers tout le cluster (Traefik
TLS → JWT → api-ia → API Données → Postgres, + TMDB et web) :
- « Parle-moi du film Hereditary » → parcours `rag → narration`, sources
  `validate_film`, `get_metadata`, `get_credits`, 75 s (chargement du modèle
  inclus) ;
- « Raconte-moi des anecdotes de tournage sur Hereditary » → parcours
  `rag → scraper → narration`, sources + `search_web`, `scrape`, 29 s ;
- **Langfuse intégré** : une trace par session ; pour la seconde, 24
  observations dont 6 générations LLM (6 698 tokens), l'arbre complet des
  nœuds, des routeurs (`should_continue_rag`, `should_continue_scraper`) et
  des outils (`lookup_movie`, `web_search`, `wikipedia_synopsis`) ;
- Prometheus : `/chat` 2 × `2xx` ; **10 sondes Uptime Kuma UP**.

### La livraison
- PR #11 à #18 mergées ; #16 à #18, arrivées par erreur sur
  `ci/cd-ghcr-pages`, rejoignent `main` par la PR #20, qui clôt #19.
- Le 2026-10-19, les messages de commit des phases A à F sont réécrits
  (lignes de co-auteur retirées, contenu des fichiers inchangé) : tous les
  hashes changent, et la PR #21 reporte les nouveaux dans la documentation et
  les tickets.
- CD vert sur `main` : images publiques sur GHCR, documentation en ligne
  (chapitre 13) ; tickets archivés (chapitre 14).

*Fin de la Phase G — l'épilogue MLOps du brief.*

---

## Chapitre 17 — La vérification finale (la lettre du brief)

Dernière relecture du brief, du plan et de la documentation, confrontés au
code. Le système tournait, mais six points s'écartaient de la lettre du brief
ou des règles du plan. Chacun a été tracé par un ticket (#22 à #25), puis
corrigé.

### `src/graph/router.py` — la règle logique revient à l'aiguilleur (#22)
- **Le brief (p. 3)** : c'est dans `router.py` qu'on écrit « les règles
  logiques (ex. : le message de l'agent RAG contient-il assez
  d'informations ? Si oui "narration", sinon "scraper") ».
- **Avant** : `rag_node` jugeait sa récolte (`is_complete`), le routeur ne
  lisait qu'un booléen.
- **Après** : `should_scrape_or_narrate` décide sur `lore` et sur la question
  (`wants_web_details` déménage dans le routeur) ; `is_complete` disparaît du
  State. Le nœud récolte, le routeur juge et aiguille, et la raison de la
  décision est écrite dans la trace.

### `src/graph/pipeline.py` — la dernière ligne du livrable (#22)
- **Le brief (p. 4)** : « ce fichier se termine par `app = workflow.compile()` ».
- **Avant** : `app = build_graph()`, équivalent mais pas à la lettre.
- **Après** : `build_workflow()` renvoie le `StateGraph` câblé ; le fichier se
  termine par `workflow = build_workflow()` puis `app = workflow.compile()`.

### `src/graph/nodes.py` et `src/engine.py` — des nœuds purs (#22)
- Les trois `logger.info` métier des nœuds sont retirés (règle « nœuds purs,
  instrumentation centralisée » du plan). Le moteur journalise une ligne de
  résumé par run : `Graphe : rag → scraper → narration (lore 626 car., web
  1810 car., récit 1762 car.)`.

### La corrélation, de l'écran aux traces (#23)
- `app_frontend.py` : chaque conversation reçoit son `session_id` (uuid4),
  renouvelé par « Nouvelle conversation » et à la déconnexion. Jusque-là, le
  Front envoyait toujours « default » : toutes les conversations de tous les
  visiteurs tombaient dans la même session Langfuse.
- `src/main.py` : `/chat` pose `session_id` et un `request_id` (8 caractères)
  dans le contexte Loguru ; toutes les lignes du run, graphe compris, les
  portent dans le champ `extra` du JSON. `logs/traces.jsonl` enregistre aussi
  le `session_id`.

### Loguru de bout en bout (#24)
- `src/logging_conf.py` : les loggers d'uvicorn (handlers posés par le serveur
  avant l'import de l'app, sans propagation) contournaient Loguru ; ils sont
  rebranchés. L'`InterceptHandler` signait chaque log de la stdlib
  « logging:callHandlers » : il remonte désormais jusqu'au vrai appelant.
- `app_frontend.py` : le Front journalise via Loguru (refus de connexion,
  nouvelle conversation, échec de `/chat`), comme les deux API.
- Healthchecks ajoutés à `langfuse-web`, `langfuse-worker` (qui n'écoute que
  sur `$HOSTNAME`) et `ollama-relay` (chemin complet passerelle → relais →
  Ollama) : les 15 conteneurs ont désormais un état de santé.

### `scripts/build_faiss.py` — un index reproductible (#25)
- **Entrées** : la table `movies` (`DATABASE_URL`) et Ollama.
- **Sorties** : `data/faiss_index/` (ou `--out`), `--limit` pour un essai.
- **Ce qui s'y passe** : repris du `build_faiss.py` de HorRAGor2, il réutilise
  `TitleIndex.build_from_pairs`, qui n'était appelé nulle part : sur un clone
  neuf, l'index du brief se reconstruit en une commande.

### Les finitions
- `.env.example` documente toutes les variables lues ; les réglages jamais
  lus (`API_HOST`, `API_PORT`, `TITLES_DB_PATH`) sont retirés avec leurs
  champs de `config.py`. `.python-version` épingle Python 3.12.
- `SupabaseFilmRepository` devient `SqlFilmRepository` (en cluster, il
  interroge le Postgres conteneurisé). Les bouchons `validate_film` qui
  levaient `NotImplementedError` quittent le Protocol et les deux
  repositories : la validation floue appartient à FAISS.
- La fixture SQLite des tests ferme sa connexion (plus de `ResourceWarning`
  en Python 3.13).
- Sphinx : une page par agent et le guide de la console ; le formulaire
  « comportement déviant » gagne la nature « CI/CD ».

### L'analyse Langfuse chiffrée (exigence p. 5)
Deux questions posées à travers tout le cluster (Traefik TLS → JWT → api-ia),
dans la même conversation (`session_id` `verif-finale-ead05fd2`), puis lues
dans l'API publique de Langfuse (`/api/public/traces?sessionId=…`,
`/api/public/observations?traceId=…`).

| Nœud | Q1 « Parle-moi du film Hereditary » | Q2 « Des anecdotes de tournage de The Thing ? » |
|---|---|---|
| Parcours | `rag → narration` | `rag → scraper → narration` |
| `rag` (2 générations) | 11,6 s · 1 293 tokens in / 122 out | 2,8 s · 1 321 in / 100 out |
| `rag_tools` | 1,1 s (`lookup_movie`) | 1,1 s (`lookup_movie`) |
| Routeur | « récolte locale suffisante » | « détails web exigés par la question » |
| `scraper` (3 générations) | — | 13,6 s · 3 642 in / 294 out |
| `scraper_tools` | — | 3,0 s (`web_search` 2,4 s, `wikipedia_synopsis` 0,6 s) |
| `narration` (1 génération) | 8,0 s · 421 in / 326 out | 12,7 s · 964 in / 498 out |
| Routeurs (`should_continue_*`) | < 0,01 s | < 0,01 s |
| **Total** | **20,8 s · 1 714 in / 448 out** | **33,3 s · 5 927 in / 892 out** |

Ce qu'on en lit :
- **Le coût est dans les générations, pas dans les outils** : les outils
  pèsent 1 à 3 s, les routeurs rien ; une génération locale va d'environ 1 s
  (une décision d'outil) à 13 s (le récit, 300 à 500 tokens écrits).
- **Le premier appel paie le chargement du modèle** : 11,6 s pour le RAG de
  Q1 contre 2,8 s pour le même travail en Q2 (qwen2.5:7b venait d'être
  rechargé en mémoire GPU après la reconstruction du cluster).
- **Le détour par l'Enquêteur coûte cher** : 16,6 s (le Scraper et ses
  outils) et 3,5 fois plus de tokens d'entrée au total (5 927 contre 1 714).
  Le routeur ne l'envoie que lorsque c'est nécessaire.
- **Le context trimming se mesure** : la Narration reçoit 421 tokens (Q1) et
  964 tokens (Q2), contre 1 293 et 3 642 dans les canaux du Chercheur et de
  l'Enquêteur. L'Écrivain ne voit que le dossier, jamais les échanges
  d'outils.

**Vu en réel** (2026-10-19) : cluster reconstruit sur ce code, 15 conteneurs
*healthy* ; les deux parcours ci-dessus, dont les deux traces Langfuse sont
dans une même session ; lignes JSON d'api-ia portant `session_id` et
`request_id`, accès uvicorn au format Loguru ; une connexion refusée dans le
conteneur du Front journalisée « Connexion refusée par l'API (HTTP 401) » ;
`scripts/build_faiss.py --limit 300` : 300 titres en 33 s, « Get Out »
retrouvé avec un score de 1,000 ; 123 tests, couverture 96 % (API IA 95 %,
API Données 95 %, UI 99 %).

*Fin du projet.*
