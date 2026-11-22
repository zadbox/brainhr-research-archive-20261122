#!/usr/bin/env bash
set -euo pipefail

AWS_CLI_PROFILE="${AWS_CLI_PROFILE-${AWS_PROFILE-${AWS_DEFAULT_PROFILE-brainrh-sso}}}"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
AWS_REGION="${AWS_REGION:-eu-north-1}"
AWS_INSTANCE_ID="${AWS_INSTANCE_ID:-i-0d2ac4ca5d6bb5ca5}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-406260455536}"
PUBLIC_URL="${PUBLIC_URL:-https://app.brainhr.braingentech.com/}"
REPOSITORY="brainrh/frontend"
SHA="${1:-$(git rev-parse HEAD)}"

fail() {
  printf 'light-frontend-release: %s\n' "$*" >&2
  exit 1
}

[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA: $SHA"
[[ "$AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || fail "invalid AWS account ID"
[[ "$AWS_REGION" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ ]] || fail "invalid AWS region"
[[ "$AWS_INSTANCE_ID" =~ ^i-[0-9a-f]{17}$ ]] || fail "invalid EC2 instance ID"
[[ "$PUBLIC_URL" == "https://app.brainhr.braingentech.com/" ]] || fail "unexpected public URL"
[[ "$(git branch --show-current)" == main ]] || fail "the active branch must be main"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail "tracked worktree changes are present"
git fetch origin main --quiet
[[ "$(git rev-parse HEAD)" == "$SHA" ]] || fail "SHA is not local HEAD"
[[ "$(git rev-parse main)" == "$SHA" ]] || fail "SHA is not local main"
[[ "$(git rev-parse origin/main)" == "$SHA" ]] || fail "local main and origin/main are not aligned"

aws_options=(--region "$AWS_REGION")
if [[ -n "$AWS_CLI_PROFILE" ]]; then
  aws_options+=(--profile "$AWS_CLI_PROFILE")
fi

digest="$(aws ecr describe-images \
  "${aws_options[@]}" \
  --repository-name "$REPOSITORY" \
  --image-ids "imageTag=sha-$SHA" \
  --query 'imageDetails[0].imageDigest' \
  --output text)"
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "no immutable frontend image found for $SHA"
image="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPOSITORY@$digest"

read -r -d '' remote_script <<'REMOTE' || true
set -euo pipefail

exec 9>/var/lock/brainrh-light-frontend-release.lock
flock -n 9 || {
  printf 'light-frontend-release: another frontend deployment is running\n' >&2
  exit 1
}

new_image="$1"
public_url="$2"
aws_region="$3"
container=brainrh-frontend-1

old_image="$(docker inspect --format '{{.Config.Image}}' "$container")"
old_frontend_id="$(docker inspect --format '{{.Id}}' "$container")"
backend_image="$(docker inspect --format '{{.Config.Image}}' brainrh-backend-1)"
worker_image="$(docker inspect --format '{{.Config.Image}}' brainrh-worker-video-1)"
backend_id="$(docker inspect --format '{{.Id}}' brainrh-backend-1)"
worker_id="$(docker inspect --format '{{.Id}}' brainrh-worker-video-1)"
working_dir="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$container")"
config_csv="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$container")"
env_file="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.environment_file" }}' "$container")"
project="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$container")"

[[ -n "$old_image" && -n "$working_dir" && -n "$config_csv" && -n "$project" ]]
[[ "$new_image" == *@sha256:* ]]

