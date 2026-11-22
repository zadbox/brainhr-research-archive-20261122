#!/usr/bin/env bash
set -euo pipefail

RELEASE_SHA="${1:?current main SHA required}"
BACKEND_SOURCE_SHA="${2:?deployed backend source SHA required}"
AWS_CLI_PROFILE="${AWS_CLI_PROFILE-${AWS_PROFILE-${AWS_DEFAULT_PROFILE-brainrh-sso}}}"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
AWS_REGION="${AWS_REGION:-eu-north-1}"
AWS_INSTANCE_ID="${AWS_INSTANCE_ID:-i-0d2ac4ca5d6bb5ca5}"
FROM_ADDRESS="invitations@brainrh.braingentech.com"
PARAMETER_PREFIX="/brainrh/prod/env"

fail() { printf 'ses-invitations-activation: %s\n' "$*" >&2; exit 1; }

[[ "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid release SHA'
[[ "$BACKEND_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid backend source SHA'
[[ "$AWS_REGION" == eu-north-1 ]] || fail 'unexpected AWS region'
[[ "$AWS_INSTANCE_ID" =~ ^i-[0-9a-f]{17}$ ]] || fail 'invalid EC2 instance'
cd "$(git rev-parse --show-toplevel)"
[[ "$(git branch --show-current)" == main ]] || fail 'main must be active'
git fetch origin main --quiet
[[ "$(git rev-parse HEAD)" == "$RELEASE_SHA" ]] || fail 'release SHA is not HEAD'
[[ "$(git rev-parse origin/main)" == "$RELEASE_SHA" ]] || fail 'release SHA is not origin/main'
git merge-base --is-ancestor "$BACKEND_SOURCE_SHA" "$RELEASE_SHA" || fail 'backend source is not an ancestor'

for path in scripts/prod/activate_ses_invitations.sh scripts/prod/activate_ses_invitations_remote.sh; do
  git cat-file -e "$RELEASE_SHA:$path" 2>/dev/null || fail "$path is absent from the release SHA"
  cmp -s <(git show "$RELEASE_SHA:$path") "$path" || fail "$path differs from the release SHA"
done

aws_options=(--region "$AWS_REGION")
if [[ -n "$AWS_CLI_PROFILE" ]]; then aws_options+=(--profile "$AWS_CLI_PROFILE"); fi
[[ "$(aws sts get-caller-identity "${aws_options[@]}" --query Account --output text)" == 406260455536 ]] || fail 'unexpected AWS account'

identity_status="$(aws sesv2 get-email-identity "${aws_options[@]}" --email-identity brainrh.braingentech.com --query VerificationStatus --output text)"
[[ "$identity_status" == SUCCESS ]] || fail 'SES domain is not verified'
sending_enabled="$(aws sesv2 get-account "${aws_options[@]}" --query SendingEnabled --output text)"
[[ "$sending_enabled" == True ]] || fail 'SES sending is unavailable'

stage_string_parameter() {
  local name="$1" expected_value="$2" current type version
  current="$(aws ssm get-parameter "${aws_options[@]}" --name "$PARAMETER_PREFIX/$name" --output json)"
  type="$(jq -r '.Parameter.Type' <<< "$current")"
  [[ "$type" == String ]] || fail "$name must remain String"
  version="$(jq -r '.Parameter.Version' <<< "$current")"
  if [[ "$(jq -r '.Parameter.Value' <<< "$current")" != "$expected_value" ]]; then
    version="$(aws ssm put-parameter "${aws_options[@]}" --name "$PARAMETER_PREFIX/$name" \
      --type String --value "$expected_value" --overwrite --query Version --output text)"
  fi
  [[ "$version" =~ ^[1-9][0-9]*$ ]] || fail "invalid $name version"
  printf '%s' "$version"
}

from_version="$(stage_string_parameter BRAINRH_INVITATION_FROM_EMAIL "$FROM_ADDRESS")"
provider_version="$(stage_string_parameter BRAINRH_EMAIL_PROVIDER ses)"

digest="$(aws ecr describe-images "${aws_options[@]}" --repository-name brainrh/backend \
  --image-ids "imageTag=sha-$BACKEND_SOURCE_SHA" --query 'imageDetails[0].imageDigest' --output text)"
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'backend image digest missing'
image="406260455536.dkr.ecr.$AWS_REGION.amazonaws.com/brainrh/backend@$digest"

payload="$(git show "$RELEASE_SHA:scripts/prod/activate_ses_invitations_remote.sh" | base64 | tr -d '\n')"
command="printf '%s' '$payload' | base64 --decode | bash -s -- '$RELEASE_SHA' '$image' '$AWS_REGION' '$from_version' '$provider_version'"
parameters="$(jq -cn --arg command "$command" '{commands:[$command]}')"
command_id="$(aws ssm send-command "${aws_options[@]}" --instance-ids "$AWS_INSTANCE_ID" \
  --document-name AWS-RunShellScript --comment "Activate BrainRH SES invitations $RELEASE_SHA" \
  --parameters "$parameters" --query 'Command.CommandId' --output text)"

aws ssm wait command-executed "${aws_options[@]}" --command-id "$command_id" --instance-id "$AWS_INSTANCE_ID" || true
result="$(aws ssm get-command-invocation "${aws_options[@]}" --command-id "$command_id" --instance-id "$AWS_INSTANCE_ID" --output json)"
printf '%s\n' "$result" | jq -r '.StandardOutputContent, .StandardErrorContent'
[[ "$(jq -r '.Status' <<< "$result")" == Success ]] || fail "SSM activation failed: $command_id"
grep -q 'email_provider=ses backend_recreated=true frontend_unchanged=true worker_unchanged=true caddy_unchanged=true' \
  <<< "$(jq -r '.StandardOutputContent' <<< "$result")" || fail 'component invariants not confirmed'
printf 'ses-invitations-activation: success sha=%s from_version=%s provider_version=%s command=%s\n' \
  "$RELEASE_SHA" "$from_version" "$provider_version" "$command_id"
