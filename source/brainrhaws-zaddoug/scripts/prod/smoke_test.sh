#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.prod}"

source "$ROOT_DIR/scripts/prod/load_env.sh" "$ENV_FILE"

require_command curl /usr/bin/python3
require_env PUBLIC_API_BASE_URL
require_http_url PUBLIC_API_BASE_URL

BASE_URL="${SMOKE_BASE_URL:-${FRONTEND_URL:-${PUBLIC_API_BASE_URL}}}"
API_URL="${PUBLIC_API_BASE_URL}"
SMOKE_EXPECT_ENV="${SMOKE_EXPECT_ENV:-${BRAINRH_ENV:-}}"
CURL_FLAGS=(
  --fail
  --show-error
  --silent
  --connect-timeout "${SMOKE_CONNECT_TIMEOUT_SECONDS:-5}"
  --max-time "${SMOKE_MAX_TIME_SECONDS:-30}"
  --retry "${SMOKE_RETRIES:-2}"
  --retry-delay "${SMOKE_RETRY_DELAY_SECONDS:-2}"
  --retry-connrefused
)
TMP_FILES=()

require_http_url_value BASE_URL "$BASE_URL"

build_fallback_base_url() {
  /usr/bin/python3 - <<'PY'
import os
from urllib.parse import urlsplit

frontend = (os.getenv("FRONTEND_URL") or "").strip()
api = (os.getenv("PUBLIC_API_BASE_URL") or "").strip()
cookie_secure = (os.getenv("AUTH_COOKIE_SECURE") or "").strip().lower() in {"1", "true", "yes", "on"}

if not frontend or not api:
    print("")
    raise SystemExit(0)

front = urlsplit(frontend)
api_url = urlsplit(api)
if front.hostname != api_url.hostname:
    print("")
    raise SystemExit(0)

if cookie_secure:
    print("")
    raise SystemExit(0)

if front.scheme == "https" and api_url.scheme == "http":
    print(f"{api_url.scheme}://{api_url.netloc}")
    raise SystemExit(0)

print("")
PY
}

FALLBACK_BASE_URL="$(build_fallback_base_url)"

cleanup() {
  if (( ${#TMP_FILES[@]} > 0 )); then
    rm -f "${TMP_FILES[@]}"
  fi
}
trap cleanup EXIT

mktemp_tracked() {
  local path
  path="$(mktemp)"
  TMP_FILES+=("$path")
  echo "$path"
}

echo "Smoke: health"
HEALTH_PAYLOAD="$(mktemp_tracked)"
curl "${CURL_FLAGS[@]}" -o "$HEALTH_PAYLOAD" "${API_URL%/}/health/ready"
/usr/bin/python3 - "$HEALTH_PAYLOAD" "$SMOKE_EXPECT_ENV" <<'PY'
import json
import sys

payload_path, expected_env = sys.argv[1], sys.argv[2]
with open(payload_path, encoding="utf-8") as handle:
    payload = json.load(handle)

errors = []
if payload.get("status") != "ok":
    errors.append(f"health status={payload.get('status')!r}")
database = payload.get("database") or {}
if database.get("status") != "ok":
    errors.append(f"database status={database.get('status')!r}")
runtime = payload.get("runtime") or {}
if runtime and runtime.get("status") != "ok":
    errors.append(f"runtime status={runtime.get('status')!r}")
if expected_env and payload.get("environment") != expected_env:
    errors.append(f"environment={payload.get('environment')!r}, expected={expected_env!r}")

if errors:
    raise SystemExit("Health smoke failed: " + "; ".join(errors))

print(
    "Health ok: "
    f"env={payload.get('environment')} "
    f"db={database.get('backend')} "
    f"runtime={runtime.get('status', 'not-reported')}"
)
PY

echo "Smoke: homepage"
if ! curl "${CURL_FLAGS[@]}" -o /dev/null "${BASE_URL%/}/"; then
  if [[ -n "$FALLBACK_BASE_URL" && "$FALLBACK_BASE_URL" != "$BASE_URL" ]]; then
    echo "Smoke: homepage fallback -> ${FALLBACK_BASE_URL%/}/"
    curl "${CURL_FLAGS[@]}" -o /dev/null "${FALLBACK_BASE_URL%/}/"
    BASE_URL="$FALLBACK_BASE_URL"
  else
    exit 1
  fi
fi

if [[ -n "${SMOKE_LOGIN_EMAIL:-}" && -n "${SMOKE_LOGIN_PASSWORD:-}" ]]; then
  COOKIE_JAR="$(mktemp_tracked)"
  LOGIN_PAYLOAD="$(mktemp_tracked)"
  /usr/bin/python3 - "$LOGIN_PAYLOAD" <<'PY'
import json
import os
import sys

payload = {
    "email": os.environ["SMOKE_LOGIN_EMAIL"],
    "password": os.environ["SMOKE_LOGIN_PASSWORD"],
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY

  echo "Smoke: login"
  curl "${CURL_FLAGS[@]}" -c "$COOKIE_JAR" \
    -H 'Content-Type: application/json' \
    -d @"$LOGIN_PAYLOAD" \
    "${API_URL%/}/api/v1/auth/login" >/dev/null

  if [[ -n "${SMOKE_PROJECT_ID:-}" ]]; then
    echo "Smoke: project CV listing"
    curl "${CURL_FLAGS[@]}" -b "$COOKIE_JAR" \
      "${API_URL%/}/api/v1/cvs/projects/${SMOKE_PROJECT_ID}/cvs" >/dev/null
  fi
else
  echo "Smoke: login scenario skipped (SMOKE_LOGIN_EMAIL/SMOKE_LOGIN_PASSWORD missing)"
fi

if [[ "${SMOKE_SKIP_BACKUP_CHECK:-false}" == "true" ]]; then
  echo "Smoke: backup freshness skipped (SMOKE_SKIP_BACKUP_CHECK=true)"
else
  "$ROOT_DIR/scripts/prod/check_recent_backup.sh"
fi
echo "Smoke tests passed."
