#!/usr/bin/env bash
set -euo pipefail

release_sha="${1:?current main SHA required}"
aws_cli_profile="${AWS_CLI_PROFILE-${AWS_PROFILE-${AWS_DEFAULT_PROFILE-brainrh-sso}}}"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
aws_region="${AWS_REGION:-eu-north-1}"
instance_id="${AWS_INSTANCE_ID:-i-0d2ac4ca5d6bb5ca5}"
parameter_name="/brainrh/prod/env/BRAINRH_INVITATION_TTL_MINUTES"
target_ttl="7200"
account_id="406260455536"

fail() { printf 'invitation-personalization-activation: %s\n' "$*" >&2; exit 1; }

[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid release SHA'
[[ "$aws_region" == eu-north-1 && "$instance_id" == i-0d2ac4ca5d6bb5ca5 ]] || fail 'unexpected AWS target'
cd "$(git rev-parse --show-toplevel)"
[[ "$(git branch --show-current)" == main ]] || fail 'main must be active'
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail 'tracked worktree changes are present'
git fetch origin main --quiet
[[ "$(git rev-parse HEAD)" == "$release_sha" && "$(git rev-parse origin/main)" == "$release_sha" ]] || fail 'release SHA is not current main'
for path in scripts/prod/activate_invitation_personalization.sh scripts/prod/activate_invitation_personalization_remote.sh; do
  git cat-file -e "$release_sha:$path" 2>/dev/null || fail "$path is absent from release SHA"
  cmp -s <(git show "$release_sha:$path") "$path" || fail "$path differs from release SHA"
done

aws_options=(--region "$aws_region")
if [[ -n "$aws_cli_profile" ]]; then aws_options+=(--profile "$aws_cli_profile"); fi
[[ "$(aws sts get-caller-identity "${aws_options[@]}" --query Account --output text)" == "$account_id" ]] || fail 'unexpected AWS account'
digest="$(aws ecr describe-images "${aws_options[@]}" --repository-name brainrh/backend \
  --image-ids "imageTag=sha-$release_sha" --query 'imageDetails[0].imageDigest' --output text)"
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'immutable backend image missing'
image="$account_id.dkr.ecr.$aws_region.amazonaws.com/brainrh/backend@$digest"

parameter="$(aws ssm get-parameter "${aws_options[@]}" --name "$parameter_name" --output json)"
[[ "$(jq -r '.Parameter.Type' <<< "$parameter")" == String ]] || fail 'TTL parameter must remain String'
previous_ttl="$(jq -r '.Parameter.Value' <<< "$parameter")"
[[ "$previous_ttl" =~ ^[0-9]+$ ]] || fail 'existing TTL must be numeric'
ttl_version="$(jq -r '.Parameter.Version' <<< "$parameter")"
git fetch origin main --quiet
[[ "$(git rev-parse origin/main)" == "$release_sha" ]] || fail 'main advanced before activation'
parameter_changed=false
activation_state=not_started
cleanup() {
  local result=$?
  trap - EXIT
  if [[ "$result" -ne 0 && "$parameter_changed" == true && ( "$activation_state" == not_started || "$activation_state" == rolled_back ) ]]; then
    if aws ssm put-parameter "${aws_options[@]}" --name "$parameter_name" --type String \
      --value "$previous_ttl" --overwrite >/dev/null; then
      echo 'invitation-personalization-activation: SSM TTL restored after failure' >&2
    else
      echo 'invitation-personalization-activation: SSM_TTL_ROLLBACK_FAILED' >&2
    fi
  elif [[ "$result" -ne 0 && "$parameter_changed" == true ]]; then
    echo 'invitation-personalization-activation: remote outcome uncertain; inspect the SSM command before changing TTL again' >&2
  fi
  exit "$result"
}
trap cleanup EXIT
if [[ "$previous_ttl" != "$target_ttl" ]]; then
  parameter_changed=true
  ttl_version="$(aws ssm put-parameter "${aws_options[@]}" --name "$parameter_name" \
    --type String --value "$target_ttl" --overwrite --query Version --output text)"
fi
[[ "$ttl_version" =~ ^[1-9][0-9]*$ ]] || fail 'invalid TTL parameter version'

remote_script_digest="$(git show "$release_sha:scripts/prod/activate_invitation_personalization_remote.sh" | shasum -a 256 | awk '{print $1}')"
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
docker cp "$extract_container:/app/scripts/prod/activate_invitation_personalization_remote.sh" "$temporary_dir/activate.sh"
docker rm "$extract_container" >/dev/null
extract_container=''
[[ "$(sha256sum "$temporary_dir/activate.sh" | awk '{print $1}')" == "$expected_script_digest" ]]
chmod 0500 "$temporary_dir/activate.sh"
"$temporary_dir/activate.sh" "$1" "$2" "$3" "$4"
REMOTE
payload="$(printf '%s' "$remote_launcher" | base64 | tr -d '\n')"
command="printf '%s' '$payload' | base64 --decode | bash -s -- '$release_sha' '$image' '$aws_region' '$ttl_version' '$remote_script_digest'"
parameters="$(jq -cn --arg command "$command" '{commands:[$command]}')"
command_id="$(aws ssm send-command "${aws_options[@]}" --instance-ids "$instance_id" \
  --document-name AWS-RunShellScript --comment "Activate invitation personalization $release_sha" \
  --parameters "$parameters" --query 'Command.CommandId' --output text)"
activation_state=unknown
[[ "$command_id" =~ ^[0-9a-f-]{36}$ ]] || fail 'SSM did not return a command ID'
aws ssm wait command-executed "${aws_options[@]}" --command-id "$command_id" --instance-id "$instance_id" || true
result="$(aws ssm get-command-invocation "${aws_options[@]}" --command-id "$command_id" --instance-id "$instance_id" --output json)"
printf '%s\n' "$result" | jq -r '.StandardOutputContent, .StandardErrorContent'
if [[ "$(jq -r '.Status' <<< "$result")" != Success ]]; then
  if grep -Eq 'application rollback completed|runtime_unchanged=true' \
    <<< "$(jq -r '.StandardOutputContent, .StandardErrorContent' <<< "$result")"; then
    activation_state=rolled_back
  fi
  fail "activation failed: $command_id"
fi
grep -q 'ttl_minutes=7200 backend_recreated=true frontend_unchanged=true worker_unchanged=true caddy_unchanged=true' \
  <<< "$(jq -r '.StandardOutputContent' <<< "$result")" || fail 'activation invariants not confirmed'
activation_state=success
parameter_changed=false
printf 'invitation-personalization-activation: success sha=%s ttl_version=%s image=%s command=%s\n' \
  "$release_sha" "$ttl_version" "$image" "$command_id"
