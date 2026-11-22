#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-promote}"
ACTIVE_DIR="${BRAINRH_ACTIVE_DIR:-/opt/brainrh}"
RELEASE_ROOT="${BRAINRH_RELEASE_ROOT:-/srv/brainrh/releases}"
PUBLIC_ORIGIN="${BRAINRH_PUBLIC_ORIGIN:-https://app.brainhr.braingentech.com}"
MIGRATION_TREE_FINGERPRINT="${MIGRATION_TREE_FINGERPRINT:-UNKNOWN}"
RISK_ACCEPTANCE_EXPIRES_AT="${RISK_ACCEPTANCE_EXPIRES_AT:-NONE}"
RDS_INSTANCE_ID="${RDS_INSTANCE_ID:-brainrh-pilot-postgres}"
BACKEND_SOURCE_SHA="${BACKEND_SOURCE_SHA:-${CANDIDATE_SHA:-}}"
FRONTEND_SOURCE_SHA="${FRONTEND_SOURCE_SHA:-${CANDIDATE_SHA:-}}"
WORKER_SOURCE_SHA="${WORKER_SOURCE_SHA:-${CANDIDATE_SHA:-}}"
RELEASE_SCOPE="${RELEASE_SCOPE:-full}"
AUTHORITY_BUCKET="${AUTHORITY_BUCKET:-NONE}"

require_env() {
  local name
  for name in "$@"; do
    if [[ -z "${!name:-}" ]]; then
      echo "exact-release: missing required environment variable $name" >&2
      exit 2
    fi
  done
}

require_command() {
  local name
  for name in "$@"; do
    command -v "$name" >/dev/null || {
      echo "exact-release: missing command $name" >&2
      exit 2
    }
  done
}

require_env \
  CANDIDATE_SHA EXPECTED_BASE_REVISION EXPECTED_HEAD_REVISION \
  BACKEND_DIGEST BACKEND_CRITICAL BACKEND_HIGH \
  FRONTEND_DIGEST FRONTEND_CRITICAL FRONTEND_HIGH \
  WORKER_DIGEST WORKER_CRITICAL WORKER_HIGH \
  RISK_ACCEPTANCE_ID AWS_REGION AWS_ACCOUNT_ID \
  EXPECTED_COMPOSE_SHA256 EXPECTED_SECCOMP_SHA256
require_command aws curl docker flock jq sha256sum

