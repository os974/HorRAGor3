# Agent RAG — le Chercheur local

Premier point de contact du graphe (`START → rag`). Il fouille la base locale,
corrige les approximations de titre et rapporte le lore brut. Il ne décide pas
de la suite : c'est le routeur `should_scrape_or_narrate` qui juge sa récolte.

| | |
|---|---|
| Nœud | `rag`, avec sa micro-boucle `rag ⇄ rag_tools` |
| Lit dans le `State` | `question`, `rag_messages` (son propre canal) |
| Écrit dans le `State` | `rag_messages` ; `lore` en fin de fouille ; `path` à la première visite |
| Outils | `lookup_movie` (FAISS → SQL + TMDB : le dossier du film), `find_similar` (pgvector : recommandations) |
| LLM | `qwen2.5:7b`, température 0 (choix d'outils reproductibles) |
| Suite | `should_scrape_or_narrate` : `narration` si le `lore` suffit, sinon `scraper` |

Chaque outil renvoie un JSON marqué `"found": true` ou `false`. En fin de
fouille, le nœud ne garde que les résultats fructueux (`harvest_facts`) : c'est
le `lore`, que le routeur juge sans aucun LLM.

## Mesuré dans Langfuse

Deux générations par question (choisir l'outil, puis conclure), environ 1 300
tokens en entrée et 100 à 120 en sortie ; l'outil `lookup_movie` prend environ
1,1 s. Le premier appel après un redémarrage paie le chargement du modèle en
mémoire GPU (11,6 s contre 2,8 s). Détail : {doc}`../livre`, chapitre 17.

## Référence

```{eval-rst}
.. autofunction:: src.graph.nodes.rag_node
   :no-index:

.. autofunction:: src.graph.nodes.harvest_facts
   :no-index:

.. autofunction:: src.tools.rag_tool.validate_film
   :no-index:

.. autofunction:: src.tools.rag_tool.query_movie_metadata
   :no-index:

.. autofunction:: src.tools.rag_tool.find_similar_horror_movies
   :no-index:
```
