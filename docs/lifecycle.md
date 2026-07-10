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
src/graph/pipeline.py (graphe compilé)          [Phase C — à venir]
   │ State initial {messages: [question]}
   ▼
rag_node ⇄ rag_tools (fouille locale)           [Phase C — à venir]
   │ state.lore, state.is_complete
   ▼
router: should_scrape_or_narrate                [Phase C — à venir]
   │ "narration" si le lore suffit, sinon "scraper"
   ├─────────────► scraper_node ⇄ scraper_tools [Phase C — à venir]
   │                  │ state.web_findings
   ▼                  ▼
narration_node (plume gothique, sans outils)    [Phase C — à venir]
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

*Chapitres suivants (au fil des phases) : outils natifs (B), graphe
multi-agent (C), API et Front (D), monitoring Langfuse (E).*
