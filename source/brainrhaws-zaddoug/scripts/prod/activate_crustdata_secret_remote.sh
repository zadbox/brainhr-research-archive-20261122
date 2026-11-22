#!/usr/bin/env bash
set -euo pipefail

parameter_name="${1:?parameter name required}"
expected_version="${2:?parameter version required}"
aws_region="${3:?AWS region required}"
release_sha="${4:?release SHA required}"
public_origin="${5:?public origin required}"

[[ "$parameter_name" == "/brainrh/prod/env/CRUSTDATA_API_KEY" ]]
[[ "$expected_version" =~ ^[1-9][0-9]*$ ]]
[[ "$aws_region" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ ]]
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$public_origin" == "https://app.brainhr.braingentech.com" ]]

install -d -m 0700 /srv/brainrh/releases
exec 9>/srv/brainrh/releases/.runtime.lock
flock -n 9 || {
  printf 'crustdata-secret-activation: another runtime deployment is running\n' >&2
  exit 1
}
exec 8>/var/lock/brainrh-light-frontend-release.lock
flock -n 8 || {
  printf 'crustdata-secret-activation: a frontend deployment is running\n' >&2
  exit 1
}

container=brainrh-backend-1
backend_image="$(docker inspect --format '{{.Config.Image}}' "$container")"
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

[[ "$backend_image" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/brainrh/backend@sha256:[0-9a-f]{64}$ ]]
[[ -n "$working_dir" && -n "$config_csv" && -n "$project" ]]
if [[ -z "$env_file" ]]; then
  env_file="$working_dir/.env.prod"
fi
[[ -f "$env_file" && ! -L "$env_file" ]]

