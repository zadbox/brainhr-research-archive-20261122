#!/usr/bin/env python3
"""Run one exact Alembic transition under a PostgreSQL advisory lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text


def _revision(connection) -> str:
    return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _lock_key(name: str) -> int:
    value = int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "big")
    return value - (1 << 64) if value >= (1 << 63) else value


def _is_ancestor(config: Config, current: str, target: str) -> bool:
    """Return whether *current* is on a forward-only path to *target*."""
    scripts = ScriptDirectory.from_config(config)
    pending = [scripts.get_revision(target)]
    visited: set[str] = set()
    while pending:
        revision = pending.pop()
        if revision is None or revision.revision in visited:
            continue
        if revision.revision == current:
            return True
        visited.add(revision.revision)
        down_revisions = revision.down_revision
        if isinstance(down_revisions, str):
            down_revisions = (down_revisions,)
        for down_revision in down_revisions or ():
            pending.append(scripts.get_revision(down_revision))
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--lock-timeout", default="15s")
    parser.add_argument("--statement-timeout", default="5min")
    args = parser.parse_args(argv)

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+")):
        parser.error("DATABASE_URL must be PostgreSQL")

    repo_root = Path(__file__).resolve().parents[2]
    config = Config(str(repo_root / "alembic.ini"))
    engine = create_engine(database_url, pool_pre_ping=True)
    lock_key = _lock_key("brainrh:production:alembic")

    try:
        with engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('lock_timeout', :value, true)"),
                {"value": args.lock_timeout},
            )
            connection.execute(
                text("SELECT set_config('statement_timeout', :value, true)"),
                {"value": args.statement_timeout},
            )
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
            current = _revision(connection)
            if current == args.expected_head:
                print(json.dumps({"status": "already_at_head", "revision": current}))
                return 0
            if args.expected_base == "AUTO":
                if not _is_ancestor(config, current, args.expected_head):
                    raise RuntimeError(
                        f"database revision {current} is not an ancestor of {args.expected_head}"
                    )
            elif current != args.expected_base:
                raise RuntimeError(
                    f"unexpected database revision: expected {args.expected_base}, got {current}"
                )

            config.attributes["connection"] = connection
            command.upgrade(config, args.expected_head)
            final = _revision(connection)
            if final != args.expected_head:
                raise RuntimeError(
                    f"migration ended at {final}, expected {args.expected_head}"
                )
            print(
                json.dumps(
                    {
                        "status": "upgraded",
                        "from_revision": current,
                        "revision": final,
                    },
                    sort_keys=True,
                )
            )
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from None
