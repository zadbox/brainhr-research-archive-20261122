#!/usr/bin/env bash
set -euo pipefail

release_sha="${1:?current main SHA required}"
base_sha="${2:?base main SHA required}"
aws_cli_profile="${AWS_CLI_PROFILE-${AWS_PROFILE-${AWS_DEFAULT_PROFILE-brainrh-sso}}}"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
aws_region="${AWS_REGION:-eu-north-1}"
instance_id="${AWS_INSTANCE_ID:-i-0d2ac4ca5d6bb5ca5}"
account_id="406260455536"
repository="brainrh/backend"

fail() { printf 'invitation-names-expand: %s\n' "$*" >&2; exit 1; }

[[ "$release_sha" =~ ^[0-9a-f]{40}$ && "$base_sha" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid SHA'
[[ "$aws_region" == eu-north-1 && "$instance_id" == i-0d2ac4ca5d6bb5ca5 ]] || fail 'unexpected AWS target'
cd "$(git rev-parse --show-toplevel)"
[[ "$(git branch --show-current)" == main ]] || fail 'main must be active'
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail 'tracked worktree changes are present'
git fetch origin main --quiet
[[ "$(git rev-parse HEAD)" == "$release_sha" && "$(git rev-parse origin/main)" == "$release_sha" ]] || fail 'release SHA is not current main'
git merge-base --is-ancestor "$base_sha" "$release_sha" || fail 'base SHA is not an ancestor'
changed_migrations="$(git diff --name-only "$base_sha" "$release_sha" -- alembic/versions/)"
[[ "$changed_migrations" == alembic/versions/e1f2a3b4c5d6_add_invitation_recipient_names.py ]] || fail 'unexpected migration tree change'

for path in scripts/prod/expand_invitation_names.sh scripts/prod/expand_invitation_names_remote.sh; do
  git cat-file -e "$release_sha:$path" 2>/dev/null || fail "$path is absent from release SHA"
  cmp -s <(git show "$release_sha:$path") "$path" || fail "$path differs from release SHA"
done

aws_options=(--region "$aws_region")
if [[ -n "$aws_cli_profile" ]]; then aws_options+=(--profile "$aws_cli_profile"); fi
[[ "$(aws sts get-caller-identity "${aws_options[@]}" --query Account --output text)" == "$account_id" ]] || fail 'unexpected AWS account'
rds="$(aws rds describe-db-instances "${aws_options[@]}" --db-instance-identifier brainrh-pilot-postgres --query 'DBInstances[0]' --output json)"
jq -e '.DBInstanceStatus == "available" and .BackupRetentionPeriod > 0 and .LatestRestorableTime != null' <<< "$rds" >/dev/null || fail 'RDS recovery is unavailable'
unset rds

registry="$account_id.dkr.ecr.$aws_region.amazonaws.com"
docker_host="$(docker context inspect "$(docker context show)" --format '{{.Endpoints.docker.Host}}')"
[[ "$docker_host" == unix://* ]] || fail 'unexpected local Docker endpoint'
digest="$(aws ecr describe-images "${aws_options[@]}" --repository-name "$repository" --image-ids "imageTag=sha-$release_sha" --query 'imageDetails[0].imageDigest' --output text 2>/dev/null || true)"
build_context=''
docker_config=''
cleanup() {
  [[ -z "$build_context" ]] || rm -rf -- "$build_context"
  [[ -z "$docker_config" ]] || rm -rf -- "$docker_config"
}
trap cleanup EXIT
if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  build_context="$(mktemp -d)"
  docker_config="$(mktemp -d)"
  git archive "$release_sha" | tar -x -C "$build_context"
  aws ecr get-login-password "${aws_options[@]}" | DOCKER_CONFIG="$docker_config" docker login --username AWS --password-stdin "$registry" >/dev/null
  if docker buildx version >/dev/null 2>&1; then
    DOCKER_CONFIG="$docker_config" DOCKER_HOST="$docker_host" docker buildx build --pull --push --platform linux/amd64 --provenance=false \
      --file "$build_context/Dockerfile" --tag "$registry/$repository:sha-$release_sha" "$build_context"
  else
    DOCKER_HOST="$docker_host" docker build --pull --platform linux/amd64 --file "$build_context/Dockerfile" \
      --tag "$registry/$repository:sha-$release_sha" "$build_context"
    [[ "$(DOCKER_HOST="$docker_host" docker image inspect --format '{{.Os}}/{{.Architecture}}' "$registry/$repository:sha-$release_sha")" == linux/amd64 ]] || fail 'backend image architecture mismatch'
    DOCKER_CONFIG="$docker_config" DOCKER_HOST="$docker_host" docker push "$registry/$repository:sha-$release_sha"
  fi
  digest="$(aws ecr describe-images "${aws_options[@]}" --repository-name "$repository" --image-ids "imageTag=sha-$release_sha" --query 'imageDetails[0].imageDigest' --output text)"
fi
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'immutable backend image missing'
image="$registry/$repository@$digest"
migration_digest="$(git show "$release_sha:alembic/versions/e1f2a3b4c5d6_add_invitation_recipient_names.py" | shasum -a 256 | awk '{print $1}')"
[[ "$migration_digest" =~ ^[0-9a-f]{64}$ ]] || fail 'migration digest missing'
git fetch origin main --quiet
[[ "$(git rev-parse origin/main)" == "$release_sha" ]] || fail 'main advanced during image preparation'

remote_script_digest="$(git show "$release_sha:scripts/prod/expand_invitation_names_remote.sh" | shasum -a 256 | awk '{print $1}')"
read -r -d '' remote_launcher <<'REMOTE' || true
set -euo pipefail
release_sha="$1"
image="$2"
aws_region="$3"
expected_script_digest="$5"
docker_config="$(mktemp -d)"
temporary_dir="$(mktemp -d)"
extract_container=''
cleanup() {
  local result=$?
  trap - EXIT
  [[ -z "$extract_container" ]] || docker rm -f "$extract_container" >/dev/null 2>&1 || true
  rm -rf -- "$docker_config" "$temporary_dir"
  exit "$result"
}
trap cleanup EXIT
registry="${image%%/*}"
aws ecr get-login-password --region "$aws_region" | DOCKER_CONFIG="$docker_config" docker login --username AWS --password-stdin "$registry" >/dev/null
DOCKER_CONFIG="$docker_config" docker pull "$image" >/dev/null
extract_container="$(docker create "$image")"
docker cp "$extract_container:/app/scripts/prod/expand_invitation_names_remote.sh" "$temporary_dir/expand.sh"
docker rm "$extract_container" >/dev/null
extract_container=''
[[ "$(sha256sum "$temporary_dir/expand.sh" | awk '{print $1}')" == "$expected_script_digest" ]]
chmod 0500 "$temporary_dir/expand.sh"
"$temporary_dir/expand.sh" "$1" "$2" "$3" "$4"
REMOTE
payload="$(printf '%s' "$remote_launcher" | base64 | tr -d '\n')"
command="printf '%s' '$payload' | base64 --decode | bash -s -- '$release_sha' '$image' '$aws_region' '$migration_digest' '$remote_script_digest'"
parameters="$(jq -cn --arg command "$command" '{commands:[$command]}')"
command_id="$(aws ssm send-command "${aws_options[@]}" --instance-ids "$instance_id" \
  --document-name AWS-RunShellScript --comment "Expand invitation names $release_sha" \
  --parameters "$parameters" --query 'Command.CommandId' --output text)"
[[ "$command_id" =~ ^[0-9a-f-]{36}$ ]] || fail 'SSM did not return a command ID'
aws ssm wait command-executed "${aws_options[@]}" --command-id "$command_id" --instance-id "$instance_id" || true
result="$(aws ssm get-command-invocation "${aws_options[@]}" --command-id "$command_id" --instance-id "$instance_id" --output json)"
printf '%s\n' "$result" | jq -r '.StandardOutputContent, .StandardErrorContent'
[[ "$(jq -r '.Status' <<< "$result")" == Success ]] || fail "migration failed: $command_id"
grep -q 'migration_upgraded=true backend_unchanged=true frontend_unchanged=true worker_unchanged=true caddy_unchanged=true' \
  <<< "$(jq -r '.StandardOutputContent' <<< "$result")" || fail 'migration invariants not confirmed'
printf 'invitation-names-expand: success sha=%s image=%s command=%s\n' "$release_sha" "$image" "$command_id"
