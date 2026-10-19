# Cartographie du graphe multi-agent

Aucun agent « chef de projet » : les trois agents travaillent en chaîne
directe et partagent un `State` commun. Le diagramme ci-dessous est **généré
depuis `src/graph/pipeline.py`** (`app.get_graph().draw_mermaid()`) à chaque
construction de la documentation.

```{include} _generated/graphe.md
```

## Lecture du graphe

| Élément | Rôle |
|---|---|
| `rag` | **Agent RAG — le Chercheur local** : premier point de contact, corrige les approximations de titre (FAISS), lit le savoir structuré (métadonnées) et vectoriel (films similaires, pgvector) |
| `rag_tools` | Exécution des outils du Chercheur (micro-boucle `rag ⇄ rag_tools`) |
| `scraper` | **Agent Scraper — l'Enquêteur du web** : déclenché seulement si la récolte locale est insuffisante ou si la question réclame des anecdotes |
| `scraper_tools` | Exécution des outils de l'Enquêteur (Wikipédia, DuckDuckGo) |
| `narration` | **Agent de Narration — l'Écrivain gothique** : sans outils, ne reçoit que la synthèse (context trimming) |
| `should_continue_rag` | Routeur du Chercheur : outils à appeler → `rag_tools` ; sinon délègue à **`should_scrape_or_narrate`**, l'aiguillage du brief, qui porte la règle « la récolte suffit-elle ? » (`lore` non vide et question sans demande d'anecdotes → `narration`, sinon → `scraper`) |
| `should_continue_scraper` | Routeur de l'Enquêteur : outils à appeler → `scraper_tools`, sinon → `narration` |

**Mémoire de session.** Le graphe est compilé avec un checkpointer : chaque
conversation (compte + `session_id`) retrouve son `State` d'une question à
l'autre. Les reducers n'écrasent rien (`add_messages`, `extend_path`,
`keep_recent_exchanges`) ; à chaque nouvelle question, les canaux des agents
et le dossier repartent à zéro, seul `history` (les trois derniers échanges)
traverse les tours. Le Chercheur et l'Enquêteur en lisent un résumé pour
comprendre les relances ; l'Écrivain, lui, reste isolé.

Les règles d'or du brief sont tenues par construction : un nœud est une
fonction `(state) -> dict` qui ignore ses voisins ; un routeur lit le `State`
et ne renvoie qu'une chaîne (la destination), testable sans lancer le graphe ;
`pipeline.py` est le seul point de vérité de la topologie et se termine par
`app = workflow.compile(...)` (avec son checkpointer), importé par l'API.

## Les trois agents

Une page par agent : son rôle, ce qu'il lit et écrit dans le `State`, ses
outils, et ce que Langfuse mesure de son travail.

```{toctree}
:maxdepth: 1

agents/rag
agents/scraper
agents/narration
```

## Le State — la mémoire commune

```{eval-rst}
.. automodule:: src.models.state
```

## Les nœuds — la logique métier

```{eval-rst}
.. automodule:: src.graph.nodes
```

## Les routeurs — la logique décisionnelle

```{eval-rst}
.. automodule:: src.graph.router
```

## Le câblage — le point de vérité

```{eval-rst}
.. automodule:: src.graph.pipeline
```
