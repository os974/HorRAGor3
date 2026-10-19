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
app_frontend.py (Streamlit)
   │ POST /chat {message, session_id}
   ▼
src/main.py (FastAPI) → src/engine.py (GraphEngine)
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
  = au moins un outil a marqué `"found": true` **ET** la question ne réclame
  pas d'informations hors du périmètre local (`wants_web_details` : mots-clés
  anecdotes/coulisses/tournage... — la base n'a que métadonnées et synopsis,
  donc ces demandes envoient l'Enquêteur même si le film est connu). Aucun
  LLM dans la décision de routage. `scraper_node` reçoit un brief reformulé (question + lore),
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
  Toute erreur API s'affiche en bulle, jamais de crash. Lancement :
  `uv run streamlit run app_frontend.py`.

### `src/main.py` — la porte d'entrée (FastAPI/Uvicorn)
- **Entrées** : requêtes HTTP (`/health`, `/metrics`, `POST /chat`).
- **Sorties** : `ChatResponse` JSON ; métriques Prometheus ; logs Loguru.
- **Ce qui s'y passe** : `setup_logging()` unifie les logs (uvicorn compris) ;
  le `lifespan` charge l'index FAISS une fois en RAM (dégradation propre s'il
  manque) et l'injecte dans `rag_tool` ; `/metrics` est exposé dès la
  naissance (prometheus-fastapi-instrumentator — règle observabilité) ;
  `/chat` délègue au moteur via l'abstraction `AgentEngine` (inversion de
  dépendance : les tests injectent un fake). Lancement :
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
  tmdb/wikipedia/ddg) ; `_invoke_config()` est le point d'ancrage où la
  Phase E branchera le CallbackHandler Langfuse ; `log_trace` archive le run
  dans `logs/traces.jsonl`.

**Vu en conditions réelles** : `.env` branché sur Supabase (métadonnées
enrichies TMDB : réalisateur/casting, et recommandations pgvector réelles) ;
`/health` ok, `/metrics` Prometheus actif, « Des films semblables à
Midsommar ? » → `[rag, narration]`, 7 étapes de trace, réponse gothique en
19 s ; Streamlit démarré, `/_stcore/health` = ok (la future cible Uptime Kuma).

---

## Chapitre 4 — Le monitoring Langfuse (Phase E)

Langfuse est le « tableau de bord visuel » du registre de bord : chaque
question devient une **trace** consultable sur `http://localhost:3000`.

### La stack Langfuse (hors du repo : `../langfuse/`, self-hosted)
- **Entrées** : les événements envoyés par le CallbackHandler de l'API.
- **Sorties** : l'UI d'analyse (arbre des décisions, tokens, latences, coûts).
- **Ce qui s'y passe** : `docker compose up -d` démarre 6 conteneurs — web
  (l'UI, port 3000), worker (ingestion), Postgres (comptes/projets),
  ClickHouse (le stockage analytique des traces), Redis (file d'attente),
  MinIO (blobs). ⚠️ Particularité locale : ClickHouse voulait publier le port
  hôte 9000, déjà pris par Portainer → `docker-compose.override.yml` le
  décale vers 9002 (les services internes n'en dépendent pas).

### `src/engine.py::_langfuse_callbacks()` — le branchement
- **Entrées** : `settings.langfuse_*` (clés du `.env`, générées dans l'UI).
- **Sorties** : le `CallbackHandler` passé au graphe via
  `config={"callbacks": [...]}` (le mécanisme exact du brief), plus
  `langfuse_session_id` pour regrouper les traces par conversation.
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
  jugement déterministe (`harvest_facts`, `wants_web_details` — dont le cas
  « anecdotes d'un film connu → Enquêteur quand même »), le contrat
  « jamais d'exception » des outils (Ollama éteint, TMDB en panne, réseau
  coupé), le « jamais de 500 » du moteur (récursion, panne → repli gothique),
  le context trimming (la plume ne reçoit que system + dossier), et le
  garde-fou de dimension des embeddings.
- **CI** (`.github/workflows/ci.yml`) : à chaque push/PR sur main — ruff
  check + format, puis pytest avec `fail_under = 80` (l'exigence du brief est
  un verrou de build, pas une intention).
- L'UI Streamlit (`app_frontend.py`) est hors mesure pour l'instant : elle
  sera testée en Phase G (`st.testing.v1.AppTest`) avec la conteneurisation.

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
  chapitre 9 : la base elle-même rejoint le cluster). Réutilise `SupabaseFilmRepository` tel quel,
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
  il expire vite) + **refresh** ~7 j (sert UNIQUEMENT à renouveler, avec
  rotation complète à chaque usage).
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
10 tests couvrent la serrurerie (types croisés, expiration, non configurée).

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
  (`host-gateway`) ; l'index FAISS est monté en volume RO (jamais dans
  l'image) ; Traefik résout `api.horragor.localhost` en interne (alias
  réseau) et route le navigateur vers le front. Chaque Dockerfile embarque
  un `HEALTHCHECK` (sondes Docker + Uptime Kuma).

### Les tests de l'UI (`tests/test_frontend.py`)
- `st.testing.AppTest` pilote le vrai script Streamlit, httpx mocké : porte
  close sans session, login réussi/refusé, chat complet (récit + parcours +
  sources), déconnexion. `app_frontend.py` entre dans la couverture —
  l'exigence « les deux API **et l'UI** » est complète.

---

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
- Le code applicatif n'a pas changé d'une ligne : `SupabaseFilmRepository`
  parle du SQL standard et `<=>` (pgvector) — seul `DATABASE_URL` diffère.

**Vu en réel** (2026-10-19) : dump en 40 s ; restauration + index HNSW en 35 s
(33 961 films, 31 284 embeddings) ; depuis api-ia, `GET /films/41` → Hereditary,
`/films/41/similar` → voisins cosinus servis par l'index HNSW (`EXPLAIN` :
*Index Scan using movie_embeddings_hnsw*), id inconnu → 404 ; api-donnees →
internet : bloqué ; api-ia → db : nom introuvable ; depuis l'hôte, seul le 443
répond (front HTTPS 200, certificat vérifié contre la CA locale ; login → jeton,
`/chat` sans jeton → 401).

⚠️ **Anomalie découverte** : `/chat` en cluster renvoie le repli gothique —
Ollama, sur l'hôte, n'écoute que sur `127.0.0.1:11434` et refuse les connexions
venues des conteneurs (`host.docker.internal` → *Connection refused*). Le
cluster n'avait donc jamais servi un récit de bout en bout. Correctif en attente
d'arbitrage (configuration d'Ollama côté hôte).

*Chapitre suivant : monitoring + CD + Sphinx + Issues (G4).*
