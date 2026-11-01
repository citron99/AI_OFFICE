"""Conservative synthetic-pilot detectors; never log matched values."""

import re
from typing import Any

PATTERNS = {
    "REDACTED_DATA": re.compile(r"\[REDACTED:[A-Z_]+\]"),
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----"),
    "AWS_ACCESS_KEY": re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b"),
    "API_KEY": re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "GITHUB_TOKEN": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,})\b"),
    "SLACK_TOKEN": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "STRIPE_SECRET": re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{24,}\b"),
    "GOOGLE_API_KEY": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "PASSWORD": re.compile(r"(?i)\b(?:password|passwd|пароль|api[_-]?key)\s*[:=]\s*[^\s,;]+"),
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    "CARD_NUMBER": re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b"),
}


def detections(text: str) -> dict[str, int]:
    return {
        kind: len(matches)
        for kind, pattern in PATTERNS.items()
        if (matches := pattern.findall(text))
    }


def redact(text: str) -> str:
    for kind, pattern in PATTERNS.items():
        text = pattern.sub(f"[REDACTED:{kind}]", text)
    return text


def redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_payload(item) for key, item in value.items()}
    return value
