#!/usr/bin/env python3
"""Print a tenant-scoped, read-only erasure inventory without PII content."""

from __future__ import annotations

import argparse
import json

from sqlmodel import Session

from brainrh.database import engine
from brainrh.services.rgpd_erasure_inventory import (
    SubjectNotFoundError,
    begin_read_only_snapshot,
    build_erasure_inventory,
)
from brainrh.services.storage_service import get_storage_service


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enterprise-id", required=True)
    parser.add_argument("--talent-profile-id", required=True, type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if engine.dialect.name != "postgresql":
        print(json.dumps({"status": "REFUSED", "reason": "POSTGRESQL_REQUIRED"}))
        return 2

    try:
        with Session(engine) as session:
            begin_read_only_snapshot(session)
            report = build_erasure_inventory(
                session,
                get_storage_service(),
                enterprise_id=args.enterprise_id,
                talent_profile_id=args.talent_profile_id,
            )
            session.rollback()
    except SubjectNotFoundError:
        print(json.dumps({"status": "NOT_FOUND"}))
        return 3
    except Exception:
        print(json.dumps({"status": "FAILED", "reason": "INVENTORY_ERROR"}))
        return 1

    print(json.dumps(report.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
