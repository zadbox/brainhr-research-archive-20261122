"""Update one existing Turnover IT draft by reference without creating a new job."""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from urllib.parse import quote

import httpx
import requests

from brainrh.services.turnover_it_service import SSMTokenStore, TURNOVER_API_BASE_URL


OLD_ORIGIN = "https://brainhr.braingentech.com"
NEW_ORIGIN = "https://app.brainhr.braingentech.com"
API_BASE = f"{NEW_ORIGIN}/api/v1"
STABLE_FIELDS = (
    "reference", "contract", "title", "description", "qualifications",
    "employerOverview", "experienceLevel", "startDate", "expiredAt", "skills",
    "durationInMonths", "renewable", "salary", "location", "remote",
    "applicationForm", "status",
)
REQUEST_FIELDS = set(STABLE_FIELDS) | {"recruiterAlias", "pushToTop"}


def fail(message: str) -> None:
    raise SystemExit(f"turnover-callback: {message}")


def own_api(session: requests.Session, path: str, *, params: dict | None = None):
    response = session.get(f"{API_BASE}{path}", params=params, timeout=15)
    if response.status_code != 200:
        fail(f"BrainRH read failed: HTTP {response.status_code}")
    return response.json()


def stable_view(job: dict) -> dict:
    view = {key: deepcopy(job.get(key)) for key in STABLE_FIELDS}
    if isinstance(view["description"], str):
        view["description"] = " ".join(view["description"].split())
    if view["experienceLevel"] == "":
        view["experienceLevel"] = None
    if isinstance(view["location"], dict):
        view["location"].pop("latitude", None)
        view["location"].pop("longitude", None)
    return view


def full_payload(job: dict, callback_url: str) -> dict:
    body = {key: deepcopy(value) for key, value in job.items() if key in REQUEST_FIELDS}
    if body.get("experienceLevel") == "":
        body["experienceLevel"] = None
    body["application"] = {"callbackUrl": callback_url}
    body["pushToTop"] = False
    if isinstance(body.get("location"), dict):
        body["location"].pop("latitude", None)
        body["location"].pop("longitude", None)
    required = ("reference", "contract", "title", "description", "location", "remote", "status")
    if any(not body.get(key) for key in required):
        fail("provider job has an incomplete full-update body")
    return body


