#!/usr/bin/env python3
"""Write a validated, metadata-only proof for one versioned S3 database dump."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ACCOUNT_PATTERN = re.compile(r"^[0-9]{12}$")
BACKUP_KEY_PATTERN = re.compile(
    r"^postgres/(daily|weekly)/postgres-[0-9]{8}T[0-9]{6}Z\.sql\.gz$"
)
TIMESTAMP_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def require_opaque_version_id(value: str) -> str:
    if not value or value == "None" or len(value) > 1024:
        raise ValueError("S3 VersionId is missing or invalid")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("S3 VersionId contains whitespace or control characters")
    return value


def build_manifest(args: argparse.Namespace) -> dict[str, object]:
    identity = json.loads(args.identity_file.read_text(encoding="utf-8"))
    account = identity.get("Account")
    arn = identity.get("Arn")

    if not isinstance(account, str) or not ACCOUNT_PATTERN.fullmatch(account):
        raise ValueError("AWS caller account must be a 12-digit account ID")
    if not isinstance(arn, str) or not arn.startswith("arn:aws:"):
        raise ValueError("AWS caller ARN is missing or invalid")
    if not TIMESTAMP_PATTERN.fullmatch(args.created_at):
        raise ValueError("created_at must use YYYYMMDDTHHMMSSZ")
    if not BACKUP_KEY_PATTERN.fullmatch(args.object_key):
        raise ValueError("backup object key is outside the approved daily/weekly prefixes")
    if args.size_bytes <= 0:
        raise ValueError("backup size must be positive")
    if not SHA256_PATTERN.fullmatch(args.sha256):
        raise ValueError("backup SHA-256 must be 64 lowercase hexadecimal characters")
    if args.release_commit and not COMMIT_PATTERN.fullmatch(args.release_commit):
        raise ValueError("release commit must be empty or a full lowercase Git SHA")
    if args.release_ref and args.release_ref != "origin/main":
        raise ValueError("release ref must be empty or origin/main")

    return {
        "schema_version": 2,
        "created_at": args.created_at,
        "database": args.database,
        "object": {
            "bucket": args.bucket,
            "key": args.object_key,
            "version_id": require_opaque_version_id(args.object_version_id),
            "size_bytes": args.size_bytes,
            "sha256": args.sha256,
        },
        "aws_identity": {"account": account, "arn": arn},
        "release_commit": args.release_commit or None,
        "release_ref": args.release_ref or None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--identity-file", type=Path, required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--object-key", required=True)
    parser.add_argument("--object-version-id", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--size-bytes", type=int, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--release-commit", default="")
    parser.add_argument("--release-ref", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_manifest(args)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
