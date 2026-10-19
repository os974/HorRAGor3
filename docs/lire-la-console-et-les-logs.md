# Lire la console et les logs — guide pour non-initiés

Ce guide explique ce qui s'affiche dans le terminal quand HorRAGor3 tourne, et
ce que contiennent les fichiers du dossier `logs/`. Il est écrit pour être
compris (et réutilisé) par quelqu'un qui n'est pas du métier.

**L'image à garder en tête** : le projet est un manoir avec du personnel — un
portier (l'interface Streamlit), un concierge (l'API), un chercheur aux
archives (l'Agent RAG), un détective (l'Agent Scraper) et un écrivain (l'Agent
Narration). La console et les logs sont **le registre de bord que le personnel
remplit** au fil de son travail.

## 1. L'anatomie d'une ligne de console

```
2026-10-19 11:51:11.200 | INFO     | src.engine:run:77 - Graphe : rag → narration (lore 445 car., web 0 car., récit 1117 car.)
```

Quatre morceaux, toujours dans le même ordre :

1. **L'horodatage** (`2026-10-19 11:51:11.200`) — le « quand », à la
   milliseconde (en cluster, l'heure des conteneurs est en UTC).
2. **Le niveau** — le ton de voix de l'employé :
   | Niveau | Sens |
   |---|---|
   | `INFO` | simple compte-rendu d'activité |
   | `WARNING` | « j'ai rencontré un souci, mais je continue » |
   | `ERROR` | vraie panne |
3. **La signature** (`src.engine:run:77`) — *qui* parle : le module, la
   fonction et la ligne qui ont écrit l'entrée. Chaque employé signe ses
   entrées, y compris les bibliothèques (uvicorn, httpx…), dont les lignes
   passent par le même registre.
4. **Le message** — ce qui s'est passé, en clair.

## 2. Les lignes types d'une session HorRAGor3

Les exemples ci-dessous sont de vraies lignes du cluster.

**Au démarrage de l'API**
- `Index FAISS chargé : 33961 titres en RAM` — le chercheur a monté le
  catalogue complet des films dans sa mémoire de travail, pour répondre
  instantanément au lieu de fouiller le disque à chaque question. S'il manque :
  `Index FAISS absent (...)`, avec la commande pour le reconstruire.
- `Uvicorn running on http://0.0.0.0:8000` — le concierge ouvre la porte.

**À la connexion**
- `Connexion réussie : olivier` — un visiteur a présenté les bons
  identifiants et reçu ses jetons d'accès.
- `Tentative de connexion refusée pour 'intrus'` (WARNING, côté API) et
  `Connexion refusée par l'API (HTTP 401)` (côté interface) — les deux
  versants d'un même refus.

**Pendant une question**
- `POST /chat [verif-finale-ead05fd2] par olivier : 'Parle-moi du film Hereditary'`
  — la question entre. Entre crochets, le **numéro de conversation**
  (`session_id`) : il relie cette ligne à la trace Langfuse de la même
  conversation.
- `Langfuse activé → http://langfuse-web:3000` — au premier appel, le
  concierge branche le tableau de bord (Langfuse).
- `response: https://en.wikipedia.org/w/api.php?... 200` — le détective
  consulte le web (ici, via le métamoteur DuckDuckGo). `200` = l'appel a
  abouti.
- `Graphe : rag → scraper → narration (lore 626 car., web 1810 car., récit 1762 car.)`
  — le compte-rendu de l'enquête : le trajet de la question dans le manoir
  (ici chercheur → détective → écrivain), la taille de ce que chacun a
  rapporté, puis la longueur du récit rendu.
- `"POST /chat HTTP/1.1" 200` — le concierge a remis la réponse.

**Les vérifications de santé**
- `"GET /health HTTP/1.1" 200` — le pouls du serveur : on frappe, il répond
  « tout va bien ». Docker, Uptime Kuma et la CI frappent régulièrement.
- `"GET /metrics HTTP/1.1" 200` — Prometheus relève les compteurs
  kilométriques du service (combien de requêtes, en combien de temps), que
  Grafana met en graphiques.

**Un WARNING sain (exemple réel)**
```
WARNING | find_similar_horror_movies(41) en échec technique : no such table: movie_embeddings
```
Pendant un test sur la base de secours locale (SQLite), le programme a
constaté qu'un rayonnage n'existe pas là-bas (les recommandations ne vivent
que dans la base Postgres). Plutôt que de tout faire planter, il l'a **noté
au registre et a continué avec ce qu'il avait**. C'est un choix de conception
du projet : un souci se consigne, il ne provoque pas d'effondrement.

## 3. Où lire ces lignes

- **En local** : dans les terminaux où tournent l'API et l'interface.
- **En cluster** : chaque service a son registre,
  `docker compose logs -f api-ia` (ou `api-donnees`, `frontend`…).

Le dossier `logs/` (à la racine du projet en local, `/app/logs` dans chaque
conteneur) contient deux cahiers :

| Fichier | Contenu | À quoi il sert |
|---|---|---|
| `app.jsonl` (tous les services) | Le registre continu : chaque événement, dans un format que les machines relisent (message, heure, module, ligne, et pour une question : `session_id` et `request_id`) | Retrouver toutes les lignes d'une même question ou conversation. Aucun outil de la stack ne le collecte aujourd'hui ; en cluster, il vit dans le conteneur |
| `traces.jsonl` (API IA) | **Une ligne par question posée** : la conversation, la question, la réponse complète, le trajet des agents, toutes les étapes | Le « procès-verbal » de chaque enquête — celui qu'on relit pour comprendre *pourquoi* le bot a répondu ça |

## 4. La phrase à retenir

> « La console, c'est le personnel du manoir qui commente son travail en
> direct, ligne par ligne, avec l'heure et sa signature ; les fichiers de
> logs, ce sont les mêmes comptes-rendus archivés — un registre continu pour
> la maintenance, et un procès-verbal par question pour comprendre chaque
> réponse. »

Langfuse (`http://localhost:3000`) offre la version « tableau de bord
visuel » de tout ceci : arbre des décisions, tokens consommés et latence par
agent, regroupés par conversation grâce au même `session_id`. Grafana
(`http://localhost:3002`) montre les compteurs, et Uptime Kuma
(`http://localhost:3001`) la disponibilité de chaque couche.
