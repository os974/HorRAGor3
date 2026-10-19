#!/usr/bin/env bash
# Génère l'autorité locale + le certificat TLS du cluster (communication
# chiffrée UI → API IA exigée par le brief). Idempotent : ne régénère pas
# si les fichiers existent. Sortie : certs/ (gitignoré). Lancé à chaque
# `docker compose up` par le conteneur one-shot certs-init ; utilisable aussi
# à la main.
#
#   ca.pem / ca.key          — l'autorité locale (montée dans le front pour
#                              VÉRIFIER le certificat : pas de verify=False)
#   cluster.pem / cluster.key — le certificat servi par Traefik
#                              (SAN : horragor.localhost, api.horragor.localhost)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p certs

if [[ -f certs/cluster.pem && -f certs/ca.pem ]]; then
  echo "certs/ déjà en place — rien à faire."
  exit 0
fi

# 1. L'autorité locale, contrainte aux noms en *.localhost : même installée
#    dans un navigateur, elle ne peut signer aucun autre site.
openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
  -keyout certs/ca.key -out certs/ca.pem \
  -subj "/CN=HorRAGor3 Local CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "nameConstraints=critical,permitted;DNS:localhost" 2>/dev/null

# 2. Le certificat du cluster, signé par l'autorité.
openssl req -newkey rsa:2048 -nodes \
  -keyout certs/cluster.key -out certs/cluster.csr \
  -subj "/CN=horragor.localhost" 2>/dev/null
openssl x509 -req -in certs/cluster.csr -days 825 \
  -CA certs/ca.pem -CAkey certs/ca.key -CAcreateserial \
  -out certs/cluster.pem \
  -extfile <(printf "subjectAltName=DNS:horragor.localhost,DNS:api.horragor.localhost,DNS:localhost") 2>/dev/null
rm -f certs/cluster.csr certs/ca.srl

echo "certs/ générés (CA + certificat SAN horragor.localhost, api.horragor.localhost)."
