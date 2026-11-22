#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
Direct production environment rendering is disabled (fail closed).

This legacy helper could overwrite .env.prod outside a signed release and did
not bind exact SSM parameter versions. Runtime configuration remains unchanged
until a separately reviewed promotion adapter can verify and apply an exact,
signed configuration contract without logging secret values.
EOF
exit 78
