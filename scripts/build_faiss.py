"""Reconstruit l'index FAISS des titres (``data/faiss_index/``) depuis la base.

L'index (~100 Mo) est gitignoré : sur un clone neuf, ce job offline le
régénère à partir de la table ``movies`` (``DATABASE_URL``) et d'Ollama
(``nomic-embed-text``), avec le code de production :
:meth:`TitleIndex.build_from_pairs` puis :meth:`TitleIndex.save`. Repris du
``build_faiss.py`` de HorRAGor2.

Lancement (depuis la racine, Ollama démarré, ``DATABASE_URL`` dans le .env) :
    uv run python -m scripts.build_faiss                       # ~34 000 titres
    uv run python -m scripts.build_faiss --limit 300 --out /tmp/faiss  # essai rapide
"""

import argparse
import time
from pathlib import Path

from loguru import logger
from sqlalchemy import text

from src.data.db import get_engine
from src.data.faiss_index import TitleIndex
from src.logging_conf import setup_logging


def load_pairs(limit: int | None = None) -> list[tuple[int, str]]:
    """Lit les couples ``(id, title)`` de la table ``movies``.

    Args:
        limit: Nombre maximal de titres (None = toute la table).

    Returns:
        Les couples triés par identifiant, titres vides exclus.
    """
    sql = "SELECT id, title FROM movies WHERE title IS NOT NULL ORDER BY id"
    params: dict[str, int] = {}
    if limit:
        sql += " LIMIT :limit"
        params["limit"] = limit
    with get_engine().connect() as conn:
        return [(int(row.id), str(row.title)) for row in conn.execute(text(sql), params)]


def build(limit: int | None = None, out: str | None = None) -> Path:
    """Construit et persiste l'index des titres.

    Args:
        limit: Nombre maximal de titres (None = toute la table).
        out: Dossier cible (None = ``settings.faiss_index_dir``).

    Returns:
        Le dossier dans lequel l'index a été écrit.
    """
    pairs = load_pairs(limit)
    logger.info("{} titres à embedder", len(pairs))
    start = time.perf_counter()
    index = TitleIndex.build_from_pairs(pairs)
    path = index.save(out)
    logger.info(
        "Index construit : {} titres en {:.1f} s → {}",
        len(index),
        time.perf_counter() - start,
        path,
    )
    return path


def main(argv: list[str] | None = None) -> None:
    """Point d'entrée en ligne de commande.

    Args:
        argv: Arguments (None = ceux de la ligne de commande).
    """
    parser = argparse.ArgumentParser(description="Reconstruit l'index FAISS des titres.")
    parser.add_argument("--limit", type=int, default=None, help="limiter le nombre de titres")
    parser.add_argument("--out", default=None, help="dossier cible (défaut : la config)")
    args = parser.parse_args(argv)
    setup_logging()
    build(args.limit, args.out)


if __name__ == "__main__":
    main()
