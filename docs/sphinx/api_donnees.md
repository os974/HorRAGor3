# API Données — couche Données

La base encapsulée derrière son API dédiée. Aucun port publié : sur le réseau
privé `data_net`, seule l'API IA l'interroge ; Prometheus (métriques) et
Uptime Kuma (sondes) y ont aussi une patte pour l'observer. Elle se connecte à
Postgres avec un rôle en lecture seule.

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
