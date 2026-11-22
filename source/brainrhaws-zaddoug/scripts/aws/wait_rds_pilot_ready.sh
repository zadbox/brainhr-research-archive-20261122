#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT_DIR/scripts/aws/rds_pilot_common.sh"

require_command aws

attempts="${1:-90}"
sleep_seconds="${2:-20}"
attempt=1

while (( attempt <= attempts )); do
  status="$(
    aws_text rds describe-db-instances \
      --db-instance-identifier "$BRAINRH_RDS_IDENTIFIER" \
      --query 'DBInstances[0].DBInstanceStatus' 2>/dev/null || true
  )"
  if [[ "$status" == "available" ]]; then
    endpoint="$(
      aws_text rds describe-db-instances \
        --db-instance-identifier "$BRAINRH_RDS_IDENTIFIER" \
        --query 'DBInstances[0].Endpoint.Address'
    )"
    persist_rds_metadata "$endpoint"
    echo "RDS instance available: ${BRAINRH_RDS_IDENTIFIER}"
    echo "Endpoint: ${endpoint}"
    exit 0
  fi
  echo "Waiting for ${BRAINRH_RDS_IDENTIFIER}: status=${status:-unknown} (${attempt}/${attempts})"
  sleep "$sleep_seconds"
  ((attempt += 1))
done

echo "Timed out waiting for ${BRAINRH_RDS_IDENTIFIER} to become available." >&2
exit 1
