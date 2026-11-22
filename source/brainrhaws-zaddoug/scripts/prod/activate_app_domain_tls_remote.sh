#!/usr/bin/env bash
set -euo pipefail

release_sha="${1:?release SHA required}"
previous_sha="${2:?previous Caddyfile SHA-256 required}"
candidate_sha="${3:?candidate Caddyfile SHA-256 required}"
candidate_base64="${4:?candidate Caddyfile required}"
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$previous_sha" =~ ^[0-9a-f]{64}$ ]]
[[ "$candidate_sha" =~ ^[0-9a-f]{64}$ ]]

install -d -m 0700 /srv/brainrh/releases
exec 9>/srv/brainrh/releases/.runtime.lock
flock -n 9 || { echo 'domain-tls: runtime release in progress' >&2; exit 1; }
exec 8>/var/lock/brainrh-light-frontend-release.lock
flock -n 8 || { echo 'domain-tls: frontend release in progress' >&2; exit 1; }

container=brainrh-caddy-1
caddy_id="$(docker inspect --format '{{.Id}}' "$container")"
backend_id="$(docker inspect --format '{{.Id}}' brainrh-backend-1)"
frontend_id="$(docker inspect --format '{{.Id}}' brainrh-frontend-1)"
worker_id="$(docker inspect --format '{{.Id}}' brainrh-worker-video-1)"
caddyfile="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{.Source}}{{end}}{{end}}' "$container")"
[[ "$caddyfile" == /opt/brainrh/Caddyfile && -f "$caddyfile" && ! -L "$caddyfile" ]]
compose_file="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$container")"
env_file="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.environment_file"}}' "$container")"
project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$container")"
[[ "$compose_file" == /opt/brainrh/docker-compose.prod.yml && "$env_file" == /opt/brainrh/.env.prod && "$project" == brainrh ]]
[[ -f "$compose_file" && -f "$env_file" ]]
backend_image="$(docker inspect --format '{{.Config.Image}}' brainrh-backend-1)"
frontend_image="$(docker inspect --format '{{.Config.Image}}' brainrh-frontend-1)"
worker_image="$(docker inspect --format '{{.Config.Image}}' brainrh-worker-video-1)"
volume_names() {
  docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} {{end}}{{end}}' "$container" |
    tr ' ' '\n' | sed '/^$/d' | sort
}
volumes_before="$(volume_names)"

receipt_dir="/srv/brainrh/releases/$release_sha/domain"
install -d -m 0700 "$receipt_dir"
candidate="$(mktemp "$receipt_dir/Caddyfile.candidate.XXXXXX")"
backup="$receipt_dir/Caddyfile.previous"
cleanup() { rm -f "$candidate"; }
trap cleanup EXIT
printf '%s' "$candidate_base64" | base64 --decode > "$candidate"
[[ "$(sha256sum "$candidate" | cut -d' ' -f1)" == "$candidate_sha" ]]

recreated=false
recreate_caddy() {
  BRAINRH_BACKEND_IMAGE="$backend_image" \
  BRAINRH_FRONTEND_IMAGE="$frontend_image" \
  BRAINRH_WORKER_VIDEO_IMAGE="$worker_image" \
    docker compose --project-name "$project" --env-file "$env_file" --file "$compose_file" \
      up -d --no-deps --no-build --pull never --force-recreate caddy
  recreated=true
}

apply_caddy() {
  local expected_sha="$1" mounted_sha
  mounted_sha="$(docker exec "$container" sha256sum /etc/caddy/Caddyfile | cut -d' ' -f1)"
  if [[ "$mounted_sha" != "$expected_sha" ]]; then
    # A prior atomic host-file replacement can leave the live bind mount on an old inode.
    recreate_caddy || { echo 'domain-tls: Caddy recreation failed' >&2; return 1; }
  else
    docker exec "$container" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile || return 1
  fi
  mounted_sha="$(docker exec "$container" sha256sum /etc/caddy/Caddyfile | cut -d' ' -f1)"
  if [[ "$mounted_sha" != "$expected_sha" ]]; then
    echo 'domain-tls: mounted Caddyfile differs from candidate after activation' >&2
    return 1
  fi
}

rollback() {
  if [[ -f "$backup" ]]; then
    cat "$backup" > "$caddyfile"
    apply_caddy "$previous_sha" || true
  fi
  echo 'domain-tls: validation failed; previous Caddyfile restored' >&2
}

current_sha="$(sha256sum "$caddyfile" | cut -d' ' -f1)"
[[ "$current_sha" == "$previous_sha" || "$current_sha" == "$candidate_sha" ]] ||
  { echo 'domain-tls: unexpected active Caddyfile' >&2; exit 1; }
docker exec -i "$container" caddy validate --config /dev/stdin --adapter caddyfile < "$candidate" >/dev/null
if [[ "$current_sha" == "$previous_sha" ]]; then
  cp --preserve=all "$caddyfile" "$backup"
  chmod 0600 "$backup"
  cat "$candidate" > "$caddyfile"
fi
if ! apply_caddy "$candidate_sha"; then
  rollback
  exit 1
fi

healthy=false
for _ in {1..60}; do
  if curl --fail --silent --show-error --max-time 10 https://brainhr.braingentech.com/health/ready >/dev/null 2>&1 &&
     curl --fail --silent --show-error --max-time 10 https://app.brainhr.braingentech.com/health/ready >/dev/null 2>&1; then
    healthy=true
    break
  fi
  sleep 2
done
if [[ "$healthy" != true ]]; then
  echo 'domain-tls: one or both public HTTPS health checks failed' >&2
  rollback
  exit 1
fi
if [[ "$(docker inspect --format '{{.Id}}' brainrh-backend-1)" != "$backend_id" ]] ||
   [[ "$(docker inspect --format '{{.Id}}' brainrh-frontend-1)" != "$frontend_id" ]] ||
   [[ "$(docker inspect --format '{{.Id}}' brainrh-worker-video-1)" != "$worker_id" ]]; then
  echo 'domain-tls: a non-Caddy container changed' >&2
  rollback
  exit 1
fi
if [[ "$(volume_names)" != "$volumes_before" ]]; then
  echo 'domain-tls: Caddy certificate volumes changed' >&2
  rollback
  exit 1
fi
echo "domain-tls: success sha=$release_sha both_hosts_healthy=true other_containers_unchanged=true caddy_recreated=$recreated previous_caddy_id=$caddy_id"
