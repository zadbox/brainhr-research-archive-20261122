#!/usr/bin/env bash
set -euo pipefail

release_sha="${1:?release SHA required}"
expected_image="${2:?backend image required}"
aws_region="${3:?AWS region required}"
from_version="${4:?From SSM version required}"
provider_version="${5:?provider SSM version required}"
public_origin="https://app.brainhr.braingentech.com"

[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$expected_image" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/brainrh/backend@sha256:[0-9a-f]{64}$ ]]
[[ "$aws_region" == eu-north-1 ]]
[[ "$from_version" =~ ^[1-9][0-9]*$ ]]
[[ "$provider_version" =~ ^[1-9][0-9]*$ ]]

install -d -m 0700 /srv/brainrh/releases
exec 9>/srv/brainrh/releases/.runtime.lock
flock -n 9 || { echo 'ses-invitations-activation: runtime release in progress' >&2; exit 1; }
exec 8>/var/lock/brainrh-light-frontend-release.lock
flock -n 8 || { echo 'ses-invitations-activation: frontend release in progress' >&2; exit 1; }

container=brainrh-backend-1
backend_image="$(docker inspect --format '{{.Config.Image}}' "$container")"
[[ "$backend_image" == "$expected_image" ]]
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
[[ -n "$working_dir" && -n "$config_csv" && -n "$project" ]]
if [[ -z "$env_file" ]]; then env_file="$working_dir/.env.prod"; fi
[[ -f "$env_file" && ! -L "$env_file" ]]

docker exec "$container" python -c '
import os
assert os.environ.get("AWS_REGION") == "eu-north-1"
assert os.environ.get("FRONTEND_URL") == "https://app.brainhr.braingentech.com"
assert os.environ.get("AUTH_COOKIE_SECURE", "").lower() == "true"
'

IFS=',' read -r -a config_files <<< "$config_csv"
compose_args=(--env-file "$env_file")
for config_file in "${config_files[@]}"; do
  if [[ ! -f "$config_file" ]]; then
    if [[ "$config_file" == /tmp/*.brainrh-frontend.yml || "$config_file" == /tmp/*.brainrh-backend.yml || "$config_file" == /tmp/*.brainrh-worker-video.yml ]]; then
      continue
    fi
    echo "ses-invitations-activation: missing compose file $config_file" >&2
    exit 1
  fi
  compose_args+=(--file "$config_file")
done

read_parameter() {
  local name="$1" version="$2" response
  response="$(aws ssm get-parameter --region "$aws_region" --name "/brainrh/prod/env/$name:$version" --output json)"
  [[ "$(jq -r '.Parameter.Type' <<< "$response")" == String ]]
  [[ "$(jq -r '.Parameter.Version' <<< "$response")" == "$version" ]]
  parameter_value="$(jq -r '.Parameter.Value' <<< "$response")"
  unset response
}

read_parameter BRAINRH_INVITATION_FROM_EMAIL "$from_version"
from_address="$parameter_value"
read_parameter BRAINRH_EMAIL_PROVIDER "$provider_version"
email_provider="$parameter_value"
unset parameter_value
[[ "$from_address" == invitations@brainrh.braingentech.com ]]
[[ "$email_provider" == ses ]]

health_before="$(curl --fail --silent --show-error --max-time 15 "$public_origin/health/ready")"
previous_provider="$(jq -r '.runtime.checks.features.email_provider' <<< "$health_before")"
[[ "$previous_provider" == disabled || "$previous_provider" == ses ]]
[[ "$(curl --fail --silent --show-error --max-time 15 "$public_origin/api/v1/auth/google/config" | jq -r '.enabled')" == true ]]
unset health_before

rollback_file=''
replacement=''
override=''
env_changed=false

write_override() { printf 'services:\n  backend:\n    image: %s\n' "$backend_image" > "$override"; }

compose_backend() {
  BRAINRH_BACKEND_IMAGE="$backend_image" \
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
  local expected_provider="$1" current_image state health
  for _ in {1..45}; do
    current_image="$(docker inspect --format '{{.Config.Image}}' "$container" 2>/dev/null || true)"
    state="$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || true)"
    health="$(curl --fail --silent --show-error --max-time 10 "$public_origin/health/ready" 2>/dev/null || true)"
    if [[ "$current_image" == "$backend_image" && "$state" == running ]] &&
       jq -e --arg provider "$expected_provider" \
         '.status == "ok" and .database.status == "ok" and .runtime.checks.features.email_provider == $provider and ($provider != "ses" or .runtime.checks.features.invitation_email_configured == true)' \
         <<< "$health" >/dev/null 2>&1 &&
       [[ "$(curl --fail --silent --show-error --max-time 10 "$public_origin/api/v1/auth/google/config" 2>/dev/null | jq -r '.enabled' 2>/dev/null || true)" == true ]] &&
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
    echo 'ses-invitations-activation: verification failed; restoring previous environment' >&2
    mv -f "$rollback_file" "$env_file"
    rollback_file=''
    if [[ -n "$override" ]] && compose_backend && wait_backend "$previous_provider"; then
      echo 'ses-invitations-activation: backend rollback completed' >&2
    else
      echo 'ses-invitations-activation: AUTOMATIC_ROLLBACK_FAILED' >&2
    fi
  fi
  [[ -z "$rollback_file" ]] || rm -f "$rollback_file"
  [[ -z "$replacement" ]] || rm -f "$replacement"
  [[ -z "$override" ]] || rm -f "$override"
  exit "$result"
}
trap cleanup EXIT

env_dir="$(dirname "$env_file")"
rollback_file="$(mktemp "$env_dir/.env.prod.ses.rollback.XXXXXX")"
cp --preserve=all "$env_file" "$rollback_file"
replacement="$(mktemp "$env_dir/.env.prod.ses.next.XXXXXX")"
while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    BRAINRH_EMAIL_PROVIDER=*|BRAINRH_INVITATION_FROM_EMAIL=*) ;;
    *) printf '%s\n' "$line" >> "$replacement" ;;
  esac
done < "$env_file"
printf 'BRAINRH_INVITATION_FROM_EMAIL=%s\n' "$from_address" >> "$replacement"
printf 'BRAINRH_EMAIL_PROVIDER=%s\n' "$email_provider" >> "$replacement"
chown --reference="$env_file" "$replacement"
chmod --reference="$env_file" "$replacement"
mv -f "$replacement" "$env_file"
replacement=''
env_changed=true
sync -f "$env_file"

override="$(mktemp --suffix=.brainrh-backend.yml)"
write_override
compose_backend
wait_backend ses
[[ "$(docker inspect --format '{{.Id}}' "$container")" != "$old_backend_id" ]]

receipt_dir="/srv/brainrh/releases/$release_sha"
install -d -m 0700 "$receipt_dir"
jq -n --arg sha "$release_sha" --arg image "$backend_image" \
  --argjson from_version "$from_version" --argjson provider_version "$provider_version" \
  --arg activated_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{sha:$sha,backend_image:$image,from_version:$from_version,provider_version:$provider_version,activated_at:$activated_at}' \
  > "$receipt_dir/ses-invitations-activation.json"
chmod 0600 "$receipt_dir/ses-invitations-activation.json"
env_changed=false
echo "ses-invitations-activation: success sha=$release_sha email_provider=ses backend_recreated=true frontend_unchanged=true worker_unchanged=true caddy_unchanged=true"
