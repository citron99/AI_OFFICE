"""Content-based antivirus scan for uploads (ART-002, MVP level).

Full SIEM/AV is out of MVP scope (TZ 1.4); this module provides the
deterministic content checks the MVP owes before indexing: the EICAR test
signature and executable containers hidden inside allowed formats. A
deployment can plug a real scanner behind the same interface later.
"""

import re
from typing import Literal

from pydantic import BaseModel

EICAR_TEST_FILE = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

_EMBEDDED_SIGNATURES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("EICAR_TEST_FILE", re.compile(re.escape(EICAR_TEST_FILE.encode()))),
    ("LINUX_EXECUTABLE", re.compile(re.escape(b"\x7fELF"))),
)


class ScanResult(BaseModel):
    status: Literal["clean", "threat"]
    threats: list[str] = []


def content_scan(data: bytes) -> ScanResult:
    """Deterministic signature scan; fails closed on known-bad markers."""

    threats: list[str] = []
    if data.startswith(b"MZ"):
        # A Windows PE must never arrive under a document content type.
        threats.append("WINDOWS_EXECUTABLE")
    for name, pattern in _EMBEDDED_SIGNATURES:
        if pattern.search(data):
            threats.append(name)
    return ScanResult(status="threat" if threats else "clean", threats=threats)
