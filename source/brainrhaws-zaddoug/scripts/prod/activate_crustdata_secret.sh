#!/usr/bin/env bash
set -euo pipefail

AWS_CLI_PROFILE="${AWS_CLI_PROFILE-${AWS_PROFILE-${AWS_DEFAULT_PROFILE-brainrh-sso}}}"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
AWS_REGION="${AWS_REGION:-eu-north-1}"
AWS_INSTANCE_ID="${AWS_INSTANCE_ID:-i-0d2ac4ca5d6bb5ca5}"
PUBLIC_ORIGIN="${PUBLIC_ORIGIN:-https://app.brainhr.braingentech.com}"
PARAMETER_NAME="/brainrh/prod/env/CRUSTDATA_API_KEY"
SHA="${1:-$(git rev-parse HEAD)}"

fail() {
  printf 'crustdata-secret-activation: %s\n' "$*" >&2
  exit 1
}

[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA: $SHA"
[[ "$AWS_REGION" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ ]] || fail "invalid AWS region"
[[ "$AWS_INSTANCE_ID" =~ ^i-[0-9a-f]{17}$ ]] || fail "invalid EC2 instance ID"
[[ "$PUBLIC_ORIGIN" == "https://app.brainhr.braingentech.com" ]] || fail "unexpected public origin"
[[ "$(git branch --show-current)" == main ]] || fail "the active branch must be main"
git fetch origin main --quiet
[[ "$(git rev-parse HEAD)" == "$SHA" ]] || fail "SHA is not local HEAD"
[[ "$(git rev-parse main)" == "$SHA" ]] || fail "SHA is not local main"
[[ "$(git rev-parse origin/main)" == "$SHA" ]] || fail "local main and origin/main are not aligned"

repo_root="$(git rev-parse --show-toplevel)"
local_script="scripts/prod/activate_crustdata_secret.sh"
remote_script="scripts/prod/activate_crustdata_secret_remote.sh"
for script_path in "$local_script" "$remote_script"; do
  git cat-file -e "$SHA:$script_path" 2>/dev/null || fail "$script_path is not tracked by the candidate SHA"
  cmp -s <(git show "$SHA:$script_path") "$repo_root/$script_path" || \
    fail "$script_path differs from the candidate SHA"
done

aws_options=(--region "$AWS_REGION")
if [[ -n "$AWS_CLI_PROFILE" ]]; then
  aws_options+=(--profile "$AWS_CLI_PROFILE")
fi

read -r parameter_type parameter_version < <(aws ssm get-parameter \
  "${aws_options[@]}" \
  --name "$PARAMETER_NAME" \
  --query 'Parameter.[Type,Version]' \
  --output text)
[[ "$parameter_type" == SecureString ]] || fail "$PARAMETER_NAME is not a SecureString"
[[ "$parameter_version" =~ ^[1-9][0-9]*$ ]] || fail "invalid SSM parameter version"

payload="$(git show "$SHA:$remote_script" | base64 | tr -d '\n')"
command="printf '%s' '$payload' | base64 --decode | bash -s -- '$PARAMETER_NAME' '$parameter_version' '$AWS_REGION' '$SHA' '$PUBLIC_ORIGIN'"
parameters="$(jq -cn --arg command "$command" '{commands:[$command]}')"
command_id="$(aws ssm send-command \
  "${aws_options[@]}" \
  --instance-ids "$AWS_INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "Activate Crustdata secret version $parameter_version for $SHA" \
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
[[ "$(jq -r '.Status' <<< "$result")" == Success ]] || fail "SSM activation failed: $command_id"
grep -q 'secret_activated=true' <<< "$(jq -r '.StandardOutputContent' <<< "$result")" || \
  fail "secret activation was not confirmed"
grep -q 'frontend_unchanged=true worker_unchanged=true caddy_unchanged=true' <<< "$(jq -r '.StandardOutputContent' <<< "$result")" || \
  fail "component invariants were not confirmed"

printf 'crustdata-secret-activation: success sha=%s parameter=%s version=%s command=%s\n' \
  "$SHA" "$PARAMETER_NAME" "$parameter_version" "$command_id"
