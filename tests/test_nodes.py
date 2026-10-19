"""Les trois nœuds avec un LLM factice : comportement sans Ollama."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

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
    assert out["lore"] == ""  # aucun ToolMessage encore
    assert len(out["rag_messages"]) == 3  # system + human + ai
    assert "Chercheur" in fake.last_messages[0].content


def test_rag_node_fige_sa_recolte_dans_le_lore(monkeypatch):
    """Les faits "found": true du canal deviennent le lore (sans jugement)."""
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

    assert "Alien" in out["lore"]
    assert "is_complete" not in out  # le jugement appartient au routeur
    assert "path" not in out  # déjà visité : pas de doublon


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


HISTORY = [
    HumanMessage(content="Parle-moi du film Hereditary"),
    AIMessage(content="Dans l'ombre des bois, Hereditary " + "x" * 600),
]


def test_rag_node_lit_les_echanges_precedents(monkeypatch):
    """Une relance : le Chercheur reçoit le résumé des échanges, réponses tronquées."""
    fake = FakeLLM(AIMessage(content="rien"))
    monkeypatch.setattr(nodes, "_worker_llm", lambda: fake)

    nodes.rag_node({"question": "Et son réalisateur ?", "history": HISTORY})

    prompt = fake.last_messages[1].content
    assert "Parle-moi du film Hereditary" in prompt
    assert prompt.endswith("Question actuelle : Et son réalisateur ?")
    assert "x" * 400 not in prompt  # la réponse précédente est tronquée


def test_scraper_node_recoit_aussi_le_resume(monkeypatch):
    """L'Enquêteur voit les échanges précédents dans son brief."""
    fake = FakeLLM(AIMessage(content="enquête close"))
    monkeypatch.setattr(nodes, "_worker_llm", lambda: fake)

    nodes.scraper_node({"question": "Et ses anecdotes ?", "history": HISTORY})

    assert "Parle-moi du film Hereditary" in fake.last_messages[1].content


def test_narration_node_consigne_l_echange(monkeypatch):
    """La plume reste isolée de la mémoire mais y consigne l'échange du tour."""
    fake = FakeLLM(AIMessage(content="Il était une nuit..."))
    monkeypatch.setattr(nodes, "_writer_llm", lambda: fake)

    out = nodes.narration_node({"question": "Parle-moi d'Alien", "history": HISTORY})

    assert [m.content for m in out["history"]] == ["Parle-moi d'Alien", "Il était une nuit..."]
    assert "Hereditary" not in fake.last_messages[1].content  # aucun historique transmis
