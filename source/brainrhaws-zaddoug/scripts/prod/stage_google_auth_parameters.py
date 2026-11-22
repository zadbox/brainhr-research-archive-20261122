#!/usr/bin/env python3
"""Validate a private Google Web OAuth JSON and stage exact SSM parameters."""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import re
import sys

import boto3
from botocore.exceptions import ClientError


PREFIX = "/brainrh/prod/env/"
PROJECT_ID = "brainrh-braingentech"
CALLBACK = "https://app.brainhr.braingentech.com/api/v1/auth/google/callback"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _web_credentials(path: Path) -> tuple[str, str]:
    if not path.is_file() or path.resolve().is_relative_to(REPO_ROOT):
        raise ValueError("OAuth JSON must be an existing file outside the repository")
    payload = json.loads(path.read_text(encoding="utf-8"))
    web = payload.get("web") if isinstance(payload, dict) else None
    if not isinstance(web, dict):
        raise ValueError("OAuth JSON has no Web application credentials")
    if web.get("project_id") != PROJECT_ID or web.get("redirect_uris") != [CALLBACK]:
        raise ValueError("OAuth project or exact callback does not match BrainRH production")
    client_id, secret = web.get("client_id"), web.get("client_secret")
    if not isinstance(client_id, str) or not re.fullmatch(r"[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", client_id):
        raise ValueError("OAuth client ID is invalid")
    if not isinstance(secret, str) or len(secret) < 20 or any(char.isspace() for char in secret):
        raise ValueError("OAuth client secret is invalid")
    return client_id, secret


def _proxy_cidr(value: str) -> str:
    network = ipaddress.ip_network(value, strict=True)
    if network.version != 4 or network.prefixlen != 32 or network.is_unspecified:
        raise ValueError("Use the exact Caddy proxy address as an IPv4 /32 CIDR")
    return str(network)


def _put_if_needed(ssm, key: str, value: str, kind: str) -> int:
    name = PREFIX + key
    try:
        current = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ParameterNotFound":
            raise
    else:
        if current["Type"] != kind:
            raise ValueError(f"Existing parameter has the wrong type: {name}")
        if key == "BRAINRH_GOOGLE_AUTH_ENABLED" and current["Value"] == "true" and value == "false":
            raise ValueError("Google Auth is already active; staging must not disable it")
        if current["Value"] == value:
            return int(current["Version"])
    result = ssm.put_parameter(Name=name, Value=value, Type=kind, Overwrite=True)
    return int(result["Version"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oauth-json", type=Path, required=True)
    parser.add_argument("--trusted-caddy-cidr", required=True)
    parser.add_argument("--profile", default="brainrh-sso")
    parser.add_argument("--region", default="eu-north-1")
    parser.add_argument("--enable", action="store_true", help="switch the SSM flag to true after backend log verification")
    args = parser.parse_args()

    client_id, secret = _web_credentials(args.oauth_json)
    cidr = _proxy_cidr(args.trusted_caddy_cidr)
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    if session.client("sts").get_caller_identity()["Account"] != "406260455536":
        raise ValueError("Unexpected AWS account")
    ssm = session.client("ssm")
    parameters = (
        ("BRAINRH_GOOGLE_CLIENT_ID", client_id, "String"),
        ("BRAINRH_GOOGLE_CLIENT_SECRET", secret, "SecureString"),
        ("BRAINRH_GOOGLE_TRUSTED_PROXY_CIDRS", cidr, "String"),
        ("BRAINRH_GOOGLE_AUTH_ENABLED", "true" if args.enable else "false", "String"),
    )
    versions = {name: _put_if_needed(ssm, name, value, kind) for name, value, kind in parameters}
    print(json.dumps({"status": "enabled_in_ssm" if args.enable else "staged_disabled", "parameter_versions": versions}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ClientError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"google-auth-staging: {type(exc).__name__}; no credential values printed", file=sys.stderr)
        raise SystemExit(1) from None
