"""Scenario runner: executes closed-set scenarios and returns violations.

An empty violations list means the scenario passed. The runner never mutates
expectations: a scenario passes only when the system demonstrably matches
every declared expectation and none of the forbidden effects happened.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from app.accounting.mock import Mock1CConnector
from app.agents.accountant import AccountantAgent
from app.agents.security import SecurityAgent
from app.core.policy import decide
from app.models.accounting import AccountingResult
from app.models.enums import PolicyDecision
from app.security.dlp import scan_and_redact
from app.security.egress_gateway import EgressRequest, evaluate_egress

AS_OF = datetime(2026, 8, 27).date()

SECURITY_CLEAN = SecurityAgent().execute(["Проверь договор и счёт"])


def _prepared_accounting(spec: dict[str, Any]) -> AccountingResult | None:
    if spec.get("no_invoice"):
        return None
    if spec.get("critical_finding"):
        base = AccountantAgent(Mock1CConnector()).execute(invoice_id="inv_004", as_of=AS_OF)
        return base
    if spec.get("counterparty_status") or spec.get("amount") or spec.get("zero_balance"):
        base = AccountantAgent(Mock1CConnector()).execute(invoice_id="inv_100", as_of=AS_OF)
        counterparty = (
            base.counterparty.model_copy(
                update={"relationship_status": spec.get("counterparty_status", "established")}
            )
            if base.counterparty
            else None
        )
        amount = Decimal(spec["amount"]) if "amount" in spec else base.outstanding
        if spec.get("zero_balance"):
            amount = Decimal("0")
        return base.model_copy(
            update={"outstanding": amount, "findings": [], "counterparty": counterparty}
        )
    return AccountantAgent(Mock1CConnector()).execute(invoice_id="inv_100", as_of=AS_OF)


def run_policy_scenario(scenario: dict[str, Any]) -> list[str]:
    spec = scenario["input"]
    expect = scenario["expect"]
    if "egress_content" in spec:
        verdict = evaluate_egress(
            EgressRequest(
                company_id="comp_demo",
                route=spec["route"],
                purpose="eval",
                content=spec["egress_content"],
            )
        )
        return (
            []
            if verdict.decision == expect["egress_decision"]
            else [f"egress decision {verdict.decision} != {expect['egress_decision']}"]
        )
    if "dlp_content" in spec:
        scan = scan_and_redact(spec["dlp_content"])
        leaked = expect["redacted_not_contains"] in scan.redacted_text
        return [] if not leaked else ["DLP redaction leaked the secret"]
    if "detections" in spec or "control_flags" in spec:
        security = SecurityAgent().execute(["Clean text"])
        if spec.get("detections"):
            security = SecurityAgent().execute(["password=leak-1"])
        for flag in spec.get("control_flags", []):
            security.control_flags.append(flag)
        decision, reasons = decide(
            action="prepare_payment_draft",
            accounting=_prepared_accounting({}),
            legal=None,
            security=security,
        )
    else:
        security = SECURITY_CLEAN
        if spec.get("write_tools_disabled"):
            decision, reasons = decide(
                action="prepare_payment_draft",
                accounting=_prepared_accounting(spec),
                legal=None,
                security=security,
                write_tools_enabled=False,
            )
        else:
            action = spec.get("action", "prepare_payment_draft")
            decision, reasons = decide(
                action=action,
                accounting=_prepared_accounting(spec),
                legal=None,
                security=security,
            )
    violations: list[str] = []
    expected = PolicyDecision(expect["decision"])
    if decision != expected:
        violations.append(f"decision {decision.value} != {expected.value}")
    for reason in expect.get("reasons_contain", []):
        if reason not in reasons:
            violations.append(f"missing reason {reason}")
    return violations


async def _count(client: httpx.AsyncClient, path: str) -> int:
    response = await client.get(path)
    return len(response.json())


async def run_api_scenario(
    scenario: dict[str, Any],
    client: httpx.AsyncClient,
    clients_by_app: dict[str, httpx.AsyncClient],
) -> list[str]:
    payload = {k: v for k, v in scenario["input"].items() if not k.startswith("__")}
    app_name = scenario["input"].get("__app__", "default")
    client = clients_by_app[app_name]
    expect = scenario["expect"]
    violations: list[str] = []
    # Draft/approval expectations are deltas over the pre-scenario baseline so
    # scenarios stay valid whether they share an app or run in isolation.
    drafts_before = await _count(client, "/api/v1/drafts")
    approvals_before = await _count(client, "/api/v1/approvals")

    idempotency = scenario["input"].get("__idempotency__")
    headers = {"Idempotency-Key": idempotency} if idempotency else {}
    # TZ 7.1: the safe pilot default is A1 (recommendation only). Scenarios
    # that expect a draft raise the ladder to A2 explicitly, the way the
    # owner would after the quality gate.
    if expect.get("policy_decision") in {"allow_draft", "require_owner_approval"}:
        ladder = await client.post(
            "/api/v1/processes/office_review/runtime",
            json={"autonomy_level": "a2_draft"},
        )
        if ladder.status_code != 200:
            return [f"ladder setup failed: HTTP {ladder.status_code}"]
    created = await client.post("/api/v1/tasks", json=payload, headers=headers)
    if created.status_code != 201:
        return [f"task creation failed: HTTP {created.status_code}: {created.text[:200]}"]
    task = created.json()
    result = task.get("result") or {}

    if expect.get("same_task"):
        replay = await client.post("/api/v1/tasks", json=payload, headers=headers)
        if replay.json().get("task_id") != task["task_id"]:
            violations.append("idempotent replay produced a different task")

    if "state" in expect and task["state"] != expect["state"]:
        violations.append(f"state {task['state']} != {expect['state']}")
    if "state_completed_or_waiting" in expect and task["state"] not in {
        "completed",
        "waiting_source",
        "waiting_input",
    }:
        violations.append(f"unexpected state {task['state']}")
    if "policy_decision" in expect and result.get("policy_decision") != expect["policy_decision"]:
        violations.append(f"policy {result.get('policy_decision')} != {expect['policy_decision']}")
    if "status" in expect and result.get("status") != expect["status"]:
        violations.append(f"status {result.get('status')} != {expect['status']}")
    if expect.get("findings_empty") and (result.get("findings") or []):
        violations.append("findings must be empty")
    codes = {f.get("code") for f in result.get("findings", [])}
    for code in expect.get("finding_codes_contain", []):
        if code not in codes:
            violations.append(f"missing finding code {code}")
    for warning in expect.get("warnings_contain", []):
        if not any(w.startswith(warning) for w in result.get("warnings", [])):
            violations.append(f"missing warning {warning}")
    if expect.get("specialist_review") and not result.get("specialist_review_recommended"):
        violations.append("specialist review must be recommended")
    unresolved = result.get("unresolved_questions") or []
    for marker in expect.get("unresolved_contain", []):
        if not any(marker in q for q in unresolved):
            violations.append(f"missing unresolved marker {marker}")

    consultant = result.get("consultant_plus") or {}
    if (
        "consultant_searched" in expect
        and consultant.get("searched") is not (expect["consultant_searched"])
    ):
        violations.append(
            f"consultant searched {consultant.get('searched')} != {expect['consultant_searched']}"
        )
    if expect.get("consultant_queries_at_least"):
        if len(consultant.get("queries", [])) < expect["consultant_queries_at_least"]:
            violations.append("consultant trail has too few queries")
    if expect.get("trail_metadata_complete"):
        for query in consultant.get("queries", []):
            missing = [
                k for k in ("query_id", "source_id", "edition", "locator") if not query.get(k)
            ]
            if missing:
                violations.append(f"trail metadata missing {missing}")
    if expect.get("citations_have_source_or_locator"):
        for citation in result.get("citations", []):
            if not (citation.get("source_id") or citation.get("locator")):
                violations.append("citation without source or locator")

    # Interactions after creation.
    if expect.get("cancel"):
        cancelled = await client.post(f"/api/v1/tasks/{task['task_id']}/cancel")
        if cancelled.status_code != 200:
            violations.append("cancel failed")
    if expect.get("approve") is not None and task["state"] == "waiting_approval":
        approval_id = result.get("approval_id")
        decided = await client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": "approve" if expect["approve"] else "reject"},
        )
        if decided.status_code != 200:
            violations.append(f"approval decision failed: {decided.status_code}")
    if expect.get("repeat_decision_idempotent") and task["state"] == "waiting_approval":
        approval_id = result.get("approval_id")
        first = await client.post(
            f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}
        )
        second = await client.post(
            f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}
        )
        if first.status_code != 200 or second.status_code != 200:
            violations.append("repeat decision must stay idempotent")
        if await _count(client, "/api/v1/drafts") - drafts_before != 1:
            violations.append("repeat decision created a second draft")
    if expect.get("review_decision"):
        task_id = task["task_id"]
        preview_response = await client.get(f"/api/v1/tasks/{task_id}/result-review")
        preview = preview_response.json()
        reviewed = await client.post(
            f"/api/v1/tasks/{task_id}/result-review",
            json={
                "decision": expect["review_decision"],
                "reason": "Closed-set review",
                "result_hash": preview["result_hash"],
            },
        )
        if reviewed.status_code != 200:
            violations.append(f"review failed: {reviewed.status_code}")
    if expect.get("graph_dependency"):
        node_action, dependency_action = expect["graph_dependency"]
        graph_response = await client.get(f"/api/v1/tasks/{task['task_id']}/process-graph")
        graph = graph_response.json()
        nodes = {n["action"]: n for n in graph["nodes"] if n.get("kind") == "agent_step"}
        parent = nodes.get(dependency_action, {}).get("id")
        if parent not in nodes.get(node_action, {}).get("depends_on", []):
            violations.append(f"{node_action} does not depend on {dependency_action}")
    if "trace_attempts" in expect:
        trace_response = await client.get(f"/api/v1/tasks/{task['task_id']}/trace")
        trace = trace_response.json()
        attempts = {step["attempt"] for step in trace["steps"]}
        if attempts != set(expect["trace_attempts"]):
            violations.append(f"trace attempts {attempts} != {expect['trace_attempts']}")

    # Global effects.
    if "drafts" in expect:
        drafts = await _count(client, "/api/v1/drafts") - drafts_before
        if drafts != expect["drafts"]:
            violations.append(f"drafts {drafts} != {expect['drafts']}")
    if "approvals" in expect:
        approvals = await _count(client, "/api/v1/approvals") - approvals_before
        if approvals != expect["approvals"]:
            violations.append(f"approvals {approvals} != {expect['approvals']}")
    if "drafts_after" in expect:
        after = await _count(client, "/api/v1/drafts") - drafts_before
        if after != expect["drafts_after"]:
            violations.append(f"drafts after {after} != {expect['drafts_after']}")
    if expect.get("listed"):
        tasks_response = await client.get("/api/v1/tasks")
        ids = {t["task_id"] for t in tasks_response.json()}
        if task["task_id"] not in ids:
            violations.append("task not listed for its owner")

    if scenario["input"].get("__post__") == "retry_must_conflict":
        retry = await client.post(f"/api/v1/tasks/{task['task_id']}/retry")
        if task["state"] != "failed_safe" and retry.status_code != 409:
            violations.append("retry of a non-failed task must conflict")
    return violations


async def run_scenario(
    scenario: dict[str, Any],
    client: httpx.AsyncClient,
    clients_by_app: dict[str, httpx.AsyncClient],
) -> list[str]:
    if scenario["kind"] == "policy":
        return run_policy_scenario(scenario)
    return await run_api_scenario(scenario, client, clients_by_app)
