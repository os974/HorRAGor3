# Architecture du cluster

Trois couches isolées, comme l'exige l'épilogue MLOps du brief, plus la stack
d'observabilité. Chaque flèche correspond à un réseau Docker ; les réseaux
marqués *internal* n'ont aucune sortie hors du cluster.

## Le chemin d'une question

```{mermaid}
flowchart LR
    nav([Navigateur]) -- "HTTPS<br/>127.0.0.1:443" --> traefik{{Traefik<br/>TLS}}
    traefik -- "front_net<br/>(internal)" --> frontend
    frontend -- "HTTPS vérifié<br/>via Traefik" --> traefik
    traefik -- ia_net --> apiia
    apiia -- "data_net<br/>(internal)" --> apidon
    apidon -- "db_net<br/>(internal)" --> db
    subgraph presentation["Présentation"]
        frontend[Streamlit]
    end
    subgraph intelligence["Intelligence"]
        apiia[API IA<br/>graphe + JWT]
    end
    subgraph donnees["Données"]
        apidon[API Données]
        db[(Postgres<br/>+ pgvector)]
    end
    apiia -. "relais<br/>(passerelle Docker)" .-> ollama[(Ollama<br/>hôte)]
    apiia -. ia_net .-> web((Wikipédia<br/>DuckDuckGo<br/>TMDB))
```

## L'observabilité

```{mermaid}
flowchart LR
    subgraph cluster["Composants observés"]
        traefik{{Traefik}}
        frontend[Streamlit]
        apiia[API IA]
        apidon[API Données]
    end
    apiia -- "traces de l'agent<br/>(langfuse_ingest)" --> langfuse[Langfuse :3000]
    prometheus[Prometheus :9090] -- "/metrics" --> apiia & apidon & traefik
    grafana[Grafana :3002] --> prometheus
    kuma[Uptime Kuma :3001] -- "10 sondes" --> cluster
```

Les interfaces d'administration (ports ci-dessus) ne sont liées qu'à
`127.0.0.1` : seul le 443 de Traefik sert l'application.

## Les choix qui portent les exigences du brief

| Exigence du brief | Mise en œuvre |
|---|---|
| Base encapsulée derrière son API, réseau privé étanche | `db` sur `db_net` (internal), seul `api-donnees` y accède, avec un rôle en lecture seule |
| API IA parlant exclusivement à l'API Données par le réseau privé | `data_net` (internal) ; `api-ia` ne détient aucun identifiant de base |
| Authentification robuste par Refresh Tokens | JWT access (15 min) + refresh (12 h) avec rotation et révocation sur rejeu |
| UI isolée, communication chiffrée vers l'API IA | front sur `front_net` (internal) : son seul chemin vers l'IA est Traefik en TLS vérifié |
| Infrastructure souveraine | base, Langfuse et monitoring conteneurisés ; aucune télémétrie éditeur ; seul Ollama (GPU) reste sur l'hôte |
| Monitoring 360° | Prometheus + Grafana + Uptime Kuma (3 couches) et Langfuse (agent) |
| Journalisation de bout en bout | Loguru dans les deux API et l'UI (uvicorn compris), logs JSON portant `session_id` et `request_id` ; un `session_id` par conversation, partagé avec les traces Langfuse |

Le détail fichier par fichier, dans l'ordre du flux d'une requête, se trouve
dans {doc}`livre`.
