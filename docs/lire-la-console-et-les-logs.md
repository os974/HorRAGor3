# Lire la console et les logs — guide pour non-initiés

Ce guide explique ce qui s'affiche dans le terminal quand HorRAGor3 tourne, et
ce que contiennent les fichiers du dossier `logs/`. Il est écrit pour être
compris (et réutilisé) par quelqu'un qui n'est pas du métier.

**L'image à garder en tête** : le projet est un manoir avec du personnel — un
concierge (l'API), un chercheur aux archives (l'Agent RAG), un détective
(l'Agent Scraper) et un écrivain (l'Agent Narration). La console et les logs
sont **le registre de bord que chaque employé remplit** au fil de son travail.

## 1. L'anatomie d'une ligne de console

```
2026-07-10 10:18:28.142 | INFO | src.tools.rag_tool - validate_film → id=42 title='Midsommar'
```

Quatre morceaux, toujours dans le même ordre :

1. **L'horodatage** (`2026-07-10 10:18:28.142`) — le « quand », à la milliseconde.
2. **Le niveau** — le ton de voix de l'employé :
   | Niveau | Sens |
   |---|---|
   | `INFO` | simple compte-rendu d'activité |
   | `SUCCESS` | mission accomplie |
   | `WARNING` | « j'ai rencontré un souci, mais je continue » |
   | `ERROR` | vraie panne |
3. **La signature** (`src.tools.rag_tool`) — *qui* parle : le fichier (et la
   fonction) qui a écrit la ligne. Chaque employé signe ses entrées.
4. **Le message** — ce qui s'est passé, en clair.

## 2. Les lignes types d'une session HorRAGor3

**Au démarrage du serveur**
- `Index FAISS chargé : 33961 titres en RAM` — le chercheur a monté le
  catalogue complet des films dans sa mémoire de travail, pour répondre
  instantanément au lieu de fouiller le disque à chaque question.

**Pendant une question** (les étapes d'une enquête)
- `validate_film → id=42 title='Midsommar'` — le chercheur confirme que le
  film existe et note son numéro de fiche.
- `metadata → réalisateur=Ari Aster, casting=[...]` — la fiche complète sort
  des archives (Supabase), complétée auprès d'un service externe (TMDB).
- `HTTP Request: POST http://localhost:11434/api/embed "200 OK"` — le
  programme « téléphone » à un service (ici l'IA locale Ollama). `200 OK` =
  l'appel a abouti ; un `404` = numéro inexistant.
- `Agent RAG : récolte True (1 fait(s))` — le chercheur déclare sa fouille
  fructueuse. C'est sur cette déclaration que l'aiguilleur décide de la suite.
- `Agent Scraper : 2 trouvaille(s) web` — le détective rentre du web avec
  2 indices.
- `Agent Narration : récit de 1349 car.` — l'écrivain a rendu sa copie.
- `path = ['rag', 'narration']` — le trajet complet de la question dans le
  manoir (ici : chercheur → écrivain, sans besoin du détective).

**Les vérifications de santé**
- `GET /health` → `{"status":"ok"}` — le pouls du serveur : on frappe, il
  répond « tout va bien ». (Utilisé par la CI, Docker et Uptime Kuma.)
- `GET /metrics` → `http_requests_total{...} 1.0` — les compteurs
  kilométriques du service : combien de requêtes, en combien de temps. C'est
  ce que Prometheus/Grafana viendront relever en Phase G.

**Le chronomètre**
- `real 0m18,974s` — la commande a duré 19 secondes. Long pour de
  l'informatique classique, normal pour trois « employés IA » qui
  réfléchissent tour à tour sur la machine locale.

**Un WARNING sain (exemple réel)**
```
WARNING | find_similar_horror_movies(41) en échec technique : no such table: movie_embeddings
```
Pendant un test sur la base de secours locale (SQLite), le programme a
constaté qu'un rayonnage n'existe pas là-bas (les recommandations ne vivent
que sur Supabase). Plutôt que de tout faire planter, il l'a **noté au registre
et a continué avec ce qu'il avait**. C'est un choix de conception du projet :
un souci se consigne, il ne provoque pas d'effondrement.

## 3. Les deux cahiers du dossier `logs/`

| Fichier | Contenu | À quoi il sert |
|---|---|---|
| `app.jsonl` | Le registre continu : chaque événement, dans un format que les machines relisent (message + heure + fichier + ligne + processus) | La matière première du monitoring (Phase G) |
| `traces.jsonl` | **Une ligne par question posée** : la question, la réponse complète, le trajet des agents, toutes les étapes | Le « procès-verbal » de chaque enquête — celui qu'on relit pour comprendre *pourquoi* le bot a répondu ça |

## 4. La phrase à retenir

> « La console, c'est le personnel du manoir qui commente son travail en
> direct, ligne par ligne, avec l'heure et sa signature ; les fichiers de
> logs, ce sont les mêmes comptes-rendus archivés — un registre continu pour
> la maintenance, et un procès-verbal par question pour comprendre chaque
> réponse. »

*(Phase E : Langfuse ajoutera la version « tableau de bord visuel » de tout
ceci — arbre des décisions, tokens consommés et latence par agent.)*