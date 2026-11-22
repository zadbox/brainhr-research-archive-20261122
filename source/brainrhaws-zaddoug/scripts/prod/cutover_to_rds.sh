#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
The legacy local-PostgreSQL to RDS cutover is disabled (fail closed).

Production already uses RDS. This obsolete one-shot helper must never stop
services, rewrite runtime secrets, import data or invoke deployment scripts.
EOF
exit 78
