#!/usr/bin/env bash
set -euo pipefail

mode="${1:?apply or rollback required}"
release_sha="${2:?release SHA required}"
new_frontend_image="${3:?frontend image required}"
previous_caddy_sha="${4:?previous Caddyfile SHA-256 required}"
target_caddy_sha="${5:?target Caddyfile SHA-256 required}"
caddy_base64="${6:?target Caddyfile required}"
[[ "$mode" == apply || "$mode" == rollback ]]
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]]
if [[ "$mode" == apply ]]; then
  [[ "$new_frontend_image" =~ ^[0-9]{12}\.dkr\.ecr\.eu-north-1\.amazonaws\.com/brainrh/frontend@sha256:[0-9a-f]{64}$ ]]
fi
[[ "$previous_caddy_sha" =~ ^[0-9a-f]{64}$ && "$target_caddy_sha" =~ ^[0-9a-f]{64}$ ]]

old_origin=https://brainhr.braingentech.com
new_origin=https://app.brainhr.braingentech.com
install -d -m 0700 /srv/brainrh/releases
exec 9>/srv/brainrh/releases/.runtime.lock
flock -n 9 || { echo 'domain-cutover: runtime release in progress' >&2; exit 1; }
exec 8>/var/lock/brainrh-light-frontend-release.lock
flock -n 8 || { echo 'domain-cutover: frontend release in progress' >&2; exit 1; }

backend=brainrh-backend-1
frontend=brainrh-frontend-1
caddy=brainrh-caddy-1
worker=brainrh-worker-video-1
backend_image="$(docker inspect --format '{{.Config.Image}}' "$backend")"
frontend_image="$(docker inspect --format '{{.Config.Image}}' "$frontend")"
worker_image="$(docker inspect --format '{{.Config.Image}}' "$worker")"
caddy_id="$(docker inspect --format '{{.Id}}' "$caddy")"
worker_id="$(docker inspect --format '{{.Id}}' "$worker")"
project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$backend")"
config_csv="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$backend")"
env_file="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.environment_file"}}' "$backend")"
caddyfile="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{.Source}}{{end}}{{end}}' "$caddy")"
[[ "$project" == brainrh && "$env_file" == /opt/brainrh/.env.prod ]]
[[ "$caddyfile" == /opt/brainrh/Caddyfile && -f "$caddyfile" && ! -L "$caddyfile" ]]
[[ -f "$env_file" && ! -L "$env_file" ]]
[[ "$worker_image" == *@sha256:* && "$backend_image" == *@sha256:* && "$frontend_image" == *@sha256:* ]]

