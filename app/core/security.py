"""Conservative synthetic-pilot detectors; never log matched values."""

import re
from typing import Any

PATTERNS = {
    "REDACTED_DATA": re.compile(r"\[REDACTED:[A-Z_]+\]"),
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "API_KEY": re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16})\b"),
    "PASSWORD": re.compile(r"(?i)\b(?:password|passwd|пароль|api[_-]?key)\s*[:=]\s*[^\s,;]+"),
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
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
