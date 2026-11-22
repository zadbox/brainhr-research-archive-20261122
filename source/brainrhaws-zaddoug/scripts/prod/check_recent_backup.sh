#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.prod}"

source "$ROOT_DIR/scripts/prod/load_env.sh" "$ENV_FILE"

require_command aws /usr/bin/python3
require_env S3_BUCKET_BACKUPS AWS_REGION

MAX_AGE_HOURS="${MAX_AGE_HOURS:-36}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
LATEST_JSON="$TMP_DIR/latest-backup.json"

aws s3api list-objects-v2 \
  --bucket "$S3_BUCKET_BACKUPS" \
  --prefix "postgres/daily/" \
  --query "reverse(sort_by(Contents[?ends_with(Key, '.sql.gz')],&LastModified))[0]" \
  --output json \
  --region "$AWS_REGION" >"$LATEST_JSON"

LATEST_KEY="$(
  /usr/bin/python3 - "$LATEST_JSON" "$MAX_AGE_HOURS" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
try:
    max_age_hours = int(sys.argv[2])
except ValueError as exc:
    raise SystemExit("MAX_AGE_HOURS must be an integer.") from exc

if not payload or payload == "None":
    raise SystemExit("No backup found under postgres/daily/.")

key = payload.get("Key")
latest_time = payload.get("LastModified")
size_bytes = int(payload.get("Size") or 0)
if not key or not latest_time:
    raise SystemExit("Latest backup metadata is incomplete.")
if size_bytes <= 0:
    raise SystemExit(f"Latest backup is empty: {key}")

parsed_time = datetime.fromisoformat(str(latest_time).replace("Z", "+00:00"))
if parsed_time.tzinfo is None:
    parsed_time = parsed_time.replace(tzinfo=timezone.utc)
age_hours = int((datetime.now(timezone.utc) - parsed_time.astimezone(timezone.utc)).total_seconds() // 3600)
if age_hours > max_age_hours:
    raise SystemExit(f"Latest backup is too old: {age_hours}h")

print(
    f"Latest backup ok: key={key} age={age_hours}h size={size_bytes} last_modified={latest_time}",
    file=sys.stderr,
)
print(key)
PY
)"

for sidecar in manifest.json sha256; do
  sidecar_size="$(
    aws s3api head-object \
      --bucket "$S3_BUCKET_BACKUPS" \
      --key "${LATEST_KEY}.${sidecar}" \
      --query ContentLength \
      --output text \
      --region "$AWS_REGION"
  )"
  if [[ ! "$sidecar_size" =~ ^[0-9]+$ || "$sidecar_size" -le 0 ]]; then
    echo "Latest backup sidecar is missing or empty: ${LATEST_KEY}.${sidecar}" >&2
    exit 1
  fi
done

echo "Latest backup manifest: s3://${S3_BUCKET_BACKUPS}/${LATEST_KEY}.manifest.json"
