"""Configuration Sphinx de HorRAGor3 — la documentation exigée par le brief.

Le brief impose trois contenus : la doc automatique des API, les schémas
relationnels de la base et la cartographie complète du graphe multi-agent.
Les deux contenus vivants (endpoints des API, carte du graphe) sont générés
à chaque construction depuis le code lui-même, dans ``_generated/`` : la doc
ne peut pas dériver du code.

Construction (depuis la racine) :
    uv run --group docs sphinx-build -W -b html docs/sphinx docs/sphinx/_build/html
"""

import json
import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent
ROOT = DOCS_DIR.parents[1]
GENERATED = DOCS_DIR / "_generated"
sys.path.insert(0, str(ROOT))

project = "HorRAGor3"
author = "Olivier Schollaert"
copyright = "2026, Olivier Schollaert — Simplon DEV IA"
language = "fr"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "myst_parser",
    "sphinxcontrib.mermaid",
]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
# _generated : fragments inclus par les pages, pas des pages en soi.
exclude_patterns = ["_build", "_generated"]

# Docstrings Google style (règle de travail du projet).
napoleon_google_docstring = True
napoleon_numpy_docstring = False
# « Attributes: » rendu en champs : évite les doublons avec les champs Pydantic.
napoleon_use_ivar = True
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {"members": True, "show-inheritance": True}

myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 3

html_theme = "furo"
html_title = "HorRAGor3 — documentation technique"


def _write(path: Path, text: str) -> None:
    """Écrit un fichier généré (en créant ses dossiers).

    Args:
        path: Destination.
        text: Contenu.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _endpoints_table(openapi: dict) -> str:
    """Rend la table Markdown des routes d'une spécification OpenAPI.

    Args:
        openapi: La spécification produite par ``FastAPI.openapi()``.

    Returns:
        Une table Markdown (méthode, chemin, résumé, protection).
    """
    lines = ["| Méthode | Chemin | Résumé | Protection |", "|---|---|---|---|"]
    for path, operations in openapi["paths"].items():
        for method, op in operations.items():
            summary = (op.get("summary") or "").replace("|", "\\|")
            locked = "JWT (Bearer)" if op.get("security") else "—"
            lines.append(f"| `{method.upper()}` | `{path}` | {summary} | {locked} |")
    return "\n".join(lines) + "\n"


def generate(_app=None) -> None:
    """Génère la carte du graphe, les tables d'endpoints et les OpenAPI.

    Args:
        _app: L'application Sphinx (hook ``builder-inited``), inutilisée.
    """
    # Imports différés : le code n'est chargé qu'au moment de construire,
    # une fois sys.path complété et la configuration Sphinx lue.
    from services.data_api.main import app as data_api
    from src.graph.pipeline import app as graph
    from src.main import app as ia_api

    mermaid = graph.get_graph().draw_mermaid()
    # LangGraph préfixe un front matter YAML (---config---) que MyST prendrait
    # pour les options de la directive : on ne garde que le diagramme.
    if mermaid.startswith("---"):
        mermaid = mermaid.split("---", 2)[2].lstrip("\n")
    _write(GENERATED / "graphe.md", "```{mermaid}\n" + mermaid + "```\n")
    for name, api in (("ia", ia_api), ("donnees", data_api)):
        spec = api.openapi()
        _write(GENERATED / f"endpoints_{name}.md", _endpoints_table(spec))
        _write(
            GENERATED / "openapi" / f"openapi-{name}.json",
            json.dumps(spec, ensure_ascii=False, indent=2),
        )


def setup(app) -> None:
    """Branche la génération au démarrage de la construction.

    Args:
        app: L'application Sphinx.
    """
    app.connect("builder-inited", generate)
