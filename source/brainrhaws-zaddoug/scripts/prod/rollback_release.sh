#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
Direct production rollback is disabled (fail closed).

Runtime rollback remains unavailable until a separately reviewed adapter and
closed AWS Systems Manager automation are installed. A future rollback must use
a fresh signed authorization and must never run an Alembic downgrade. See
docs/operations/promotion-authority.md.
EOF
exit 78
