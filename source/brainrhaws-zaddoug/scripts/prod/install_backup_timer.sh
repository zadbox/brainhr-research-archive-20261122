#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SYSTEMD_SOURCE_DIR="$ROOT_DIR/deploy/aws/systemd"
SYSTEMD_TARGET_DIR="/etc/systemd/system"
LOGROTATE_SOURCE="$ROOT_DIR/deploy/aws/logrotate/brainrh-backup"
LOGROTATE_TARGET="/etc/logrotate.d/brainrh-backup"
RUN_INITIAL_BACKUP="${RUN_INITIAL_BACKUP:-1}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-36}"
LOCK_FILE="/run/lock/brainrh-backup-timer.install.lock"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root on the BrainRH EC2 instance." >&2
  exit 1
fi

if [[ ! -d /run/systemd/system ]]; then
  echo "systemd is not running on this host." >&2
  exit 1
fi

for required_file in \
  "$SYSTEMD_SOURCE_DIR/brainrh-backup.service" \
  "$SYSTEMD_SOURCE_DIR/brainrh-backup.timer" \
  "$LOGROTATE_SOURCE" \
  "$ROOT_DIR/scripts/prod/assert_release_is_origin_main.sh" \
  "$ROOT_DIR/scripts/prod/backup_db.sh" \
  "$ROOT_DIR/scripts/prod/check_recent_backup.sh" \
  "$ROOT_DIR/scripts/prod/publish_backup_freshness_metric.sh" \
  "$ROOT_DIR/.env.prod"; do
  if [[ ! -f "$required_file" ]]; then
    echo "Required file missing: $required_file" >&2
    exit 1
  fi
done

case "$RUN_INITIAL_BACKUP" in
  0|1) ;;
  *)
    echo "RUN_INITIAL_BACKUP must be 0 or 1." >&2
    exit 1
    ;;
esac

if ! [[ "$MAX_AGE_HOURS" =~ ^[0-9]+$ ]] || [[ "$MAX_AGE_HOURS" -lt 1 ]]; then
  echo "MAX_AGE_HOURS must be a positive integer." >&2
  exit 1
fi

if ! command -v logrotate >/dev/null 2>&1; then
  echo "logrotate is required to bound backup log retention." >&2
  exit 1
fi
if ! command -v flock >/dev/null 2>&1; then
  echo "flock is required to serialize backup timer installation." >&2
  exit 1
fi
logrotate --debug "$LOGROTATE_SOURCE" >/dev/null

# No host/runtime mutation is allowed before the promoted release is proven.
"$ROOT_DIR/scripts/prod/assert_release_is_origin_main.sh"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another backup timer installation is already running." >&2
  exit 1
fi

ROLLBACK_DIR="$(mktemp -d)"
SERVICE_TARGET="$SYSTEMD_TARGET_DIR/brainrh-backup.service"
TIMER_TARGET="$SYSTEMD_TARGET_DIR/brainrh-backup.timer"
timer_was_enabled=0
timer_was_active=0

systemctl is-enabled --quiet brainrh-backup.timer && timer_was_enabled=1 || true
systemctl is-active --quiet brainrh-backup.timer && timer_was_active=1 || true

backup_file() {
  local target="${1:?target required}"
  local key="${2:?key required}"
  if [[ -e "$target" ]]; then
    cp -a "$target" "$ROLLBACK_DIR/$key"
  else
    touch "$ROLLBACK_DIR/$key.absent"
  fi
}

restore_file() {
  local target="${1:?target required}"
  local key="${2:?key required}"
  if [[ -e "$ROLLBACK_DIR/$key" ]]; then
    cp -a "$ROLLBACK_DIR/$key" "$target"
  else
    rm -f "$target"
  fi
}

backup_file "$SERVICE_TARGET" brainrh-backup.service
backup_file "$TIMER_TARGET" brainrh-backup.timer
backup_file "$LOGROTATE_TARGET" brainrh-backup.logrotate

rollback() {
  local exit_code="${1:-1}"
  trap - ERR INT TERM EXIT
  set +e
  echo "Backup timer installation failed; restoring previous units and state." >&2
  systemctl stop brainrh-backup.service >/dev/null 2>&1
  restore_file "$SERVICE_TARGET" brainrh-backup.service
  restore_file "$TIMER_TARGET" brainrh-backup.timer
  restore_file "$LOGROTATE_TARGET" brainrh-backup.logrotate
  systemctl daemon-reload
  if [[ "$timer_was_enabled" == "1" ]]; then
    systemctl enable brainrh-backup.timer >/dev/null 2>&1
  else
    systemctl disable brainrh-backup.timer >/dev/null 2>&1
  fi
  if [[ "$timer_was_active" == "1" ]]; then
    systemctl restart brainrh-backup.timer
  else
    systemctl stop brainrh-backup.timer >/dev/null 2>&1
  fi
  rm -rf "$ROLLBACK_DIR"
  exit "$exit_code"
}
trap 'rollback $?' ERR
trap 'rollback 130' INT
trap 'rollback 143' TERM

mkdir -p /srv/brainrh/logs
touch /srv/brainrh/logs/backup.log
chown root:root /srv/brainrh/logs/backup.log
chmod 0600 /srv/brainrh/logs/backup.log

install -o root -g root -m 0644 \
  "$SYSTEMD_SOURCE_DIR/brainrh-backup.service" "$SERVICE_TARGET"
install -o root -g root -m 0644 \
  "$SYSTEMD_SOURCE_DIR/brainrh-backup.timer" "$TIMER_TARGET"
install -o root -g root -m 0644 "$LOGROTATE_SOURCE" "$LOGROTATE_TARGET"

systemctl daemon-reload
systemctl enable --now brainrh-backup.timer

if [[ "$RUN_INITIAL_BACKUP" == "1" ]]; then
  systemctl start brainrh-backup.service
fi

systemctl is-enabled --quiet brainrh-backup.timer
systemctl is-active --quiet brainrh-backup.timer

ENV_FILE="$ROOT_DIR/.env.prod" MAX_AGE_HOURS="$MAX_AGE_HOURS" \
  "$ROOT_DIR/scripts/prod/check_recent_backup.sh"

trap - ERR INT TERM EXIT
rm -rf "$ROLLBACK_DIR"
echo "BrainRH backup timer installed and latest S3 backup is within ${MAX_AGE_HOURS}h."
