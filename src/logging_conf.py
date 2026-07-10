"""Journalisation centralisée du projet (Loguru).

Règle observabilité du projet : Loguru dès la Phase A, zéro ``print()``.
Ce module est le SEUL endroit où le logging se configure ; le reste du code
fait simplement ``from loguru import logger`` puis ``logger.info(...)``.

Deux sorties :
    - stderr, lisible par un humain (niveau selon ``settings.log_level``) ;
    - ``logs/app.jsonl``, JSON sérialisé (``serialize=True``) exploitable en
      Phase G par la stack de monitoring.

Les logs de la stdlib (uvicorn, fastapi...) sont interceptés et re-routés vers
Loguru par :class:`InterceptHandler` : un seul format, un seul flux.
"""

import logging
import sys

from loguru import logger

from src.config import _PROJECT_ROOT, settings


class InterceptHandler(logging.Handler):
    """Handler stdlib qui re-route chaque enregistrement vers Loguru.

    Permet de capter les logs des bibliothèques (uvicorn, fastapi, httpx...)
    sans les configurer une par une : la stdlib devient un simple tuyau.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Transmet un enregistrement stdlib à Loguru.

        Args:
            record: Enregistrement produit par la bibliothèque appelante.
        """
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # Remonte la pile jusqu'au vrai appelant pour que Loguru affiche le bon
        # fichier/ligne (et pas ce handler).
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    """Configure Loguru pour toute l'application (à appeler une seule fois).

    Idempotent : ``logger.remove()`` purge les sinks existants avant de les
    recréer, un double appel ne duplique donc pas les sorties.
    """
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)
    logger.add(
        _PROJECT_ROOT / "logs" / "app.jsonl",
        level=settings.log_level,
        serialize=True,
        rotation="10 MB",
        retention=5,
    )
    # force=True : remplace les handlers déjà posés par uvicorn/streamlit.
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
