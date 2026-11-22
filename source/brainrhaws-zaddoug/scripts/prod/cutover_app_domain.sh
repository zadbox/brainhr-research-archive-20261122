#!/usr/bin/env bash
set -euo pipefail

mode="${1:?--apply or --rollback required}"
SHA="${2:?reviewed origin/main SHA required}"
[[ "$mode" == --apply || "$mode" == --rollback ]]
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]]
AWS_CLI_PROFILE="${AWS_CLI_PROFILE-${AWS_PROFILE-${AWS_DEFAULT_PROFILE-brainrh-sso}}}"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
AWS_REGION="${AWS_REGION:-eu-north-1}"
AWS_INSTANCE_ID="${AWS_INSTANCE_ID:-i-0d2ac4ca5d6bb5ca5}"
[[ "$AWS_REGION" == eu-north-1 && "$AWS_INSTANCE_ID" == i-0d2ac4ca5d6bb5ca5 ]]

fail() { printf 'domain-cutover: %s\n' "$*" >&2; exit 1; }
cd "$(git rev-parse --show-toplevel)"
[[ "$(git branch --show-current)" == main ]] || fail 'main must be active'
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail 'tracked changes present'
git fetch origin main --quiet
[[ "$(git rev-parse HEAD)" == "$SHA" && "$(git rev-parse origin/main)" == "$SHA" ]] || fail 'SHA is not current origin/main'
for path in Caddyfile frontend/Dockerfile.prod scripts/prod/cutover_app_domain.sh scripts/prod/cutover_app_domain_remote.sh; do
  git cat-file -e "$SHA:$path" || fail "$path is absent from candidate SHA"
  cmp -s <(git show "$SHA:$path") "$path" || fail "$path differs from candidate SHA"
done
caddy_change="$(git log -1 --format=%H "$SHA" -- Caddyfile)"
[[ -n "$caddy_change" ]] || fail 'Caddyfile history unavailable'
previous_caddy_sha="$(git show "$caddy_change^:Caddyfile" | shasum -a 256 | cut -d' ' -f1)"
target_caddy_sha="$(shasum -a 256 Caddyfile | cut -d' ' -f1)"
[[ "$previous_caddy_sha" != "$target_caddy_sha" ]] || fail 'Caddyfile has no cutover change'

aws_options=(--profile "$AWS_CLI_PROFILE" --region "$AWS_REGION")
[[ "$(aws sts get-caller-identity "${aws_options[@]}" --query Account --output text)" == 406260455536 ]] || fail 'unexpected AWS account'
eip_instance="$(aws ec2 describe-addresses "${aws_options[@]}" --filters Name=public-ip,Values=13.63.230.47 --query 'Addresses[0].InstanceId' --output text)"
[[ "$eip_instance" == "$AWS_INSTANCE_ID" ]] || fail 'DNS target is not the expected Elastic IP association'

