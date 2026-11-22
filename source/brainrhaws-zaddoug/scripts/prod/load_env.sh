#!/usr/bin/env bash
set -euo pipefail

env_file="${1:?env file required}"

if [[ ! -f "$env_file" ]]; then
  echo "Missing env file: $env_file" >&2
  exit 1
fi

env_exports="$(
  /usr/bin/python3 - "$env_file" <<'PY'
import re
import shlex
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
key_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    if key.startswith("export "):
        key = key[len("export "):].strip()
    if not key_pattern.fullmatch(key):
        raise SystemExit(f"Invalid env var name in {env_path}: {key!r}")
    print(f"export {key}={shlex.quote(value)}")
PY
)"
eval "$env_exports"

require_env() {
  local missing=()
  local name

  for name in "$@"; do
    if [[ -z "${!name:-}" ]]; then
      missing+=("$name")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    echo "Missing required env var(s): ${missing[*]}" >&2
    exit 1
  fi
}

require_command() {
  local name

  for name in "$@"; do
    if ! command -v "$name" >/dev/null 2>&1; then
      echo "Missing required command: $name" >&2
      exit 1
    fi
  done
}

require_http_url_value() {
  local label="${1:?label required}"
  local value="${2:-}"

  if [[ ! "$value" =~ ^https?://[^[:space:]]+$ ]]; then
    echo "$label must be an absolute http(s) URL." >&2
    exit 1
  fi
}

require_http_url() {
  local name

  for name in "$@"; do
    require_http_url_value "$name" "${!name:-}"
  done
}
