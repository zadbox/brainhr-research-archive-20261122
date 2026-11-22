from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlparse, urlunparse

import psycopg

TABLES = [
    "tenants",
    "enterprises",
    "projects",
    "users",
    "memberships",
    "access_grants",
    "cv_meta",
    "interview_sheets",
    "interview_appointments",
    "realtime_interviews",
    "tenant_cv_templates",
    "audit_logs",
    "integration_accounts",
    "outbound_events",
    "delivery_attempts",
    "webhook_subscriptions",
    "alembic_version",
]


def to_libpq_url(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    scheme = parsed.scheme
    if scheme == "postgresql+psycopg":
        scheme = "postgresql"
    elif scheme == "postgres+psycopg":
        scheme = "postgres"
    return urlunparse(parsed._replace(scheme=scheme))


def table_count(conn: psycopg.Connection, table_name: str) -> dict[str, int | bool]:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table_name,))
        exists = cur.fetchone()[0] is not None
        if not exists:
            return {"exists": False, "count": 0}
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        count = int(cur.fetchone()[0])
        return {"exists": True, "count": count}


def collect_counts(database_url: str) -> dict[str, dict[str, int | bool]]:
    with psycopg.connect(to_libpq_url(database_url)) as conn:
        return {table: table_count(conn, table) for table in TABLES}


def main() -> int:
    source_url = os.getenv("SOURCE_DATABASE_URL")
    target_url = os.getenv("TARGET_DATABASE_URL")
    if not source_url or not target_url:
        raise SystemExit("SOURCE_DATABASE_URL and TARGET_DATABASE_URL are required")

    source_counts = collect_counts(source_url)
    target_counts = collect_counts(target_url)

    mismatches: list[dict[str, object]] = []
    for table in TABLES:
        source_info = source_counts[table]
        target_info = target_counts[table]
        if source_info != target_info:
            mismatches.append(
                {
                    "table": table,
                    "source": source_info,
                    "target": target_info,
                }
            )

    payload = {
        "status": "ok" if not mismatches else "mismatch",
        "tables": {table: {"source": source_counts[table], "target": target_counts[table]} for table in TABLES},
        "mismatches": mismatches,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