[[ "$CANDIDATE_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$EXPECTED_BASE_REVISION" =~ ^(AUTO|[0-9a-f]{12})$ ]]
[[ "$EXPECTED_HEAD_REVISION" =~ ^[0-9a-f]{12}$ ]]
[[ "$BACKEND_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$FRONTEND_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$WORKER_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$BACKEND_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$FRONTEND_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$WORKER_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$EXPECTED_COMPOSE_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$EXPECTED_SECCOMP_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$RISK_ACCEPTANCE_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$ ]]
[[ "$MIGRATION_TREE_FINGERPRINT" =~ ^(UNKNOWN|NONE|sha256:[0-9a-f]{64})$ ]]
[[ "$MODE" =~ ^(promote|recover|rollback)$ ]]
[[ "$RELEASE_SCOPE" =~ ^(full|frontend-only)$ ]]
[[ "$(id -u)" -eq 0 ]]

if [[ "$MODE" == promote && "$RISK_ACCEPTANCE_EXPIRES_AT" != NONE ]]; then
  expiry_epoch="$(date -u -d "$RISK_ACCEPTANCE_EXPIRES_AT" +%s)"
  [[ "$expiry_epoch" -gt "$(date -u +%s)" ]]
fi

REGISTRY="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
BACKEND_REF="$REGISTRY/brainrh/backend@$BACKEND_DIGEST"
FRONTEND_REF="$REGISTRY/brainrh/frontend@$FRONTEND_DIGEST"
WORKER_REF="$REGISTRY/brainrh/worker-video@$WORKER_DIGEST"
RELEASE_DIR="$RELEASE_ROOT/$CANDIDATE_SHA"
STATE_FILE="$RELEASE_DIR/state.json"
RECEIPT_FILE="$RELEASE_DIR/receipt.json"
OVERRIDE_FILE="$RELEASE_DIR/images.override.yml"
LOCK_FILE="$RELEASE_ROOT/.runtime.lock"
MIGRATION_FINGERPRINT_FILE="$RELEASE_ROOT/.migration-tree-fingerprint"
ENV_FILE="$ACTIVE_DIR/.env.prod"
COMPOSE_FILE="$RELEASE_DIR/source/docker-compose.prod.yml"
SECCOMP_FILE="$RELEASE_DIR/source/deploy/docker/chromium-seccomp.json"
DOCKER_CONFIG=""
ROLLOUT_STARTED=no
COMMITTED=no

install -d -o root -g root -m 0700 "$RELEASE_ROOT" "$RELEASE_DIR"
exec 9>"$LOCK_FILE"
flock -n 9 || {
  echo "exact-release: another runtime operation holds $LOCK_FILE" >&2
  exit 1
}

service_identity() {
  local service="$1" ids
  ids="$(docker ps -q --no-trunc \
    --filter 'label=com.docker.compose.project=brainrh' \
    --filter "label=com.docker.compose.service=$service")"
  [[ -n "$ids" ]]
  [[ "$(printf '%s\n' "$ids" | wc -l | tr -d ' ')" == 1 ]]
  docker inspect "$ids" | jq -er \
    '.[0] | select(.State.Status == "running") | [.Id,.Image,.Config.Image,(.RestartCount|tostring)] | @tsv'
}

write_override() {
  local backend="$1" frontend="$2" worker="$3"
  printf 'services:\n  backend:\n    image: %s\n  frontend:\n    image: %s\n  worker-video:\n    image: %s\n' \
    "$backend" "$frontend" "$worker" >"$OVERRIDE_FILE"
  chmod 0600 "$OVERRIDE_FILE"
}

compose() {
  BRAINRH_BACKEND_IMAGE="$BACKEND_REF" \
    BRAINRH_FRONTEND_IMAGE="$FRONTEND_REF" \
    BRAINRH_WORKER_VIDEO_IMAGE="$WORKER_REF" \
    docker compose \
      --project-name brainrh \
      --env-file "$ENV_FILE" \
      -f "$COMPOSE_FILE" \
      -f "$OVERRIDE_FILE" \
      "$@"
}

compose_up() {
  compose up -d --no-build --no-deps backend frontend worker-video >/dev/null
}

wait_healthy() {
  local attempt backend_id
  for attempt in $(seq 1 60); do
    backend_id="$(docker ps -q --filter 'label=com.docker.compose.project=brainrh' --filter 'label=com.docker.compose.service=backend')"
    if [[ -n "$backend_id" ]] && \
      docker exec "$backend_id" python -c \
        "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=10)); assert d['status']=='ok'; assert d['database']['status']=='ok'" \
        >/dev/null 2>&1 && \
      curl --fail --silent --show-error --max-time 15 "$PUBLIC_ORIGIN/health/ready" >/dev/null && \
      curl --fail --silent --show-error --max-time 15 "$PUBLIC_ORIGIN/" >/dev/null; then
      return 0
    fi
    sleep 5
  done
  echo "exact-release: health checks did not converge" >&2
  return 1
}

restore_from_state() {
  [[ -s "$STATE_FILE" ]] || return 1
  local old_backend old_frontend old_worker
  old_backend="$(jq -er '.previous.backend.image_ref' "$STATE_FILE")" || return 1
  old_frontend="$(jq -er '.previous.frontend.image_ref' "$STATE_FILE")" || return 1
  old_worker="$(jq -er '.previous.worker.image_ref' "$STATE_FILE")" || return 1
  write_override "$old_backend" "$old_frontend" "$old_worker" || return 1
  compose_up || return 1
  wait_healthy || return 1
  tmp_state="$(mktemp "$RELEASE_DIR/.state.XXXXXX")" || return 1
  jq --arg recovered_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '.status="rolled_back" | .rolled_back_at=$recovered_at' \
    "$STATE_FILE" >"$tmp_state" || return 1
  chmod 0600 "$tmp_state" || return 1
  mv -f "$tmp_state" "$STATE_FILE" || return 1
  sync -f "$STATE_FILE" || return 1
  echo "exact-release: rollback completed without schema downgrade"
}

if [[ "$MODE" == recover || "$MODE" == rollback ]]; then
  restore_from_state
  exit 0
fi

if [[ -e "$STATE_FILE" ]]; then
  echo "exact-release: state already exists; use the closed recovery or rollback automation" >&2
  exit 1
fi
rm -rf -- "$RELEASE_DIR/source"

cleanup() {
  local rc=$?
  trap - EXIT HUP INT TERM
  set +e
  [[ -n "${DOCKER_CONFIG:-}" ]] && rm -rf -- "$DOCKER_CONFIG"
  if [[ "$ROLLOUT_STARTED" == yes && "$COMMITTED" != yes ]]; then
    echo "exact-release: promotion failed; restoring prior application images" >&2
    if ! restore_from_state; then
      echo "exact-release: AUTOMATIC_ROLLBACK_FAILED; run the closed recovery automation" >&2
    fi
    rc=1
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

echo "exact-release: stage=preflight_started candidate_sha=$CANDIDATE_SHA"
systemctl is-active --quiet docker
test -r "$ENV_FILE"

backend_before="$(service_identity backend)"
frontend_before="$(service_identity frontend)"
worker_before="$(service_identity worker-video)"
caddy_before="$(service_identity caddy)"
old_backend_ref="$(printf '%s\n' "$backend_before" | cut -f 3)"
old_frontend_ref="$(printf '%s\n' "$frontend_before" | cut -f 3)"
old_worker_ref="$(printf '%s\n' "$worker_before" | cut -f 3)"

verify_image() {
  local repository="$1" digest="$2" critical="$3" high="$4" source_sha="$5"
  local tag_digest scan status actual_critical actual_high
  tag_digest="$(aws ecr describe-images --region "$AWS_REGION" --repository-name "$repository" \
    --image-ids "imageTag=sha-$source_sha" --query 'imageDetails[0].imageDigest' --output text)"
  [[ "$tag_digest" == "$digest" ]]
  scan="$(aws ecr describe-image-scan-findings --region "$AWS_REGION" --repository-name "$repository" \
    --image-id "imageDigest=$digest" \
    --query '[imageScanStatus.status,imageScanFindings.findingSeverityCounts.CRITICAL || `0`,imageScanFindings.findingSeverityCounts.HIGH || `0`]' \
    --output text)"
  read -r status actual_critical actual_high <<<"$scan"
  [[ "$status" == COMPLETE ]]
  [[ "$actual_critical" == "$critical" ]]
  [[ "$actual_high" == "$high" ]]
  echo "exact-release: ecr repository=$repository digest=$digest critical=$critical high=$high accepted=$RISK_ACCEPTANCE_ID"
}

verify_image brainrh/backend "$BACKEND_DIGEST" "$BACKEND_CRITICAL" "$BACKEND_HIGH" "$BACKEND_SOURCE_SHA"
verify_image brainrh/frontend "$FRONTEND_DIGEST" "$FRONTEND_CRITICAL" "$FRONTEND_HIGH" "$FRONTEND_SOURCE_SHA"
verify_image brainrh/worker-video "$WORKER_DIGEST" "$WORKER_CRITICAL" "$WORKER_HIGH" "$WORKER_SOURCE_SHA"

DOCKER_CONFIG="$(mktemp -d /var/tmp/brainrh-exact-release-docker.XXXXXX)"
export DOCKER_CONFIG
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$REGISTRY" >/dev/null
docker pull "$BACKEND_REF" >/dev/null
docker pull "$FRONTEND_REF" >/dev/null
docker pull "$WORKER_REF" >/dev/null

extract_container="$(docker create "$BACKEND_REF")"
trap 'docker rm -f "$extract_container" >/dev/null 2>&1 || true; exit 1' HUP INT TERM
install -d -o root -g root -m 0700 "$RELEASE_DIR/source/scripts"
docker cp "$extract_container:/app/scripts/prod" "$RELEASE_DIR/source/scripts/prod"
docker cp "$extract_container:/app/docker-compose.prod.yml" "$RELEASE_DIR/source/docker-compose.prod.yml"
docker cp "$extract_container:/app/deploy" "$RELEASE_DIR/source/deploy"
docker cp "$extract_container:/app/Caddyfile" "$RELEASE_DIR/source/Caddyfile"
docker rm "$extract_container" >/dev/null
trap 'exit 1' HUP INT TERM
ln -s "$ENV_FILE" "$RELEASE_DIR/source/.env.prod"
[[ "$(sha256sum "$COMPOSE_FILE" | cut -d ' ' -f 1)" == "$EXPECTED_COMPOSE_SHA256" ]]
[[ "$(sha256sum "$SECCOMP_FILE" | cut -d ' ' -f 1)" == "$EXPECTED_SECCOMP_SHA256" ]]
chmod -R go-rwx "$RELEASE_DIR/source"
rm -rf -- "$DOCKER_CONFIG"
DOCKER_CONFIG=""
unset DOCKER_CONFIG
echo "exact-release: stage=images_and_release_source_verified"

initial_frontend_only_tree_match=no
if [[ "$RELEASE_SCOPE" == frontend-only && "$MIGRATION_TREE_FINGERPRINT" != UNKNOWN && ! -s "$MIGRATION_FINGERPRINT_FILE" ]]; then
  retained_tree_digest="$(docker run --rm --entrypoint sh "$BACKEND_REF" -c \
    "cd /app && find alembic/versions -maxdepth 1 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print \$1}'")"
  if [[ "sha256:$retained_tree_digest" == "$MIGRATION_TREE_FINGERPRINT" ]]; then
    initial_frontend_only_tree_match=yes
  fi
fi

check_rds_recovery() {
  local evidence retention latest latest_epoch age_seconds
  evidence="$(aws rds describe-db-instances --region "$AWS_REGION" \
    --db-instance-identifier "$RDS_INSTANCE_ID" \
    --query 'DBInstances[0].[DBInstanceStatus,BackupRetentionPeriod,LatestRestorableTime]' \
    --output text)"
  read -r status retention latest <<<"$evidence"
  [[ "$status" == available ]]
  [[ "$retention" =~ ^[0-9]+$ && "$retention" -gt 0 ]]
  latest_epoch="$(date -u -d "$latest" +%s)"
  age_seconds=$(( $(date -u +%s) - latest_epoch ))
  [[ "$age_seconds" -ge 0 && "$age_seconds" -le 86400 ]]
  echo "exact-release: stage=rds_pitr_verified retention_days=$retention latest_restorable_age_seconds=$age_seconds"
}

migration_required=yes
if [[ "$MIGRATION_TREE_FINGERPRINT" != UNKNOWN && -s "$MIGRATION_FINGERPRINT_FILE" ]] && \
  [[ "$(<"$MIGRATION_FINGERPRINT_FILE")" == "$MIGRATION_TREE_FINGERPRINT" ]]; then
  migration_required=no
fi
if [[ "$initial_frontend_only_tree_match" == yes ]]; then
  migration_required=no
fi

if [[ "$migration_required" == no ]]; then
  database_revision_before="$(docker run --rm --env-file "$ENV_FILE" --entrypoint python "$BACKEND_REF" -c \
    "import os; from sqlalchemy import create_engine,text; e=create_engine(os.environ['DATABASE_URL']); c=e.connect(); print(c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()); c.close(); e.dispose()")"
  [[ "$database_revision_before" == "$EXPECTED_HEAD_REVISION" ]]
  echo "exact-release: stage=database_revision_verified revision=$database_revision_before"
fi

if [[ "$MIGRATION_TREE_FINGERPRINT" != UNKNOWN ]]; then
  check_rds_recovery
fi

if [[ "$migration_required" == yes ]]; then
  backup_log="$RELEASE_DIR/backup.log"
  ENV_FILE="$ENV_FILE" \
    BRAINRH_RELEASE_COMMIT_SHA="$CANDIDATE_SHA" \
    "$RELEASE_DIR/source/scripts/prod/backup_db.sh" | tee "$backup_log"
  chmod 0600 "$backup_log"
  grep -q '^Backup evidence:' "$backup_log"
  echo "exact-release: stage=fresh_versioned_backup_completed reason=migration_tree_changed"
else
  printf '{"status":"skipped_unchanged_tree","migration_tree_fingerprint":"%s"}\n' \
    "$MIGRATION_TREE_FINGERPRINT" >"$RELEASE_DIR/migration.log"
  chmod 0600 "$RELEASE_DIR/migration.log"
  echo "exact-release: stage=backup_and_migration_skipped reason=migration_tree_unchanged"
fi

tmp_state="$(mktemp "$RELEASE_DIR/.state.XXXXXX")"
jq -n \
  --arg candidate_sha "$CANDIDATE_SHA" \
  --arg risk_acceptance_id "$RISK_ACCEPTANCE_ID" \
  --arg risk_acceptance_expires_at "$RISK_ACCEPTANCE_EXPIRES_AT" \
  --arg migration_tree_fingerprint "$MIGRATION_TREE_FINGERPRINT" \
  --arg release_scope "$RELEASE_SCOPE" \
  --arg started_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg old_backend "$old_backend_ref" \
  --arg old_frontend "$old_frontend_ref" \
  --arg old_worker "$old_worker_ref" \
  --arg backend "$BACKEND_REF" \
  --arg frontend "$FRONTEND_REF" \
  --arg worker "$WORKER_REF" \
  '{schema_version:2,status:"in_progress",candidate_sha:$candidate_sha,scope:$release_scope,risk_acceptance_id:$risk_acceptance_id,risk_acceptance_expires_at:$risk_acceptance_expires_at,migration_tree_fingerprint:$migration_tree_fingerprint,started_at:$started_at,previous:{backend:{image_ref:$old_backend},frontend:{image_ref:$old_frontend},worker:{image_ref:$old_worker}},candidate:{backend:{image_ref:$backend},frontend:{image_ref:$frontend},worker:{image_ref:$worker}}}' \
  >"$tmp_state"
chmod 0600 "$tmp_state"
mv -f "$tmp_state" "$STATE_FILE"
sync -f "$STATE_FILE"

if [[ "$migration_required" == yes ]]; then
  docker run --rm \
    --env-file "$ENV_FILE" \
    --entrypoint python \
    "$BACKEND_REF" \
    /app/scripts/prod/run_one_shot_migration.py \
    --expected-base "$EXPECTED_BASE_REVISION" \
    --expected-head "$EXPECTED_HEAD_REVISION" | tee "$RELEASE_DIR/migration.log"
  chmod 0600 "$RELEASE_DIR/migration.log"
  grep -Eq '"status": "(upgraded|already_at_head)"' "$RELEASE_DIR/migration.log"
  echo "exact-release: stage=migration_completed revision=$EXPECTED_HEAD_REVISION"
fi

write_override "$BACKEND_REF" "$FRONTEND_REF" "$WORKER_REF"
configured_images="$(compose config --images)"
[[ "$(printf '%s\n' "$configured_images" | grep -Fxc "$BACKEND_REF")" == 1 ]]
[[ "$(printf '%s\n' "$configured_images" | grep -Fxc "$FRONTEND_REF")" == 1 ]]
[[ "$(printf '%s\n' "$configured_images" | grep -Fxc "$WORKER_REF")" == 1 ]]

ROLLOUT_STARTED=yes
compose_up
wait_healthy

backend_after="$(service_identity backend)"
frontend_after="$(service_identity frontend)"
worker_after="$(service_identity worker-video)"
[[ "$(printf '%s\n' "$backend_after" | cut -f 3)" == "$BACKEND_REF" ]]
[[ "$(printf '%s\n' "$frontend_after" | cut -f 3)" == "$FRONTEND_REF" ]]
[[ "$(printf '%s\n' "$worker_after" | cut -f 3)" == "$WORKER_REF" ]]
[[ "$(printf '%s\n' "$backend_after" | cut -f 4)" == 0 ]]
[[ "$(printf '%s\n' "$frontend_after" | cut -f 4)" == 0 ]]
[[ "$(printf '%s\n' "$worker_after" | cut -f 4)" == 0 ]]
[[ "$(service_identity caddy)" == "$caddy_before" ]]

receipt_tmp="$(mktemp "$RELEASE_DIR/.receipt.XXXXXX")"
jq -n \
  --arg candidate_sha "$CANDIDATE_SHA" \
  --arg revision "$EXPECTED_HEAD_REVISION" \
  --arg risk_acceptance_id "$RISK_ACCEPTANCE_ID" \
  --arg risk_acceptance_expires_at "$RISK_ACCEPTANCE_EXPIRES_AT" \
  --arg migration_tree_fingerprint "$MIGRATION_TREE_FINGERPRINT" \
  --arg migration_required "$migration_required" \
  --arg release_scope "$RELEASE_SCOPE" \
  --arg deployed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg backend "$BACKEND_REF" \
  --arg frontend "$FRONTEND_REF" \
  --arg worker "$WORKER_REF" \
  --arg previous_backend "$old_backend_ref" \
  --arg previous_frontend "$old_frontend_ref" \
  --arg previous_worker "$old_worker_ref" \
  --argjson backend_critical "$BACKEND_CRITICAL" --argjson backend_high "$BACKEND_HIGH" \
  --argjson frontend_critical "$FRONTEND_CRITICAL" --argjson frontend_high "$FRONTEND_HIGH" \
  --argjson worker_critical "$WORKER_CRITICAL" --argjson worker_high "$WORKER_HIGH" \
  '{schema_version:2,candidate_sha:$candidate_sha,scope:$release_scope,database_revision:$revision,risk_acceptance_id:$risk_acceptance_id,risk_acceptance_expires_at:$risk_acceptance_expires_at,migration_tree_fingerprint:$migration_tree_fingerprint,migration:{required:($migration_required=="yes"),strategy:"if_tree_changed"},deployed_at:$deployed_at,images:{backend:$backend,frontend:$frontend,worker:$worker},previous_images:{backend:$previous_backend,frontend:$previous_frontend,worker:$previous_worker},ecr_scan:{backend:{critical:$backend_critical,high:$backend_high},frontend:{critical:$frontend_critical,high:$frontend_high},worker:{critical:$worker_critical,high:$worker_high}},health:{internal:"ok",public:"ok"},automatic_rollback:"armed",schema_downgrade:"forbidden"}' \
  >"$receipt_tmp"
chmod 0600 "$receipt_tmp"
mv -f "$receipt_tmp" "$RECEIPT_FILE"
sync -f "$RECEIPT_FILE"

tmp_state="$(mktemp "$RELEASE_DIR/.state.XXXXXX")"
jq --arg completed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '.status="completed" | .completed_at=$completed_at' "$STATE_FILE" >"$tmp_state"
chmod 0600 "$tmp_state"
mv -f "$tmp_state" "$STATE_FILE"
sync -f "$STATE_FILE"

if [[ "$MIGRATION_TREE_FINGERPRINT" != UNKNOWN ]]; then
  fingerprint_tmp="$(mktemp "$RELEASE_ROOT/.migration-tree-fingerprint.XXXXXX")"
  printf '%s' "$MIGRATION_TREE_FINGERPRINT" >"$fingerprint_tmp"
  chmod 0600 "$fingerprint_tmp"
  mv -f "$fingerprint_tmp" "$MIGRATION_FINGERPRINT_FILE"
  sync -f "$MIGRATION_FINGERPRINT_FILE"
fi

COMMITTED=yes
if [[ "$AUTHORITY_BUCKET" != NONE ]]; then
  receipt_key="release-authority/receipts/fast/$CANDIDATE_SHA.json"
  receipt_published=no
  for receipt_attempt in 1 2 3; do
    if receipt_version="$(aws s3api put-object --bucket "$AUTHORITY_BUCKET" --key "$receipt_key" \
      --body "$RECEIPT_FILE" --content-type application/json --if-none-match '*' \
      --query VersionId --output text)" && \
      [[ -n "$receipt_version" && "$receipt_version" != None ]]; then
      receipt_published=yes
      rm -f -- "$RELEASE_DIR/receipt-upload-pending"
      echo "exact-release: stage=receipt_published key=$receipt_key version_id=$receipt_version"
      break
    fi
    sleep $((receipt_attempt * 2))
  done
  if [[ "$receipt_published" != yes ]]; then
    printf '%s\n' "$receipt_key" >"$RELEASE_DIR/receipt-upload-pending"
    chmod 0600 "$RELEASE_DIR/receipt-upload-pending"
    echo "exact-release: WARNING receipt_upload_pending key=$receipt_key; runtime remains committed" >&2
  fi
fi
echo "exact-release: promoted candidate_sha=$CANDIDATE_SHA revision=$EXPECTED_HEAD_REVISION risk_acceptance_id=$RISK_ACCEPTANCE_ID"
