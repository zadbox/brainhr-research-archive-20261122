#!/usr/bin/env bash
set -euo pipefail

new_image="${1:?new image required}"
aws_region="${2:?AWS region required}"
release_sha="${3:?release SHA required}"

install -d -m 0700 /srv/brainrh/releases
exec 9>/srv/brainrh/releases/.runtime.lock
flock -n 9 || {
  printf 'light-worker-video-release: another runtime deployment is running\n' >&2
  exit 1
}
exec 8>/var/lock/brainrh-light-frontend-release.lock
flock -n 8 || {
  printf 'light-worker-video-release: a frontend deployment is running\n' >&2
  exit 1
}

container=brainrh-worker-video-1
old_image="$(docker inspect --format '{{.Config.Image}}' "$container")"
old_worker_id="$(docker inspect --format '{{.Id}}' "$container")"
backend_image="$(docker inspect --format '{{.Config.Image}}' brainrh-backend-1)"
frontend_image="$(docker inspect --format '{{.Config.Image}}' brainrh-frontend-1)"
backend_id="$(docker inspect --format '{{.Id}}' brainrh-backend-1)"
frontend_id="$(docker inspect --format '{{.Id}}' brainrh-frontend-1)"
caddy_id="$(docker inspect --format '{{.Id}}' brainrh-caddy-1)"
working_dir="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$container")"
config_csv="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$container")"
env_file="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.environment_file" }}' "$container")"
project="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$container")"

[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$aws_region" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ ]]
[[ -n "$old_image" && -n "$working_dir" && -n "$config_csv" && -n "$project" ]]
[[ "$new_image" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/brainrh/worker-video@sha256:[0-9a-f]{64}$ ]]
[[ "$old_image" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/brainrh/worker-video@sha256:[0-9a-f]{64}$ ]]
if [[ -z "$env_file" ]]; then
  env_file="$working_dir/.env.prod"
fi
[[ -f "$env_file" ]]

IFS=',' read -r -a config_files <<< "$config_csv"
compose_args=(--env-file "$env_file")
for config_file in "${config_files[@]}"; do
  if [[ ! -f "$config_file" ]]; then
    if [[ "$config_file" == /tmp/*.brainrh-frontend.yml || \
          "$config_file" == /tmp/*.brainrh-backend.yml || \
          "$config_file" == /tmp/*.brainrh-worker-video.yml ]]; then
      continue
    fi
    printf 'light-worker-video-release: missing compose file %s\n' "$config_file" >&2
    exit 1
  fi
  compose_args+=(--file "$config_file")
done

override="$(mktemp --suffix=.brainrh-worker-video.yml)"
cleanup() {
  rm -f "$override"
}
trap cleanup EXIT

write_override() {
  printf 'services:\n  worker-video:\n    image: %s\n' "$1" > "$override"
}

compose_worker() {
  BRAINRH_BACKEND_IMAGE="$backend_image" \
  BRAINRH_FRONTEND_IMAGE="$frontend_image" \
  BRAINRH_WORKER_VIDEO_IMAGE="$1" \
    docker compose --project-name "$project" "${compose_args[@]}" --file "$override" up -d --no-build --no-deps worker-video
}

unchanged_services() {
  [[ "$(docker inspect --format '{{.Id}}' brainrh-backend-1)" == "$backend_id" ]] && \
    [[ "$(docker inspect --format '{{.Id}}' brainrh-frontend-1)" == "$frontend_id" ]] && \
    [[ "$(docker inspect --format '{{.Id}}' brainrh-caddy-1)" == "$caddy_id" ]]
}

wait_worker() {
  local expected_image="$1" current_image state first_restart_count second_restart_count
  for _ in {1..45}; do
    current_image="$(docker inspect --format '{{.Config.Image}}' "$container" 2>/dev/null || true)"
    state="$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || true)"
    if [[ "$current_image" == "$expected_image" && "$state" == running ]] && \
       docker top "$container" -eo args 2>/dev/null | grep -Fq 'python -m brainrh.worker.cal_video_worker_service'; then
      first_restart_count="$(docker inspect --format '{{.RestartCount}}' "$container")"
      sleep 3
      second_restart_count="$(docker inspect --format '{{.RestartCount}}' "$container" 2>/dev/null || true)"
      if [[ "$first_restart_count" == "$second_restart_count" ]] && unchanged_services; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

rollback() {
  printf 'light-worker-video-release: verification failed, restoring %s\n' "$old_image" >&2
  write_override "$old_image"
  if compose_worker "$old_image" && wait_worker "$old_image"; then
    printf 'light-worker-video-release: automatic worker-video rollback completed\n' >&2
    return 0
  fi
  printf 'light-worker-video-release: AUTOMATIC_ROLLBACK_FAILED\n' >&2
  return 1
}

write_override "$new_image"
if ! compose_worker "$new_image"; then
  rollback || true
  exit 1
fi

if ! wait_worker "$new_image" || ! unchanged_services; then
  rollback || true
  exit 1
fi

new_worker_id="$(docker inspect --format '{{.Id}}' "$container")"
[[ "$new_worker_id" != "$old_worker_id" ]]
printf 'light-worker-video-release: sha=%s deployed=%s previous=%s worker_recreated=true backend_unchanged=true frontend_unchanged=true caddy_unchanged=true\n' \
  "$release_sha" "$new_image" "$old_image"