IFS=',' read -r -a config_files <<< "$config_csv"
compose_args=(--env-file "$env_file")
for config_file in "${config_files[@]}"; do
  if [[ ! -f "$config_file" ]]; then
    if [[ "$config_file" == /tmp/*.brainrh-frontend.yml || \
          "$config_file" == /tmp/*.brainrh-backend.yml || \
          "$config_file" == /tmp/*.brainrh-worker-video.yml ]]; then
      continue
    fi
    printf 'crustdata-secret-activation: missing compose file %s\n' "$config_file" >&2
    exit 1
  fi
  compose_args+=(--file "$config_file")
done

parameter_json="$(aws ssm get-parameter \
  --region "$aws_region" \
  --name "$parameter_name" \
  --with-decryption \
  --output json)"
parameter_type="$(jq -r '.Parameter.Type' <<< "$parameter_json")"
parameter_version="$(jq -r '.Parameter.Version' <<< "$parameter_json")"
secret="$(jq -r '.Parameter.Value' <<< "$parameter_json")"
unset parameter_json

[[ "$parameter_type" == SecureString ]]
[[ "$parameter_version" == "$expected_version" ]]
[[ ${#secret} -ge 20 ]]
[[ "$secret" =~ ^[A-Za-z0-9._-]+$ ]]

secret_hash="$(printf '%s' "$secret" | sha256sum | cut -d ' ' -f 1)"
current_secret=''
current_count=0
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" == CRUSTDATA_API_KEY=* ]]; then
    current_count=$((current_count + 1))
    if [[ $current_count -eq 1 ]]; then
      current_secret="${line#CRUSTDATA_API_KEY=}"
    fi
  fi
done < "$env_file"

container_secret_hash="$(docker exec "$container" python -c \
  'import hashlib, os; print(hashlib.sha256(os.environ.get("CRUSTDATA_API_KEY", "").encode()).hexdigest())')"

env_changed=false
backend_recreated=false
rollback_file=''
override=''
replacement=''

cleanup() {
  unset secret current_secret
  [[ -z "$rollback_file" ]] || rm -f "$rollback_file"
  [[ -z "$override" ]] || rm -f "$override"
  [[ -z "$replacement" ]] || rm -f "$replacement"
}
trap cleanup EXIT

write_override() {
  printf 'services:\n  backend:\n    image: %s\n' "$backend_image" > "$override"
}

compose_backend() {
  BRAINRH_BACKEND_IMAGE="$backend_image" \
  BRAINRH_FRONTEND_IMAGE="$frontend_image" \
  BRAINRH_WORKER_VIDEO_IMAGE="$worker_image" \
    docker compose --project-name "$project" "${compose_args[@]}" --file "$override" \
      up -d --no-build --force-recreate --no-deps backend
}

unchanged_services() {
  [[ "$(docker inspect --format '{{.Id}}' brainrh-frontend-1)" == "$frontend_id" ]] && \
    [[ "$(docker inspect --format '{{.Id}}' brainrh-worker-video-1)" == "$worker_id" ]] && \
    [[ "$(docker inspect --format '{{.Id}}' brainrh-caddy-1)" == "$caddy_id" ]]
}

wait_backend() {
  local require_secret="${1:-true}" current_image state runtime_hash
  for _ in {1..45}; do
    current_image="$(docker inspect --format '{{.Config.Image}}' "$container" 2>/dev/null || true)"
    state="$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || true)"
    runtime_hash="$(docker exec "$container" python -c \
      'import hashlib, os; print(hashlib.sha256(os.environ.get("CRUSTDATA_API_KEY", "").encode()).hexdigest())' \
      2>/dev/null || true)"
    if [[ "$current_image" == "$backend_image" && "$state" == running ]] && \
       docker exec "$container" python -c \
         "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=10)); assert d['status']=='ok'; assert d['database']['status']=='ok'" \
         >/dev/null 2>&1 && \
       curl --fail --silent --show-error --max-time 15 "$public_origin/health/ready" >/dev/null && \
       unchanged_services; then
      if [[ "$require_secret" != true || "$runtime_hash" == "$secret_hash" ]]; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

rollback() {
  printf 'crustdata-secret-activation: verification failed, restoring previous runtime environment\n' >&2
  if [[ "$env_changed" == true && -f "$rollback_file" ]]; then
    mv -f "$rollback_file" "$env_file"
    rollback_file=''
  fi
  write_override
  if compose_backend && wait_backend false; then
    printf 'crustdata-secret-activation: automatic rollback completed\n' >&2
    return 0
  fi
  printf 'crustdata-secret-activation: AUTOMATIC_ROLLBACK_FAILED\n' >&2
  return 1
}

if [[ $current_count -ne 1 || "$current_secret" != "$secret" ]]; then
  env_dir="$(dirname "$env_file")"
  rollback_file="$(mktemp "$env_dir/.env.prod.crustdata.rollback.XXXXXX")"
  cp --preserve=all "$env_file" "$rollback_file"
  replacement="$(mktemp "$env_dir/.env.prod.crustdata.next.XXXXXX")"
  found=false
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == CRUSTDATA_API_KEY=* ]]; then
      if [[ "$found" == false ]]; then
        printf 'CRUSTDATA_API_KEY=%s\n' "$secret" >> "$replacement"
        found=true
      fi
    else
      printf '%s\n' "$line" >> "$replacement"
    fi
  done < "$env_file"
  if [[ "$found" == false ]]; then
    printf 'CRUSTDATA_API_KEY=%s\n' "$secret" >> "$replacement"
  fi
  chown --reference="$env_file" "$replacement"
  chmod --reference="$env_file" "$replacement"
  mv -f "$replacement" "$env_file"
  replacement=''
  env_changed=true
fi

if [[ "$env_changed" == true || "$container_secret_hash" != "$secret_hash" ]]; then
  override="$(mktemp --suffix=.brainrh-backend.yml)"
  write_override
  if ! compose_backend || ! wait_backend true; then
    rollback || true
    exit 1
  fi
  new_backend_id="$(docker inspect --format '{{.Id}}' "$container")"
  [[ "$new_backend_id" != "$old_backend_id" ]]
  backend_recreated=true
fi

receipt_dir="/srv/brainrh/releases/$release_sha"
install -d -m 0700 "$receipt_dir"
jq -n \
  --arg sha "$release_sha" \
  --arg parameter "$parameter_name" \
  --argjson parameter_version "$parameter_version" \
  --arg backend_image "$backend_image" \
  --argjson backend_recreated "$backend_recreated" \
  --arg activated_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{sha:$sha,parameter:$parameter,parameter_version:$parameter_version,backend_image:$backend_image,backend_recreated:$backend_recreated,activated_at:$activated_at}' \
  > "$receipt_dir/crustdata-secret-activation.json"
chmod 0600 "$receipt_dir/crustdata-secret-activation.json"

printf 'crustdata-secret-activation: sha=%s parameter=%s version=%s secret_activated=true backend_recreated=%s frontend_unchanged=true worker_unchanged=true caddy_unchanged=true\n' \
  "$release_sha" "$parameter_name" "$parameter_version" "$backend_recreated"
