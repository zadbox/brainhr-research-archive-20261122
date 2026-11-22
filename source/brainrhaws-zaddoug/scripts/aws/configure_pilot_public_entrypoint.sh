#!/usr/bin/env bash
set -euo pipefail

MODE="${1:?mode required: http or https}"
HOSTNAME_VALUE="${2:?public hostname required}"
AWS_REGION="${AWS_REGION:-eu-north-1}"

CADDY_SITE_ADDRESS=""
PUBLIC_BASE_URL=""
AUTH_COOKIE_SECURE_VALUE=""
AUTH_COOKIE_SAMESITE_VALUE=""

case "$MODE" in
  http)
    PUBLIC_BASE_URL="http://${HOSTNAME_VALUE}"
    CADDY_SITE_ADDRESS="$PUBLIC_BASE_URL"
    AUTH_COOKIE_SECURE_VALUE="false"
    AUTH_COOKIE_SAMESITE_VALUE="lax"
    ;;
  https)
    if [[ "$HOSTNAME_VALUE" == *.compute.amazonaws.com ]]; then
      echo "HTTPS mode is not supported on raw EC2 compute hostnames with public ACME issuance." >&2
      echo "Use a real custom domain for HTTPS, or keep the raw EC2 hostname on HTTP." >&2
      exit 1
    fi
    PUBLIC_BASE_URL="https://${HOSTNAME_VALUE}"
    CADDY_SITE_ADDRESS="$HOSTNAME_VALUE"
    AUTH_COOKIE_SECURE_VALUE="true"
    AUTH_COOKIE_SAMESITE_VALUE="lax"
    ;;
  *)
    echo "Unsupported mode: $MODE" >&2
    echo "Use http or https." >&2
    exit 1
    ;;
esac

put_string_parameter() {
  local name="${1:?name required}"
  local value="${2:?value required}"
  aws ssm put-parameter \
    --region "$AWS_REGION" \
    --name "$name" \
    --type String \
    --value "$value" \
    --overwrite >/dev/null
}

put_string_parameter /brainrh/prod/env/BRAINRH_DOMAIN "$CADDY_SITE_ADDRESS"
put_string_parameter /brainrh/prod/env/PUBLIC_API_BASE_URL "$PUBLIC_BASE_URL"
put_string_parameter /brainrh/prod/env/FRONTEND_URL "$PUBLIC_BASE_URL"
put_string_parameter /brainrh/prod/env/CORS_ALLOWED_ORIGINS "$PUBLIC_BASE_URL"
put_string_parameter /brainrh/prod/env/AUTH_COOKIE_SECURE "$AUTH_COOKIE_SECURE_VALUE"
put_string_parameter /brainrh/prod/env/AUTH_COOKIE_SAMESITE "$AUTH_COOKIE_SAMESITE_VALUE"
put_string_parameter /brainrh/prod/env/SMOKE_BASE_URL "$PUBLIC_BASE_URL"

echo "Configured pilot public entrypoint:"
echo "  mode=$MODE"
echo "  hostname=$HOSTNAME_VALUE"
echo "  caddy_site_address=$CADDY_SITE_ADDRESS"
echo "  public_url=$PUBLIC_BASE_URL"
