#!/usr/bin/env python3
"""Report the sanitized RGPD retention switch state without mutating data."""

from __future__ import annotations

import json

from brainrh.services.rgpd_retention_policy import (
    RetentionPolicyError,
    load_retention_policy,
)
from brainrh.settings import is_production


def main() -> int:
    try:
        policy = load_retention_policy(production=is_production())
    except RetentionPolicyError:
        print(json.dumps({"status": "REFUSED", "reason": "INVALID_RGPD_POLICY"}))
        return 2

    print(json.dumps(policy.sanitized_state(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