IFS=',' read -r -a config_files <<< "$config_csv"
compose_args=()
for config_file in "${config_files[@]}"; do
  if [[ ! -f "$config_file" ]]; then
    # A previous light release adds its temporary override to the Compose
    # labels, then removes that file during cleanup. Ignore only that known
    # ephemeral entry; permanent Compose files still fail closed.
    if [[ "$config_file" == /tmp/*.brainrh-frontend.yml ]]; then
      continue
    fi
    printf 'light-frontend-release: missing compose file %s\n' "$config_file" >&2
    exit 1
  fi
  compose_args+=(--file "$config_file")
done
if [[ -n "$env_file" ]]; then
  [[ -f "$env_file" ]]
  compose_args=(--env-file "$env_file" "${compose_args[@]}")
fi

override="$(mktemp --suffix=.brainrh-frontend.yml)"
docker_config="$(mktemp -d)"
cleanup() {
  rm -f "$override"
  rm -rf "$docker_config"
}
trap cleanup EXIT

write_override() {
  printf 'services:\n  frontend:\n    image: %s\n' "$1" > "$override"
}

compose_frontend() {
  BRAINRH_BACKEND_IMAGE="$backend_image" \
  BRAINRH_FRONTEND_IMAGE="$1" \
  BRAINRH_WORKER_VIDEO_IMAGE="$worker_image" \
    docker compose --project-name "$project" "${compose_args[@]}" --file "$override" up -d --no-deps frontend
}

rollback() {
  printf 'light-frontend-release: verification failed, restoring %s\n' "$old_image" >&2
  write_override "$old_image"
  compose_frontend "$old_image"
  printf 'light-frontend-release: automatic frontend rollback completed\n' >&2
}

registry="${new_image%%/*}"
aws ecr get-login-password --region "$aws_region" | \
  DOCKER_CONFIG="$docker_config" docker login --username AWS --password-stdin "$registry" >/dev/null
DOCKER_CONFIG="$docker_config" docker pull "$new_image" >/dev/null

write_override "$new_image"
if ! compose_frontend "$new_image"; then
  rollback
  exit 1
fi

healthy=false
for _ in {1..30}; do
  current_image="$(docker inspect --format '{{.Config.Image}}' "$container" 2>/dev/null || true)"
  state="$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || true)"
  if [[ "$current_image" == "$new_image" && "$state" == running ]] && curl --fail --silent --show-error --max-time 10 "$public_url" >/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done

if [[ "$healthy" != true ]] || \
   [[ "$(docker inspect --format '{{.Id}}' brainrh-backend-1)" != "$backend_id" ]] || \
   [[ "$(docker inspect --format '{{.Id}}' brainrh-worker-video-1)" != "$worker_id" ]]; then
  rollback
  exit 1
fi

new_frontend_id="$(docker inspect --format '{{.Id}}' "$container")"
[[ "$new_frontend_id" != "$old_frontend_id" ]]
printf 'light-frontend-release: deployed=%s previous=%s frontend_recreated=true backend_unchanged=true worker_unchanged=true\n' "$new_image" "$old_image"
REMOTE

payload="$(printf '%s' "$remote_script" | base64 | tr -d '\n')"
command="printf '%s' '$payload' | base64 --decode | bash -s -- '$image' '$PUBLIC_URL' '$AWS_REGION'"
parameters="$(jq -cn --arg command "$command" '{commands:[$command]}')"
command_id="$(aws ssm send-command \
  "${aws_options[@]}" \
  --instance-ids "$AWS_INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "Light frontend release $SHA" \
  --parameters "$parameters" \
  --query 'Command.CommandId' \
  --output text)"

aws ssm wait command-executed \
  "${aws_options[@]}" \
  --command-id "$command_id" \
  --instance-id "$AWS_INSTANCE_ID" || true

result="$(aws ssm get-command-invocation \
  "${aws_options[@]}" \
  --command-id "$command_id" \
  --instance-id "$AWS_INSTANCE_ID" \
  --output json)"
printf '%s\n' "$result" | jq -r '.StandardOutputContent, .StandardErrorContent'
[[ "$(jq -r '.Status' <<< "$result")" == Success ]] || fail "SSM deployment failed: $command_id"
grep -q 'frontend_recreated=true backend_unchanged=true worker_unchanged=true' <<< "$(jq -r '.StandardOutputContent' <<< "$result")" || \
  fail "deployment invariants were not confirmed"

printf 'light-frontend-release: success sha=%s image=%s command=%s\n' "$SHA" "$image" "$command_id"
