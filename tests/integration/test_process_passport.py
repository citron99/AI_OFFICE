"""ProcessDefinitionV3 passports: schema validation and runtime ceiling."""

import pytest

from app.orchestrator.passport import (
    ProcessDefinitionV3,
    autonomy_rank,
    available_passports,
    passport_for,
)


def test_shipped_passports_load_and_validate() -> None:
    passports = available_passports()
    by_id = {passport.id: passport for passport in passports}
    assert {"office_review", "daily_cash_and_receivable_risk"} <= set(by_id)
    for passport in passports:
        assert passport.version == 3
        assert passport.passport.trigger
        assert passport.passport.acceptance_criteria
        assert passport.passport.manual_fallback
        # Every executing node is covered by the passport's capability list.
        node_ids = {node.id for node in passport.nodes}
        assert set(passport.passport.allowed_capabilities) == node_ids
        assert "real_payment" in passport.forbidden_actions


def test_passport_graph_rejects_cycles_and_unknown_dependencies() -> None:
    base = available_passports()[0].model_dump()
    # Unknown dependency
    broken = {**base, "nodes": [dict(base["nodes"][0], depends_on=["missing_node"])]}
    with pytest.raises(ValueError, match="unknown dependencies"):
        ProcessDefinitionV3.model_validate(broken)
    # Cycle between two nodes
    first, second = base["nodes"][0], base["nodes"][1]
    cycled = {
        **base,
        "nodes": [
            dict(first, depends_on=[second["id"]]),
            dict(second, depends_on=[first["id"]]),
        ],
    }
    with pytest.raises(ValueError, match="cycle"):
        ProcessDefinitionV3.model_validate(cycled)


def test_autonomy_ranking_orders_the_ladder() -> None:
    order = ["a0_shadow", "a1_recommendation", "a2_draft", "a3_approved_action"]
    for lower, higher in zip(order, order[1:], strict=False):
        assert autonomy_rank(lower) < autonomy_rank(higher)
    with pytest.raises(ValueError, match="Unknown autonomy level"):
        autonomy_rank("a4_limited_autonomy")


def test_daily_process_ceiling_is_recommendation_only() -> None:
    passport = passport_for("daily_cash_and_receivable_risk")
    assert passport is not None
    assert passport.allows_autonomy("a1_recommendation")
    assert not passport.allows_autonomy("a2_draft")


def test_unknown_passport_returns_none() -> None:
    assert passport_for("nonexistent_process") is None


async def test_runtime_api_rejects_levels_above_the_ceiling(client) -> None:
    response = await client.post(
        "/api/v1/processes/daily_cash_and_receivable_risk/runtime",
        json={"autonomy_level": "a2_draft"},
    )
    assert response.status_code == 409
    assert "ceiling" in response.text
    allowed = await client.post(
        "/api/v1/processes/daily_cash_and_receivable_risk/runtime",
        json={"autonomy_level": "a1_recommendation"},
    )
    assert allowed.status_code == 200


async def test_processes_endpoint_includes_v3_passports(client) -> None:
    response = await client.get("/api/v1/processes")
    assert response.status_code == 200
    versions = {item.get("version") for item in response.json()}
    assert 3 in versions
    v3 = [item for item in response.json() if item.get("version") == 3]
    assert all("passport" in item for item in v3)
