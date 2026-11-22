#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
Direct database import is disabled (fail closed).

This obsolete migration helper could drop schemas and run Alembic outside the
promotion authority. Use no production import path until a versioned recovery
runbook has been reviewed and installed.
EOF
exit 78
