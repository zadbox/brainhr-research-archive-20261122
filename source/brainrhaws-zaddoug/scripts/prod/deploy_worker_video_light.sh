#!/usr/bin/env bash
set -euo pipefail

AWS_CLI_PROFILE="${AWS_CLI_PROFILE-${AWS_PROFILE-${AWS_DEFAULT_PROFILE-brainrh-sso}}}"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
AWS_REGION="${AWS_REGION:-eu-north-1}"
AWS_INSTANCE_ID="${AWS_INSTANCE_ID:-i-0d2ac4ca5d6bb5ca5}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-406260455536}"
REPOSITORY="brainrh/worker-video"
SHA="${1:-$(git rev-parse HEAD)}"

fail() {
  printf 'light-worker-video-release: %s\n' "$*" >&2
  exit 1
}

[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA: $SHA"
[[ "$AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || fail "invalid AWS account ID"
[[ "$AWS_REGION" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ ]] || fail "invalid AWS region"
[[ "$AWS_INSTANCE_ID" =~ ^i-[0-9a-f]{17}$ ]] || fail "invalid EC2 instance ID"
[[ "$(git branch --show-current)" == main ]] || fail "the active branch must be main"
git fetch origin main --quiet
[[ "$(git rev-parse HEAD)" == "$SHA" ]] || fail "SHA is not local HEAD"
[[ "$(git rev-parse main)" == "$SHA" ]] || fail "SHA is not local main"
[[ "$(git rev-parse origin/main)" == "$SHA" ]] || fail "local main and origin/main are not aligned"

repo_root="$(git rev-parse --show-toplevel)"
script_path="${BASH_SOURCE[0]}"
if [[ "$script_path" == "$repo_root/"* ]]; then
  script_path="${script_path#"$repo_root/"}"
fi
git cat-file -e "$SHA:$script_path" 2>/dev/null || fail "deployment script is not tracked by the candidate SHA"
cmp -s <(git show "$SHA:$script_path") "${BASH_SOURCE[0]}" || fail "deployment script differs from the candidate SHA"

aws_options=(--region "$AWS_REGION")
if [[ -n "$AWS_CLI_PROFILE" ]]; then
  aws_options+=(--profile "$AWS_CLI_PROFILE")
fi

registry="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
tag="sha-$SHA"
digest="$(aws ecr describe-images \
  "${aws_options[@]}" \
  --repository-name "$REPOSITORY" \
  --image-ids "imageTag=$tag" \
  --query 'imageDetails[0].imageDigest' \
  --output text 2>/dev/null || true)"

if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  build_context="$(mktemp -d)"
  cleanup() {
    rm -rf "$build_context"
  }
  trap cleanup EXIT
  git archive "$SHA" | tar -x -C "$build_context"
  aws ecr get-login-password "${aws_options[@]}" | \
    docker login --username AWS --password-stdin "$registry" >/dev/null
  if docker buildx version >/dev/null 2>&1; then
    docker buildx build --pull --push \
      --platform linux/amd64 \
      --provenance=false \
      --file "$build_context/Dockerfile.worker-video" \
      --tag "$registry/$REPOSITORY:$tag" \
      "$build_context"
  else
    docker build --pull \
      --platform linux/amd64 \
      --file "$build_context/Dockerfile.worker-video" \
      --tag "$registry/$REPOSITORY:$tag" \
      "$build_context"
    [[ "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$registry/$REPOSITORY:$tag")" == "linux/amd64" ]] || \
      fail "fallback builder did not produce a linux/amd64 worker-video image"
    docker push "$registry/$REPOSITORY:$tag"
  fi
  digest="$(aws ecr describe-images \
    "${aws_options[@]}" \
    --repository-name "$REPOSITORY" \
    --image-ids "imageTag=$tag" \
    --query 'imageDetails[0].imageDigest' \
    --output text)"
fi

[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "no immutable worker-video image found for $SHA"
image="$registry/$REPOSITORY@$digest"

read -r -d '' remote_script <<'REMOTE' || true
set -euo pipefail
new_image="$1"
aws_region="$2"
[[ "$new_image" == *@sha256:* ]]
docker_config="$(mktemp -d)"
tmp="$(mktemp -d)"
extract_container=''
cleanup() {
  [[ -z "$extract_container" ]] || docker rm -f "$extract_container" >/dev/null 2>&1 || true
  rm -rf "$docker_config" "$tmp"
}
trap cleanup EXIT

registry="${new_image%%/*}"
aws ecr get-login-password --region "$aws_region" | \
  DOCKER_CONFIG="$docker_config" docker login --username AWS --password-stdin "$registry" >/dev/null
DOCKER_CONFIG="$docker_config" docker pull "$new_image" >/dev/null
extract_container="$(docker create "$new_image")"
docker cp "$extract_container:/app/scripts/prod/deploy_worker_video_light_remote.sh" "$tmp/deploy_worker_video_light_remote.sh"
docker rm "$extract_container" >/dev/null
extract_container=''
chmod 0500 "$tmp/deploy_worker_video_light_remote.sh"
"$tmp/deploy_worker_video_light_remote.sh" "$@"
REMOTE

payload="$(printf '%s' "$remote_script" | base64 | tr -d '\n')"
command="printf '%s' '$payload' | base64 --decode | bash -s -- '$image' '$AWS_REGION' '$SHA'"
parameters="$(jq -cn --arg command "$command" '{commands:[$command]}')"
command_id="$(aws ssm send-command \
  "${aws_options[@]}" \
  --instance-ids "$AWS_INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "Light worker-video release $SHA" \
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
grep -q 'worker_recreated=true backend_unchanged=true frontend_unchanged=true caddy_unchanged=true' <<< "$(jq -r '.StandardOutputContent' <<< "$result")" || \
  fail "deployment invariants were not confirmed"

printf 'light-worker-video-release: success sha=%s image=%s command=%s\n' "$SHA" "$image" "$command_id"
