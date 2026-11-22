#!/usr/bin/env bash
set -euo pipefail

release_sha="${1:?release SHA required}"
image="${2:?backend image required}"
aws_region="${3:?AWS region required}"
expected_migration_digest="${4:?migration digest required}"
public_origin="https://app.brainhr.braingentech.com"
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$image" =~ ^406260455536\.dkr\.ecr\.eu-north-1\.amazonaws\.com/brainrh/backend@sha256:[0-9a-f]{64}$ ]]
[[ "$aws_region" == eu-north-1 ]]
[[ "$expected_migration_digest" =~ ^[0-9a-f]{64}$ ]]

install -d -m 0700 /srv/brainrh/releases
exec 9>/srv/brainrh/releases/.runtime.lock
flock -n 9 || { echo 'client-trial-expand: runtime release in progress' >&2; exit 1; }
exec 8>/var/lock/brainrh-light-frontend-release.lock
flock -n 8 || { echo 'client-trial-expand: frontend release in progress' >&2; exit 1; }

backend_id="$(docker inspect --format '{{.Id}}' brainrh-backend-1)"
frontend_id="$(docker inspect --format '{{.Id}}' brainrh-frontend-1)"
worker_id="$(docker inspect --format '{{.Id}}' brainrh-worker-video-1)"
caddy_id="$(docker inspect --format '{{.Id}}' brainrh-caddy-1)"
working_dir="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' brainrh-backend-1)"
env_file="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.environment_file" }}' brainrh-backend-1)"
[[ -n "$working_dir" ]]
if [[ -z "$env_file" ]]; then env_file="$working_dir/.env.prod"; fi
[[ -f "$env_file" && ! -L "$env_file" ]]

release_dir="/srv/brainrh/releases/$release_sha"
install -d -m 0700 "$release_dir"
backup_evidence="$release_dir/client-trial-backup-evidence.json"
[[ ! -e "$release_dir/client-trial-migration.json" && ! -e "$release_dir/client-trial-backup.log" && ! -e "$backup_evidence" ]] || {
  echo 'client-trial-expand: existing migration evidence requires review' >&2
  exit 1
}

current_revision="$(docker exec brainrh-backend-1 alembic current 2>/dev/null | awk 'NR == 1 {print $1}')"
[[ "$current_revision" == e1f2a3b4c5d6 ]] || {
  echo "client-trial-expand: expected e1f2a3b4c5d6, got $current_revision" >&2
  exit 1
}

docker_config="$(mktemp -d)"
source_root="$(mktemp -d)"
extract_container=''
cleanup() {
  local result=$?
  trap - EXIT
  [[ -z "$extract_container" ]] || docker rm -f "$extract_container" >/dev/null 2>&1 || true
  rm -rf -- "$docker_config" "$source_root"
  exit "$result"
}
trap cleanup EXIT

registry="${image%%/*}"
aws ecr get-login-password --region "$aws_region" | DOCKER_CONFIG="$docker_config" docker login --username AWS --password-stdin "$registry" >/dev/null
DOCKER_CONFIG="$docker_config" docker pull "$image" >/dev/null
actual_migration_digest="$(docker run --rm --entrypoint sha256sum "$image" \
  /app/alembic/versions/f2a3b4c5d6e7_add_client_trial_window.py | awk '{print $1}')"
[[ "$actual_migration_digest" == "$expected_migration_digest" ]] || {
  echo 'client-trial-expand: image migration does not match Git' >&2
  exit 1
}
extract_container="$(docker create "$image")"
install -d "$source_root/scripts"
docker cp "$extract_container:/app/scripts/prod" "$source_root/scripts/"
docker cp "$extract_container:/app/docker-compose.prod.yml" "$source_root/docker-compose.prod.yml"
docker rm "$extract_container" >/dev/null
extract_container=''

backup_log="$release_dir/client-trial-backup.log"
if ! ENV_FILE="$env_file" BRAINRH_RELEASE_COMMIT_SHA="$release_sha" \
  BRAINRH_BACKUP_EVIDENCE_FILE="$backup_evidence" \
  bash "$source_root/scripts/prod/backup_db.sh" >"$backup_log" 2>&1; then
  chmod 0600 "$backup_log"
  echo 'client-trial-expand: fresh backup failed; migration not started' >&2
  exit 1
