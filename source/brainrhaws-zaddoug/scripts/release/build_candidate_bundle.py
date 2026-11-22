#!/usr/bin/env python3
"""Build and validate an unsigned, non-promotable release evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence


SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_PATTERN = re.compile(
    r"^(?P<registry>[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com)/"
    r"(?P<repository>[a-z0-9]+(?:[._/-][a-z0-9]+)*)@(?P<digest>sha256:[0-9a-f]{64})$"
)
EXPECTED_GATES = {
    "business_logic_guard": "business-logic-guard.yml",
    "migration_contract": "migration-contract.yml",
    "security_baseline": "security-baseline.yml",
}
SCAN_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


class BundleError(ValueError):
    """Candidate evidence is incomplete or internally inconsistent."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"cannot read JSON evidence {path}: {exc}") from exc


def require_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise BundleError(f"gate evidence field {field!r} must be a non-empty string")
    return value


def validate_gate(
    path: Path,
    *,
    gate_name: str,
    expected_workflow: str,
    candidate_sha: str,
) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise BundleError(f"gate evidence {path} must be a JSON object")

    workflow_file = require_string(payload, "workflow_file")
    if workflow_file != expected_workflow:
        raise BundleError(
            f"{gate_name} evidence references {workflow_file!r}, expected {expected_workflow!r}"
        )
    if require_string(payload, "head_sha") != candidate_sha:
        raise BundleError(f"{gate_name} evidence does not match candidate SHA")
    if require_string(payload, "event") != "push":
        raise BundleError(f"{gate_name} evidence must come from a push run")
    if require_string(payload, "status") != "completed":
        raise BundleError(f"{gate_name} run is not completed")
    if require_string(payload, "conclusion") != "success":
        raise BundleError(f"{gate_name} run did not conclude successfully")

    normalized: dict[str, Any] = {
        "conclusion": "success",
        "event": "push",
        "head_sha": candidate_sha,
        "status": "completed",
        "url": require_string(payload, "url"),
        "workflow_file": workflow_file,
    }
    for field in ("run_attempt", "run_id", "run_number"):
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise BundleError(f"gate evidence field {field!r} must be a positive integer")
        normalized[field] = value
    if gate_name == "security_baseline":
        normalized["assurance"] = {
            "dependency_vulnerability_absence_attested": False,
            "scope": "repository-security-controls",
        }
    return normalized


def validate_image(reference: str, expected_repository: str) -> dict[str, str]:
    match = IMAGE_PATTERN.fullmatch(reference)
    if not match:
        raise BundleError(f"invalid immutable ECR image reference: {reference!r}")
    if match.group("repository") != expected_repository:
        raise BundleError(
            f"image repository {match.group('repository')!r} does not match "
            f"{expected_repository!r}"
        )
    digest = match.group("digest")
    if not DIGEST_PATTERN.fullmatch(digest):
        raise BundleError(f"invalid image digest: {digest!r}")
    return {
        "digest": digest,
        "reference": reference,
        "repository": expected_repository,
    }


