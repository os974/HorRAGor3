# HorRAGor3 — documentation technique

HorRAGor est un chatbot spécialisé dans l'univers de l'horreur. Cette troisième
partie remplace l'agent monolithique de HorRAGor2 par un **système multi-agent
peer-to-peer sous LangGraph** (Chercheur local, Enquêteur web, Écrivain
gothique), puis l'industrialise : microservices Docker isolés, authentification
par Refresh Tokens, monitoring à 360°, CI/CD.

Cette documentation couvre les trois contenus exigés par le brief :

- la **documentation automatique des deux API** (Intelligence et Données) ;
- les **schémas relationnels** de la base de données ;
- la **cartographie complète du graphe multi-agent**.

Les pages des API et du graphe sont **générées depuis le code** à chaque
construction : elles ne peuvent pas diverger de ce qui tourne.

```{toctree}
:maxdepth: 2
:caption: Comprendre

architecture
graphe
livre
console
```

```{toctree}
:maxdepth: 2
:caption: Référence

api_ia
api_donnees
bdd
outils
```

```{toctree}
:maxdepth: 1
:caption: Pilotage

plan
```
