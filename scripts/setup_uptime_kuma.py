"""Provisionne les sondes Uptime Kuma du cluster HorRAGor3 (idempotent).

Uptime Kuma n'a pas de provisioning natif par fichier : ce script le remplace,
via l'API socket.io (bibliothèque ``uptime-kuma-api``, chargée à la volée pour
ne pas alourdir les dépendances du projet). Il crée le compte admin au premier
lancement, ajoute chaque sonde absente et remet à jour celles dont l'URL ou le
mot-clé a changé.

Lancement (cluster démarré ; identifiants lus dans le .env) :
    uv run --env-file .env --with uptime-kuma-api==1.2.1 python scripts/setup_uptime_kuma.py
"""

import os

from loguru import logger
from uptime_kuma_api import MonitorType, UptimeKumaApi

# Depuis l'hôte par défaut ; le conteneur one-shot du compose passe l'URL interne.
KUMA_URL = os.environ.get("KUMA_URL", "http://127.0.0.1:3001")
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
    # Le LLM de l'hôte, par le même chemin qu'api-ia : sans lui, /health reste
    # vert mais chaque récit tombe sur la réponse de repli.
    (
        "Intelligence — Ollama (via relais)",
        MonitorType.HTTP,
        "http://host.docker.internal:11434/api/version",
        None,
    ),
    ("Données — API Données", MonitorType.HTTP, "http://api-donnees:8100/health", None),
    # /health de l'API Données interroge la base (SELECT 1) : la chaîne entière
    # est sondée sans jeton, les routes /films/* exigeant celui d'un utilisateur.
    (
        "Données — chaîne API → Postgres",
        MonitorType.KEYWORD,
        "http://api-donnees:8100/health",
        '"db":"ok"',
    ),
    ("Agent — Langfuse", MonitorType.HTTP, "http://langfuse-web:3000/api/public/health", None),
    ("Observabilité — Prometheus", MonitorType.HTTP, "http://prometheus:9090/-/healthy", None),
    ("Observabilité — Grafana", MonitorType.HTTP, "http://grafana:3000/api/health", None),
]


def main() -> None:
    """Crée le compte admin si besoin, ajoute les sondes manquantes et met à jour les autres.

    Raises:
        KeyError: Si ``KUMA_ADMIN_USER``/``KUMA_ADMIN_PASSWORD`` manquent au ``.env``.
    """
    user, password = os.environ["KUMA_ADMIN_USER"], os.environ["KUMA_ADMIN_PASSWORD"]

    with UptimeKumaApi(KUMA_URL) as api:
        if api.need_setup():
            api.setup(user, password)
            logger.info("Compte admin {!r} créé", user)
        api.login(user, password)

        existing = {m["name"]: m for m in api.get_monitors()}
        for name, monitor_type, url, keyword in MONITORS:
            extra = {"keyword": keyword} if keyword else {}
            current = existing.get(name)
            if current is None:
                api.add_monitor(type=monitor_type, name=name, url=url, interval=INTERVAL_S, **extra)
                logger.info("+ {}", name)
            elif current["url"] != url or (keyword and current.get("keyword") != keyword):
                api.edit_monitor(current["id"], type=monitor_type, url=url, **extra)
                logger.info("~ {} (mise à jour)", name)
            else:
                logger.info("= {} (déjà présente)", name)


if __name__ == "__main__":
    main()
