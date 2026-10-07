import pytest

from app.knowledge.embeddings import tokens
from app.knowledge.evaluation import score_case
from app.models.enums import AgentType
from app.models.legal import LegalResult


def test_metrics_do_not_reward_duplicate_chunks() -> None:
    result = score_case(["a", "b"], ["noise", "a", "a"])
    assert result["recall_at_k"] == 0.5
    assert result["precision_returned"] == 0.5
    assert result["reciprocal_rank"] == 0.5


@pytest.mark.parametrize("expected,returned", [([], []), (["a"], []), ([], ["noise"])])
def test_empty_metrics_are_not_false_success(expected: list[str], returned: list[str]) -> None:
    assert score_case(expected, returned) == {
        "recall_at_k": 0.0,
        "precision_returned": 0.0,
        "reciprocal_rank": 0.0,
    }


def test_tokenization_is_case_insensitive_not_semantic() -> None:
    assert tokens("ОПЛАТА, Payment!") == ["оплата", "payment"]
    assert set(tokens("оплата")).isdisjoint(tokens("оплатить payment"))


def test_legacy_results_keep_legacy_retrieval_version() -> None:
    old = LegalResult(
        agent=AgentType.LAWYER,
        status="retrieval_only",
        summary="legacy",
        jurisdiction="LV",
        effective_on=None,
    )
    assert old.retrieval_version == "mock-hash-v1"
