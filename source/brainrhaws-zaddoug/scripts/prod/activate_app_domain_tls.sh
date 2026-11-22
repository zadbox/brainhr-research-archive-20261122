#!/usr/bin/env bash
set -euo pipefail

SHA="${1:?reviewed origin/main SHA required}"
AWS_CLI_PROFILE="${AWS_CLI_PROFILE-${AWS_PROFILE-${AWS_DEFAULT_PROFILE-brainrh-sso}}}"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
AWS_REGION="${AWS_REGION:-eu-north-1}"
AWS_INSTANCE_ID="${AWS_INSTANCE_ID:-i-0d2ac4ca5d6bb5ca5}"

fail() { printf 'domain-tls: %s\n' "$*" >&2; exit 1; }
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid SHA'
[[ "$AWS_REGION" == eu-north-1 ]] || fail 'unexpected region'
[[ "$AWS_INSTANCE_ID" == i-0d2ac4ca5d6bb5ca5 ]] || fail 'unexpected instance'
cd "$(git rev-parse --show-toplevel)"
[[ "$(git branch --show-current)" == main ]] || fail 'main must be active'
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail 'tracked changes present'
git fetch origin main --quiet
[[ "$(git rev-parse HEAD)" == "$SHA" && "$(git rev-parse origin/main)" == "$SHA" ]] || fail 'SHA is not current main'

for path in Caddyfile scripts/prod/activate_app_domain_tls.sh scripts/prod/activate_app_domain_tls_remote.sh; do
  git cat-file -e "$SHA:$path" || fail "$path is absent from candidate SHA"
  cmp -s <(git show "$SHA:$path") "$path" || fail "$path differs from candidate SHA"
done
caddy_change="$(git log -1 --format=%H "$SHA" -- Caddyfile)"
[[ -n "$caddy_change" ]] || fail 'Caddyfile history is unavailable'
previous_sha="$(git show "$caddy_change^:Caddyfile" | shasum -a 256 | cut -d' ' -f1)"
candidate_sha="$(shasum -a 256 Caddyfile | cut -d' ' -f1)"
[[ "$previous_sha" != "$candidate_sha" ]] || fail 'Caddyfile has no candidate change'

aws_options=(--profile "$AWS_CLI_PROFILE" --region "$AWS_REGION")
[[ "$(aws sts get-caller-identity "${aws_options[@]}" --query Account --output text)" == 406260455536 ]] || fail 'unexpected AWS account'
candidate_base64="$(git show "$SHA:Caddyfile" | base64 | tr -d '\n')"
remote_base64="$(git show "$SHA:scripts/prod/activate_app_domain_tls_remote.sh" | base64 | tr -d '\n')"
command="printf '%s' '$remote_base64' | base64 --decode | bash -s -- '$SHA' '$previous_sha' '$candidate_sha' '$candidate_base64'"
parameters="$(jq -cn --arg command "$command" '{commands:[$command]}')"
command_id="$(aws ssm send-command "${aws_options[@]}" \
  --instance-ids "$AWS_INSTANCE_ID" --document-name AWS-RunShellScript \
  --comment "Activate app domain HTTPS for $SHA" --parameters "$parameters" \
  --query 'Command.CommandId' --output text)"
aws ssm wait command-executed "${aws_options[@]}" --command-id "$command_id" --instance-id "$AWS_INSTANCE_ID" || true
result="$(aws ssm get-command-invocation "${aws_options[@]}" --command-id "$command_id" --instance-id "$AWS_INSTANCE_ID" --output json)"
printf '%s\n' "$result" | jq -r '.StandardOutputContent, .StandardErrorContent'
[[ "$(jq -r '.Status' <<< "$result")" == Success ]] || fail "SSM activation failed: $command_id"
grep -q 'both_hosts_healthy=true other_containers_unchanged=true' <<< "$(jq -r '.StandardOutputContent' <<< "$result")" || fail 'invariants not confirmed'
printf 'domain-tls: success sha=%s command=%s\n' "$SHA" "$command_id"
