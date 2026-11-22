#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ATTESTATION_FILE="${BRAINRH_RELEASE_ATTESTATION_FILE:-$ROOT_DIR/.brainrh-release.env}"

if [[ -d "$ROOT_DIR/.git" ]]; then
  git -C "$ROOT_DIR" fetch origin --prune >/dev/null 2>&1 || {
    echo "Unable to fetch origin for deploy source verification." >&2
    exit 1
  }

  head_sha="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  main_sha="$(git -C "$ROOT_DIR" rev-parse origin/main)"
  branch_name="$(git -C "$ROOT_DIR" rev-parse --abbrev-ref HEAD)"

  if [[ -n "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=no)" ]]; then
    echo "Refusing deploy: tracked files in the release checkout are modified." >&2
    exit 1
  fi

  if [[ "$head_sha" != "$main_sha" ]]; then
    echo "Refusing deploy: HEAD ($head_sha) does not match origin/main ($main_sha)." >&2
    exit 1
  fi

  echo "Deploy source verified from Git checkout: origin/main @ $head_sha (branch: $branch_name)"
  exit 0
fi

if [[ -f "$ATTESTATION_FILE" ]]; then
  source "$ROOT_DIR/scripts/prod/load_env.sh" "$ATTESTATION_FILE"

  if [[ "${BRAINRH_RELEASE_SOURCE_REF:-}" != "origin/main" ]]; then
    echo "Refusing deploy: release attestation must declare BRAINRH_RELEASE_SOURCE_REF=origin/main." >&2
    exit 1
  fi

  if [[ ! "${BRAINRH_RELEASE_COMMIT_SHA:-}" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Refusing deploy: release attestation must declare a full lowercase Git commit SHA." >&2
    exit 1
  fi

  echo "Deploy source verified from release attestation: ${BRAINRH_RELEASE_SOURCE_REF} @ ${BRAINRH_RELEASE_COMMIT_SHA}"
  exit 0
fi

echo "Refusing deploy: no Git checkout and no release attestation file at $ATTESTATION_FILE." >&2
echo "Production deploys must prove that the final source was built from GitHub origin/main." >&2
exit 1