old_origin=https://brainhr.braingentech.com
new_origin=https://app.brainhr.braingentech.com
registry="406260455536.dkr.ecr.$AWS_REGION.amazonaws.com"
repository=brainrh/frontend
tag="sha-$SHA"
docker_config="$(mktemp -d)"
docker_host="$(docker context inspect "$(docker context show)" --format '{{.Endpoints.docker.Host}}')"
[[ "$docker_host" == unix://* ]] || fail 'Docker must use a local Unix socket'
unset DOCKER_CONTEXT
build_context=''
cleanup() {
  rm -rf "$docker_config"
  [[ -z "$build_context" ]] || rm -rf "$build_context"
}
trap cleanup EXIT

frontend_image=rollback-unused
if [[ "$mode" == --apply ]]; then
  frontend_digest="$(aws ecr describe-images "${aws_options[@]}" --repository-name "$repository" \
    --image-ids "imageTag=$tag" --query 'imageDetails[0].imageDigest' --output text 2>/dev/null || true)"
  if [[ ! "$frontend_digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    build_context="$(mktemp -d)"
    git archive "$SHA" | tar -x -C "$build_context"
    aws ecr get-login-password "${aws_options[@]}" |
      DOCKER_CONFIG="$docker_config" DOCKER_HOST="$docker_host" docker login --username AWS --password-stdin "$registry" >/dev/null
    image_tag="$registry/$repository:$tag"
    if docker buildx version >/dev/null 2>&1; then
      DOCKER_CONFIG="$docker_config" DOCKER_HOST="$docker_host" docker buildx build --pull --push \
        --platform linux/amd64 --provenance=false \
        --file "$build_context/frontend/Dockerfile.prod" \
        --build-arg "VITE_API_BASE_URL=$new_origin" \
        --tag "$image_tag" "$build_context"
    else
      docker build --pull --platform linux/amd64 \
        --file "$build_context/frontend/Dockerfile.prod" \
        --build-arg "VITE_API_BASE_URL=$new_origin" \
        --tag "$image_tag" "$build_context"
      [[ "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image_tag")" == linux/amd64 ]] ||
        fail 'frontend image has the wrong platform'
      DOCKER_CONFIG="$docker_config" DOCKER_HOST="$docker_host" docker push "$image_tag"
    fi
    frontend_digest="$(aws ecr describe-images "${aws_options[@]}" --repository-name "$repository" \
      --image-ids "imageTag=$tag" --query 'imageDetails[0].imageDigest' --output text)"
  fi
  [[ "$frontend_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'immutable frontend image missing'
  frontend_image="$registry/$repository@$frontend_digest"
  aws ecr get-login-password "${aws_options[@]}" |
    DOCKER_CONFIG="$docker_config" DOCKER_HOST="$docker_host" docker login --username AWS --password-stdin "$registry" >/dev/null
  DOCKER_CONFIG="$docker_config" DOCKER_HOST="$docker_host" docker pull "$frontend_image" >/dev/null
  [[ "$(docker image inspect --format '{{index .Config.Labels "org.brainrh.public-api-origin"}}' "$frontend_image")" == "$new_origin" ]] ||
    fail 'frontend image origin label does not match app domain'
fi

remote_base64="$(git show "$SHA:scripts/prod/cutover_app_domain_remote.sh" | base64 | tr -d '\n')"
caddy_base64="$(git show "$SHA:Caddyfile" | base64 | tr -d '\n')"
call_remote() {
  local requested_mode="$1" command parameters command_id result
  command="printf '%s' '$remote_base64' | base64 --decode | bash -s -- '$requested_mode' '$SHA' '$frontend_image' '$previous_caddy_sha' '$target_caddy_sha' '$caddy_base64'"
  parameters="$(jq -cn --arg command "$command" '{commands:[$command]}')"
  command_id="$(aws ssm send-command "${aws_options[@]}" --instance-ids "$AWS_INSTANCE_ID" \
    --document-name AWS-RunShellScript --comment "App domain $requested_mode $SHA" \
    --parameters "$parameters" --query 'Command.CommandId' --output text)"
  result=''
  for _ in {1..180}; do
    if result="$(aws ssm get-command-invocation "${aws_options[@]}" --command-id "$command_id" --instance-id "$AWS_INSTANCE_ID" --output json 2>/dev/null)"; then
      case "$(jq -r '.Status' <<< "$result")" in
        Success|Failed|Cancelled|TimedOut) break ;;
      esac
    fi
    sleep 5
  done
  [[ -n "$result" ]] || { echo "domain-cutover: no SSM result for $command_id" >&2; return 1; }
  printf '%s\n' "$result" | jq -r '.StandardOutputContent, .StandardErrorContent'
  [[ "$(jq -r '.Status' <<< "$result")" == Success ]] || return 1
  printf 'domain-cutover: remote %s command=%s\n' "$requested_mode" "$command_id"
}

keys=(BRAINRH_DOMAIN FRONTEND_URL PUBLIC_API_BASE_URL CORS_ALLOWED_ORIGINS SMOKE_BASE_URL)
old_values=(brainhr.braingentech.com "$old_origin" "$old_origin" "$old_origin" "$old_origin")
new_values=(app.brainhr.braingentech.com "$new_origin" "$new_origin" "$new_origin" "$new_origin")
parameters_match() {
  local target="$1" index response expected
  for index in "${!keys[@]}"; do
    if [[ "$target" == new ]]; then expected="${new_values[$index]}"; else expected="${old_values[$index]}"; fi
    response="$(aws ssm get-parameter "${aws_options[@]}" --name "/brainrh/prod/env/${keys[$index]}" --output json)" || return 1
    [[ "$(jq -r '.Parameter.Type' <<< "$response")" == String &&
       "$(jq -r '.Parameter.Value' <<< "$response")" == "$expected" ]] || return 1
  done
}
verify_old_parameters() {
  parameters_match old || fail 'one or more SSM values are not on the expected old origin'
}
sync_parameters() {
  local target="$1" index key expected opposite response value type
  for index in "${!keys[@]}"; do
    key="${keys[$index]}"
    if [[ "$target" == new ]]; then
      expected="${new_values[$index]}"
      opposite="${old_values[$index]}"
    else
      expected="${old_values[$index]}"
      opposite="${new_values[$index]}"
    fi
    response="$(aws ssm get-parameter "${aws_options[@]}" --name "/brainrh/prod/env/$key" --output json)" || return 1
    type="$(jq -r '.Parameter.Type' <<< "$response")"
    value="$(jq -r '.Parameter.Value' <<< "$response")"
    unset response
    [[ "$type" == String ]] || return 1
    if [[ "$value" == "$expected" ]]; then continue; fi
    [[ "$value" == "$opposite" ]] || return 1
    aws ssm put-parameter "${aws_options[@]}" --name "/brainrh/prod/env/$key" \
      --type String --value "$expected" --overwrite >/dev/null || return 1
    printf 'domain-cutover: SSM %s aligned\n' "$key"
  done
}

if [[ "$mode" == --rollback ]]; then
  call_remote rollback || fail 'runtime rollback failed'
  sync_parameters old || fail 'runtime is restored, but SSM rollback needs attention'
  echo "domain-cutover: rollback success sha=$SHA"
  exit 0
fi

if parameters_match new; then
  call_remote apply || fail 'SSM is on the new origin, but runtime verification failed'
  echo "domain-cutover: success sha=$SHA already_applied=true"
  exit 0
fi

curl --fail --silent --show-error --max-time 10 "$old_origin/health/ready" >/dev/null
curl --fail --silent --show-error --max-time 10 "$new_origin/health/ready" >/dev/null
verify_old_parameters
call_remote apply || fail 'runtime cutover failed; remote rollback attempted'
if ! sync_parameters new; then
  sync_parameters old || true
  call_remote rollback || true
  fail 'SSM alignment failed; rollback attempted'
fi
echo "domain-cutover: success sha=$SHA frontend_image=$frontend_image"
