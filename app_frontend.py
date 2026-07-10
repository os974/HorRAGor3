"""Interface Streamlit : la salle de lecture du manoir HorRAGor.

Lancement (depuis la racine, l'API devant tourner) :
    uv run streamlit run app_frontend.py

Découplage strict (hérité de HorRAGor2) : aucune logique LLM/BDD ici —
uniquement un appel HTTP à ``POST /chat`` et l'affichage. Le Front partage
seulement les schémas Pydantic (le contrat) avec le backend.

Spécificité Partie 3 : l'interface montre le PARCOURS des agents dans le
graphe (Chercheur → Enquêteur → Écrivain) — la preuve visuelle du routage
conditionnel du brief.
"""

import httpx
import streamlit as st

from src.config import settings
from src.contracts.schemas import ChatRequest, ChatResponse

st.set_page_config(page_title="HorRAGor3 🕸️", page_icon="🕸️")

# Libellés humains des nœuds du graphe (ChatResponse.path).
_AGENT_BADGES = {
    "rag": "🔎 Chercheur Local",
    "scraper": "🕵️ Enquêteur du Web",
    "narration": "🖋️ Écrivain Gothique",
}

_TRACE_ICONS = {
    "node": "🤖",
    "router": "🔀",
    "embed": "🧬",
    "faiss": "🔎",
    "sql": "🗄️",
    "pgvector": "🧭",
    "tmdb": "🎬",
    "wikipedia": "🌐",
    "ddg": "🕸️",
}


def _login(username: str, password: str) -> bool:
    """Authentifie le compte auprès de ``POST /auth/login``.

    Args:
        username: Nom du compte démo.
        password: Mot de passe associé.

    Returns:
        True si la paire de jetons a été obtenue et stockée en session.
    """
    resp = httpx.post(
        f"{settings.api_base_url}/auth/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    if resp.status_code != 200:
        return False
    tokens = resp.json()
    st.session_state.access_token = tokens["access_token"]
    st.session_state.refresh_token = tokens["refresh_token"]
    return True


def _refresh_tokens() -> bool:
    """Renouvelle la paire de jetons via ``POST /auth/refresh``.

    Returns:
        True si la session a pu être prolongée (sinon : re-login requis).
    """
    refresh_token = st.session_state.get("refresh_token")
    if not refresh_token:
        return False
    resp = httpx.post(
        f"{settings.api_base_url}/auth/refresh",
        json={"refresh_token": refresh_token},
        timeout=15,
    )
    if resp.status_code != 200:
        return False
    tokens = resp.json()
    st.session_state.access_token = tokens["access_token"]
    st.session_state.refresh_token = tokens["refresh_token"]
    return True


def _post_chat(req: ChatRequest) -> httpx.Response:
    """Poste la requête de chat avec le jeton d'accès courant.

    Args:
        req: La requête à envoyer.

    Returns:
        La réponse HTTP brute (le statut est géré par l'appelant).
    """
    return httpx.post(
        f"{settings.api_base_url}/chat",
        json=req.model_dump(),
        headers={"Authorization": f"Bearer {st.session_state.get('access_token', '')}"},
        timeout=180,  # trois agents + outils web : un run complet peut être long
    )


def _send_message(message: str, session_id: str = "default") -> ChatResponse:
    """Envoie la question à ``POST /chat`` (JWT), avec refresh automatique sur 401.

    Args:
        message: La question de l'utilisateur.
        session_id: Identifiant de conversation (corrélation logs/traces).

    Returns:
        La réponse validée contre le contrat partagé.

    Raises:
        httpx.HTTPError: API injoignable ou statut d'échec (affiché en bulle).
        PermissionError: Session expirée malgré le refresh (re-login requis).
    """
    req = ChatRequest(message=message, session_id=session_id)
    resp = _post_chat(req)
    if resp.status_code == 401:
        # Access token expiré : on tente UNE prolongation via le refresh token.
        if not _refresh_tokens():
            raise PermissionError("session expirée — reconnecte-toi")
        resp = _post_chat(req)
    resp.raise_for_status()
    return ChatResponse.model_validate(resp.json())


def _render_meta(msg: dict) -> None:
    """Affiche le parcours des agents et les sources sous une réponse.

    Args:
        msg: L'entrée d'historique de l'assistant.
    """
    bits = []
    if path := msg.get("path"):
        bits.append(" → ".join(_AGENT_BADGES.get(node, node) for node in path))
    if sources := msg.get("sources"):
        bits.append("sources : " + ", ".join(sources))
    if bits:
        st.caption(" · ".join(bits))


def _render_trace(msg: dict) -> None:
    """Expander détaillant les étapes du raisonnement multi-agent.

    Args:
        msg: L'entrée d'historique de l'assistant.
    """
    steps = msg.get("trace") or []
    if not steps:
        return
    with st.expander(f"🔍 Dans les coulisses du manoir ({len(steps)} étapes)"):
        for step in steps:
            line = f"{_TRACE_ICONS.get(step['kind'], '•')} **{step['name']}**"
            if step.get("detail"):
                line += f" — {step['detail']}"
            st.markdown(line)


# --- Barre latérale ---
with st.sidebar:
    st.header("HorRAGor3 🕸️")
    st.caption(
        "Système multi-agent LangGraph : un Chercheur fouille la crypte locale, "
        "un Enquêteur arpente le web si besoin, un Écrivain Gothique conte le tout."
    )
    # Le verrou du manoir : pas de jetons → formulaire de connexion (JWT).
    if "access_token" not in st.session_state:
        with st.form("login"):
            st.subheader("🗝️ Entrée du manoir")
            username = st.text_input("Utilisateur")
            password = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter", use_container_width=True):
                if _login(username, password):
                    st.rerun()
                st.error("Identifiants invalides")
    else:
        if st.button("🚪 Se déconnecter", use_container_width=True):
            for key in ("access_token", "refresh_token", "messages"):
                st.session_state.pop(key, None)
            st.rerun()
        if st.button("🗑️ Nouvelle conversation", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
    st.markdown("**Exemples :**")
    st.markdown(
        "- Parle-moi du film Hereditary\n"
        "- Des films semblables à Midsommar ?\n"
        "- Anecdotes de tournage de The Thing ?"
    )

st.title("Le Manoir de l'Horreur 🕸️")

# Porte close tant que le visiteur n'est pas authentifié.
if "access_token" not in st.session_state:
    st.info("🗝️ Connecte-toi dans la barre latérale pour entrer dans le manoir.")
    st.stop()

# session_state : Streamlit ré-exécute tout le script à chaque interaction ;
# c'est ici que l'historique survit entre deux rendus.
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            _render_meta(msg)
            _render_trace(msg)

if prompt := st.chat_input("Ose poser ta question sur un film d'horreur..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Les agents s'affairent dans la crypte..."):
            try:
                response = _send_message(prompt)
                entry = {
                    "role": "assistant",
                    "content": response.answer,
                    "path": response.path,
                    "sources": response.sources,
                    "trace": [step.model_dump() for step in response.trace],
                }
            except Exception as exc:  # noqa: BLE001 — toute erreur s'affiche à l'utilisateur
                entry = {
                    "role": "assistant",
                    "content": f"⚠️ Le manoir ne répond pas (API) : {exc}",
                    "path": [],
                    "sources": [],
                    "trace": [],
                }
        st.markdown(entry["content"])
        _render_meta(entry)
        _render_trace(entry)

    st.session_state.messages.append(entry)
