#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENT_CTL="/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl"
AGENT_CONFIG_SOURCE="$ROOT_DIR/deploy/aws/cloudwatch-agent-config.json"
AGENT_CONFIG_TARGET="/opt/aws/amazon-cloudwatch-agent/etc/brainrh-cloudwatch-agent.json"
AGENT_RUNTIME_CONFIG="/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.toml"
LOCK_FILE="/run/lock/brainrh-cloudwatch-agent.install.lock"
BACKUP_LOG_DIR="/srv/brainrh/logs"
BACKUP_LOG="$BACKUP_LOG_DIR/backup.log"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root on the BrainRH EC2 instance." >&2
  exit 1
fi

if [[ ! -x "$AGENT_CTL" ]]; then
  echo "Amazon CloudWatch agent is not installed; install it through AWS Systems Manager Distributor first." >&2
  exit 1
fi

for required_file in \
  "$AGENT_CONFIG_SOURCE" \
  "$ROOT_DIR/scripts/prod/assert_release_is_origin_main.sh"; do
  if [[ ! -f "$required_file" ]]; then
    echo "Required file missing: $required_file" >&2
    exit 1
  fi
done

if ! command -v flock >/dev/null 2>&1; then
  echo "flock is required to serialize CloudWatch agent installation." >&2
  exit 1
fi

# No host/runtime mutation is allowed before the promoted release is proven.
"$ROOT_DIR/scripts/prod/assert_release_is_origin_main.sh"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another CloudWatch agent installation is already running." >&2
  exit 1
fi

ROLLBACK_DIR="$(mktemp -d)"
target_existed=0
runtime_config_existed=0
agent_was_active=0
agent_was_enabled=0
backup_log_dir_existed=0
backup_log_existed=0
backup_log_owner=""
backup_log_mode=""

if [[ -f "$AGENT_CONFIG_TARGET" ]]; then
  install -o root -g root -m 0600 "$AGENT_CONFIG_TARGET" "$ROLLBACK_DIR/brainrh-cloudwatch-agent.json"
  target_existed=1
fi
if [[ -f "$AGENT_RUNTIME_CONFIG" ]]; then
  install -o root -g root -m 0600 "$AGENT_RUNTIME_CONFIG" "$ROLLBACK_DIR/amazon-cloudwatch-agent.toml"
  runtime_config_existed=1
fi
systemctl is-active --quiet amazon-cloudwatch-agent && agent_was_active=1 || true
systemctl is-enabled --quiet amazon-cloudwatch-agent && agent_was_enabled=1 || true
if [[ -d "$BACKUP_LOG_DIR" ]]; then
  backup_log_dir_existed=1
fi
if [[ -f "$BACKUP_LOG" ]]; then
  backup_log_existed=1
  backup_log_owner="$(stat -c '%u:%g' "$BACKUP_LOG")"
  backup_log_mode="$(stat -c '%a' "$BACKUP_LOG")"
fi

rollback() {
  local exit_code="${1:-1}"
  trap - ERR INT TERM EXIT
  set +e
  echo "CloudWatch agent installation failed; restoring previous configuration." >&2
  if [[ "$target_existed" == "1" ]]; then
    install -o root -g root -m 0600 \
      "$ROLLBACK_DIR/brainrh-cloudwatch-agent.json" "$AGENT_CONFIG_TARGET"
    if [[ "$agent_was_active" == "1" ]]; then
      "$AGENT_CTL" -a fetch-config -m ec2 -s -c "file:$AGENT_CONFIG_TARGET"
    else
      "$AGENT_CTL" -a fetch-config -m ec2 -c "file:$AGENT_CONFIG_TARGET"
      systemctl stop amazon-cloudwatch-agent >/dev/null 2>&1
    fi
  else
    rm -f "$AGENT_CONFIG_TARGET"
    if [[ "$runtime_config_existed" == "1" ]]; then
      install -o root -g root -m 0600 \
        "$ROLLBACK_DIR/amazon-cloudwatch-agent.toml" "$AGENT_RUNTIME_CONFIG"
    else
      rm -f "$AGENT_RUNTIME_CONFIG"
    fi
    if [[ "$agent_was_active" == "1" ]]; then
      systemctl restart amazon-cloudwatch-agent
    else
      systemctl stop amazon-cloudwatch-agent >/dev/null 2>&1
    fi
  fi
  if [[ "$agent_was_enabled" == "1" ]]; then
    systemctl enable amazon-cloudwatch-agent >/dev/null 2>&1
  else
    systemctl disable amazon-cloudwatch-agent >/dev/null 2>&1
  fi
  if [[ "$runtime_config_existed" == "0" ]]; then
    rm -f "$AGENT_RUNTIME_CONFIG"
  fi
  if [[ "$backup_log_existed" == "1" ]]; then
    chown "$backup_log_owner" "$BACKUP_LOG"
    chmod "$backup_log_mode" "$BACKUP_LOG"
  else
    rm -f "$BACKUP_LOG"
    if [[ "$backup_log_dir_existed" == "0" ]]; then
      rmdir "$BACKUP_LOG_DIR" >/dev/null 2>&1 || true
    fi
  fi
  rm -rf "$ROLLBACK_DIR"
  exit "$exit_code"
}
trap 'rollback $?' ERR
trap 'rollback 130' INT
trap 'rollback 143' TERM

mkdir -p "$BACKUP_LOG_DIR"
touch "$BACKUP_LOG"
chown root:root "$BACKUP_LOG"
chmod 0600 "$BACKUP_LOG"

install -o root -g root -m 0600 "$AGENT_CONFIG_SOURCE" "$AGENT_CONFIG_TARGET"

"$AGENT_CTL" \
  -a fetch-config \
  -m ec2 \
  -s \
  -c "file:$AGENT_CONFIG_TARGET"

systemctl enable amazon-cloudwatch-agent >/dev/null
systemctl is-active --quiet amazon-cloudwatch-agent
systemctl is-enabled --quiet amazon-cloudwatch-agent
trap - ERR INT TERM EXIT
rm -rf "$ROLLBACK_DIR"
echo "CloudWatch agent configured for backup metadata plus bounded host memory and disk metrics."
