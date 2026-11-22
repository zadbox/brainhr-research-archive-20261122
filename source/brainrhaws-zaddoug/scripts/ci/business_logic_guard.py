#!/usr/bin/env python3
"""Fail closed when a release changes protected BrainRH business behavior.

The internal light-release circuit may consume an explicit, versioned owner
authorization.  The authorization is bound to an immutable business-change SHA,
its base SHA, exact protected paths and zero-tolerance business invariants.  It is
an audit record; Git and AWS permissions remain the actual identity boundaries.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


class RegistryError(ValueError):
    """The protection registry cannot be trusted."""


@dataclass(frozen=True)
class Rule:
    category: str
    exact_paths: frozenset[str]
    prefixes: tuple[str, ...]
    allow_initial_add: bool

    def matches(self, path: str) -> bool:
        return path in self.exact_paths or any(path.startswith(prefix) for prefix in self.prefixes)


@dataclass(frozen=True)
class Change:
    status: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Violation:
    status: str
    path: str
    category: str


@dataclass(frozen=True)
class OwnerAuthorization:
    base_sha: str
    authorized_sha: str
    protected_paths: frozenset[str]
    governance_paths: frozenset[str]
    required_tests: tuple[str, ...]


def normalize_repo_path(raw_path: str) -> str:
    value = raw_path.strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    candidate = PurePosixPath(value)
    if not value or candidate.is_absolute() or ".." in candidate.parts:
        raise RegistryError(f"unsafe repository path: {raw_path!r}")
    return candidate.as_posix()


def _string_list(value: object, field: str, category: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RegistryError(f"{category}.{field} must be a list of strings")
    return value


def load_registry(path: Path) -> list[Rule]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read registry {path}: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RegistryError("registry schema_version must be 1")
    if payload.get("default_policy") != "allow_unmatched":
        raise RegistryError("registry default_policy must be allow_unmatched")
    if payload.get("authorization") != "external_only":
        raise RegistryError("registry authorization must be external_only")
    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise RegistryError("registry rules must be a non-empty list")

    rules: list[Rule] = []
    categories: set[str] = set()
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            raise RegistryError("each registry rule must be an object")
        category = raw_rule.get("category")
        if not isinstance(category, str) or not category.strip() or category in categories:
            raise RegistryError(f"invalid or duplicate rule category: {category!r}")
        categories.add(category)
        exact = {
            normalize_repo_path(item)
            for item in _string_list(raw_rule.get("exact_paths"), "exact_paths", category)
        }
        prefixes = tuple(
            normalize_repo_path(item).rstrip("/") + "/"
            for item in _string_list(raw_rule.get("prefixes"), "prefixes", category)
        )
        allow_initial_add = raw_rule.get("allow_initial_add")
        if not isinstance(allow_initial_add, bool):
            raise RegistryError(f"{category}.allow_initial_add must be a boolean")
        if not exact and not prefixes:
            raise RegistryError(f"{category} must protect at least one path")
        rules.append(
            Rule(
                category=category,
                exact_paths=frozenset(exact),
                prefixes=prefixes,
                allow_initial_add=allow_initial_add,
            )
        )
    return rules


def parse_name_status(output: str) -> list[Change]:
    changes: list[Change] = []
    for line_number, raw_line in enumerate(output.splitlines(), start=1):
        if not raw_line.strip():
            continue
        fields = raw_line.split("\t")
        status = fields[0]
        code = status[:1]
        expected_paths = 2 if code in {"R", "C"} else 1
        if code not in {"A", "M", "D", "R", "C", "T", "U", "X", "B"}:
            raise RegistryError(f"unsupported git status {status!r} on line {line_number}")
        if len(fields) != expected_paths + 1:
            raise RegistryError(f"malformed git name-status line {line_number}: {raw_line!r}")
        changes.append(
            Change(status=code, paths=tuple(normalize_repo_path(value) for value in fields[1:]))
        )
    return changes


def collect_git_changes(repo: Path, base_ref: str, head_ref: str) -> list[Change]:
    command = ["git", "diff", "--name-status", "-M", base_ref, head_ref, "--"]
    completed = subprocess.run(command, cwd=repo, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown git diff error"
        raise RegistryError(f"git diff failed: {detail}")
    return parse_name_status(completed.stdout)


def resolve_sha(repo: Path, ref: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RegistryError(f"cannot resolve commit: {ref}")
    return completed.stdout.strip()


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo,
        capture_output=True,
        check=False,
    ).returncode == 0


def load_owner_authorization(path: Path) -> OwnerAuthorization:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read owner authorization {path}: {exc}") from exc

    expected_fields = {
        "schema_version",
        "authorization_type",
        "authorization_id",
        "repository",
        "base_sha",
        "authorized_sha",
        "protected_paths",
        "governance_paths",
        "authorized_behavior",
        "expected_result",
        "tolerances",
        "required_tests",
        "approval",
    }
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise RegistryError("owner authorization fields do not match schema version 1")
    if payload.get("schema_version") != 1 or payload.get("authorization_type") != "owner_light_release":
        raise RegistryError("unsupported owner authorization type or schema")
    if payload.get("repository") != "SamAI10/brainrhaws":
        raise RegistryError("owner authorization repository mismatch")
    for field in ("authorization_id", "authorized_behavior", "expected_result"):
        if not isinstance(payload.get(field), str) or len(payload[field].strip()) < 12:
            raise RegistryError(f"owner authorization {field} is invalid")
    for field in ("base_sha", "authorized_sha"):
        value = payload.get(field)
        if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
            raise RegistryError(f"owner authorization {field} must be a full lowercase SHA")

    def path_set(field: str, *, allow_empty: bool = False) -> frozenset[str]:
        raw = payload.get(field)
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise RegistryError(f"owner authorization {field} must be a list of paths")
        normalized = frozenset(normalize_repo_path(item) for item in raw)
        if (not normalized and not allow_empty) or len(normalized) != len(raw):
            raise RegistryError(f"owner authorization {field} is empty or contains duplicates")
        return normalized

    tolerances = payload.get("tolerances")
    if tolerances != {
        "ranking_changes_allowed": False,
        "score_delta_max": 0,
        "output_contract_changes_allowed": False,
    }:
        raise RegistryError("owner authorization must preserve ranking, scores and output contracts")
    approval = payload.get("approval")
    if not isinstance(approval, dict) or set(approval) != {"approved_by", "approved_at", "source"}:
        raise RegistryError("owner authorization approval metadata is invalid")
    if approval.get("approved_by") != "Oussam — propriétaire BrainRH":
        raise RegistryError("owner authorization approver is not the BrainRH owner")
    if approval.get("source") != "explicit_codex_conversation":
        raise RegistryError("owner authorization source is invalid")
    if not isinstance(approval.get("approved_at"), str) or not approval["approved_at"].endswith("Z"):
        raise RegistryError("owner authorization approved_at must be UTC")

    required_tests = tuple(path_set("required_tests"))
    return OwnerAuthorization(
        base_sha=payload["base_sha"],
        authorized_sha=payload["authorized_sha"],
        protected_paths=path_set("protected_paths"),
        governance_paths=path_set("governance_paths", allow_empty=True),
        required_tests=required_tests,
    )


def authorize_violations(
    repo: Path,
    base_ref: str,
    head_ref: str,
    violations: Sequence[Violation],
    authorization: OwnerAuthorization,
) -> None:
    base_sha = resolve_sha(repo, base_ref)
    head_sha = resolve_sha(repo, head_ref)
    if base_sha != authorization.base_sha:
        raise RegistryError("owner authorization base SHA does not match the inspected base")
    if not is_ancestor(repo, base_sha, authorization.authorized_sha):
        raise RegistryError("authorized SHA is not descended from the approved base")
    if not is_ancestor(repo, authorization.authorized_sha, head_sha):
        raise RegistryError("release HEAD is not descended from the authorized SHA")

    approved = authorization.protected_paths | authorization.governance_paths
    actual = frozenset(item.path for item in violations)
    if actual != approved:
        raise RegistryError(
            f"protected paths differ from owner authorization: actual={sorted(actual)!r} approved={sorted(approved)!r}"
        )

    before = collect_git_changes(repo, base_sha, authorization.authorized_sha)
    before_paths = frozenset(path for change in before for path in change.paths if path in approved)
    if before_paths != authorization.protected_paths:
        raise RegistryError("business-change SHA does not contain exactly the authorized protected paths")
    after = collect_git_changes(repo, authorization.authorized_sha, head_sha)
    after_paths = frozenset(path for change in after for path in change.paths if path in approved)
    if after_paths != authorization.governance_paths:
        raise RegistryError("post-authorization commits are not limited to the approved governance paths")
    missing_tests = [path for path in authorization.required_tests if not (repo / path).is_file()]
    if missing_tests:
        raise RegistryError(f"required authorization tests are missing: {missing_tests!r}")


def evaluate_changes(changes: Iterable[Change], rules: Sequence[Rule]) -> list[Violation]:
    violations: list[Violation] = []
    for change in changes:
        for path in change.paths:
            matches = [rule for rule in rules if rule.matches(path)]
            for rule in matches:
                if change.status == "A" and rule.allow_initial_add:
                    continue
                violations.append(
                    Violation(status=change.status, path=path, category=rule.category)
                )
    return violations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--owner-authorization", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rules = load_registry(args.registry)
        changes = collect_git_changes(args.repo, args.base_ref, args.head_ref)
        violations = evaluate_changes(changes, rules)
        if violations and args.owner_authorization:
            authorization = load_owner_authorization(args.owner_authorization)
            authorize_violations(
                args.repo,
                args.base_ref,
                args.head_ref,
                violations,
                authorization,
            )
            print(
                "business-logic-guard: explicit owner authorization accepted "
                f"for {authorization.authorized_sha}"
            )
            return 0
    except RegistryError as exc:
        print(f"business-logic-guard: configuration error: {exc}", file=sys.stderr)
        return 2

    if violations:
        print("business-logic-guard: protected changes require explicit external authorization", file=sys.stderr)
        for violation in violations:
            print(
                f"- status={violation.status} category={violation.category} path={violation.path}",
                file=sys.stderr,
            )
        return 1

    print(f"business-logic-guard: OK ({len(changes)} changed entries inspected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
