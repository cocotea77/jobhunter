#!/bin/sh
# The backup-restore drill (Step 11).
#
# The rule this script exists for: A BACKUP YOU HAVE NEVER RESTORED IS A
# HOPE, NOT A BACKUP. Railway takes backups of the production database;
# this drill proves, on demand and in CI, that a dump of our schema and
# data actually restores into a working database — extension, tables,
# migration bookmark, and rows all present.
#
# What it does, in order:
#   1. pg_dump the source database to a compressed archive
#   2. drop and recreate a scratch database (jobhunter_drill)
#   3. pg_restore the archive into the scratch database
#   4. compare: alembic bookmark, public table count, and row counts of
#      three representative tables must MATCH the source exactly
#   5. print DRILL PASSED, or fail loudly at the first mismatch (set -e)
#
# Local note: the docker-compose Postgres user is the cluster superuser,
# so createdb/dropdb just work. Run it monthly against a production dump
# too (download from Railway, point SOURCE_URL at a local restore of it).

set -e

SOURCE_URL="${DATABASE_URL:-postgresql://jobhunter:jobhunter@localhost:5432/jobhunter}"
DRILL_DB="jobhunter_drill"
# The scratch database lives on the same server: swap the database name
# in the URL. (Everything after the last "/" is the database.)
SERVER_URL="${SOURCE_URL%/*}"
DRILL_URL="${SERVER_URL}/${DRILL_DB}"
DUMP_FILE="$(mktemp /tmp/jobhunter_drill_XXXXXX)"

echo "[drill] 1/5 dumping source database..."
pg_dump "$SOURCE_URL" --format=custom --file="$DUMP_FILE"

echo "[drill] 2/5 recreating scratch database ${DRILL_DB}..."
psql "${SERVER_URL}/postgres" -q -c "DROP DATABASE IF EXISTS ${DRILL_DB}"
psql "${SERVER_URL}/postgres" -q -c "CREATE DATABASE ${DRILL_DB}"

echo "[drill] 3/5 restoring into ${DRILL_DB}..."
pg_restore --dbname="$DRILL_URL" --no-owner "$DUMP_FILE"

echo "[drill] 4/5 comparing source and restore..."
compare() {
    query="$1"
    label="$2"
    source_value=$(psql "$SOURCE_URL" -tA -c "$query")
    restored_value=$(psql "$DRILL_URL" -tA -c "$query")
    if [ "$source_value" = "$restored_value" ]; then
        echo "  match: ${label} = ${source_value}"
    else
        echo "  MISMATCH: ${label}: source=${source_value} restored=${restored_value}"
        exit 1
    fi
}

compare "SELECT version_num FROM alembic_version" "migration bookmark"
compare "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" "public tables"
compare "SELECT count(*) FROM jobs" "jobs rows"
compare "SELECT count(*) FROM users" "users rows"
compare "SELECT count(*) FROM agent_runs" "agent_runs rows"
compare "SELECT count(*) FROM pg_extension WHERE extname='vector'" "vector extension"

echo "[drill] 5/5 cleaning up..."
psql "${SERVER_URL}/postgres" -q -c "DROP DATABASE ${DRILL_DB}"
rm -f "$DUMP_FILE"

echo "DRILL PASSED: the backup restores into a complete, bookmarked database."
