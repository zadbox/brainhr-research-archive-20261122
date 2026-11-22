#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
Direct production deployment is disabled (fail closed).

No repository script may pull, start, stop, migrate, or promote production
containers. Runtime promotion remains unavailable until a separately reviewed
adapter and closed AWS Systems Manager automation are installed. See
docs/operations/promotion-authority.md.
EOF
exit 78
