#!/usr/bin/env python3
"""Enforce append-only, single-head Alembic history between immutable Git refs."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Any


VERSIONS_PREFIX = "alembic/versions/"


class ContractError(RuntimeError):
    """Raised when the migration history violates the production contract."""


@dataclass(frozen=True)
class Revision:
    revision: str
    down_revision: str | None
    path: str


def run_git(repo: Path, *args: str) -> bytes:
    process = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise ContractError(f"git {' '.join(args)} failed: {detail}")
    return process.stdout


def resolve_commit(repo: Path, ref: str) -> str:
    resolved = run_git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    value = resolved.decode("ascii").strip()
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"invalid immutable commit for {ref!r}")
    return value


def migration_tree(repo: Path, ref: str) -> dict[str, str]:
    raw = run_git(
        repo,
        "ls-tree",
        "-rz",
        "--full-tree",
        ref,
        "--",
        "alembic/versions",
    )
    entries: dict[str, str] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, path_bytes = record.split(b"\t", 1)
        _mode, object_type, object_id = metadata.decode("ascii").split()
        path = path_bytes.decode("utf-8")
        if object_type != "blob" or not path.endswith(".py") or path.endswith("/__init__.py"):
            continue
        entries[path] = object_id
    return entries


def compare_append_only(base_tree: dict[str, str], head_tree: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for path, base_object in sorted(base_tree.items()):
        head_object = head_tree.get(path)
        if head_object is None:
            errors.append(f"existing migration removed or renamed: {path}")
        elif head_object != base_object:
            errors.append(f"existing migration modified: {path}")
    return errors


def assignment_value(module: ast.Module, name: str, path: str) -> Any:
    matches: list[ast.expr] = []
    for node in module.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and target.id == name and value is not None:
            matches.append(value)
    if not matches:
        raise ContractError(f"{path}: missing {name}")
    if len(matches) != 1:
        raise ContractError(f"{path}: duplicate assignment for {name}")
    try:
        return ast.literal_eval(matches[0])
    except (ValueError, TypeError) as exc:
        raise ContractError(f"{path}: {name} must be a literal") from exc


def parse_revision(path: str, source: str) -> Revision:
    try:
        module = ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise ContractError(f"{path}: invalid Python: {exc}") from exc

    functions = {
        node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = {"upgrade", "downgrade"} - functions
    if missing:
        raise ContractError(f"{path}: missing function(s): {', '.join(sorted(missing))}")

    revision = assignment_value(module, "revision", path)
    down_revision = assignment_value(module, "down_revision", path)
    branch_labels = assignment_value(module, "branch_labels", path)
    depends_on = assignment_value(module, "depends_on", path)
    if not isinstance(revision, str) or not revision:
        raise ContractError(f"{path}: revision must be a non-empty string")
    if down_revision is not None and not isinstance(down_revision, str):
        raise ContractError(f"{path}: branches/merge revisions are not allowed")
    if branch_labels is not None:
        raise ContractError(f"{path}: branch_labels must be None")
    if depends_on is not None:
        raise ContractError(f"{path}: depends_on must be None")
    return Revision(revision=revision, down_revision=down_revision, path=path)


def load_revisions(repo: Path, ref: str, tree: dict[str, str]) -> list[Revision]:
    revisions: list[Revision] = []
    for path in sorted(tree):
        source = run_git(repo, "show", f"{ref}:{path}").decode("utf-8")
        revisions.append(parse_revision(path, source))
    return revisions


def validate_linear_graph(revisions: list[Revision]) -> str:
    if not revisions:
        raise ContractError("no Alembic revision found")
    by_id: dict[str, Revision] = {}
    for item in revisions:
        if item.revision in by_id:
            raise ContractError(f"duplicate revision id: {item.revision}")
        by_id[item.revision] = item

    roots = [item for item in revisions if item.down_revision is None]
    if len(roots) != 1:
        raise ContractError(f"expected exactly one root, found {len(roots)}")

    child_by_parent: dict[str, str] = {}
    for item in revisions:
        parent = item.down_revision
        if parent is None:
            continue
        if parent not in by_id:
            raise ContractError(f"{item.path}: unknown down_revision {parent}")
        if parent in child_by_parent:
            raise ContractError(
                f"branch detected after {parent}: {child_by_parent[parent]} and {item.revision}"
            )
        child_by_parent[parent] = item.revision

    heads = [item for item in revisions if item.revision not in child_by_parent]
    if len(heads) != 1:
        raise ContractError(f"expected exactly one head, found {len(heads)}")

    visited: set[str] = set()
    current: Revision | None = heads[0]
    while current is not None:
        if current.revision in visited:
            raise ContractError(f"cycle detected at {current.revision}")
        visited.add(current.revision)
        current = by_id.get(current.down_revision) if current.down_revision else None
    if len(visited) != len(revisions):
        raise ContractError("migration graph contains a disconnected revision")
    return heads[0].revision


def check_contract(repo: Path, base_ref: str, head_ref: str) -> tuple[str, int, int]:
    base = resolve_commit(repo, base_ref)
    head = resolve_commit(repo, head_ref)
    base_tree = migration_tree(repo, base)
    head_tree = migration_tree(repo, head)
    errors = compare_append_only(base_tree, head_tree)
    if errors:
        raise ContractError("\n".join(errors))
    revisions = load_revisions(repo, head, head_tree)
    head_revision = validate_linear_graph(revisions)
    return head_revision, len(base_tree), len(head_tree)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--repo", default=".")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        head_revision, base_count, head_count = check_contract(
            Path(args.repo).resolve(), args.base_ref, args.head_ref
        )
    except ContractError as exc:
        print(f"Migration contract rejected:\n{exc}", file=sys.stderr)
        return 1
    print(
        "Migration contract accepted: "
        f"base_revisions={base_count} head_revisions={head_count} head={head_revision}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