IFS=',' read -r -a config_files <<< "$config_csv"
compose_args=(--env-file "$env_file")
for config_file in "${config_files[@]}"; do
  if [[ ! -f "$config_file" ]]; then
    if [[ "$config_file" == /tmp/*.brainrh-frontend.yml ||
          "$config_file" == /tmp/*.brainrh-backend.yml ||
          "$config_file" == /tmp/*.brainrh-worker-video.yml ]]; then
      continue
    fi
    echo "domain-cutover: missing Compose file $config_file" >&2
    exit 1
  fi
  compose_args+=(--file "$config_file")
done

caddy_ip="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$caddy")"
trusted_proxy="$(sed -n 's/^BRAINRH_GOOGLE_TRUSTED_PROXY_CIDRS=//p' "$env_file" | tail -1)"
[[ "$caddy_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ && "$trusted_proxy" == "$caddy_ip/32" ]] ||
  { echo 'domain-cutover: Google trusted proxy no longer matches Caddy' >&2; exit 1; }

receipt_dir="/srv/brainrh/releases/$release_sha/domain-cutover"
install -d -m 0700 "$receipt_dir"
env_backup="$receipt_dir/env.before"
caddy_backup="$receipt_dir/Caddyfile.before"
receipt="$receipt_dir/receipt.json"
candidate="$(mktemp "$receipt_dir/Caddyfile.candidate.XXXXXX")"
override="$(mktemp --suffix=.brainrh-frontend.yml)"
docker_config="$(mktemp -d)"
rollback_needed=false
cleanup() {
  local result=$?
  trap - EXIT
  if [[ "$result" -ne 0 && "$rollback_needed" == true ]]; then
    rollback_runtime || echo 'domain-cutover: AUTOMATIC_ROLLBACK_FAILED' >&2
  fi
  rm -f "$candidate" "$override"
  rm -rf "$docker_config"
  exit "$result"
}
trap cleanup EXIT
printf '%s' "$caddy_base64" | base64 --decode > "$candidate"
[[ "$(sha256sum "$candidate" | cut -d' ' -f1)" == "$target_caddy_sha" ]]
docker exec -i "$caddy" caddy validate --config /dev/stdin --adapter caddyfile < "$candidate" >/dev/null

compose_images() {
  local backend_ref="$1" frontend_ref="$2"
  printf 'services:\n  backend:\n    image: %s\n  frontend:\n    image: %s\n' "$backend_ref" "$frontend_ref" > "$override"
  BRAINRH_BACKEND_IMAGE="$backend_ref" \
  BRAINRH_FRONTEND_IMAGE="$frontend_ref" \
  BRAINRH_WORKER_VIDEO_IMAGE="$worker_image" \
    docker compose --project-name "$project" "${compose_args[@]}" --file "$override" \
      up -d --no-build --pull never --force-recreate --no-deps backend frontend
}

check_backend() {
  local expected_image="$1" origin="$2"
  for _ in {1..45}; do
    if [[ "$(docker inspect --format '{{.Config.Image}}' "$backend" 2>/dev/null || true)" == "$expected_image" ]] &&
       docker exec "$backend" python -c "import json,urllib.request; p=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=5)); assert p['status']=='ok'" >/dev/null 2>&1 &&
       curl --fail --silent --show-error --max-time 10 "$origin/health/ready" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

restore_caddy() {
  cat "$caddy_backup" > "$caddyfile"
  [[ "$(docker exec "$caddy" sha256sum /etc/caddy/Caddyfile | cut -d' ' -f1)" == "$previous_caddy_sha" ]]
  docker exec "$caddy" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
}

rollback_runtime() {
  [[ -f "$env_backup" && -f "$caddy_backup" && -f "$receipt" ]] || return 1
  local old_backend old_frontend
  old_backend="$(jq -r '.backend_image' "$receipt")"
  old_frontend="$(jq -r '.frontend_image' "$receipt")"
  cat "$env_backup" > "$env_file"
  restore_caddy || return 1
  compose_images "$old_backend" "$old_frontend" || return 1
  check_backend "$old_backend" "$old_origin" || return 1
  curl --fail --silent --show-error --max-time 10 "$old_origin/login" >/dev/null
  echo 'domain-cutover: runtime rollback complete; old domain healthy' >&2
}

if [[ "$mode" == rollback ]]; then
  rollback_runtime
  echo "domain-cutover: rollback success sha=$release_sha"
  exit 0
fi

if [[ -f "$receipt" &&
      "$(sha256sum "$caddyfile" | cut -d' ' -f1)" == "$target_caddy_sha" &&
      "$frontend_image" == "$new_frontend_image" ]]; then
  docker exec "$backend" python -c "from brainrh.settings import get_google_auth_config; c=get_google_auth_config(); assert c and c['redirect_uri']=='$new_origin/api/v1/auth/google/callback'"
  curl --fail --silent --show-error --max-time 10 "$new_origin/health/ready" >/dev/null
  [[ "$(curl --silent --show-error --max-time 10 --output /dev/null --write-out '%{http_code}' "$old_origin/login")" == 302 ]]
  echo "domain-cutover: success sha=$release_sha already_applied=true"
  exit 0
fi

[[ "$(sha256sum "$caddyfile" | cut -d' ' -f1)" == "$previous_caddy_sha" ]] ||
  { echo 'domain-cutover: expected dual-host Caddyfile is not active' >&2; exit 1; }
python3 - "$env_file" <<'PY'
import sys
from pathlib import Path
pairs = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        pairs[key] = value.strip().strip('"').strip("'")
old = "https://brainhr.braingentech.com"
assert pairs.get("BRAINRH_DOMAIN") == "brainhr.braingentech.com"
assert all(pairs.get(key) == old for key in ("FRONTEND_URL", "PUBLIC_API_BASE_URL", "CORS_ALLOWED_ORIGINS", "SMOKE_BASE_URL"))
assert pairs.get("AUTH_COOKIE_SECURE", "").lower() == "true"
PY

registry="${new_frontend_image%%/*}"
aws ecr get-login-password --region eu-north-1 |
  DOCKER_CONFIG="$docker_config" docker login --username AWS --password-stdin "$registry" >/dev/null
DOCKER_CONFIG="$docker_config" docker pull "$new_frontend_image" >/dev/null
[[ "$(docker image inspect --format '{{index .Config.Labels "org.brainrh.public-api-origin"}}' "$new_frontend_image")" == "$new_origin" ]] ||
  { echo 'domain-cutover: frontend image was built for another origin' >&2; exit 1; }

if [[ -e "$receipt" ]]; then
  [[ -f "$env_backup" && -f "$caddy_backup" ]]
  [[ "$(jq -r '.backend_image' "$receipt")" == "$backend_image" ]]
  [[ "$(jq -r '.frontend_image' "$receipt")" == "$frontend_image" ]]
  [[ "$(sha256sum "$caddy_backup" | cut -d' ' -f1)" == "$previous_caddy_sha" ]]
else
  cp --preserve=all "$env_file" "$env_backup"
  cp --preserve=all "$caddyfile" "$caddy_backup"
  chmod 0600 "$env_backup" "$caddy_backup"
  jq -n --arg sha "$release_sha" --arg backend_image "$backend_image" \
    --arg frontend_image "$frontend_image" --arg worker_image "$worker_image" \
    --arg new_frontend_image "$new_frontend_image" \
    '{sha:$sha,backend_image:$backend_image,frontend_image:$frontend_image,worker_image:$worker_image,new_frontend_image:$new_frontend_image}' > "$receipt"
  chmod 0600 "$receipt"
fi

python3 - "$env_file" <<'PY'
import os
import sys
import tempfile
from pathlib import Path
path = Path(sys.argv[1])
values = {
    "BRAINRH_DOMAIN": "app.brainhr.braingentech.com",
    "FRONTEND_URL": "https://app.brainhr.braingentech.com",
    "PUBLIC_API_BASE_URL": "https://app.brainhr.braingentech.com",
    "CORS_ALLOWED_ORIGINS": "https://app.brainhr.braingentech.com",
    "AUTH_COOKIE_SECURE": "true",
    "AUTH_COOKIE_DOMAIN": "",
    "SMOKE_BASE_URL": "https://app.brainhr.braingentech.com",
}
original = path.read_text()
seen = set()
lines = []
for line in original.splitlines(keepends=True):
    key = line.split("=", 1)[0] if "=" in line else ""
    if key in values:
        if key not in seen:
            lines.append(f"{key}={values[key]}\n")
            seen.add(key)
    else:
        lines.append(line)
for key, value in values.items():
    if key not in seen:
        lines.append(f"{key}={value}\n")
fd, temporary = tempfile.mkstemp(prefix=".env.prod.domain.", dir=path.parent)
try:
    with os.fdopen(fd, "w") as stream:
        stream.writelines(lines)
        stream.flush()
        os.fsync(stream.fileno())
    st = path.stat()
    os.chown(temporary, st.st_uid, st.st_gid)
    os.chmod(temporary, st.st_mode & 0o777)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
rollback_needed=true
compose_images "$backend_image" "$new_frontend_image"
check_backend "$backend_image" "$new_origin"
[[ "$(docker inspect --format '{{.Config.Image}}' "$frontend")" == "$new_frontend_image" ]]

cat "$candidate" > "$caddyfile"
[[ "$(docker exec "$caddy" sha256sum /etc/caddy/Caddyfile | cut -d' ' -f1)" == "$target_caddy_sha" ]] ||
  { echo 'domain-cutover: Caddy bind mount is stale' >&2; exit 1; }
docker exec "$caddy" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
check_public() {
  curl --fail --silent --show-error --max-time 10 "$new_origin/health/ready" >/dev/null 2>&1 &&
  curl --fail --silent --show-error --max-time 10 "$new_origin/login" >/dev/null 2>&1 &&
  curl --fail --silent --show-error --max-time 10 "$old_origin/health/ready" >/dev/null 2>&1 &&
  [[ "$(curl --silent --show-error --max-time 10 --output /dev/null --write-out '%{http_code}' "$old_origin/login")" == 302 ]]
}
for _ in {1..20}; do
  if check_public; then break; fi
  sleep 2
done
check_public
docker exec "$backend" python -c "from brainrh.settings import get_google_auth_config,get_auth_cookie_domain,get_cors_allowed_origins; c=get_google_auth_config(); assert c and c['redirect_uri']=='$new_origin/api/v1/auth/google/callback'; assert get_auth_cookie_domain() is None; assert get_cors_allowed_origins()==['$new_origin']"
[[ "$(docker inspect --format '{{.Id}}' "$worker")" == "$worker_id" ]]
[[ "$(docker inspect --format '{{.Id}}' "$caddy")" == "$caddy_id" ]]
[[ "$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$caddy")" == "$caddy_ip" ]]
rollback_needed=false
echo "domain-cutover: success sha=$release_sha new_origin_healthy=true old_pages_redirect=true worker_unchanged=true caddy_unchanged=true"
