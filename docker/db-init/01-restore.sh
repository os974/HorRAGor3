#!/bin/bash
# Premier démarrage du conteneur db (docker-entrypoint-initdb.d) : restaure le
# dump de Supabase produit par scripts/dump_supabase.sh. Ne tourne qu'une fois,
# volume vide ; ensuite la base vit dans le volume nommé db_data.
set -euo pipefail

DUMP=/dump/horragor.dump
if [[ ! -f "$DUMP" ]]; then
  echo "ERREUR : $DUMP introuvable — lancer d'abord ./scripts/dump_supabase.sh" >&2
  exit 1
fi

psql=(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB")

# Le dump est limité au schéma public : l'extension n'y figure pas.
"${psql[@]}" -c "CREATE EXTENSION IF NOT EXISTS vector"

# Le schéma public existe déjà dans une base neuve : on retire son entrée de
# la table des matières pour pouvoir restaurer en --exit-on-error.
pg_restore -l "$DUMP" | grep -v ' SCHEMA - public ' > /tmp/toc.list
pg_restore --exit-on-error --no-owner --no-privileges \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -L /tmp/toc.list "$DUMP"

# L'index HNSW supprimé sur Supabase (quota du plan gratuit) est recréé ici :
# en local, aucune limite de taille ne s'y oppose.
"${psql[@]}" <<'SQL'
SET maintenance_work_mem = '512MB';
CREATE INDEX IF NOT EXISTS movie_embeddings_hnsw
  ON movie_embeddings USING hnsw (embedding vector_cosine_ops);
ANALYZE;
SQL

# Le rôle de l'API Données : lecture seule, requêtes bornées dans le temps.
# Le superutilisateur ne sort jamais de ce conteneur.
"${psql[@]}" -v ro_user="$POSTGRES_RO_USER" -v ro_pass="$POSTGRES_RO_PASSWORD" \
  -v db="$POSTGRES_DB" <<'SQL'
CREATE ROLE :"ro_user" LOGIN PASSWORD :'ro_pass';
GRANT CONNECT ON DATABASE :"db" TO :"ro_user";
GRANT USAGE ON SCHEMA public TO :"ro_user";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"ro_user";
ALTER ROLE :"ro_user" SET default_transaction_read_only = on;
ALTER ROLE :"ro_user" SET statement_timeout = '30s';
SQL

echo "Base HorRAGor restaurée : $("${psql[@]}" -Atc 'select count(*) from movies') films."
