# API IA — couche Intelligence

L'API FastAPI qui héberge le graphe multi-agent. Elle n'est jointe de
l'extérieur que par Traefik (`https://api.horragor.localhost`), parle à l'API
Données par le réseau privé, et verrouille ses routes métier par JWT. Le jeton
du visiteur est relayé à l'API Données : toute la chaîne reste liée à son
compte. Chaque requête métier ouvre une trace Langfuse, dans laquelle le graphe
de `/chat` s'imbrique (nœuds, routeurs, outils, tokens).

## Endpoints

Table générée depuis la spécification OpenAPI de `src.main:app`
(téléchargeable : {download}`openapi-ia.json <_generated/openapi/openapi-ia.json>`). En cluster, `/metrics`
et la doc OpenAPI ne sont pas routés en public.

```{include} _generated/endpoints_ia.md
```

## Point d'entrée

```{eval-rst}
.. automodule:: src.main
```

## Authentification par Refresh Tokens

```{eval-rst}
.. automodule:: src.auth
```

## Le pont contrat ↔ graphe

```{eval-rst}
.. automodule:: src.engine
```

## Une trace Langfuse par requête

```{eval-rst}
.. automodule:: src.observability
```

## Contrats partagés

```{eval-rst}
.. automodule:: src.contracts.schemas

.. automodule:: src.contracts.interfaces
```
