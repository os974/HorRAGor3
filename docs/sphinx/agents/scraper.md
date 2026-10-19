# Agent Scraper — l'Enquêteur du web

Déclenché **conditionnellement** : le routeur ne l'envoie que si la récolte
locale est vide, ou si la question réclame des informations que la base ne
possède pas (anecdotes, coulisses, tournage…). Il creuse alors le web.

| | |
|---|---|
| Nœud | `scraper`, avec sa micro-boucle `scraper ⇄ scraper_tools` |
| Lit dans le `State` | `question`, `lore` (via un brief reformulé), `scraper_messages` (son propre canal) |
| Écrit dans le `State` | `scraper_messages` ; `web_findings` en fin d'enquête ; `path` à la première visite |
| Outils | `wikipedia_synopsis` (API REST Wikipédia), `web_search` (DuckDuckGo via `ddgs`, sans clé) |
| LLM | `qwen2.5:7b`, température 0 |
| Suite | toujours `narration` (`should_continue_scraper`, une fois les outils épuisés) |

Il ne voit jamais l'historique du Chercheur : il reçoit un brief reformulé
(la question et le lore éventuel). Si le web ne donne rien, sa conclusion
tient lieu de `web_findings`, pour que l'Écrivain sache que l'enquête a fait
chou blanc.

## Mesuré dans Langfuse

Sur « Des anecdotes de tournage de The Thing ? » : trois générations,
13,6 s, 3 642 tokens en entrée et 294 en sortie — le canal le plus lourd du
graphe ; outils `web_search` 2,4 s et `wikipedia_synopsis` 0,6 s. Détail :
{doc}`../livre`, chapitre 17.

## Référence

```{eval-rst}
.. autofunction:: src.graph.nodes.scraper_node
   :no-index:

.. autofunction:: src.graph.router.wants_web_details
   :no-index:

.. autofunction:: src.tools.scraper_tool.scrape_detailed_synopsis
   :no-index:

.. autofunction:: src.tools.scraper_tool.search_web
   :no-index:
```
