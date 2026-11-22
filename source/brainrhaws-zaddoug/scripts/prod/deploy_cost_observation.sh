#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AWS_CLI_PROFILE="${AWS_CLI_PROFILE-${AWS_PROFILE-${AWS_DEFAULT_PROFILE-brainrh-sso}}}"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
AWS_REGION="${AWS_REGION:-eu-north-1}"
AWS_INSTANCE_ID="${AWS_INSTANCE_ID:-i-0d2ac4ca5d6bb5ca5}"
AWS_RDS_INSTANCE_ID="${AWS_RDS_INSTANCE_ID:-brainrh-pilot-postgres}"
SHA="${1:-$(git -C "$ROOT_DIR" rev-parse HEAD)}"

fail() {
  printf 'cost-observation-release: %s\n' "$*" >&2
  exit 1
}

[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA: $SHA"
[[ "$AWS_REGION" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ ]] || fail "invalid AWS region"
[[ "$AWS_INSTANCE_ID" =~ ^i-[0-9a-f]{17}$ ]] || fail "invalid EC2 instance ID"
[[ "$AWS_RDS_INSTANCE_ID" =~ ^[a-z][a-z0-9-]{0,62}$ ]] || fail "invalid RDS instance ID"
[[ "$(git -C "$ROOT_DIR" branch --show-current)" == main ]] || fail "the active branch must be main"
[[ -z "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=no)" ]] || \
  fail "tracked worktree changes are present"

for required_command in aws base64 git gzip jq tar; do
  command -v "$required_command" >/dev/null 2>&1 || fail "missing command: $required_command"
done

git -C "$ROOT_DIR" fetch origin main --quiet
[[ "$(git -C "$ROOT_DIR" rev-parse HEAD)" == "$SHA" ]] || fail "SHA is not local HEAD"
[[ "$(git -C "$ROOT_DIR" rev-parse main)" == "$SHA" ]] || fail "SHA is not local main"
[[ "$(git -C "$ROOT_DIR" rev-parse origin/main)" == "$SHA" ]] || \
  fail "local main and origin/main are not aligned"

aws_options=(--region "$AWS_REGION")
if [[ -n "$AWS_CLI_PROFILE" ]]; then
  aws_options+=(--profile "$AWS_CLI_PROFILE")
fi

archive_payload="$(
  git -C "$ROOT_DIR" archive "$SHA" \
    deploy/aws/cloudwatch-agent-config.json \
    scripts/prod/assert_release_is_origin_main.sh \
    scripts/prod/install_cloudwatch_agent.sh \
    scripts/prod/load_env.sh |
    gzip -9 |
    base64 |
    tr -d '\n'
)"
[[ -n "$archive_payload" ]] || fail "unable to build the exact observability bundle"

read -r -d '' remote_script <<'REMOTE' || true
set -Eeuo pipefail

archive_payload="$1"
candidate_sha="$2"
lock_file=/var/lock/brainrh-cost-observation.lock

exec 9>"$lock_file"
flock -n 9 || {
  printf 'cost-observation-release: another observability deployment is running\n' >&2
  exit 1
}

bundle_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$bundle_dir"
}
trap cleanup EXIT

printf '%s' "$archive_payload" | base64 --decode | gzip -d | tar -xf - -C "$bundle_dir"
printf 'BRAINRH_RELEASE_SOURCE_REF=origin/main\nBRAINRH_RELEASE_COMMIT_SHA=%s\n' \
  "$candidate_sha" > "$bundle_dir/.brainrh-release.env"
chmod 0600 "$bundle_dir/.brainrh-release.env"

cd "$bundle_dir"
./scripts/prod/install_cloudwatch_agent.sh

systemctl is-active --quiet amazon-cloudwatch-agent
systemctl is-enabled --quiet amazon-cloudwatch-agent
printf 'cost-observation-release: sha=%s agent_active=true agent_enabled=true runtime_unchanged=true\n' \
  "$candidate_sha"
REMOTE

payload="$(printf '%s' "$remote_script" | base64 | tr -d '\n')"
remote_command="printf '%s' '$payload' | base64 --decode | bash -s -- '$archive_payload' '$SHA'"
parameters="$(jq -cn --arg command "$remote_command" '{commands:[$command]}')"
command_id="$(
  aws ssm send-command \
    "${aws_options[@]}" \
    --instance-ids "$AWS_INSTANCE_ID" \
    --document-name AWS-RunShellScript \
    --comment "Enable bounded BrainRH cost observation $SHA" \
    --parameters "$parameters" \
    --query 'Command.CommandId' \
    --output text
)"

aws ssm wait command-executed \
  "${aws_options[@]}" \
  --command-id "$command_id" \
  --instance-id "$AWS_INSTANCE_ID" || true

result="$(
  aws ssm get-command-invocation \
    "${aws_options[@]}" \
    --command-id "$command_id" \
    --instance-id "$AWS_INSTANCE_ID" \
    --output json
)"
printf '%s\n' "$result" | jq -r '.StandardOutputContent, .StandardErrorContent'
[[ "$(jq -r '.Status' <<< "$result")" == Success ]] || \
  fail "SSM observability deployment failed: $command_id"
grep -q 'agent_active=true agent_enabled=true runtime_unchanged=true' \
  <<< "$(jq -r '.StandardOutputContent' <<< "$result")" || \
  fail "observability deployment invariants were not confirmed"

