"""Outil natif de l'Agent Scraper (Enquêteur du Web) : Wikipédia + DuckDuckGo.

Déclenché par routage conditionnel UNIQUEMENT si la récolte locale de l'Agent
RAG est insuffisante (brief) : le scraping est lent et gourmand en contexte.

Deux capacités complémentaires :
    - :func:`scrape_detailed_synopsis` — API REST Wikipédia (repris de la
      Partie 2) : le résumé encyclopédique d'une œuvre ;
    - :func:`search_web` — recherche DuckDuckGo (lib ``ddgs``, sans clé API,
      cohérent avec le 100 % local) : anecdotes et détails hors Wikipédia.

Même contrat que ``rag_tool`` : **jamais d'exception** — erreur réseau →
message explicite ou liste vide, l'agent décide de la suite.
"""

import httpx
from ddgs import DDGS
from loguru import logger

from src import trace

_WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
# Wikipédia exige un User-Agent identifiant l'application.
# ASCII uniquement : les en-têtes HTTP n'acceptent pas les accents (httpx encode en ascii).
_HEADERS = {"User-Agent": "HorRAGor3/0.1 (projet pedagogique)"}


def scrape_detailed_synopsis(title: str) -> str:
    """Récupère l'extrait Wikipédia d'une œuvre.

    Args:
        title: Titre de l'œuvre (idéalement confirmé par ``validate_film``).

    Returns:
        L'extrait de l'article, ou un message d'erreur explicite (page
        absente, homonymie, réseau) que l'agent peut restituer tel quel.
    """
    try:
        resp = httpx.get(
            _WIKI_SUMMARY + title.replace(" ", "_"),
            headers=_HEADERS,
            timeout=15,
            follow_redirects=True,
        )
    except httpx.HTTPError:
        trace.record("wikipedia", "scrape", f"{title!r} → erreur réseau")
        return f"Impossible de contacter Wikipédia pour '{title}' (erreur réseau)."
    if resp.status_code != 200:
        trace.record("wikipedia", "scrape", f"{title!r} → introuvable (HTTP {resp.status_code})")
        return f"Aucune page Wikipédia trouvée pour '{title}'."
    data = resp.json()
    if data.get("type") == "disambiguation":
        trace.record("wikipedia", "scrape", f"{title!r} → page d'homonymie")
        return (
            f"'{title}' est une page d'homonymie sur Wikipédia : plusieurs titres correspondent. "
            "Précise l'année ou le réalisateur pour affiner la recherche."
        )
    extract = data.get("extract")
    if not extract:
        trace.record("wikipedia", "scrape", f"{title!r} → rien")
        return f"La page Wikipédia de '{title}' ne contient pas de synopsis exploitable."
    trace.record("wikipedia", "scrape", f"{title!r} → extrait {len(extract)} car.")
    return extract


def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Recherche DuckDuckGo pour creuser anecdotes et détails manquants.

    Nouveauté Partie 3 : la Partie 2 n'avait que Wikipédia ; l'Enquêteur du
    Web du brief doit pouvoir « creuser le web en direct ». ``ddgs`` est
    gratuit et sans clé API.

    Args:
        query: Requête de recherche (ex. "Hereditary 2018 anecdotes tournage").
        max_results: Nombre maximal de résultats.

    Returns:
        Une liste de ``{"title", "url", "snippet"}`` (vide si aucun résultat
        ou erreur réseau — jamais d'exception).
    """
    try:
        with DDGS() as client:
            raw = list(client.text(query, max_results=max_results))
    except Exception as exc:  # noqa: BLE001 — contrat "jamais d'exception" pour l'agent
        logger.warning("search_web({!r}) en échec technique : {}", query, exc)
        trace.record("ddg", "search_web", f"{query!r} → erreur réseau")
        return []
    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("href") or r.get("url", ""),
            "snippet": r.get("body") or r.get("snippet", ""),
        }
        for r in raw
    ]
    trace.record("ddg", "search_web", f"{query!r} → {len(results)} résultat(s)")
    return results
