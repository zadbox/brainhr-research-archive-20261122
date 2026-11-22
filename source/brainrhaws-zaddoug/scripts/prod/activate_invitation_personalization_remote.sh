#!/usr/bin/env bash
set -euo pipefail

release_sha="${1:?release SHA required}"
new_image="${2:?backend image required}"
aws_region="${3:?AWS region required}"
ttl_version="${4:?SSM TTL version required}"
public_origin="https://app.brainhr.braingentech.com"
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$new_image" =~ ^406260455536\.dkr\.ecr\.eu-north-1\.amazonaws\.com/brainrh/backend@sha256:[0-9a-f]{64}$ ]]
[[ "$aws_region" == eu-north-1 && "$ttl_version" =~ ^[1-9][0-9]*$ ]]

install -d -m 0700 /srv/brainrh/releases
exec 9>/srv/brainrh/releases/.runtime.lock
flock -n 9 || { echo 'invitation-personalization-activation: runtime release in progress' >&2; exit 1; }
exec 8>/var/lock/brainrh-light-frontend-release.lock
flock -n 8 || { echo 'invitation-personalization-activation: frontend release in progress' >&2; exit 1; }

migration_receipt="/srv/brainrh/releases/$release_sha/invitation-names-migration.json"
[[ -f "$migration_receipt" && ! -L "$migration_receipt" ]]
jq -e --arg sha "$release_sha" --arg image "$new_image" \
  '.sha == $sha and .image == $image and .revision == "e1f2a3b4c5d6"' \
  "$migration_receipt" >/dev/null
parameter="$(aws ssm get-parameter --region "$aws_region" \
  --name "/brainrh/prod/env/BRAINRH_INVITATION_TTL_MINUTES:$ttl_version" --output json)"
[[ "$(jq -r '.Parameter.Type' <<< "$parameter")" == String ]]
[[ "$(jq -r '.Parameter.Version' <<< "$parameter")" == "$ttl_version" ]]
[[ "$(jq -r '.Parameter.Value' <<< "$parameter")" == 7200 ]]
unset parameter

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
if [[ -z "$env_file" ]]; then env_file="$working_dir/.env.prod"; fi
[[ -f "$env_file" && ! -L "$env_file" ]]
old_ttl="$(docker exec "$container" python -c 'from brainrh.settings import get_invitation_ttl_minutes; print(get_invitation_ttl_minutes())')"
[[ "$old_ttl" =~ ^[0-9]+$ ]]
health_before="$(curl --fail --silent --show-error --max-time 15 "$public_origin/health/ready")"
old_provider="$(jq -r '.runtime.checks.features.email_provider' <<< "$health_before")"
old_google="$(curl --fail --silent --show-error --max-time 15 "$public_origin/api/v1/auth/google/config" | jq -r '.enabled')"
[[ "$old_provider" == ses && "$old_google" == true ]]
unset health_before

