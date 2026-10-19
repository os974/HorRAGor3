"""Journalisation centralisée du projet (Loguru).

Règle observabilité du projet : Loguru dès la Phase A, zéro ``print()``.
Ce module est le SEUL endroit où le logging se configure ; le reste du code
fait simplement ``from loguru import logger`` puis ``logger.info(...)``.

Deux sorties :
    - stderr, lisible par un humain (niveau selon ``settings.log_level``) ;
    - ``logs/app.jsonl``, JSON sérialisé (``serialize=True``) exploitable en
      Phase G par la stack de monitoring.

Les logs de la stdlib (uvicorn, fastapi...) sont interceptés et re-routés vers
Loguru par :class:`InterceptHandler` : un seul format, un seul flux. Les
loggers d'uvicorn, configurés par le serveur AVANT l'import de l'app (handlers
propres, ``propagate=False``), sont explicitement rebranchés sur ce flux.

Corrélation : l'API pose ``session_id`` et ``request_id`` dans le contexte
Loguru (``logger.contextualize``) ; ils figurent dans chaque ligne JSON
(champ ``extra``) émise pendant la requête, graphe compris.
"""

import inspect
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
        # Remonte la pile au-delà de ce handler et du module logging, jusqu'au
        # vrai appelant : Loguru affiche alors son fichier/sa ligne (recette
        # officielle de Loguru).
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    """Configure Loguru pour toute l'application (à appeler une seule fois).

    Idempotent : ``logger.remove()`` purge les sinks existants avant de les
    recréer, un double appel ne duplique donc pas les sorties. Appelé par les
    deux API et par l'interface Streamlit (journalisation de bout en bout).
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
    # force=True : remplace les handlers déjà posés sur le logger racine.
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    # uvicorn pose ses propres handlers (propagate=False) avant d'importer
    # l'app : on les retire pour que ses logs remontent eux aussi à Loguru.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        std_logger = logging.getLogger(name)
        std_logger.handlers = []
        std_logger.propagate = True
