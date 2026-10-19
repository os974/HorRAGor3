# Outillage d'initialisation du cluster, pour les conteneurs « one-shot » du
# compose : certs-init (certificats TLS manquants) et kuma-setup (sondes
# Uptime Kuma). Grâce à eux, `docker compose up -d` monte tout le cluster en
# une seule commande. Les scripts ne sont pas copiés : le compose les monte en
# lecture seule depuis scripts/, la version du dépôt fait toujours foi.
FROM ghcr.io/astral-sh/uv:0.9.30-python3.12-bookworm-slim

# bash et openssl sont fournis par l'image ; le client de l'API Uptime Kuma
# (socket.io) et Loguru sont épinglés comme partout dans le projet.
RUN uv pip install --system --no-cache uptime-kuma-api==1.2.1 loguru==0.7.3

WORKDIR /work
