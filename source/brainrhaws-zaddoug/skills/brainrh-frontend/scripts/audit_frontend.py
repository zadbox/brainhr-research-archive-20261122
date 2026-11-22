#!/usr/bin/env python3
"""Report frontend patterns that deserve human review.

The default mode reports findings without failing so the tool can be introduced
on an existing codebase. Use --strict for new or already-clean surfaces.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_ROOT = REPO_ROOT / "frontend"
TEXT_SUFFIXES = {".ts", ".tsx", ".css"}
PATTERNS = {
    "raw color": re.compile(r"(?<![\w-])#[0-9a-fA-F]{3,8}\b"),
    "large radius": re.compile(r"\brounded-3xl\b"),
    "decorative gradient": re.compile(r"\bbg-gradient-to-[a-z]+\b"),
    "heavy blur": re.compile(r"\bbackdrop-blur-(?:lg|xl|2xl|3xl)\b"),
}


def git_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", "frontend"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        raw = line[3:]
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        path = REPO_ROOT / raw
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            paths.append(path)
    return sorted(set(paths))


def all_paths() -> list[Path]:
    return sorted(
        path
        for path in (FRONTEND_ROOT / "src").rglob("*")
        if path.is_file() and path.suffix in TEXT_SUFFIXES
    )


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def inspect(path: Path) -> list[tuple[int, str, str]]:
    text = path.read_text(encoding="utf-8")
    findings: list[tuple[int, str, str]] = []
    relative_path = relative(path)

    for line_number, line in enumerate(text.splitlines(), start=1):
        for label, pattern in PATTERNS.items():
            if label == "raw color" and relative_path == "frontend/src/index.css":
                continue
            if pattern.search(line):
                findings.append((line_number, label, line.strip()[:160]))

    if path.suffix == ".tsx" and "/pages/" in path.as_posix():
        if "useI18n" not in text:
            findings.append((1, "page without useI18n", "verify that every visible label is translated"))

    line_count = text.count("\n") + 1
    if line_count > 700 and relative_path != "frontend/src/i18n/messages.ts":
        findings.append((1, "large source file", f"{line_count} lines; review component boundaries"))

    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="scan all frontend source files")
    parser.add_argument("--strict", action="store_true", help="return a failure when findings exist")
    parser.add_argument("paths", nargs="*", help="specific repository-relative files")
    args = parser.parse_args()

    if args.paths:
        paths = [REPO_ROOT / raw for raw in args.paths]
    elif args.all:
        paths = all_paths()
    else:
        paths = git_paths()

    paths = [path for path in paths if path.is_file() and path.suffix in TEXT_SUFFIXES]
    total = 0

    if not paths:
        print("Frontend quality inventory: no changed frontend source files.")
        return 0

    for path in paths:
        findings = inspect(path)
        if not findings:
            continue
        print(f"\n{relative(path)}")
        for line_number, label, excerpt in findings:
            total += 1
            print(f"  L{line_number}: {label}: {excerpt}")

    print(f"\nFrontend quality inventory: {len(paths)} file(s), {total} finding(s).")
    print("Findings require review; they are not automatic defects.")
    return 1 if args.strict and total else 0


if __name__ == "__main__":
    raise SystemExit(main())
