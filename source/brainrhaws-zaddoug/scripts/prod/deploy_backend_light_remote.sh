#!/usr/bin/env bash
set -euo pipefail

new_image="${1:?new image required}"
public_origin="${2:?public origin required}"
aws_region="${3:?AWS region required}"
release_sha="${4:?release SHA required}"
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]]

install -d -m 0700 /srv/brainrh/releases
exec 9>/srv/brainrh/releases/.runtime.lock
flock -n 9 || {
  printf 'light-backend-release: another backend deployment is running\n' >&2
  exit 1
}
exec 8>/var/lock/brainrh-light-frontend-release.lock
flock -n 8 || {
  printf 'light-backend-release: a frontend deployment is running\n' >&2
  exit 1
}

container=brainrh-backend-1
old_image="$(docker inspect --format '{{.Config.Image}}' "$container")"
old_backend_id="$(docker inspect --format '{{.Id}}' "$container")"
frontend_image="$(docker inspect --format '{{.Config.Image}}' brainrh-frontend-1)"
worker_image="$(docker inspect --format '{{.Config.Image}}' brainrh-worker-video-1)"
frontend_id="$(docker inspect --format '{{.Id}}' brainrh-frontend-1)"
worker_id="$(docker inspect --format '{{.Id}}' brainrh-worker-video-1)"
caddy_id="$(docker inspect --format '{{.Id}}' brainrh-caddy-1)"
working_dir="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$container")"
config_csv="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$container")"
env_file="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.environment_file" }}' "$container")"
project="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$container")"

[[ -n "$old_image" && -n "$working_dir" && -n "$config_csv" && -n "$project" ]]
[[ "$new_image" == *@sha256:* ]]
[[ "$old_image" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/brainrh/backend@sha256:[0-9a-f]{64}$ ]]
if [[ -z "$env_file" ]]; then
  env_file="$working_dir/.env.prod"
fi
[[ -f "$env_file" ]]

IFS=',' read -r -a config_files <<< "$config_csv"
compose_args=(--env-file "$env_file")
for config_file in "${config_files[@]}"; do
  if [[ ! -f "$config_file" ]]; then
    if [[ "$config_file" == /tmp/*.brainrh-frontend.yml || "$config_file" == /tmp/*.brainrh-backend.yml ]]; then
      continue
    fi
    printf 'light-backend-release: missing compose file %s\n' "$config_file" >&2
    exit 1
  fi
  compose_args+=(--file "$config_file")
done

override="$(mktemp --suffix=.brainrh-backend.yml)"
cleanup() {
  rm -f "$override"
}
trap cleanup EXIT

write_override() {
  printf 'services:\n  backend:\n    image: %s\n' "$1" > "$override"
}

compose_backend() {
  BRAINRH_BACKEND_IMAGE="$1" \
  BRAINRH_FRONTEND_IMAGE="$frontend_image" \
  BRAINRH_WORKER_VIDEO_IMAGE="$worker_image" \
    docker compose --project-name "$project" "${compose_args[@]}" --file "$override" up -d --no-deps backend
}

wait_backend() {
  local expected_image="$1" current_image state
  for _ in {1..45}; do
    current_image="$(docker inspect --format '{{.Config.Image}}' "$container" 2>/dev/null || true)"
    state="$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || true)"
    if [[ "$current_image" == "$expected_image" && "$state" == running ]] && \
       docker exec "$container" python -c \
         "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=10)); assert d['status']=='ok'; assert d['database']['status']=='ok'" \
         >/dev/null 2>&1 && \
       curl --fail --silent --show-error --max-time 15 "$public_origin/health/ready" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}

rollback() {
  printf 'light-backend-release: verification failed, restoring %s\n' "$old_image" >&2
  write_override "$old_image"
  if compose_backend "$old_image" && wait_backend "$old_image"; then
    printf 'light-backend-release: automatic backend rollback completed\n' >&2
    return 0
  fi
  printf 'light-backend-release: AUTOMATIC_ROLLBACK_FAILED\n' >&2
  return 1
}

write_override "$new_image"
if ! compose_backend "$new_image"; then
  rollback || true
  exit 1
fi

if ! wait_backend "$new_image" || \
   [[ "$(docker inspect --format '{{.Id}}' brainrh-frontend-1)" != "$frontend_id" ]] || \
   [[ "$(docker inspect --format '{{.Id}}' brainrh-worker-video-1)" != "$worker_id" ]] || \
   [[ "$(docker inspect --format '{{.Id}}' brainrh-caddy-1)" != "$caddy_id" ]]; then
  rollback || true
  exit 1
fi

new_backend_id="$(docker inspect --format '{{.Id}}' "$container")"
[[ "$new_backend_id" != "$old_backend_id" ]]
printf 'light-backend-release: sha=%s deployed=%s previous=%s backend_recreated=true frontend_unchanged=true worker_unchanged=true caddy_unchanged=true\n' \
  "$release_sha" "$new_image" "$old_image"
