#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
Direct production database restore is disabled (fail closed).

No script may stop production, drop a schema, import a dump, run Alembic or
restart containers. Recovery remains blocked until a versioned, independently
reviewed SSM recovery runbook verifies the exact backup key, VersionIds and
checksums before any mutation.
EOF
exit 78
