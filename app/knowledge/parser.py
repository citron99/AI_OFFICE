"""Bounded text extraction; uploads remain untrusted data, never instructions.

This is not a sandbox or OCR service. Complex PDFs require isolated workers in production.
DOCX locations are paragraph numbers, not invented physical page numbers.
"""

import io
import re
import zipfile
from dataclasses import dataclass

from defusedxml import ElementTree
from pypdf import PdfReader

from app.core.exceptions import FileValidationError
from app.services.files import validate_file

MAX_TEXT = 500_000
MAX_CHUNKS = 2000


@dataclass(frozen=True)
class TextBlock:
    text: str
    locator: str
    page: int | None = None
    article: str | None = None


def parse_document(filename: str, mime_type: str, data: bytes) -> list[TextBlock]:
    validate_file(filename, mime_type, data)
    blocks: list[TextBlock] = []
    try:
        if filename.lower().endswith(".txt"):
            blocks = [TextBlock(data.decode("utf-8-sig"), "text")]
        elif filename.lower().endswith(".pdf"):
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise FileValidationError("Encrypted PDFs are not supported")
            if len(reader.pages) > 200:
                raise FileValidationError("PDF exceeds 200 pages")
            total = 0
            for number, page in enumerate(reader.pages, 1):
                content = page.get_contents()
                if content is not None and len(content.get_data()) > 5_000_000:
                    raise FileValidationError("PDF page content exceeds extraction limit")
                text = page.extract_text() or ""
                total += len(text)
                if total > MAX_TEXT:
                    raise FileValidationError("Extracted text exceeds limit")
                # Reject partially scanned PDFs as well: never silently omit pages.
                if not text.strip():
                    raise FileValidationError(
                        "PDF contains an empty/image page; OCR review required"
                    )
                blocks.append(TextBlock(text, f"page {number}", page=number))
        elif filename.lower().endswith(".docx"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if archive.getinfo("word/document.xml").file_size > 5_000_000:
                    raise FileValidationError("DOCX XML exceeds extraction limit")
                root = ElementTree.fromstring(archive.read("word/document.xml"))
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            for number, paragraph in enumerate(root.iter(f"{ns}p"), 1):
                text = "".join(node.text or "" for node in paragraph.iter(f"{ns}t"))
                if text.strip():
                    blocks.append(TextBlock(text, f"paragraph {number}"))
        else:
            raise FileValidationError("Legal ingestion supports TXT, PDF and DOCX only")
    except FileValidationError:
        raise
    except Exception as exc:
        raise FileValidationError("Document text could not be safely extracted") from exc
    if not blocks or not any(block.text.strip() for block in blocks):
        raise FileValidationError("No text found; OCR is not implemented")
    if sum(len(block.text) for block in blocks) > MAX_TEXT:
        raise FileValidationError("Extracted text exceeds limit")
    return blocks


def chunk_document(blocks: list[TextBlock], *, max_chars: int = 1600) -> list[TextBlock]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    chunks: list[TextBlock] = []
    article: str | None = None
    for block in blocks:
        # Split on explicit legal headings, retaining the heading with its body.
        sections = re.split(r"(?im)(?=^(?:статья|article|раздел|section)\s+[\w.\-]+)", block.text)
        for section in sections:
            section = section.strip()
            if not section:
                continue
            match = re.match(r"(?i)^((?:статья|article|раздел|section)\s+[\w.\-]+)", section)
            if match:
                article = match.group(1)[:255]
            for offset in range(0, len(section), max_chars):
                chunks.append(
                    TextBlock(
                        section[offset : offset + max_chars],
                        f"{block.locator}; part {len(chunks) + 1}",
                        block.page,
                        article,
                    )
                )
                if len(chunks) > MAX_CHUNKS:
                    raise FileValidationError("Document exceeds chunk limit")
    return chunks
