#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.prod.yml"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.prod}"

source "$ROOT_DIR/scripts/prod/load_env.sh" "$ENV_FILE"
source "$ROOT_DIR/scripts/prod/database_target.sh"

require_command docker aws gzip /usr/bin/python3
require_env DATABASE_URL S3_BUCKET_BACKUPS AWS_REGION
require_local_postgres_service_env_if_needed

BUCKET_VERSIONING="$(
  aws s3api get-bucket-versioning \
    --bucket "$S3_BUCKET_BACKUPS" \
    --query Status \
    --output text \
    --region "$AWS_REGION"
)"
if [[ "$BUCKET_VERSIONING" != "Enabled" ]]; then
  echo "Backup bucket versioning must be Enabled; refusing an unverifiable backup." >&2
  exit 1
fi

CALLER_IDENTITY_FILE="$(mktemp)"
trap 'rm -f "$CALLER_IDENTITY_FILE"' EXIT
aws sts get-caller-identity --output json --region "$AWS_REGION" >"$CALLER_IDENTITY_FILE"
CALLER_ARN="$(
  /usr/bin/python3 -c \
    'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["Arn"])' \
    "$CALLER_IDENTITY_FILE"
)"

ensure_local_postgres_started_if_needed
wait_for_database_ready
LIBPQ_DATABASE_URL="$(database_url_for_libpq)"
export LIBPQ_DATABASE_URL

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR" "$CALLER_IDENTITY_FILE"' EXIT

BACKUP_NAME="postgres-$TIMESTAMP.sql.gz"
BACKUP_FILE="$TMP_DIR/$BACKUP_NAME"
MANIFEST_FILE="$TMP_DIR/$BACKUP_NAME.manifest.json"
SHA_FILE="$TMP_DIR/$BACKUP_NAME.sha256"
DAILY_KEY="postgres/daily/$BACKUP_NAME"
WEEKLY_KEY="postgres/weekly/$BACKUP_NAME"

run_postgres_tools_shell LIBPQ_DATABASE_URL \
  'exec pg_dump --dbname="$LIBPQ_DATABASE_URL" --no-owner --no-privileges' \
  | gzip -9 >"$BACKUP_FILE"

if [[ ! -s "$BACKUP_FILE" ]]; then
  echo "Backup file is empty; refusing upload." >&2
  exit 1
fi

calculate_file_evidence() {
  local path="${1:?path required}"

  /usr/bin/python3 - "$path" <<'PY'
import base64
import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
digest = hashlib.sha256()
with path.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(path.stat().st_size, digest.hexdigest(), base64.b64encode(digest.digest()).decode("ascii"))
PY
}

read -r BACKUP_SIZE BACKUP_SHA256 BACKUP_SHA256_BASE64 < <(
  calculate_file_evidence "$BACKUP_FILE"
)

GIT_COMMIT=""
if git -C "$ROOT_DIR" rev-parse HEAD >/dev/null 2>&1; then
  GIT_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"
fi
RELEASE_COMMIT="${BRAINRH_RELEASE_COMMIT_SHA:-$GIT_COMMIT}"
RELEASE_REF="${BRAINRH_RELEASE_SOURCE_REF:-}"

write_manifest() {
  local object_key="${1:?object key required}"
  local object_version_id="${2:?object version id required}"

  /usr/bin/python3 "$ROOT_DIR/scripts/prod/write_backup_manifest.py" \
    --output "$MANIFEST_FILE" \
    --identity-file "$CALLER_IDENTITY_FILE" \
    --created-at "$TIMESTAMP" \
    --object-key "$object_key" \
    --object-version-id "$object_version_id" \
    --bucket "$S3_BUCKET_BACKUPS" \
    --size-bytes "$BACKUP_SIZE" \
    --sha256 "$BACKUP_SHA256" \
    --database "$(get_database_name)" \
    --release-commit "$RELEASE_COMMIT" \
    --release-ref "$RELEASE_REF"
}