def validate_scan(
    path: Path,
    *,
    service: str,
    expected_repository: str,
    expected_digest: str,
) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise BundleError(f"ECR scan evidence {path} must be a JSON object")
    if payload.get("repositoryName") != expected_repository:
        raise BundleError(f"{service} scan evidence references the wrong repository")

    image_id = payload.get("imageId")
    if not isinstance(image_id, dict) or image_id.get("imageDigest") != expected_digest:
        raise BundleError(f"{service} scan evidence does not match the immutable image digest")
    scan_status = payload.get("imageScanStatus")
    if not isinstance(scan_status, dict) or scan_status.get("status") != "COMPLETE":
        raise BundleError(f"{service} ECR scan is not COMPLETE")

    scan_findings = payload.get("imageScanFindings")
    if not isinstance(scan_findings, dict):
        raise BundleError(f"{service} ECR scan findings are missing")
    raw_counts = scan_findings.get("findingSeverityCounts", {})
    if not isinstance(raw_counts, dict):
        raise BundleError(f"{service} ECR severity counts must be an object")
    counts: dict[str, int] = {}
    for severity in SCAN_SEVERITIES:
        value = raw_counts.get(severity, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise BundleError(f"{service} ECR {severity} count must be a non-negative integer")
        counts[severity] = value
    if counts["CRITICAL"] or counts["HIGH"]:
        raise BundleError(f"{service} ECR scan contains HIGH or CRITICAL findings")
    return {
        "digest": expected_digest,
        "finding_severity_counts": counts,
        "repository": expected_repository,
        "status": "COMPLETE",
    }


def positive_numeric_id(value: str, field: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise BundleError(f"{field} must be a positive decimal integer without leading zeroes")
    return int(value)


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--repository-owner-id", required=True)
    parser.add_argument("--source-ref", default="refs/heads/main")
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--migration-tree-fingerprint", required=True)
    parser.add_argument("--business-gate", type=Path, required=True)
    parser.add_argument("--migration-gate", type=Path)
    parser.add_argument("--security-gate", type=Path, required=True)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--backend-repository", required=True)
    parser.add_argument("--backend-scan", type=Path, required=True)
    parser.add_argument("--worker-video-image", required=True)
    parser.add_argument("--worker-video-repository", required=True)
    parser.add_argument("--worker-video-scan", type=Path, required=True)
    parser.add_argument("--frontend-image", required=True)
    parser.add_argument("--frontend-repository", required=True)
    parser.add_argument("--frontend-scan", type=Path, required=True)
    parser.add_argument("--producer-run-id", type=int, required=True)
    parser.add_argument("--producer-run-attempt", type=int, required=True)
    parser.add_argument("--producer-workflow-ref", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not SHA_PATTERN.fullmatch(args.candidate_sha):
            raise BundleError("candidate SHA must be 40 lowercase hexadecimal characters")
        repository_id = positive_numeric_id(args.repository_id, "repository_id")
        repository_owner_id = positive_numeric_id(
            args.repository_owner_id, "repository_owner_id"
        )
        if args.source_ref != "refs/heads/main":
            raise BundleError("source ref must be refs/heads/main")
        if args.producer_run_id < 1 or args.producer_run_attempt < 1:
            raise BundleError("producer run identifiers must be positive integers")
        if args.migration_tree_fingerprint != "NONE" and not re.fullmatch(
            r"sha256:[0-9a-f]{64}", args.migration_tree_fingerprint
        ):
            raise BundleError("migration tree fingerprint must be NONE or a sha256 digest")
        if not args.source_archive.is_file():
            raise BundleError(f"source archive does not exist: {args.source_archive}")

        source_digest = sha256_file(args.source_archive)
        gates = {
            "business_logic_guard": validate_gate(
                args.business_gate,
                gate_name="business_logic_guard",
                expected_workflow=EXPECTED_GATES["business_logic_guard"],
                candidate_sha=args.candidate_sha,
            ),
            "security_baseline": validate_gate(
                args.security_gate,
                gate_name="security_baseline",
                expected_workflow=EXPECTED_GATES["security_baseline"],
                candidate_sha=args.candidate_sha,
            ),
        }
        if args.migration_gate is not None:
            gates["migration_contract"] = validate_gate(
                args.migration_gate,
                gate_name="migration_contract",
                expected_workflow=EXPECTED_GATES["migration_contract"],
                candidate_sha=args.candidate_sha,
            )
        images = {
            "backend": validate_image(args.backend_image, args.backend_repository),
            "frontend": validate_image(args.frontend_image, args.frontend_repository),
            "worker_video": validate_image(
                args.worker_video_image, args.worker_video_repository
            ),
        }
        scans = {
            "backend": validate_scan(
                args.backend_scan,
                service="backend",
                expected_repository=args.backend_repository,
                expected_digest=images["backend"]["digest"],
            ),
            "frontend": validate_scan(
                args.frontend_scan,
                service="frontend",
                expected_repository=args.frontend_repository,
                expected_digest=images["frontend"]["digest"],
            ),
            "worker_video": validate_scan(
                args.worker_video_scan,
                service="worker_video",
                expected_repository=args.worker_video_repository,
                expected_digest=images["worker_video"]["digest"],
            ),
        }

        archive_name = args.source_archive.name
        manifest = {
            "candidate_status": "unsigned-unpromotable",
            "gates": gates,
            "images": images,
            "producer": {
                "run_attempt": args.producer_run_attempt,
                "run_id": args.producer_run_id,
                "workflow_ref": args.producer_workflow_ref,
            },
            "schema_version": 1,
            "scans": scans,
            "source": {
                "archive": archive_name,
                "archive_sha256": source_digest,
                "commit_sha": args.candidate_sha,
                "migration_tree": {
                    "fingerprint": args.migration_tree_fingerprint,
                    "path": "alembic/versions",
                },
                "ref": args.source_ref,
                "repository": args.repository,
                "repository_id": repository_id,
                "repository_owner_id": repository_owner_id,
            },
        }

        args.output_dir.mkdir(parents=True, exist_ok=False)
        target_archive = args.output_dir / archive_name
        args.source_archive.replace(target_archive)
        (args.output_dir / f"{archive_name}.sha256").write_text(
            f"{source_digest}  {archive_name}\n", encoding="ascii"
        )
        (args.output_dir / "release-manifest.json").write_bytes(canonical_json(manifest))
    except (BundleError, OSError) as exc:
        print(f"candidate-bundle: {exc}", file=sys.stderr)
        return 2

    print(f"candidate-bundle: wrote unsigned evidence bundle to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
