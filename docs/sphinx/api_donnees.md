# API Données — couche Données

La base encapsulée derrière son API dédiée. Aucun port publié : sur le réseau
privé `data_net`, seule l'API IA l'interroge ; Prometheus (métriques) et
Uptime Kuma (sondes) y ont aussi une patte pour l'observer. Elle se connecte à
Postgres avec un rôle en lecture seule.

Les routes `/films/*` exigent le **jeton d'accès de l'utilisateur**, relayé
par l'API IA et vérifié avec le même secret : aucun appel anonyme, même depuis
le réseau privé. `/health`, sans jeton, vérifie aussi la base (`SELECT 1`) :
c'est la sonde de la chaîne API → Postgres. Ses requêtes métier sont tracées
dans Langfuse, rattachées au compte, par un réseau interne dédié
(`langfuse_data_ingest`) : la couche Données n'a toujours aucune sortie.

## Endpoints

Table générée depuis la spécification OpenAPI de `services.data_api.main:app`
(téléchargeable : {download}`openapi-donnees.json <_generated/openapi/openapi-donnees.json>`).

```{include} _generated/endpoints_donnees.md
```

## Service

```{eval-rst}
.. automodule:: services.data_api.main
```

## Accès à la base

```{eval-rst}
.. automodule:: src.data.repository

.. automodule:: src.data.db
```

## Client côté IA

```{eval-rst}
.. automodule:: src.data.http_repository
```
