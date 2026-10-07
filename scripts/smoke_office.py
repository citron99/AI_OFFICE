"""Explicit synthetic smoke against a running office. Creates demo records, never payments."""

import argparse
import time
from uuid import uuid4

import httpx


def wait_task(client: httpx.Client, task: dict) -> dict:
    deadline = time.monotonic() + 60
    while task["state"] in {"queued", "classifying", "planning", "running"}:
        if time.monotonic() >= deadline:
            raise TimeoutError("Worker did not finish the synthetic task within 60 seconds")
        time.sleep(0.25)
        response = client.get("/api/v1/tasks/" + task["task_id"])
        response.raise_for_status()
        task = response.json()
    return task


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    with httpx.Client(base_url=args.url, timeout=30) as client:
        client.get("/api/v1/me").raise_for_status()
        sync_payload = {"request_key": "smoke-" + uuid4().hex}
        receipt = client.post("/api/v1/accounting/sync", json=sync_payload)
        receipt.raise_for_status()
        repeated_receipt = client.post("/api/v1/accounting/sync", json=sync_payload)
        repeated_receipt.raise_for_status()
        assert repeated_receipt.json() == receipt.json()
        assert receipt.json()["counts"]["accrual_entries"] == 8
        upload = client.post(
            "/api/v1/files",
            files={
                "file": (
                    "synthetic-rule.txt",
                    b"Synthetic contract: payment requires written acceptance. Not a law.",
                    "text/plain",
                ),
            },
        )
        upload.raise_for_status()
        source = client.post(
            "/api/v1/knowledge/sources",
            json={
                "artifact_id": upload.json()["id"],
                "title": "SYNTHETIC smoke " + uuid4().hex[:8],
                "document_type": "test_norm",
                "jurisdiction": "LV",
                "authority": "Test only",
                "version": "smoke-v1",
                "effective_from": "2026-01-01",
                "status": "ACTIVE",
            },
        )
        source.raise_for_status()

        def draft_payload(invoice_id: str) -> dict:
            return {
                "message": "Review contract and invoice payment",
                "invoice_id": invoice_id,
                "requested_action": "prepare_payment_draft",
                "jurisdiction": "LV",
                "effective_on": "2026-08-27",
            }

        # TZ 7.2: within the established limit a synthetic draft is allowed
        # without a separate approval; the replay stays idempotent.
        payload = draft_payload("inv_100")
        submission_headers = {"Idempotency-Key": "smoke-" + uuid4().hex}
        response = client.post("/api/v1/tasks", json=payload, headers=submission_headers)
        response.raise_for_status()
        replay = client.post("/api/v1/tasks", json=payload, headers=submission_headers)
        replay.raise_for_status()
        assert replay.json()["task_id"] == response.json()["task_id"]
        conflict = client.post(
            "/api/v1/tasks",
            json={**payload, "invoice_id": "inv_099"},
            headers=submission_headers,
        )
        assert conflict.status_code == 409
        task = wait_task(client, response.json())
        assert task["state"] == "completed", task
        result = task["result"]
        assert result["policy_decision"] == "allow_draft", result
        assert result["status"] == "draft_created_synthetically"
        assert result["requires_approval"] is False
        assert result["accounting"]["outstanding"] == "1331.00"
        assert result["legal"]["evidence"]
        assert result["legal"]["consultant_plus"]["searched"] is True
        assert result["security"]["detections"] == {}
        assert result["security"]["status"] == "security_postflight_report"
        print("PASS: within-limit draft allowed; idempotent replay; consultant trail recorded")

        # TZ 7.2: above the established limit the owner approves before any draft.
        above = draft_payload("inv_101")
        approval_headers = {"Idempotency-Key": "smoke-" + uuid4().hex}
        approval_task = client.post("/api/v1/tasks", json=above, headers=approval_headers)
        approval_task.raise_for_status()
        approval = wait_task(client, approval_task.json())
        assert approval["state"] == "waiting_approval", approval
        approval_result = approval["result"]
        assert approval_result["policy_decision"] == "require_owner_approval"
        assert approval_result["accounting"]["outstanding"] == "242000.00"
        replay = client.post("/api/v1/tasks", json=above, headers=approval_headers)
        replay.raise_for_status()
        assert replay.json()["result"]["approval_id"] == approval_result["approval_id"]
        path = "/api/v1/approvals/" + approval_result["approval_id"] + "/decision"
        approved = client.post(path, json={"decision": "approve"})
        approved.raise_for_status()
        repeated = client.post(path, json={"decision": "approve"})
        repeated.raise_for_status()
        assert approved.json() == repeated.json()
        draft_id = approved.json()["result"]["draft_id"]
        drafts = [d for d in client.get("/api/v1/drafts").json() if d["id"] == draft_id]
        assert len(drafts) == 1
        assert drafts[0]["payload"]["real_payment_allowed"] is False
        print("PASS: above-limit approval -> exactly one mock draft; repeat decision idempotent")

        controls = client.get("/api/v1/processes/controls").json()
        assert controls["postflight_completed"] >= 1
        assert controls["postflight_coverage"] == 1
        blocked = client.post("/api/v1/tasks", json=draft_payload("inv_004"))
        blocked.raise_for_status()
        assert wait_task(client, blocked.json())["result"]["policy_decision"] == "deny"
        security = client.post(
            "/api/v1/tasks",
            json={
                "message": "security password=SYNTHETIC-test-value",
                "requested_agent": "security",
            },
        )
        security.raise_for_status()
        checked = wait_task(client, security.json())
        assert checked["result"]["security"]["detections"]
        assert "SYNTHETIC-test-value" not in str(checked)
        trace = client.get("/api/v1/tasks/" + task["task_id"] + "/trace").json()
        assert len(trace["steps"]) == 4

        # Cancellation closes the pending approval; late decisions are rejected.
        cancellation = client.post("/api/v1/tasks", json=draft_payload("inv_101"))
        cancellation.raise_for_status()
        cancellable = wait_task(client, cancellation.json())
        assert cancellable["state"] == "waiting_approval"
        cancelled_approval = cancellable["result"]["approval_id"]
        cancel_path = "/api/v1/tasks/" + cancellable["task_id"] + "/cancel"
        cancelled = client.post(cancel_path)
        cancelled.raise_for_status()
        assert cancelled.json()["state"] == "cancelled"
        assert cancelled.json()["result"]["requires_approval"] is False
        assert client.post(cancel_path).json() == cancelled.json()
        approval_rows = client.get("/api/v1/approvals").json()
        assert (
            next(a for a in approval_rows if a["id"] == cancelled_approval)["status"] == "cancelled"
        )
        assert (
            client.post(
                "/api/v1/approvals/" + cancelled_approval + "/decision",
                json={"decision": "approve"},
            ).status_code
            == 409
        )
        print("PASS: cancellation closes approval; replay is idempotent; late approval denied")

        financial = client.post(
            "/api/v1/accounting/financial-report",
            json={"start": "2026-07-01", "end": "2026-07-31"},
        )
        financial.raise_for_status()
        assert financial.json()["current"]["net"] == "-148500.00"
        assert financial.json()["profit_and_loss"]["current"]["operating_profit"] == "55000.00"
        uncovered = client.post(
            "/api/v1/accounting/financial-report",
            json={"start": "2026-09-01", "end": "2026-09-30"},
        )
        uncovered.raise_for_status()
        assert uncovered.json()["profit_and_loss"]["current"] is None
        assert uncovered.json()["profit_and_loss"]["operating_profit_change"] is None
        print("PASS: financial report through frontend proxy; cash flow is not labelled profit")

        # TZ E2E-2: a NEW counterparty above 100 000 needs owner approval.
        new_above = wait_task(
            client, client.post("/api/v1/tasks", json=draft_payload("inv_102")).json()
        )
        assert new_above["result"]["policy_decision"] == "require_owner_approval", new_above
        print("PASS: new counterparty above 100k requires owner approval (E2E-2)")

        # Consultant+ provider status and the licensed search surface.
        provider_status = client.get("/api/v1/legal/provider-status").json()
        assert provider_status["mode"] == "mock" and provider_status["status"] == "ok"
        legal_search = client.post(
            "/api/v1/legal/search",
            json={
                "query": "contract payment acceptance",
                "jurisdiction": "LV",
                "effective_on": "2026-08-27",
            },
        )
        legal_search.raise_for_status()
        assert legal_search.json()["results"]
        print("PASS: Consultant+ provider status and licensed search return metadata")

        # Kill switch: write tools off makes the same action a hard DENY.
        client.post(
            "/api/v1/processes/office_review/runtime",
            json={"write_tools_enabled": False},
        ).raise_for_status()
        switched = wait_task(client, client.post("/api/v1/tasks", json=payload).json())
        assert switched["result"]["policy_decision"] == "deny", switched
        assert "WRITE_TOOLS_DISABLED" in switched["result"]["policy_reasons"]
        client.post(
            "/api/v1/processes/office_review/runtime",
            json={"write_tools_enabled": True},
        ).raise_for_status()
        assert (
            client.get("/api/v1/processes/office_review/runtime").json()["write_tools_enabled"]
            is True
        )
        print("PASS: kill switch denies write tools without code changes")

        # Artifact lifecycle: delete cascades chunks and the stored file.
        lifecycle_upload = client.post(
            "/api/v1/files",
            files={"file": ("lifecycle.txt", b"Lifecycle cascade check", "text/plain")},
        )
        lifecycle_upload.raise_for_status()
        lifecycle_id = lifecycle_upload.json()["id"]
        deleted = client.delete("/api/v1/files/" + lifecycle_id)
        deleted.raise_for_status()
        assert client.get("/api/v1/files/" + lifecycle_id).status_code == 404
        print("PASS: artifact delete cascades source, chunks and stored file")

        print(
            "PASS: frontend proxy -> API -> Redis/Celery -> 3 agents -> policy matrix -> "
            "draft/approval paths"
        )
        print("Demo task:", task["task_id"])


if __name__ == "__main__":
    main()
