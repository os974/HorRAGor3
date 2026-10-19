# Interface — couche Présentation (Streamlit)

L'interface du manoir : un script Streamlit (`app_frontend.py`) dans son propre
conteneur. Elle ne contient **aucune logique LLM ni d'accès aux données** : elle
authentifie le visiteur, envoie ses questions à l'API IA et affiche les
réponses. Elle ne partage avec le backend que les schémas Pydantic du contrat
(`ChatRequest`, `ChatResponse`).

## Le parcours du visiteur

1. **La porte** : sans jeton, la page affiche « Connecte-toi dans la barre
   latérale » et s'arrête là (`st.stop()`) ; le chat n'existe pas encore.
2. **La connexion** : le formulaire « Entrée du manoir » envoie les
   identifiants à `POST /auth/login` ; la paire de jetons (access + refresh)
   est gardée dans la session Streamlit, jamais dans le navigateur.
3. **La conversation** : chaque question part en `POST /chat` avec l'access
   token et l'identifiant de la conversation. La réponse s'affiche avec :
   - le **récit** de l'Écrivain gothique ;
   - le **parcours des agents** (🔎 Chercheur → 🕵️ Enquêteur → 🖋️ Écrivain),
     preuve visuelle du routage conditionnel ;
   - les **sources** interrogées (FAISS, SQL, pgvector, TMDB, Wikipédia,
     DuckDuckGo) ;
   - l'expander **« Dans les coulisses du manoir »**, qui déroule chaque étape
     (nœuds, décision du routeur et sa raison, appels d'outils).
4. **La session qui se prolonge** : quand l'access token (15 min) expire, l'API
   répond 401 ; l'interface tente **une** prolongation silencieuse par
   `POST /auth/refresh`, puis rejoue la question. Si le refresh est refusé
   (expiré ou révoqué), elle demande de se reconnecter.
5. **Nouvelle conversation / déconnexion** : « Nouvelle conversation » vide
   l'historique affiché et change d'identifiant de conversation (le backend
   repart d'une mémoire vierge) ; « Se déconnecter » efface aussi les jetons.

## La conversation et sa mémoire

Chaque conversation reçoit un `session_id` (uuid4) à sa première question.
Côté serveur, il désigne la mémoire de session du graphe, rattachée au compte
connecté : une relance comme « Et qui l'a réalisé ? » est comprise grâce aux
échanges précédents (voir {doc}`graphe`). Le même identifiant regroupe les
traces de la conversation dans Langfuse et se retrouve dans les logs JSON des
deux API.

## Les fonctions du script

| Fonction | Rôle |
|---|---|
| `_login` | `POST /auth/login`, range la paire de jetons dans la session ; journalise un refus |
| `_refresh_tokens` | `POST /auth/refresh` : rotation complète de la paire |
| `_session_id` | identifiant de la conversation courante, créé à la première question |
| `_post_chat` | `POST /chat` avec `Authorization: Bearer` (délai de 180 s : trois agents et leurs outils) |
| `_send_message` | la question de bout en bout : envoi, refresh unique sur 401, revalidation de la réponse contre le contrat |
| `_render_meta` | la ligne « parcours des agents · sources » sous chaque réponse |
| `_render_trace` | l'expander « Dans les coulisses du manoir » |
| `_init_logging` | Loguru configuré une fois par processus, pas à chaque rerun Streamlit |

## Sécurité

- **Communication chiffrée** : en cluster, l'interface joint l'API IA par
  `https://api.horragor.localhost`, via Traefik, en vérifiant le certificat
  contre la CA locale (`SSL_CERT_FILE`) — jamais de `verify=False`.
- **Isolement réseau** : son seul réseau (`front_net`, interne) ne mène qu'à
  Traefik ; ni l'API IA en clair, ni internet ne lui sont accessibles.
- Processus non root (uid 1001), télémétrie Streamlit désactivée.

## Observabilité

- **Santé** : `/_stcore/health`, l'endpoint natif de Streamlit, sondé par le
  `HEALTHCHECK` Docker et par Uptime Kuma (en direct et par l'entrée publique
  TLS).
- **Télémétrie** : Streamlit n'expose pas de `/metrics` ; Prometheus mesure le
  trafic qui le sert dans Traefik (`traefik_service_*{service="front@file"}` :
  débit, latence, erreurs), affiché dans Grafana.
- **Journalisation** : Loguru, comme les deux API (refus de connexion, nouvelle
  conversation, échec d'un appel à `/chat` avec sa pile d'erreur).

## Les tests

`tests/test_frontend.py` pilote le vrai script avec
`streamlit.testing.v1.AppTest`, l'API étant simulée : porte close sans
session, connexion réussie et refusée, chat complet (récit, parcours,
sources), refresh silencieux sur 401, refresh refusé, `session_id` stable sur
une conversation et renouvelé par « Nouvelle conversation », déconnexion.
Couverture de l'interface : 99 %.