fi
chmod 0600 "$backup_log"
[[ -s "$backup_evidence" && ! -L "$backup_evidence" ]]
bucket="$(jq -er '.bucket' "$backup_evidence")"
dump_key="$(jq -er '.dump_key' "$backup_evidence")"
dump_version="$(jq -er '.dump_version_id' "$backup_evidence")"
manifest_version="$(jq -er '.manifest_version_id' "$backup_evidence")"
checksum_version="$(jq -er '.checksum_version_id' "$backup_evidence")"
dump_size="$(jq -er '.dump_size_bytes' "$backup_evidence")"
dump_sha="$(jq -er '.dump_sha256' "$backup_evidence")"
[[ "$bucket" == brainrh-prod-backups-406260455536-eu-north-1 ]]
[[ "$dump_key" =~ ^postgres/daily/postgres-[0-9]{8}T[0-9]{6}Z\.sql\.gz$ ]]
[[ "$dump_version" != None && -n "$dump_version" && "$manifest_version" != None && -n "$manifest_version" && "$checksum_version" != None && -n "$checksum_version" ]]
[[ "$dump_size" =~ ^[1-9][0-9]*$ && "$dump_sha" =~ ^[0-9a-f]{64}$ ]]

dump_head="$(aws s3api head-object --region "$aws_region" --bucket "$bucket" \
  --key "$dump_key" --version-id "$dump_version" --checksum-mode ENABLED --output json)"
jq -e --arg version "$dump_version" --argjson size "$dump_size" --arg sha "$dump_sha" \
  '.VersionId == $version and .ContentLength == $size and .Metadata.sha256 == $sha and .ChecksumSHA256 != null' \
  <<< "$dump_head" >/dev/null
for item in "manifest.json:$manifest_version" "sha256:$checksum_version"; do
  suffix="${item%%:*}"
  version="${item#*:}"
  head="$(aws s3api head-object --region "$aws_region" --bucket "$bucket" \
    --key "$dump_key.$suffix" --version-id "$version" --output json)"
  jq -e --arg version "$version" '.VersionId == $version and .ContentLength > 0' <<< "$head" >/dev/null
done
echo 'client-trial-expand: backup_complete=true'

migration_log="$release_dir/client-trial-migration.log"
echo 'client-trial-expand: migration_starting=true'
if ! docker run --rm --env-file "$env_file" --entrypoint python "$image" \
  /app/scripts/prod/run_one_shot_migration.py \
  --expected-base e1f2a3b4c5d6 --expected-head f2a3b4c5d6e7 >"$migration_log" 2>&1; then
  chmod 0600 "$migration_log"
  echo 'client-trial-expand: migration failed; backend not changed' >&2
  exit 1
fi
chmod 0600 "$migration_log"
tail -1 "$migration_log" | jq -e '.status == "upgraded" and .from_revision == "e1f2a3b4c5d6" and .revision == "f2a3b4c5d6e7"' >/dev/null
healthy=false
for _ in {1..30}; do
  if curl --fail --silent --show-error --max-time 10 "$public_origin/health/ready" >/dev/null 2>&1; then
    healthy=true
    break
  fi
  sleep 2
done
[[ "$healthy" == true ]]
[[ "$(docker inspect --format '{{.Id}}' brainrh-backend-1)" == "$backend_id" ]]
[[ "$(docker inspect --format '{{.Id}}' brainrh-frontend-1)" == "$frontend_id" ]]
[[ "$(docker inspect --format '{{.Id}}' brainrh-worker-video-1)" == "$worker_id" ]]
[[ "$(docker inspect --format '{{.Id}}' brainrh-caddy-1)" == "$caddy_id" ]]

receipt_tmp="$(mktemp "$release_dir/.client-trial-migration.XXXXXX")"
jq -n --arg sha "$release_sha" --arg image "$image" \
  --slurpfile backup "$backup_evidence" \
  --arg completed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{sha:$sha,image:$image,from_revision:"e1f2a3b4c5d6",revision:"f2a3b4c5d6e7",backup:$backup[0],completed_at:$completed_at}' \
  >"$receipt_tmp"
chmod 0600 "$receipt_tmp"
mv -f "$receipt_tmp" "$release_dir/client-trial-migration.json"
sync -f "$release_dir/client-trial-migration.json"
echo "client-trial-expand: sha=$release_sha revision=f2a3b4c5d6e7 backup_recorded=true migration_upgraded=true backend_unchanged=true frontend_unchanged=true worker_unchanged=true caddy_unchanged=true"