IFS=',' read -r -a config_files <<< "$config_csv"
compose_args=(--env-file "$env_file")
for config_file in "${config_files[@]}"; do
  if [[ ! -f "$config_file" ]]; then
    if [[ "$config_file" == /tmp/*.brainrh-frontend.yml || "$config_file" == /tmp/*.brainrh-backend.yml || "$config_file" == /tmp/*.brainrh-worker-video.yml ]]; then
      continue
    fi
    echo "invitation-personalization-activation: missing compose file $config_file" >&2
    exit 1
  fi
  compose_args+=(--file "$config_file")
done

rollback_file=''
replacement=''
override=''
docker_config=''
env_changed=false

write_override() { printf 'services:\n  backend:\n    image: %s\n' "$1" >"$override"; }
compose_backend() {
  local image="$1"
  BRAINRH_BACKEND_IMAGE="$image" \
  BRAINRH_FRONTEND_IMAGE="$frontend_image" \
  BRAINRH_WORKER_VIDEO_IMAGE="$worker_image" \
    docker compose --project-name "$project" "${compose_args[@]}" --file "$override" \
      up -d --no-build --force-recreate --no-deps backend
}
unchanged_services() {
  [[ "$(docker inspect --format '{{.Id}}' brainrh-frontend-1)" == "$frontend_id" ]] &&
  [[ "$(docker inspect --format '{{.Id}}' brainrh-worker-video-1)" == "$worker_id" ]] &&
  [[ "$(docker inspect --format '{{.Id}}' brainrh-caddy-1)" == "$caddy_id" ]]
}
wait_backend() {
  local expected_image="$1" expected_ttl="$2" image state health ttl
  for _ in {1..45}; do
    image="$(docker inspect --format '{{.Config.Image}}' "$container" 2>/dev/null || true)"
    state="$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || true)"
    health="$(curl --fail --silent --show-error --max-time 10 "$public_origin/health/ready" 2>/dev/null || true)"
    ttl="$(docker exec "$container" python -c 'from brainrh.settings import get_invitation_ttl_minutes; print(get_invitation_ttl_minutes())' 2>/dev/null || true)"
    if [[ "$image" == "$expected_image" && "$state" == running && "$ttl" == "$expected_ttl" ]] &&
       jq -e --arg provider "$old_provider" \
         '.status == "ok" and .database.status == "ok" and .runtime.checks.features.email_provider == $provider and .runtime.checks.features.invitation_email_configured == true' \
         <<< "$health" >/dev/null 2>&1 &&
       [[ "$(curl --fail --silent --show-error --max-time 10 "$public_origin/api/v1/auth/google/config" 2>/dev/null | jq -r '.enabled' 2>/dev/null || true)" == "$old_google" ]] &&
       unchanged_services; then
      return 0
    fi
    sleep 2
  done
  return 1
}
cleanup() {
  local result=$?
  trap - EXIT
  set +e
  if [[ "$result" -ne 0 && "$env_changed" == true && -f "$rollback_file" ]]; then
    echo 'invitation-personalization-activation: restoring previous backend and environment' >&2
    mv -f "$rollback_file" "$env_file"
    rollback_file=''
    if [[ -n "$override" ]] && write_override "$old_image" && compose_backend "$old_image" && wait_backend "$old_image" "$old_ttl"; then
      echo 'invitation-personalization-activation: application rollback completed' >&2
    else
      echo 'invitation-personalization-activation: AUTOMATIC_ROLLBACK_FAILED' >&2
    fi
  elif [[ "$result" -ne 0 && "$env_changed" == false ]]; then
    echo 'invitation-personalization-activation: runtime_unchanged=true' >&2
  fi
  [[ -z "$rollback_file" ]] || rm -f "$rollback_file"
  [[ -z "$replacement" ]] || rm -f "$replacement"
  [[ -z "$override" ]] || rm -f "$override"
  [[ -z "$docker_config" ]] || rm -rf -- "$docker_config"
  exit "$result"
}
trap cleanup EXIT

docker_config="$(mktemp -d)"
registry="${new_image%%/*}"
aws ecr get-login-password --region "$aws_region" | DOCKER_CONFIG="$docker_config" docker login --username AWS --password-stdin "$registry" >/dev/null
DOCKER_CONFIG="$docker_config" docker pull "$new_image" >/dev/null

env_dir="$(dirname "$env_file")"
rollback_file="$(mktemp "$env_dir/.env.prod.invitation.rollback.XXXXXX")"
cp --preserve=all "$env_file" "$rollback_file"
replacement="$(mktemp "$env_dir/.env.prod.invitation.next.XXXXXX")"
while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    BRAINRH_INVITATION_TTL_MINUTES=*) ;;
    *) printf '%s\n' "$line" >>"$replacement" ;;
  esac
done <"$env_file"
printf 'BRAINRH_INVITATION_TTL_MINUTES=7200\n' >>"$replacement"
chown --reference="$env_file" "$replacement"
chmod --reference="$env_file" "$replacement"
mv -f "$replacement" "$env_file"
replacement=''
env_changed=true
sync -f "$env_file"

override="$(mktemp --suffix=.brainrh-backend.yml)"
write_override "$new_image"
compose_backend "$new_image"
wait_backend "$new_image" 7200
[[ "$(docker inspect --format '{{.Id}}' "$container")" != "$old_backend_id" ]]
for filename in brain-b-v1.gif brain-b-v1.png; do
  curl --fail --silent --show-error --max-time 15 \
    "$public_origin/api/v1/auth/invitations/assets/$filename" >/dev/null
done

receipt_dir="/srv/brainrh/releases/$release_sha"
receipt_tmp="$(mktemp "$receipt_dir/.invitation-personalization.XXXXXX")"
jq -n --arg sha "$release_sha" --arg image "$new_image" --arg previous_image "$old_image" \
  --argjson ttl_version "$ttl_version" --argjson previous_ttl "$old_ttl" \
  --arg activated_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{sha:$sha,backend_image:$image,previous_backend_image:$previous_image,ttl_minutes:7200,ttl_parameter_version:$ttl_version,previous_ttl_minutes:$previous_ttl,activated_at:$activated_at}' \
  >"$receipt_tmp"
chmod 0600 "$receipt_tmp"
mv -f "$receipt_tmp" "$receipt_dir/invitation-personalization.json"
sync -f "$receipt_dir/invitation-personalization.json"
env_changed=false
echo "invitation-personalization-activation: sha=$release_sha ttl_minutes=7200 backend_recreated=true frontend_unchanged=true worker_unchanged=true caddy_unchanged=true"
