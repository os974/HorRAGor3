# Agent de Narration — l'Écrivain gothique

La plume finale, toujours dernière (`narration → END`). Isolé de toute la
plomberie technique (le *context trimming* du brief) : pas d'outils, pas
d'historique, seulement le dossier factuel.

| | |
|---|---|
| Nœud | `narration` |
| Lit dans le `State` | `question`, `lore`, `web_findings` — aucun canal de messages |
| Écrit dans le `State` | `story` (la réponse), `path`, et l'échange du tour dans `history` (la mémoire de session) |
| Outils | aucun |
| LLM | `qwen2.5:7b`, température 0,7 (la seule créative du graphe) |
| Suite | `END` |

Il reçoit exactement deux messages : son prompt système et le dossier (question,
lore et trouvailles web, ré-indentés pour la lecture). Son prompt lui interdit
d'inventer : il stylise la forme, jamais le fond, et doit avouer un dossier vide
avec élégance plutôt que de combler par des faits inventés.

## Mesuré dans Langfuse

Une seule génération : 421 tokens en entrée sur un film connu, 964 après un
détour par le web, contre 1 300 à 3 600 dans les canaux du Chercheur et de
l'Enquêteur — la preuve chiffrée du context trimming. C'est aussi la
génération la plus longue (8 à 13 s pour 300 à 500 tokens écrits). Détail :
{doc}`../livre`, chapitre 17.

## Référence

```{eval-rst}
.. autofunction:: src.graph.nodes.narration_node
   :no-index:
```