enrollment_status="$(
  aws compute-optimizer get-enrollment-status \
    "${aws_options[@]}" \
    --query status \
    --output text
)"
case "$enrollment_status" in
  Active | Pending)
    ;;
  Inactive)
    enrollment_status="$(
      aws compute-optimizer update-enrollment-status \
        "${aws_options[@]}" \
        --status Active \
        --no-include-member-accounts \
        --query status \
        --output text
    )"
    [[ "$enrollment_status" == Active || "$enrollment_status" == Pending ]] || \
      fail "Compute Optimizer enrollment request failed: $enrollment_status"
    ;;
  *)
    fail "unexpected Compute Optimizer enrollment status: $enrollment_status"
    ;;
esac

for attempt in {1..12}; do
  enrollment_status="$(
    aws compute-optimizer get-enrollment-status \
      "${aws_options[@]}" \
      --query status \
      --output text
  )"
  [[ "$enrollment_status" == Active ]] && break
  [[ "$enrollment_status" == Pending ]] || \
    fail "Compute Optimizer did not remain Active or Pending: $enrollment_status"
  sleep 5
done
[[ "$enrollment_status" == Active ]] || \
  fail "Compute Optimizer enrollment is still Pending; rerun this release step before collecting recommendations"

account_id="$(
  aws sts get-caller-identity \
    "${aws_options[@]}" \
    --query Account \
    --output text
)"
[[ "$account_id" =~ ^[0-9]{12}$ ]] || fail "unable to resolve the AWS account ID"
optimizer_scope="name=AccountId,value=$account_id"

for resource_type in Ec2Instance RdsDBInstance; do
  aws compute-optimizer put-recommendation-preferences \
    "${aws_options[@]}" \
    --resource-type "$resource_type" \
    --scope "$optimizer_scope" \
    --enhanced-infrastructure-metrics Inactive \
    >/dev/null

  enhanced_metrics=""
  for attempt in {1..6}; do
    enhanced_metrics="$(
      aws compute-optimizer get-recommendation-preferences \
        "${aws_options[@]}" \
        --resource-type "$resource_type" \
        --scope "$optimizer_scope" \
        --query 'recommendationPreferencesDetails[].enhancedInfrastructureMetrics' \
        --output text
    )"
    [[ "$enhanced_metrics" == Inactive ]] && break
    sleep 2
  done
  [[ "$enhanced_metrics" == Inactive ]] || \
    fail "Enhanced Infrastructure Metrics are not verifiably inactive for $resource_type: ${enhanced_metrics:-missing}"
done

ec2_arn="arn:aws:ec2:$AWS_REGION:$account_id:instance/$AWS_INSTANCE_ID"
ec2_scope="name=ResourceArn,value=$ec2_arn"
aws compute-optimizer put-recommendation-preferences \
  "${aws_options[@]}" \
  --resource-type Ec2Instance \
  --scope "$ec2_scope" \
  --enhanced-infrastructure-metrics Inactive \
  >/dev/null

ec2_effective_metrics=""
for attempt in {1..6}; do
  ec2_effective_metrics="$(
    aws compute-optimizer get-effective-recommendation-preferences \
      "${aws_options[@]}" \
      --resource-arn "$ec2_arn" \
      --query enhancedInfrastructureMetrics \
      --output text
  )"
  [[ "$ec2_effective_metrics" == Inactive ]] && break
  sleep 2
done
[[ "$ec2_effective_metrics" == Inactive ]] || \
  fail "effective EC2 Enhanced Infrastructure Metrics are not inactive: ${ec2_effective_metrics:-missing}"

rds_arn="$(
  aws rds describe-db-instances \
    "${aws_options[@]}" \
    --db-instance-identifier "$AWS_RDS_INSTANCE_ID" \
    --query 'DBInstances[0].DBInstanceArn' \
    --output text
)"
[[ "$rds_arn" == "arn:aws:rds:$AWS_REGION:$account_id:db:$AWS_RDS_INSTANCE_ID" ]] || \
  fail "unable to resolve the expected RDS resource ARN"
rds_scope="name=ResourceArn,value=$rds_arn"
aws compute-optimizer put-recommendation-preferences \
  "${aws_options[@]}" \
  --resource-type RdsDBInstance \
  --scope "$rds_scope" \
  --enhanced-infrastructure-metrics Inactive \
  >/dev/null

rds_resource_metrics=""
for attempt in {1..6}; do
  rds_resource_metrics="$(
    aws compute-optimizer get-recommendation-preferences \
      "${aws_options[@]}" \
      --resource-type RdsDBInstance \
      --scope "$rds_scope" \
      --query 'recommendationPreferencesDetails[].enhancedInfrastructureMetrics' \
      --output text
  )"
  [[ "$rds_resource_metrics" == Inactive ]] && break
  sleep 2
done
[[ "$rds_resource_metrics" == Inactive ]] || \
  fail "resource-level RDS Enhanced Infrastructure Metrics are not inactive: ${rds_resource_metrics:-missing}"

printf 'cost-observation-release: success sha=%s command=%s compute_optimizer_status=%s enhanced_metrics=Inactive resources=Ec2Instance,RdsDBInstance effective_ec2=Inactive resource_rds=Inactive\n' \
  "$SHA" "$command_id" "$enrollment_status"
