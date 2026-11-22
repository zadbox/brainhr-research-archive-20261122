#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.prod.yml"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.prod}"

source "$ROOT_DIR/scripts/prod/load_env.sh" "$ENV_FILE"
source "$ROOT_DIR/scripts/prod/database_target.sh"

require_command aws docker gzip /usr/bin/python3
require_env SOURCE_DATABASE_URL S3_BUCKET_BACKUPS AWS_REGION

LIBPQ_SOURCE_DATABASE_URL="$(normalize_database_url_for_libpq SOURCE_DATABASE_URL)"
export LIBPQ_SOURCE_DATABASE_URL
EXPORT_PREFIX="${EXPORT_PREFIX:-postgres/rds-rehearsal}"

wait_for_database_url_ready SOURCE_DATABASE_URL 60 2

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

BACKUP_NAME="postgres-${TIMESTAMP}.sql.gz"
BACKUP_FILE="$TMP_DIR/$BACKUP_NAME"
MANIFEST_FILE="$TMP_DIR/$BACKUP_NAME.manifest.json"
SHA_FILE="$TMP_DIR/$BACKUP_NAME.sha256"
OBJECT_KEY="${EXPORT_PREFIX%/}/$BACKUP_NAME"

run_postgres_tools_shell LIBPQ_SOURCE_DATABASE_URL \
  'export PGDATABASE="$LIBPQ_SOURCE_DATABASE_URL"; exec pg_dump --no-owner --no-privileges' \
  | gzip -9 >"$BACKUP_FILE"

if [[ ! -s "$BACKUP_FILE" ]]; then
  echo "Export file is empty; refusing upload." >&2
  exit 1
fi

read -r BACKUP_SIZE BACKUP_SHA256 < <(
  /usr/bin/python3 - "$BACKUP_FILE" <<'PY'
import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
digest = hashlib.sha256()
with path.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(path.stat().st_size, digest.hexdigest())
PY
)

/usr/bin/python3 - \
  "$MANIFEST_FILE" \
  "$TIMESTAMP" \
  "$OBJECT_KEY" \
  "$BACKUP_SIZE" \
  "$BACKUP_SHA256" <<'PY'
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

manifest_path = Path(sys.argv[1])
timestamp, object_key, size_bytes, sha256 = sys.argv[2:6]
database_url = os.environ["SOURCE_DATABASE_URL"]
parsed = urlparse(database_url)
manifest = {
    "schema_version": 1,
    "created_at": timestamp,
    "object_key": object_key,
    "database": parsed.path.lstrip("/"),
    "host": parsed.hostname,
    "size_bytes": int(size_bytes),
    "sha256": sha256,
}
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

printf '%s  %s\n' "$BACKUP_SHA256" "$BACKUP_NAME" >"$SHA_FILE"
aws s3 cp "$BACKUP_FILE" "s3://${S3_BUCKET_BACKUPS}/${OBJECT_KEY}" --region "$AWS_REGION" --only-show-errors
aws s3 cp "$MANIFEST_FILE" "s3://${S3_BUCKET_BACKUPS}/${OBJECT_KEY}.manifest.json" --region "$AWS_REGION" --only-show-errors
aws s3 cp "$SHA_FILE" "s3://${S3_BUCKET_BACKUPS}/${OBJECT_KEY}.sha256" --region "$AWS_REGION" --only-show-errors

printf '%s\n' "$OBJECT_KEY"