def main(mode: str) -> None:
    if mode not in {"plan", "apply", "rollback"}:
        fail("mode must be plan, apply or rollback")
    email = os.getenv("SMOKE_LOGIN_EMAIL", "")
    password = os.getenv("SMOKE_LOGIN_PASSWORD", "")
    if not email or not password:
        fail("synthetic smoke account is unavailable")
    session = requests.Session()
    login = session.post(
        f"{API_BASE}/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    if login.status_code != 200:
        fail(f"synthetic login failed: HTTP {login.status_code}")

    scopes = own_api(session, "/talent-pool/scopes")
    tenant_ids = {scope["tenant_id"] for scope in scopes}
    configured: list[str] = []
    for tenant_id in tenant_ids:
        config = own_api(
            session, "/integrations/turnover-it/configuration",
            params={"tenant_id": tenant_id},
        )
        if config.get("configured"):
            configured.append(tenant_id)
    if len(configured) != 1:
        fail("expected exactly one configured Turnover IT client")
    tenant_id = configured[0]

    publications: list[dict] = []
    for project in own_api(session, "/projects", params={"tenant_id": tenant_id}):
        publications.extend(own_api(
            session,
            f"/integrations/turnover-it/publications/project/{quote(str(project['id']), safe='')}",
        ))
    old_publications = {
        str(row["id"]): row
        for row in publications
        if str(row.get("callback_url", "")).startswith(
            f"{OLD_ORIGIN}/api/v1/integrations/turnover-it/webhooks/"
        )
    }
    if len(old_publications) != 3:
        fail("expected exactly three historical old-domain publication records")

    token_store = SSMTokenStore()
    token = token_store.get(f"ssm:{token_store.parameter_name(tenant_id)}")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with httpx.Client(timeout=15, follow_redirects=False) as client:
        listed = client.get(f"{TURNOVER_API_BASE_URL}/jobs", headers=headers)
        if listed.status_code != 200 or not isinstance(listed.json(), list):
            fail(f"provider job list failed: HTTP {listed.status_code}")
        matched = [
            job for job in listed.json()
            if isinstance(job, dict) and str(job.get("reference")) in old_publications
        ]
        if len(matched) != 1 or matched[0].get("status") != "DRAFT":
            fail("expected exactly one existing draft with a historical callback")
        reference = str(matched[0]["reference"])
        if old_publications[reference].get("remote_job_id"):
            fail("unexpected stored remote job id; review before changing provider")
        path = f"{TURNOVER_API_BASE_URL}/jobs/{quote(reference, safe='')}"
        before_response = client.get(path, headers=headers)
        if before_response.status_code != 200:
            fail(f"provider job read failed: HTTP {before_response.status_code}")
        before = before_response.json()
        if not isinstance(before, dict) or before.get("status") != "DRAFT":
            fail("provider job changed during preflight")
        old_callback = str(old_publications[reference]["callback_url"])
        new_callback = NEW_ORIGIN + old_callback[len(OLD_ORIGIN):]
        if mode == "plan":
            full_payload(before, new_callback)
            print(
                "turnover-callback: plan ready local_old=3 provider_drafts=1 "
                "operation=PUT_by_reference no_new_job=true"
            )
            return

        callback = new_callback if mode == "apply" else old_callback
        response = client.put(path, headers=headers, json=full_payload(before, callback))
        print(f"turnover-callback: provider_update_http={response.status_code}")
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
            except ValueError:
                error = {}
            if isinstance(error, dict):
                print("turnover-callback: provider_error_keys=" + ",".join(sorted(error)))
                violations = error.get("violations") or error.get("errors") or []
                if isinstance(violations, dict):
                    print("turnover-callback: invalid_fields=" + ",".join(sorted(violations)))
                elif isinstance(violations, list):
                    fields = {
                        str(item.get("propertyPath") or item.get("field") or item.get("path"))
                        for item in violations if isinstance(item, dict)
                    }
                    print("turnover-callback: invalid_fields=" + ",".join(sorted(fields)))
            unchanged = client.get(path, headers=headers)
            print(
                "turnover-callback: provider_fields_unchanged_after_rejection="
                + str(unchanged.status_code == 200 and stable_view(before) == stable_view(unchanged.json())).lower()
            )
            fail("provider rejected the full update; no new job was created")
        after_response = client.get(path, headers=headers)
        if after_response.status_code != 200:
            fail("provider accepted the update but verification read failed")
        after = after_response.json()
        description_format_delta = (
            abs(len(str(before.get("description", ""))) - len(str(after.get("description", ""))))
            if isinstance(after, dict) else 0
        )
        if (
            not isinstance(after, dict)
            or stable_view(before) != stable_view(after)
            or description_format_delta > 20
        ):
            if isinstance(after, dict):
                changed = sorted(
                    key for key in STABLE_FIELDS
                    if stable_view(before)[key] != stable_view(after)[key]
                )
                print("turnover-callback: changed_provider_fields=" + ",".join(changed))
            reverse = old_callback if mode == "apply" else new_callback
            restored = client.put(path, headers=headers, json=full_payload(before, reverse))
            print(f"turnover-callback: automatic_provider_restore_http={restored.status_code}")
            if 200 <= restored.status_code < 300:
                restored_read = client.get(path, headers=headers)
                if restored_read.status_code == 200 and isinstance(restored_read.json(), dict):
                    print(
                        "turnover-callback: restored_fields_match_before="
                        + str(stable_view(before) == stable_view(restored_read.json())).lower()
                    )
            fail("non-callback job fields changed; restoration attempted")
        visible_callback = after.get("callbackUrl")
        if not visible_callback and isinstance(after.get("application"), dict):
            visible_callback = after["application"].get("callbackUrl")
        if visible_callback and visible_callback != callback:
            fail("provider exposed a different callback after update")
        print(
            f"turnover-callback: {mode} success provider_fields_equivalent=true "
            f"description_whitespace_delta={description_format_delta} "
            f"callback_visible={str(bool(visible_callback)).lower()} no_new_job=true"
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
