#!/usr/bin/env bash
set -euo pipefail

SHA="${1:?reviewed origin/main SHA required}"
ID_VERSION="${2:?client ID SSM version required}"
SECRET_VERSION="${3:?client secret SSM version required}"
ENABLED_VERSION="${4:?enabled SSM version required}"
PROXY_VERSION="${5:?trusted proxy SSM version required}"
AWS_CLI_PROFILE="${AWS_CLI_PROFILE-${AWS_PROFILE-${AWS_DEFAULT_PROFILE-brainrh-sso}}}"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
AWS_REGION="${AWS_REGION:-eu-north-1}"
AWS_INSTANCE_ID="${AWS_INSTANCE_ID:-i-0d2ac4ca5d6bb5ca5}"
PUBLIC_ORIGIN="https://app.brainhr.braingentech.com"

fail() { printf 'google-auth-activation: %s\n' "$*" >&2; exit 1; }

[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid SHA'
[[ "$AWS_REGION" == eu-north-1 ]] || fail 'unexpected AWS region'
[[ "$AWS_INSTANCE_ID" =~ ^i-[0-9a-f]{17}$ ]] || fail 'invalid EC2 instance'
for version in "$ID_VERSION" "$SECRET_VERSION" "$ENABLED_VERSION" "$PROXY_VERSION"; do
  [[ "$version" =~ ^[1-9][0-9]*$ ]] || fail 'invalid SSM version'
done
cd "$(git rev-parse --show-toplevel)"
[[ "$(git branch --show-current)" == main ]] || fail 'main must be active'
git fetch origin main --quiet
[[ "$(git rev-parse HEAD)" == "$SHA" ]] || fail 'SHA is not HEAD'
[[ "$(git rev-parse main)" == "$SHA" ]] || fail 'SHA is not local main'
[[ "$(git rev-parse origin/main)" == "$SHA" ]] || fail 'SHA is not current origin/main'

local_script=scripts/prod/activate_google_auth.sh
remote_script=scripts/prod/activate_google_auth_remote.sh
for path in "$local_script" "$remote_script"; do
  git cat-file -e "$SHA:$path" 2>/dev/null || fail "$path is absent from the release SHA"
  cmp -s <(git show "$SHA:$path") "$path" || fail "$path differs from the release SHA"
done

aws_options=(--region "$AWS_REGION")
if [[ -n "$AWS_CLI_PROFILE" ]]; then aws_options+=(--profile "$AWS_CLI_PROFILE"); fi
[[ "$(aws sts get-caller-identity "${aws_options[@]}" --query Account --output text)" == 406260455536 ]] || fail 'unexpected AWS account'

parameter_type() {
  aws ssm get-parameter "${aws_options[@]}" --name "/brainrh/prod/env/$1:$2" \
    --query 'Parameter.Type' --output text
}
[[ "$(parameter_type BRAINRH_GOOGLE_CLIENT_ID "$ID_VERSION")" == String ]] || fail 'client ID must be String'
[[ "$(parameter_type BRAINRH_GOOGLE_CLIENT_SECRET "$SECRET_VERSION")" == SecureString ]] || fail 'client secret must be SecureString'
[[ "$(parameter_type BRAINRH_GOOGLE_AUTH_ENABLED "$ENABLED_VERSION")" == String ]] || fail 'enabled flag must be String'
[[ "$(parameter_type BRAINRH_GOOGLE_TRUSTED_PROXY_CIDRS "$PROXY_VERSION")" == String ]] || fail 'trusted proxy must be String'

digest="$(aws ecr describe-images "${aws_options[@]}" --repository-name brainrh/backend \
  --image-ids "imageTag=sha-$SHA" --query 'imageDetails[0].imageDigest' --output text)"
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'backend image digest missing'
image="406260455536.dkr.ecr.$AWS_REGION.amazonaws.com/brainrh/backend@$digest"

payload="$(git show "$SHA:$remote_script" | base64 | tr -d '\n')"
command="printf '%s' '$payload' | base64 --decode | bash -s -- '$SHA' '$image' '$AWS_REGION' '$PUBLIC_ORIGIN' '$ID_VERSION' '$SECRET_VERSION' '$ENABLED_VERSION' '$PROXY_VERSION'"
parameters="$(jq -cn --arg command "$command" '{commands:[$command]}')"
command_id="$(aws ssm send-command "${aws_options[@]}" \
  --instance-ids "$AWS_INSTANCE_ID" --document-name AWS-RunShellScript \
  --comment "Activate Google OAuth versions $ID_VERSION/$SECRET_VERSION/$ENABLED_VERSION/$PROXY_VERSION for $SHA" \
  --parameters "$parameters" --query 'Command.CommandId' --output text)"

aws ssm wait command-executed "${aws_options[@]}" --command-id "$command_id" --instance-id "$AWS_INSTANCE_ID" || true
result="$(aws ssm get-command-invocation "${aws_options[@]}" \
  --command-id "$command_id" --instance-id "$AWS_INSTANCE_ID" --output json)"
printf '%s\n' "$result" | jq -r '.StandardOutputContent, .StandardErrorContent'
[[ "$(jq -r '.Status' <<< "$result")" == Success ]] || fail "SSM activation failed: $command_id"
grep -q 'enabled=true backend_recreated=true frontend_unchanged=true worker_unchanged=true caddy_unchanged=true' \
  <<< "$(jq -r '.StandardOutputContent' <<< "$result")" || fail 'component invariants not confirmed'
printf 'google-auth-activation: success sha=%s command=%s\n' "$SHA" "$command_id"
