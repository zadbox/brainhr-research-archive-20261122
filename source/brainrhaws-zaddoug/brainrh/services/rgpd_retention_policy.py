"""Fail-closed runtime contract for configurable RGPD retention.

This module validates policy configuration only.  It never schedules, mutates,
anonymises or deletes candidate data.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping

from brainrh.services.rgpd_erasure_inventory import SCOPE_VERSION


RETENTION_MODES = frozenset({"disabled", "inventory", "enforce"})
ERASURE_SCOPE_COMPLETE = False
AUTOMATIC_ERASURE_IMPLEMENTED = False
RETENTION_DURATION_FIELDS = (
    "BRAINRH_RGPD_CANDIDATE_ACTIVE_DAYS",
    "BRAINRH_RGPD_RESUME_PROJECT_DAYS",
    "BRAINRH_RGPD_MATCHING_EXPORT_DAYS",
    "BRAINRH_RGPD_INTERVIEW_ARTIFACT_DAYS",
    "BRAINRH_RGPD_REALTIME_APPOINTMENT_DAYS",
    "BRAINRH_RGPD_WEBHOOK_DELIVERY_DAYS",
    "BRAINRH_RGPD_PROVIDER_COPY_DAYS",
    "BRAINRH_RGPD_AUDIT_LOG_DAYS",
    "BRAINRH_RGPD_BACKUP_EXTINCTION_DAYS",
    "BRAINRH_RGPD_LEGAL_HOLD_MAX_DAYS",
)
# Compatibility alias for existing callers. It is a configuration catalogue,
# not a list consumed by a deletion job.
DAY_FIELDS = RETENTION_DURATION_FIELDS


class RetentionPolicyError(RuntimeError):
    """Raised when the retention switch is incomplete or unsafe."""


@dataclass(frozen=True)
class RetentionPolicy:
    mode: str
    policy_version: str | None
    approval_id: str | None
    durations_days: tuple[tuple[str, int], ...]
    scope_version: str
    scope_complete: bool

    @property
    def policy_configured(self) -> bool:
        return bool(
            self.policy_version
            and self.approval_id
            and len(self.durations_days) == len(DAY_FIELDS)
        )

    @property
    def automatic_erasure_enabled(self) -> bool:
        return (
            self.mode == "enforce"
            and AUTOMATIC_ERASURE_IMPLEMENTED
            and self.scope_complete
            and self.policy_configured
        )

    def sanitized_state(self) -> dict[str, object]:
        execution = {
            "disabled": "none",
            "inventory": "read_only_inventory",
            "enforce": "unavailable",
        }[self.mode]
        return {
            "status": "ok",
            "mode": self.mode,
            "execution": execution,
            "automatic_erasure_enabled": self.automatic_erasure_enabled,
            "data_mutation_enabled": False,
            "automatic_erasure_implemented": AUTOMATIC_ERASURE_IMPLEMENTED,
            "enforcement_available": (
                AUTOMATIC_ERASURE_IMPLEMENTED and self.scope_complete
            ),
            "policy_configured": self.policy_configured,
            "approval_configured": bool(self.approval_id),
            "durations_configured": len(self.durations_days) == len(DAY_FIELDS),
            "configured_duration_count": len(self.durations_days),
            "required_duration_count": len(DAY_FIELDS),
            "scope_version": self.scope_version,
            "scope_complete": self.scope_complete,
        }


def _value(source: Mapping[str, str], name: str) -> str | None:
    value = str(source.get(name, "")).strip()
    return value or None


def _parse_days(source: Mapping[str, str]) -> tuple[tuple[str, int], ...]:
    configured = [(name, _value(source, name)) for name in DAY_FIELDS]
    present_count = sum(value is not None for _, value in configured)
    if present_count not in {0, len(DAY_FIELDS)}:
        raise RetentionPolicyError(
            "RGPD retention durations must be either all unset or all configured"
        )

    parsed: list[tuple[str, int]] = []
    for name, raw_value in configured:
        if raw_value is None:
            continue
        try:
            days = int(raw_value)
        except ValueError as exc:
            raise RetentionPolicyError("RGPD retention duration must be an integer") from exc
        if not 1 <= days <= 36_500:
            raise RetentionPolicyError(
                "RGPD retention duration is outside the technical 1..36500 day range"
            )
        parsed.append((name, days))
    return tuple(parsed)


def load_retention_policy(
    source: Mapping[str, str] | None = None,
    *,
    production: bool,
) -> RetentionPolicy:
    """Load the switch without silently accepting partial or unknown values."""

    values = os.environ if source is None else source
    default_mode = "inventory" if production else "disabled"
    mode = (_value(values, "BRAINRH_RGPD_RETENTION_MODE") or default_mode).lower()
    if mode not in RETENTION_MODES:
        raise RetentionPolicyError(
            "BRAINRH_RGPD_RETENTION_MODE must be disabled, inventory or enforce"
        )

    policy_version = _value(values, "BRAINRH_RGPD_POLICY_VERSION")
    approval_id = _value(values, "BRAINRH_RGPD_POLICY_APPROVAL_ID")
    durations = _parse_days(values)
    any_policy_value = bool(policy_version or approval_id or durations)

    if mode == "disabled" and any_policy_value:
        raise RetentionPolicyError(
            "Disabled RGPD retention mode must not carry an ignored policy configuration"
        )

    if mode in {"inventory", "enforce"}:
        policy_parts = (
            bool(policy_version),
            bool(approval_id),
            len(durations) == len(DAY_FIELDS),
        )
        if any(policy_parts) and not all(policy_parts):
            raise RetentionPolicyError(
                "RGPD policy version, approval and all durations must be configured together"
            )

    policy = RetentionPolicy(
        mode=mode,
        policy_version=policy_version,
        approval_id=approval_id,
        durations_days=durations,
        scope_version=SCOPE_VERSION,
        scope_complete=ERASURE_SCOPE_COMPLETE,
    )
    if mode == "enforce" and not policy.policy_configured:
        raise RetentionPolicyError(
            "RGPD enforce mode requires an approved and complete retention policy"
        )
    if mode == "enforce" and not AUTOMATIC_ERASURE_IMPLEMENTED:
        raise RetentionPolicyError(
            "RGPD enforce mode is unavailable because automatic erasure is not implemented"
        )
    if mode == "enforce" and not policy.scope_complete:
        raise RetentionPolicyError(
            "RGPD enforce mode is unavailable while the erasure store scope is incomplete"
        )
    return policy
