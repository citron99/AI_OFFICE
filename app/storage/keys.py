"""Shared validation for opaque and company-namespaced object keys."""

import re

_OBJECT_KEY = re.compile(r"(?:[A-Za-z0-9_-]{1,40}/)?[0-9a-f]{32}")


def validate_object_key(key: str) -> str:
    """Return a safe storage key or reject traversal/ambiguous names."""

    if not _OBJECT_KEY.fullmatch(key):
        raise ValueError("Invalid storage key")
    return key
