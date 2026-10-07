import io
import zipfile

import pytest

from app.core.exceptions import FileValidationError
from app.knowledge.embeddings import HashEmbeddingProvider
from app.knowledge.parser import TextBlock, chunk_document, parse_document
from app.services.files import MIME_TYPES


def docx_bytes(xml: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_docx_paragraphs_and_table_cells_have_no_fabricated_pages() -> None:
    xml = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:body><w:p><w:r><w:t>Article 1</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Payment term</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
    </w:body></w:document>"""
    chunks = chunk_document(parse_document("test.docx", MIME_TYPES[".docx"], docx_bytes(xml)))
    assert [c.text for c in chunks] == ["Article 1", "Payment term"]
    assert all(c.page is None for c in chunks)
    assert chunks[1].locator.startswith("paragraph 2")
    assert chunks[1].article == "Article 1"


def test_docx_entities_rejected() -> None:
    xml = '<!DOCTYPE d [<!ENTITY x SYSTEM "file:///private">]><d>&x;</d>'
    with pytest.raises(FileValidationError, match="safely extracted"):
        parse_document("test.docx", MIME_TYPES[".docx"], docx_bytes(xml))


@pytest.mark.parametrize("data", [b"   ", b"\n\n"])
def test_empty_text_rejected(data: bytes) -> None:
    with pytest.raises(FileValidationError, match="No text"):
        parse_document("test.txt", "text/plain", data)


def test_corrupt_pdf_rejected() -> None:
    with pytest.raises(FileValidationError, match="safely extracted"):
        parse_document("test.pdf", "application/pdf", b"%PDF-invalid")


def test_chunking_keeps_articles_and_limits_length() -> None:
    text = "Article 1\n" + "a" * 80 + "\nArticle 2\n" + "b" * 80
    chunks = chunk_document([TextBlock(text, "page 3", page=3)], max_chars=40)
    assert all(len(c.text) <= 40 and c.page == 3 for c in chunks)
    assert {c.article for c in chunks} == {"Article 1", "Article 2"}
    assert len({c.locator for c in chunks}) == len(chunks)


def test_embeddings_stable_normalized_and_explicitly_mock() -> None:
    provider = HashEmbeddingProvider()
    vector = provider.embed("договор NDA договор")
    assert vector == provider.embed("ДОГОВОР nda ДОГОВОР")
    assert len(vector) == 128
    assert sum(v * v for v in vector) == pytest.approx(1)
    assert provider.embed("!?") == [0.0] * 128
    assert provider.model_id.startswith("mock-")
