"""Provisionne les sondes Uptime Kuma du cluster HorRAGor3 (idempotent).

Uptime Kuma n'a pas de provisioning natif par fichier : ce script le remplace,
via l'API socket.io (bibliothèque ``uptime-kuma-api``, chargée à la volée pour
ne pas alourdir les dépendances du projet). Il crée le compte admin au premier
lancement puis ajoute chaque sonde absente, sans toucher aux existantes.

Lancement (cluster démarré) :
    uv run --with uptime-kuma-api==1.2.1 python scripts/setup_uptime_kuma.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from uptime_kuma_api import MonitorType, UptimeKumaApi

KUMA_URL = "http://127.0.0.1:3001"
INTERVAL_S = 60

# (nom, type, url, mot-clé attendu) — chaque couche du brief + les outils.
MONITORS: list[tuple[str, MonitorType, str, str | None]] = [
    (
        "Présentation — entrée publique (TLS)",
        MonitorType.HTTP,
        "https://horragor.localhost:8443/_stcore/health",
        None,
    ),
    (
        "Intelligence — entrée publique (TLS)",
        MonitorType.HTTP,
        "https://api.horragor.localhost:8443/health",
        None,
    ),
    ("Présentation — Streamlit", MonitorType.HTTP, "http://frontend:8501/_stcore/health", None),
    ("Intelligence — API IA", MonitorType.HTTP, "http://api-ia:8000/health", None),
    ("Données — API Données", MonitorType.HTTP, "http://api-donnees:8100/health", None),
    (
        "Données — chaîne API → Postgres",
        MonitorType.KEYWORD,
        "http://api-donnees:8100/films/41",
        "Hereditary",
    ),
    ("Agent — Langfuse", MonitorType.HTTP, "http://langfuse-web:3000/api/public/health", None),
    ("Observabilité — Prometheus", MonitorType.HTTP, "http://prometheus:9090/-/healthy", None),
    ("Observabilité — Grafana", MonitorType.HTTP, "http://grafana:3000/api/health", None),
]


def main() -> None:
    """Crée le compte admin si besoin puis ajoute les sondes manquantes.

    Raises:
        KeyError: Si ``KUMA_ADMIN_USER``/``KUMA_ADMIN_PASSWORD`` manquent au ``.env``.
    """
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    user, password = os.environ["KUMA_ADMIN_USER"], os.environ["KUMA_ADMIN_PASSWORD"]

    with UptimeKumaApi(KUMA_URL) as api:
        if api.need_setup():
            api.setup(user, password)
            logger.info("Compte admin {!r} créé", user)
        api.login(user, password)

        existing = {m["name"] for m in api.get_monitors()}
        for name, monitor_type, url, keyword in MONITORS:
            if name in existing:
                logger.info("= {} (déjà présente)", name)
                continue
            extra = {"keyword": keyword} if keyword else {}
            api.add_monitor(type=monitor_type, name=name, url=url, interval=INTERVAL_S, **extra)
            logger.info("+ {}", name)


if __name__ == "__main__":
    main()
