"""Data classification and deterministic DLP scanning (TZ 10.2).

Classes follow TZ V2.1 section 10.2: PUBLIC, INTERNAL, CONFIDENTIAL,
PERSONAL, RESTRICTED. Classification is rule-based and deterministic; the
result records which rule fired so decisions are auditable without storing
the sensitive content itself.

Rules live in a versioned registry (TZ 8.1 "Версионированный Policy
Registry"): changing a pattern or adding one is a control-boundary change
that must bump the registry version and update the tests.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class DataClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PERSONAL = "personal"
    RESTRICTED = "restricted"


RULES_REGISTRY_VERSION = "dlp-rules-2026-09-v1"


@dataclass(frozen=True)
class ClassificationRule:
    """One deterministic DLP rule: name, owning class, compiled pattern."""

    name: str
    data_class: DataClass
    pattern: re.Pattern[str]


def _rule(name: str, data_class: DataClass, pattern: str) -> ClassificationRule:
    return ClassificationRule(name=name, data_class=data_class, pattern=re.compile(pattern))


# Evaluated in order; the highest-severity match wins.
RULES_REGISTRY: tuple[ClassificationRule, ...] = (
    _rule(
        "password_assignment", DataClass.RESTRICTED, r"(?i)\b(password|passwd|пароль)\s*[:=]\s*\S+"
    ),
    _rule(
        "api_key_literal",
        DataClass.RESTRICTED,
        r"(?i)\b(api[_-]?key|secret[_-]?key|токен)\s*[:=]\s*\S+",
    ),
    _rule("bearer_token", DataClass.RESTRICTED, r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    _rule("card_number", DataClass.RESTRICTED, r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b"),
    _rule("bank_account_secret", DataClass.RESTRICTED, r"(?i)\b(номер\s+карты|cvv|cvc)\b"),
    _rule("email_address", DataClass.PERSONAL, r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b"),
    _rule(
        "phone_number",
        DataClass.PERSONAL,
        r"(?<!\d)(?:\+7|8)[\s(-]?\d{3}[\s)]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)",
    ),
    _rule("passport_number", DataClass.PERSONAL, r"(?i)\bпаспорт\s*(?:рф)?\s*№?\s*\d{4}\s*\d{6}"),
    _rule("individual_tax_number", DataClass.PERSONAL, r"(?i)\b(инн|снилс)\s*[:#]?\s*\d{10,12}\b"),
    _rule("contract_marker", DataClass.CONFIDENTIAL, r"(?i)\b(договор|contract)\s*№\s*[\w/-]+"),
    _rule(
        "invoice_bank_details",
        DataClass.CONFIDENTIAL,
        r"(?i)\b(р/с|расчётный\s+счёт|счёт\s*№)\s*\d{5,}",
    ),
)


class ClassificationFinding(BaseModel):
    rule: str
    data_class: DataClass
    occurrences: int


class ClassificationResult(BaseModel):
    """The strictest class detected, with the rules that fired (no content)."""

    registry_version: str = RULES_REGISTRY_VERSION
    data_class: DataClass = DataClass.PUBLIC
    findings: list[ClassificationFinding] = Field(default_factory=list)
    scanned_chars: int = 0


Route = Literal["external_llm", "local_llm", "internal_only"]


def classify_text(text: str) -> ClassificationResult:
    """Deterministic rule scan; the strictest detected class wins."""

    result = ClassificationResult(scanned_chars=len(text))
    matched = False
    for rule in RULES_REGISTRY:
        occurrences = len(rule.pattern.findall(text))
        if occurrences:
            result.findings.append(
                ClassificationFinding(
                    rule=rule.name, data_class=rule.data_class, occurrences=occurrences
                )
            )
            if not matched or _severity(rule.data_class) > _severity(result.data_class):
                result.data_class = rule.data_class
            matched = True
    result.findings.sort(key=lambda f: (-_severity(f.data_class), f.rule))
    return result


def _severity(data_class: DataClass) -> int:
    order = list(DataClass)
    return order.index(data_class)
