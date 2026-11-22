#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
The legacy RDS migration rehearsal is disabled (fail closed).

It depended on a destructive import helper and did not prove isolation from
production. A future rehearsal must use an explicitly isolated synthetic AWS
database and a versioned recovery runbook.
EOF
exit 78
