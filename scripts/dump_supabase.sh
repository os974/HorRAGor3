#!/usr/bin/env bash
# Extrait la base Supabase (schéma public) vers data/db_init/horragor.dump,
# la matière première du conteneur Postgres du cluster (couche Données
# souveraine du brief). À lancer une fois, puis à chaque rafraîchissement.
#
# Source : SOURCE_DATABASE_URL, ou à défaut DATABASE_URL du .env (Supabase).
# pg_dump tourne DANS l'image du service db : même version majeure que le
# serveur Supabase (PG 17), quel que soit le client installé sur l'hôte.
# L'URL passe par l'environnement du conteneur, jamais en argument visible.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="pgvector/pgvector:0.8.0-pg17"
OUT_DIR="data/db_init"

set -a
# shellcheck disable=SC1091
. ./.env
set +a
SOURCE_URL="${SOURCE_DATABASE_URL:-${DATABASE_URL:?DATABASE_URL absente du .env}}"
# libpq ne connaît pas le schéma SQLAlchemy « postgresql+psycopg:// ».
SOURCE_URL="${SOURCE_URL/postgresql+psycopg:/postgresql:}"
# Base distante : chiffrement exigé.
if [[ "$SOURCE_URL" != *sslmode=* ]]; then
  [[ "$SOURCE_URL" == *\?* ]] && SOURCE_URL+="&sslmode=require" || SOURCE_URL+="?sslmode=require"
fi
# Exportée puis transmise par NOM (-e SOURCE_URL) : le mot de passe
# n'apparaît pas dans les arguments visibles par `ps`.
export SOURCE_URL

mkdir -p "$OUT_DIR"
echo "Dump du schéma public vers $OUT_DIR/horragor.dump…"
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e SOURCE_URL \
  -v "$PWD/$OUT_DIR:/out" \
  "$IMAGE" \
  sh -c 'pg_dump --dbname="$SOURCE_URL" --schema=public --no-owner --no-privileges \
           --no-publications --no-subscriptions --format=custom \
           --file=/out/horragor.dump.tmp && mv /out/horragor.dump.tmp /out/horragor.dump'

echo "OK — $(du -h "$OUT_DIR/horragor.dump" | cut -f1). Prochaine étape :"
echo "  docker compose up -d db   (restauration automatique au premier démarrage)"
