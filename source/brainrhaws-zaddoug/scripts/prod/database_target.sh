#!/usr/bin/env bash

POSTGRES_TOOLS_IMAGE="postgres:16.13-alpine3.22@sha256:caf536ebd910e85473a9f5e2fd1aea360c965c4a911c8555ac1f61b2102006cb"

database_url_field() {
  local field="${1:?field required}"

  database_url_env_field DATABASE_URL "$field"
}

database_url_env_field() {
  local database_url_env_name="${1:?database url environment variable name required}"
  local field="${2:?field required}"

  validate_environment_variable_name "$database_url_env_name"
  if [[ -z "${!database_url_env_name:-}" ]]; then
    echo "Environment variable ${database_url_env_name} must be set and non-empty." >&2
    return 1
  fi

  DATABASE_URL_ENV_NAME="$database_url_env_name" /usr/bin/python3 - "$field" <<'PY'
import os
import sys
from urllib.parse import parse_qs, urlparse

database_url = os.environ[os.environ["DATABASE_URL_ENV_NAME"]]
field = sys.argv[1]
parsed = urlparse(database_url)

values = {
    "host": parsed.hostname or "",
    "database": parsed.path.lstrip("/"),
    "sslmode": (parse_qs(parsed.query).get("sslmode") or [""])[0],
}
print(values.get(field, ""))
PY
}

database_url_for_libpq() {
  normalize_database_url_for_libpq DATABASE_URL
}

normalize_database_url_for_libpq() {
  local database_url_env_name="${1:?database url environment variable name required}"

  validate_environment_variable_name "$database_url_env_name"
  if [[ -z "${!database_url_env_name:-}" ]]; then
    echo "Environment variable ${database_url_env_name} must be set and non-empty." >&2
    return 1
  fi

  DATABASE_URL_ENV_NAME="$database_url_env_name" /usr/bin/python3 - <<'PY'
import os
import sys
from urllib.parse import urlparse, urlunparse

raw_url = os.environ[os.environ["DATABASE_URL_ENV_NAME"]].strip()
parsed = urlparse(raw_url)
scheme = parsed.scheme
if scheme == "postgresql+psycopg":
    scheme = "postgresql"
elif scheme == "postgres+psycopg":
    scheme = "postgres"
print(urlunparse(parsed._replace(scheme=scheme)))
PY
}

validate_environment_variable_name() {
  local env_name="${1:?environment variable name required}"

  if [[ ! "$env_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "Unsafe environment variable name: ${env_name}" >&2
    return 1
  fi
}

get_database_host() {
  database_url_field host
}

get_database_name() {
  database_url_field database
}

get_database_sslmode() {
  database_url_field sslmode
}

is_compose_database() {
  is_compose_database_url_env DATABASE_URL
}

is_compose_database_url_env() {
  local database_url_env_name="${1:?database url environment variable name required}"

  [[ "$(database_url_env_field "$database_url_env_name" host)" == "postgres" ]]
}

database_runtime_mode() {
  if is_compose_database; then
    echo "compose"
  else
    echo "external"
  fi
}

describe_database_target() {
  local host database_name sslmode
  host="$(get_database_host)"
  database_name="$(get_database_name)"
  sslmode="$(get_database_sslmode)"

  if [[ -z "$sslmode" ]]; then
    sslmode="none"
  fi

  printf 'mode=%s host=%s db=%s sslmode=%s' \
    "$(database_runtime_mode)" \
    "${host:-unknown}" \
    "${database_name:-unknown}" \
    "$sslmode"
}

require_local_postgres_service_env_if_needed() {
  if is_compose_database; then
    if [[ "${BRAINRH_ALLOW_LOCAL_POSTGRES:-false}" != "true" ]]; then
      echo "DATABASE_URL targets the local Compose postgres service, which is disabled in production." >&2
      echo "Use the private RDS endpoint. Break-glass use requires BRAINRH_ALLOW_LOCAL_POSTGRES=true." >&2
      return 1
    fi
    require_env POSTGRES_PASSWORD
  fi
}

ensure_local_postgres_started_if_needed() {
  if is_compose_database; then
    require_local_postgres_service_env_if_needed
    if [[ "$(docker inspect --format '{{.State.Status}}' brainrh-postgres-1 2>/dev/null || true)" != "running" ]]; then
      echo "The local break-glass PostgreSQL container is not already running; refusing runtime mutation." >&2
      return 1
    fi
  fi
}

run_postgres_tools_shell() {
  local database_url_env_name="${1:?database url environment variable name required}"
  local script="${2:?script required}"

  validate_environment_variable_name "$database_url_env_name"
  if [[ -z "${!database_url_env_name:-}" ]]; then
    echo "Environment variable ${database_url_env_name} must be set and non-empty." >&2
    return 1
  fi

  if is_compose_database_url_env "$database_url_env_name"; then
    require_local_postgres_service_env_if_needed
    docker run --rm -i --network brainrh_default \
      -e "$database_url_env_name" \
      --entrypoint sh \
      "$POSTGRES_TOOLS_IMAGE" -lc "$script"
    return
  fi

  docker run --rm -i \
    -e "$database_url_env_name" \
    --entrypoint sh \
    "$POSTGRES_TOOLS_IMAGE" -lc "$script"
}

wait_for_database_ready() {
  local attempts="${1:-60}"
  local sleep_seconds="${2:-2}"
  wait_for_database_url_ready DATABASE_URL "$attempts" "$sleep_seconds"
}

wait_for_database_url_ready() {
  local database_url_env_name="${1:?database url environment variable name required}"
  local attempts="${2:-60}"
  local sleep_seconds="${3:-2}"
  local try=1

  BRAINRH_LIBPQ_DATABASE_URL="$(normalize_database_url_for_libpq "$database_url_env_name")"
  export BRAINRH_LIBPQ_DATABASE_URL

  while (( try <= attempts )); do
    if run_postgres_tools_shell BRAINRH_LIBPQ_DATABASE_URL \
      'exec pg_isready --dbname="$BRAINRH_LIBPQ_DATABASE_URL" >/dev/null 2>&1'; then
      return 0
    fi
    sleep "$sleep_seconds"
    ((try += 1))
  done

  echo "Database did not become ready through DATABASE_URL." >&2
  return 1
}
