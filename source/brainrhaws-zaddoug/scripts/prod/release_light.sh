#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE=""
REQUESTED_COMPONENT="auto"
SHA=""
BASE_REF="origin/main"
DEPLOY_BASE_SHA=""
OWNER_AUTHORIZATION=""

fail() {
  printf 'light-release: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
Usage:
  scripts/prod/release_light.sh --verify-only [--owner-authorization <json>] [--component auto|frontend|backend|worker-video]
  scripts/prod/release_light.sh --deploy-only --sha <40-char-sha> [--base-sha <40-char-sha>] [--component auto|frontend|backend|worker-video]

The orchestrator never creates, stages, commits, or pushes Git changes. Run
--verify-only before the owner pushes main, then --deploy-only after the exact
reviewed SHA is present on origin/main.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify-only|--deploy-only)
      [[ -z "$MODE" ]] || fail "choose exactly one mode"
      MODE="${1#--}"
      shift
      ;;
    --sha)
      [[ $# -ge 2 ]] || fail "--sha requires a value"
      SHA="$2"
      shift 2
      ;;
    --component)
      [[ $# -ge 2 ]] || fail "--component requires a value"
      REQUESTED_COMPONENT="$2"
      shift 2
      ;;
    --base-sha)
      [[ $# -ge 2 ]] || fail "--base-sha requires a value"
      DEPLOY_BASE_SHA="$2"
      shift 2
      ;;
    --owner-authorization)
      [[ $# -ge 2 ]] || fail "--owner-authorization requires a value"
      OWNER_AUTHORIZATION="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ -n "$MODE" ]] || fail "one of --verify-only or --deploy-only is required"
case "$REQUESTED_COMPONENT" in
  auto|frontend|backend|worker-video) ;;
  *) fail "invalid component: $REQUESTED_COMPONENT" ;;
esac
if [[ "$MODE" == "verify-only" ]]; then
  [[ -z "$SHA" ]] || fail "--sha is valid only with --deploy-only"
  [[ -z "$DEPLOY_BASE_SHA" ]] || fail "--base-sha is valid only with --deploy-only"
else
  [[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail "--deploy-only requires a full lowercase --sha"
  [[ -z "$OWNER_AUTHORIZATION" ]] || fail "--owner-authorization is valid only with --verify-only"
  if [[ -n "$DEPLOY_BASE_SHA" ]]; then
    [[ "$DEPLOY_BASE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "--base-sha requires a full lowercase SHA"
  fi
fi

cd "$ROOT_DIR"
[[ "$(git branch --show-current)" == main ]] || fail "the active branch must be main"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail "tracked worktree changes are present"

if [[ "$MODE" == "verify-only" ]]; then
  git show-ref --verify --quiet refs/remotes/origin/main || fail "origin/main is unavailable; fetch it first"
  git merge-base --is-ancestor origin/main HEAD || fail "origin/main is not an ancestor of HEAD"
  HEAD_SHA="$(git rev-parse HEAD)"
  DIFF_RANGE="$BASE_REF..$HEAD_SHA"
else
  git fetch origin main --quiet
  HEAD_SHA="$(git rev-parse HEAD)"
  [[ "$HEAD_SHA" == "$SHA" ]] || fail "--sha is not HEAD"
  [[ "$(git rev-parse main)" == "$SHA" ]] || fail "--sha is not local main"
  [[ "$(git rev-parse origin/main)" == "$SHA" ]] || fail "--sha is not current origin/main"
  if [[ -z "$DEPLOY_BASE_SHA" ]]; then
    DEPLOY_BASE_SHA="$(git rev-parse "$SHA^")" || fail "cannot classify the root commit"
  fi
  git merge-base --is-ancestor "$DEPLOY_BASE_SHA" "$SHA" || fail "--base-sha is not an ancestor of --sha"
  DIFF_RANGE="$DEPLOY_BASE_SHA..$SHA"

  script_path="${BASH_SOURCE[0]#"$ROOT_DIR/"}"
  git cat-file -e "$SHA:$script_path" 2>/dev/null || fail "orchestrator is not tracked by the candidate SHA"
  cmp -s <(git show "$SHA:$script_path") "${BASH_SOURCE[0]}" || \
    fail "orchestrator differs from the candidate SHA"
fi

CHANGED_FILES="$(git diff --name-only --diff-filter=ACMR "$DIFF_RANGE")"
[[ -n "$CHANGED_FILES" ]] || fail "no changed file to release in $DIFF_RANGE"

needs_frontend=false
needs_backend=false
needs_worker=false
has_migration=false
runtime_files=0

while IFS= read -r path; do
  [[ -n "$path" ]] || continue
  case "$path" in
    alembic/versions/*)
      needs_backend=true
      has_migration=true
      runtime_files=$((runtime_files + 1))
      ;;
    frontend/*.md)
      ;;
    frontend/*)
      needs_frontend=true
      runtime_files=$((runtime_files + 1))
      ;;
    Dockerfile.worker-video|brainrh/worker/*|microservices/cal_video_ai_worker/*|deploy/docker/brainrh-worker-video*|scripts/ci/worker_video_container_smoke.py)
      needs_worker=true
      runtime_files=$((runtime_files + 1))
      ;;
    docker-compose.prod.yml)
      needs_frontend=true
      needs_backend=true
      needs_worker=true
      runtime_files=$((runtime_files + 1))
      ;;
    api/*|brainrh/*|lib/*|deploy/aws/backend-data-profile|config_loader.py|project_manager.py|enterprise_manager.py|matching_engine.py|requirements.txt|Dockerfile)
      needs_backend=true
      runtime_files=$((runtime_files + 1))
      ;;
    *)
      ;;
  esac
done <<< "$CHANGED_FILES"

component_count=0
for needed in "$needs_frontend" "$needs_backend" "$needs_worker"; do
  [[ "$needed" != true ]] || component_count=$((component_count + 1))
done

if [[ "$has_migration" == true && "$component_count" -eq 1 ]]; then
  DETECTED_COMPONENT="migration"
elif [[ "$component_count" -gt 1 ]]; then
  DETECTED_COMPONENT="multi"
elif [[ "$needs_frontend" == true ]]; then
  DETECTED_COMPONENT="frontend"
elif [[ "$needs_backend" == true ]]; then
  DETECTED_COMPONENT="backend"
elif [[ "$needs_worker" == true ]]; then
  DETECTED_COMPONENT="worker-video"
else
  DETECTED_COMPONENT="none"
fi

if [[ "$REQUESTED_COMPONENT" != auto ]]; then
  [[ "$DETECTED_COMPONENT" == "$REQUESTED_COMPONENT" ]] || \
    fail "requested component $REQUESTED_COMPONENT does not match detected scope $DETECTED_COMPONENT"
fi

printf 'light-release: sha=%s range=%s scope=%s migration=%s runtime_files=%s\n' \
  "$HEAD_SHA" "$DIFF_RANGE" "$DETECTED_COMPONENT" "$has_migration" "$runtime_files"
printf '%s\n' "$CHANGED_FILES" | sed 's/^/light-release: changed=/'

if [[ "$MODE" == "verify-only" ]]; then
  guard_args=(
    --registry governance/protected-business-logic.json
    --base-ref "$BASE_REF"
    --head-ref "$HEAD_SHA"
  )
  if [[ -n "$OWNER_AUTHORIZATION" ]]; then
    guard_args+=(--owner-authorization "$OWNER_AUTHORIZATION")
  fi
  python3 scripts/ci/business_logic_guard.py "${guard_args[@]}"

  if [[ "$needs_frontend" == true ]]; then
    npm --prefix frontend run build
  fi
  if [[ "$needs_backend" == true ]]; then
    python3 -m compileall -q api brainrh lib
  fi
  if [[ "$needs_worker" == true ]]; then
    python3 -m pytest -q tests/test_worker_video_entrypoint.py tests/worker_video_hardening_contract_test.py
  fi
  if [[ "$has_migration" == true ]]; then
    python3 -m pytest -q tests/migrations/test_migration_contract.py tests/release_migration_evidence_contract.py
  fi

  printf 'light-release: GO sha=%s scope=%s (verification only; no push or AWS mutation)\n' \
    "$HEAD_SHA" "$DETECTED_COMPONENT"
  exit 0
fi

[[ "$DETECTED_COMPONENT" != none ]] || fail "the candidate has no deployable runtime component"
if [[ "$has_migration" == true ]]; then
  fail "migration detected; use docs/operations/database-migration-contract.md before any service deployment"
fi

# These specialized scripts own image construction/reuse, SSM deployment,
# health checks, rollback, and proof that out-of-scope containers did not move.
if [[ "$needs_frontend" == true ]]; then
  scripts/prod/deploy_frontend_light.sh "$SHA"
fi
if [[ "$needs_backend" == true ]]; then
  scripts/prod/deploy_backend_light.sh "$SHA"
fi
if [[ "$needs_worker" == true ]]; then
  scripts/prod/deploy_worker_video_light.sh "$SHA"
fi

printf 'light-release: deployed sha=%s scope=%s; AWS browser validation remains required\n' \
  "$SHA" "$DETECTED_COMPONENT"
