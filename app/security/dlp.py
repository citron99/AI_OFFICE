"""Deterministic DLP helpers built on the data classifier.

``scan_and_redact`` returns the classification plus a redacted copy of the
text in which rule matches at or above the minimum class are replaced by
typed placeholders, so the value never reaches logs, traces or prompts.
Mappings are not kept: the original belongs only to the source system.
"""

import re

from pydantic import BaseModel, Field

from app.security.data_classification import (
    RULES_REGISTRY,
    ClassificationResult,
    DataClass,
    classify_text,
)

REDACTED = "[REDACTED]"


class DlpScan(BaseModel):
    classification: ClassificationResult
    redacted_text: str
    redactions: int = Field(default=0, ge=0)


def _apply(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> tuple[str, int]:
    count = 0
    for _, pattern in patterns:
        text, n = pattern.subn(REDACTED, text)
        count += n
    return text, count


def scan_and_redact(text: str, *, minimum_class: DataClass = DataClass.RESTRICTED) -> DlpScan:
    """Redact matches at or above ``minimum_class`` (default: RESTRICTED only)."""

    classification = classify_text(text)
    if _rank(classification.data_class) < _rank(minimum_class):
        return DlpScan(classification=classification, redacted_text=text, redactions=0)
    rules = [rule for rule in RULES_REGISTRY if _rank(rule.data_class) >= _rank(minimum_class)]
    redacted_text, redactions = _apply(text, [(r.name, r.pattern) for r in rules])
    return DlpScan(
        classification=classification, redacted_text=redacted_text, redactions=redactions
    )


def _rank(data_class: DataClass) -> int:
    return list(DataClass).index(data_class)
