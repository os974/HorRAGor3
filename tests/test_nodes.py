"""Les trois nœuds avec un LLM factice : comportement sans Ollama."""

from langchain_core.messages import AIMessage, ToolMessage

from src.graph import nodes


class FakeLLM:
    """Double du ChatOllama : rejoue des réponses préparées.

    Attributes:
        last_messages: Les messages reçus au dernier invoke (pour inspection).
    """

    def __init__(self, *responses):
        self._responses = list(responses)
        self.last_messages = None

    def bind_tools(self, tools):
        """Ignore les outils : on rejoue des réponses fixes."""
        return self

    def invoke(self, messages):
        """Renvoie la prochaine réponse préparée."""
        self.last_messages = list(messages)
        return self._responses.pop(0)


def test_rag_node_premiere_visite_construit_le_prompt(monkeypatch):
    """Première entrée : SystemMessage + question, et path enregistre "rag"."""
    fake = FakeLLM(AIMessage(content="rien trouvé"))
    monkeypatch.setattr(nodes, "_worker_llm", lambda: fake)

    out = nodes.rag_node({"question": "Parle-moi d'Alien"})

    assert out["path"] == ["rag"]
    assert out["is_complete"] is False  # aucun ToolMessage encore
    assert len(out["rag_messages"]) == 3  # system + human + ai
    assert "Chercheur" in fake.last_messages[0].content


def test_rag_node_juge_sa_recolte_sur_les_faits(monkeypatch):
    """Des faits "found": true dans le canal → récolte complète."""
    fake = FakeLLM(AIMessage(content="fouille terminée"))
    monkeypatch.setattr(nodes, "_worker_llm", lambda: fake)
    history = [
        AIMessage(content="", tool_calls=[{"name": "lookup_movie", "args": {}, "id": "1"}]),
        ToolMessage(
            content='{"found": true, "title": "Alien", "synopsis": "..."}', tool_call_id="1"
        ),
    ]

    out = nodes.rag_node(
        {"question": "Parle-moi d'Alien", "rag_messages": history, "path": ["rag"]}
    )

    assert out["is_complete"] is True
    assert "Alien" in out["lore"]
    assert "path" not in out  # déjà visité : pas de doublon


def test_rag_node_anecdotes_jamais_complet_localement(monkeypatch):
    """Question anecdotes → récolte insuffisante même avec des faits."""
    fake = FakeLLM(AIMessage(content="fouille terminée"))
    monkeypatch.setattr(nodes, "_worker_llm", lambda: fake)
    history = [ToolMessage(content='{"found": true, "title": "Weapons"}', tool_call_id="1")]

    out = nodes.rag_node(
        {"question": "Anecdotes de tournage de Weapons ?", "rag_messages": history, "path": ["rag"]}
    )

    assert out["is_complete"] is False  # l'Enquêteur devra partir
    assert "Weapons" in out["lore"]  # mais le lore local est conservé


def test_scraper_node_recoit_un_brief_reformule(monkeypatch):
    """L'Enquêteur voit la question + le lore, jamais l'historique du RAG."""
    fake = FakeLLM(AIMessage(content="enquête close"))
    monkeypatch.setattr(nodes, "_worker_llm", lambda: fake)

    out = nodes.scraper_node({"question": "Anecdotes ?", "lore": "LORE_LOCAL", "path": ["rag"]})

    brief = fake.last_messages[1].content
    assert "Anecdotes ?" in brief and "LORE_LOCAL" in brief
    assert out["path"] == ["scraper"]
    # Pas de trouvaille outil → repli sur la conclusion de l'agent.
    assert out["web_findings"] == "enquête close"


def test_scraper_node_fige_les_faits_web(monkeypatch):
    """Les résultats d'outils fructueux deviennent les web_findings."""
    fake = FakeLLM(AIMessage(content="fini"))
    monkeypatch.setattr(nodes, "_worker_llm", lambda: fake)
    history = [ToolMessage(content='{"found": true, "results": ["anecdote"]}', tool_call_id="1")]

    out = nodes.scraper_node(
        {"question": "q", "scraper_messages": history, "path": ["rag", "scraper"]}
    )

    assert "anecdote" in out["web_findings"]


def test_narration_node_ne_voit_que_le_dossier(monkeypatch):
    """Context trimming : la plume reçoit le dossier, aucun message d'agent."""
    fake = FakeLLM(AIMessage(content="Il était une nuit..."))
    monkeypatch.setattr(nodes, "_writer_llm", lambda: fake)

    out = nodes.narration_node(
        {
            "question": "Parle-moi d'Alien",
            "lore": '{"title": "Alien"}',
            "web_findings": "trouvaille web",
        }
    )

    assert out["story"] == "Il était une nuit..."
    assert out["path"] == ["narration"]
    dossier = fake.last_messages[1].content
    assert "Alien" in dossier and "trouvaille web" in dossier
    assert len(fake.last_messages) == 2  # system + dossier, rien d'autre