put_versioned_verified_object() {
  local object_key="${1:?object key required}"
  local body_file="${2:?body file required}"
  local expected_size="${3:?expected size required}"
  local expected_sha256="${4:?expected sha256 required}"
  local expected_sha256_base64="${5:?expected base64 sha256 required}"
  local content_type="${6:?content type required}"
  local version_id returned_version_id remote_size remote_checksum remote_metadata

  version_id="$(
    aws s3api put-object \
      --bucket "$S3_BUCKET_BACKUPS" \
      --key "$object_key" \
      --body "$body_file" \
      --content-type "$content_type" \
      --checksum-algorithm SHA256 \
      --checksum-sha256 "$expected_sha256_base64" \
      --metadata "sha256=$expected_sha256" \
      --query VersionId \
      --output text \
      --region "$AWS_REGION"
  )"
  if [[ -z "$version_id" || "$version_id" == "None" ]]; then
    echo "S3 did not return a VersionId for $object_key; refusing incomplete evidence." >&2
    return 1
  fi

  read -r returned_version_id remote_size remote_checksum remote_metadata < <(
    aws s3api head-object \
      --bucket "$S3_BUCKET_BACKUPS" \
      --key "$object_key" \
      --version-id "$version_id" \
      --checksum-mode ENABLED \
      --query '[VersionId,ContentLength,ChecksumSHA256,Metadata.sha256]' \
      --output text \
      --region "$AWS_REGION"
  )
  if [[ "$returned_version_id" != "$version_id" || \
        "$remote_size" != "$expected_size" || \
        "$remote_checksum" != "$expected_sha256_base64" || \
        "$remote_metadata" != "$expected_sha256" ]]; then
    echo "Version-specific S3 evidence mismatch for $object_key." >&2
    return 1
  fi

  printf '%s\n' "$version_id"
}

upload_backup() {
  local object_key="${1:?object key required}"
  local object_version_id manifest_version_id checksum_version_id
  local manifest_size manifest_sha256 manifest_sha256_base64
  local checksum_size checksum_sha256 checksum_sha256_base64
  local evidence_file evidence_dir evidence_tmp

  printf '%s  %s\n' "$BACKUP_SHA256" "$BACKUP_NAME" >"$SHA_FILE"

  object_version_id="$(put_versioned_verified_object \
    "$object_key" "$BACKUP_FILE" "$BACKUP_SIZE" \
    "$BACKUP_SHA256" "$BACKUP_SHA256_BASE64" application/gzip)"

  write_manifest "$object_key" "$object_version_id"
  read -r manifest_size manifest_sha256 manifest_sha256_base64 < <(
    calculate_file_evidence "$MANIFEST_FILE"
  )
  manifest_version_id="$(put_versioned_verified_object \
    "${object_key}.manifest.json" "$MANIFEST_FILE" "$manifest_size" \
    "$manifest_sha256" "$manifest_sha256_base64" application/json)"

  read -r checksum_size checksum_sha256 checksum_sha256_base64 < <(
    calculate_file_evidence "$SHA_FILE"
  )
  checksum_version_id="$(put_versioned_verified_object \
    "${object_key}.sha256" "$SHA_FILE" "$checksum_size" \
    "$checksum_sha256" "$checksum_sha256_base64" text/plain)"

  echo "Backup evidence: dump_key=$object_key dump_version_id=$object_version_id dump_sha256=$BACKUP_SHA256 manifest_version_id=$manifest_version_id manifest_sha256=$manifest_sha256 checksum_version_id=$checksum_version_id checksum_sha256=$checksum_sha256 identity=$CALLER_ARN"

  # One-shot migrations can request a structured receipt without parsing logs.
  if [[ -n "${BRAINRH_BACKUP_EVIDENCE_FILE:-}" && "$object_key" == "$DAILY_KEY" ]]; then
    evidence_file="$BRAINRH_BACKUP_EVIDENCE_FILE"
    evidence_dir="$(dirname "$evidence_file")"
    [[ "$evidence_file" == /* && ! -e "$evidence_file" && -d "$evidence_dir" && ! -L "$evidence_dir" ]]
    evidence_tmp="$(mktemp "$evidence_dir/.backup-evidence.XXXXXX")"
    /usr/bin/python3 - "$evidence_tmp" "$S3_BUCKET_BACKUPS" "$object_key" \
      "$object_version_id" "$manifest_version_id" "$checksum_version_id" \
      "$BACKUP_SIZE" "$BACKUP_SHA256" <<'PY'
import json
import sys
from pathlib import Path

output, bucket, key, dump_version, manifest_version, checksum_version, size, digest = sys.argv[1:]
evidence = {
    "bucket": bucket,
    "dump_key": key,
    "dump_version_id": dump_version,
    "manifest_version_id": manifest_version,
    "checksum_version_id": checksum_version,
    "dump_size_bytes": int(size),
    "dump_sha256": digest,
}
Path(output).write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")
PY
    chmod 0600 "$evidence_tmp"
    mv -f "$evidence_tmp" "$evidence_file"
    sync -f "$evidence_file"
  fi
}

upload_backup "$DAILY_KEY"

if [[ "$(date -u +%u)" == "7" ]]; then
  upload_backup "$WEEKLY_KEY"
fi

echo "Backup uploaded for $TIMESTAMP: s3://${S3_BUCKET_BACKUPS}/${DAILY_KEY} (${BACKUP_SIZE} bytes, sha256=${BACKUP_SHA256})"
