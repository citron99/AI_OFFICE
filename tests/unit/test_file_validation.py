import io
import zipfile

import pytest

from app.core.exceptions import FileValidationError
from app.services.files import MIME_TYPES, validate_file


@pytest.mark.parametrize(
    ("name", "mime", "data"),
    [
        ("../escape.txt", "text/plain", b"test"),
        ("C:\\escape.txt", "text/plain", b"test"),
        ("bad.exe", "application/octet-stream", b"MZ"),
        ("fake.pdf", "application/pdf", b"not a pdf"),
        ("fake.docx", MIME_TYPES[".docx"], b"not a zip"),
        ("empty.txt", "text/plain", b""),
        ("binary.txt", "text/plain", b"test\x00data"),
        ("bad.txt", "application/pdf", b"test"),
    ],
)
def test_reject_invalid_file(name: str, mime: str, data: bytes) -> None:
    with pytest.raises(FileValidationError):
        validate_file(name, mime, data)


@pytest.mark.parametrize("extension", [".docx", ".xlsx"])
def test_valid_office_package_and_macro_rejection(extension: str) -> None:
    stream = io.BytesIO()
    required = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(required, "<test/>")
    assert validate_file("test" + extension, MIME_TYPES[extension], stream.getvalue())
    with zipfile.ZipFile(stream, "a") as archive:
        archive.writestr("word/vbaProject.bin", b"macro")
    with pytest.raises(FileValidationError, match="Macro"):
        validate_file("test" + extension, MIME_TYPES[extension], stream.getvalue())
