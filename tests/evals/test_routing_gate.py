"""ACC-02 gate: routing accuracy >=90%, zero critical misroutes."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from routing_catalog import routing_case_rows  # noqa: E402

from app.models.enums import TaskCategory  # noqa: E402
from app.orchestrator.router import KeywordRouter  # noqa: E402

CASES = routing_case_rows()
ACCURACY_THRESHOLD = 0.9


def _route(text: str, requested_agent) -> str:
    from app.models.enums import AgentType

    agent = AgentType(requested_agent) if requested_agent else None
    return KeywordRouter().classify(text, agent).category.value


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_routing_case(case) -> None:
    actual = _route(case["text"], case["requested_agent"])
    if case["critical"]:
        # A critical misroute is a clearly single-domain message routed to a
        # DIFFERENT single domain. UNSUPPORTED/MIXED are degraded, not wrong.
        single_domains = {
            TaskCategory.ACCOUNTING.value,
            TaskCategory.LEGAL.value,
            TaskCategory.SECURITY.value,
        }
        if case["expected"] in single_domains and actual in single_domains:
            assert actual == case["expected"], (
                f"{case['id']}: critical misroute {case['expected']} -> {actual}"
            )
    assert actual == case["expected"], f"{case['id']}: expected {case['expected']}, got {actual}"


def test_routing_meets_acc02_threshold() -> None:
    correct = sum(1 for c in CASES if _route(c["text"], c["requested_agent"]) == c["expected"])
    accuracy = correct / len(CASES)
    assert accuracy >= ACCURACY_THRESHOLD, (
        f"ACC-02 routing accuracy {accuracy:.2%} < {ACCURACY_THRESHOLD:.0%} "
        f"({correct}/{len(CASES)})"
    )
    # TZ 13.2: at least 20 routing cases above the TZ minimums for the eval set.
    assert len(CASES) >= 50
