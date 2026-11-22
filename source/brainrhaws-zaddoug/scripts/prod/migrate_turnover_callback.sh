#!/usr/bin/env bash
set -euo pipefail

mode="${1:?--plan, --apply or --rollback required}"
SHA="${2:?reviewed origin/main SHA required}"
case "$mode" in
  --plan) remote_mode=plan ;;
  --apply) remote_mode=apply ;;
  --rollback) remote_mode=rollback ;;
  *) echo 'turnover-callback: invalid mode' >&2; exit 1 ;;
esac
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]]
AWS_CLI_PROFILE="${AWS_CLI_PROFILE-${AWS_PROFILE-${AWS_DEFAULT_PROFILE-brainrh-sso}}}"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
AWS_REGION="${AWS_REGION:-eu-north-1}"
AWS_INSTANCE_ID="${AWS_INSTANCE_ID:-i-0d2ac4ca5d6bb5ca5}"
[[ "$AWS_REGION" == eu-north-1 && "$AWS_INSTANCE_ID" == i-0d2ac4ca5d6bb5ca5 ]]

fail() { printf 'turnover-callback: %s\n' "$*" >&2; exit 1; }
cd "$(git rev-parse --show-toplevel)"
[[ "$(git branch --show-current)" == main ]] || fail 'main must be active'
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail 'tracked changes present'
git fetch origin main --quiet
[[ "$(git rev-parse HEAD)" == "$SHA" && "$(git rev-parse origin/main)" == "$SHA" ]] || fail 'SHA is not current origin/main'
for path in scripts/prod/migrate_turnover_callback.sh scripts/prod/migrate_turnover_callback_remote.py; do
  git cat-file -e "$SHA:$path" || fail "$path is absent from candidate SHA"
  cmp -s <(git show "$SHA:$path") "$path" || fail "$path differs from candidate SHA"
done

aws_options=(--profile "$AWS_CLI_PROFILE" --region "$AWS_REGION")
[[ "$(aws sts get-caller-identity "${aws_options[@]}" --query Account --output text)" == 406260455536 ]] || fail 'unexpected AWS account'
payload="$(git show "$SHA:scripts/prod/migrate_turnover_callback_remote.py" | base64 | tr -d '\n')"
command="exec 9>/srv/brainrh/releases/.runtime.lock; flock -n 9 || exit 1; printf '%s' '$payload' | base64 --decode | docker exec -i brainrh-backend-1 python - '$remote_mode'"
parameters="$(jq -cn --arg command "$command" '{commands:[$command]}')"
command_id="$(aws ssm send-command "${aws_options[@]}" --instance-ids "$AWS_INSTANCE_ID" \
  --document-name AWS-RunShellScript --comment "Turnover callback $remote_mode $SHA" \
  --parameters "$parameters" --query 'Command.CommandId' --output text)"
result=''
for _ in {1..60}; do
  if result="$(aws ssm get-command-invocation "${aws_options[@]}" --command-id "$command_id" --instance-id "$AWS_INSTANCE_ID" --output json 2>/dev/null)"; then
    case "$(jq -r '.Status' <<< "$result")" in
      Success|Failed|Cancelled|TimedOut) break ;;
    esac
  fi
  sleep 5
done
[[ -n "$result" ]] || fail "no SSM result for $command_id"
printf '%s\n' "$result" | jq -r '.StandardOutputContent, .StandardErrorContent'
[[ "$(jq -r '.Status' <<< "$result")" == Success ]] || fail "SSM $remote_mode failed: $command_id"
case "$remote_mode" in
  plan) grep -q 'plan ready' <<< "$(jq -r '.StandardOutputContent' <<< "$result")" ;;
  apply|rollback) grep -q "$remote_mode success" <<< "$(jq -r '.StandardOutputContent' <<< "$result")" ;;
esac || fail 'expected provider migration verdict missing'
printf 'turnover-callback: %s complete sha=%s command=%s\n' "$remote_mode" "$SHA" "$command_id"
