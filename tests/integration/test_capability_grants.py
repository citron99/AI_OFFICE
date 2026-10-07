"""Machine identities and short-lived capability grants (TZ 10.1, contour 2)."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agents.principals import (
    GRANT_MATRIX,
    PRINCIPALS,
    issue_capability_grants,
    principal_for,
)
from app.config import Settings
from app.core.exceptions import GrantDeniedError
from app.db.session import create_session_factory
from app.db.tables.grants import CapabilityGrantRecord
from app.main import create_app
from app.models.agent import AgentGrant, require_grant
from app.models.enums import AgentType, GrantScope
from app.orchestrator.capabilities import CAPABILITY_INDEX


def test_principals_are_static_and_least_privilege() -> None:
    # The registry is code: identities cannot be edited at runtime.
    assert set(PRINCIPALS) == set(AgentType)
    assert principal_for(AgentType.ACCOUNTANT).principal_id == "agt_accountant"
    # The accountant never receives knowledge or attachment scopes.
    assert set(GRANT_MATRIX[AgentType.ACCOUNTANT]) == {GrantScope.ACCOUNTING}
    assert set(GRANT_MATRIX[AgentType.LAWYER]) == {
        GrantScope.TASK_TEXT,
        GrantScope.ATTACHMENTS,
        GrantScope.KNOWLEDGE,
    }
    # The security postflight reads structured results only, not attachments.
    assert GrantScope.ATTACHMENTS not in set(GRANT_MATRIX[AgentType.SECURITY]) or (
        "scan_untrusted" in GRANT_MATRIX[AgentType.SECURITY][GrantScope.ATTACHMENTS]
    )


def test_grant_matrix_covers_every_capability_scope() -> None:
    for capability in CAPABILITY_INDEX.values():
        matrix = GRANT_MATRIX[capability.agent]
        missing = set(capability.data_scopes) - set(matrix)
        assert not missing, f"{capability.capability_id} scopes outside the grant matrix"


def test_issued_grants_expire_within_ttl() -> None:
    issued_at = datetime.now(UTC)
    grants = issue_capability_grants("legal_review", issued_at=issued_at)
    assert grants, "legal_review must declare at least one data scope"
    longest = max(expires_at for _, _, expires_at in grants)
    assert longest - issued_at <= timedelta(minutes=15)


def test_require_grant_rejects_missing_and_expired() -> None:
    now = datetime.now(UTC)
    with pytest.raises(GrantDeniedError):
        require_grant([], GrantScope.ACCOUNTING, now=now)
    expired = AgentGrant(
        data_scope=GrantScope.ACCOUNTING,
        actions=("read_snapshot",),
        expires_at=now - timedelta(seconds=1),
    )
    with pytest.raises(GrantDeniedError, match="expired"):
        require_grant([expired], GrantScope.ACCOUNTING, now=now)
    valid = AgentGrant(
        data_scope=GrantScope.ACCOUNTING,
        actions=("read_snapshot",),
        expires_at=now + timedelta(minutes=5),
    )
    assert require_grant([valid], GrantScope.ACCOUNTING, now=now) is valid


async def test_office_run_persists_grants_for_every_step(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
) -> None:
    created = await client.post(
        "/api/v1/tasks",
        json={
            "message": "Проверь договор и счёт",
            "invoice_id": "inv_100",
            "requested_action": "prepare_payment_draft",
            "jurisdiction": "LV",
            "effective_on": "2026-08-27",
        },
    )
    assert created.status_code == 201, created.text
    task = created.json()
    async with create_session_factory(engine)() as session:
        grants = list(
            await session.scalars(
                select(CapabilityGrantRecord).where(
                    CapabilityGrantRecord.task_id == task["task_id"]
                )
            )
        )
    by_node: dict[str, set[str]] = {}
    for grant in grants:
        assert grant.principal_id.startswith("agt_")
        assert grant.policy_version
        assert grant.expires_at > grant.issued_at
        by_node.setdefault(grant.node_id, set()).add(grant.data_scope)
    assert by_node["accounting_snapshot"] == {"accounting"}
    assert by_node["security_preflight"] == {"task_text", "attachments"}
    assert by_node["legal_review"] == {"task_text", "attachments", "knowledge"}
    # Postflight reads structured results only: no attachment scope.
    assert "attachments" not in by_node["security_postflight"]


async def test_grant_ledger_is_company_scoped(engine: AsyncEngine, tmp_path: Path) -> None:
    """Grant rows never leak into another company's boundary."""
    settings = Settings(
        app_env="test",
        auth_mode="api_key",
        upload_dir=tmp_path,
        auth_token_hashes={
            sha256(b"tok-grants").hexdigest(): {
                "user_id": "owner-grants",
                "role": "owner",
                "company_id": "comp_grants",
            }
        },
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            c.headers["Authorization"] = "Bearer tok-grants"
            response = await c.post(
                "/api/v1/tasks",
                json={"message": "security scan", "requested_agent": "security"},
            )
            assert response.status_code == 201, response.text
    async with create_session_factory(engine)() as session:
        grants = list((await session.scalars(select(CapabilityGrantRecord))).all())
    assert grants
    assert {grant.company_id for grant in grants} == {"comp_grants"}
