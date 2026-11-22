#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.prod}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-36}"
BACKUP_METRIC_ENVIRONMENT="${BACKUP_METRIC_ENVIRONMENT:-prod}"

source "$ROOT_DIR/scripts/prod/load_env.sh" "$ENV_FILE"

require_command aws
require_env AWS_REGION

if ! [[ "$BACKUP_METRIC_ENVIRONMENT" =~ ^[a-z0-9-]+$ ]]; then
  echo "BACKUP_METRIC_ENVIRONMENT must contain only lowercase letters, digits and hyphens." >&2
  exit 1
fi

# Freshness is the source of truth. A newly uploaded object alone is not enough
# if listing/metadata verification does not observe a recent non-empty backup.
ENV_FILE="$ENV_FILE" MAX_AGE_HOURS="$MAX_AGE_HOURS" \
  "$ROOT_DIR/scripts/prod/check_recent_backup.sh" >/dev/null

if ! aws cloudwatch put-metric-data \
  --region "$AWS_REGION" \
  --namespace BrainRH/Operations \
  --metric-data \
    "MetricName=BackupFreshness,Dimensions=[{Name=Environment,Value=${BACKUP_METRIC_ENVIRONMENT}}],Value=1,Unit=Count"; then
  echo "WARNING: backup is fresh but the CloudWatch freshness metric could not be published." >&2
fi

echo "Backup freshness verified; CloudWatch metric publication attempted for ${BACKUP_METRIC_ENVIRONMENT}."
