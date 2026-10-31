"""Unit tests for document text and structure extraction engine.

Tests:
- TXT ingestion (valid UTF-8, title inference)
- MD ingestion (heading preservation, title inference)
- DOCX extraction (headings, paragraphs, tables, python-docx & XML fallback)
- PDF extraction (selectable text, page count)
- Empty files (0 bytes error)
- Whitespace-only files
- Corrupted DOCX and PDF handling
- Scanned PDF detection (pages with no selectable text)
- Unsupported extension handling
- Document length limits & warnings
"""

import io
from pathlib import Path
import pytest
import zipfile

from app.core.document_extractor import (
    ExtractedDocument,
    extract_document_content,
    validate_document_file,
    SUPPORTED_BLOG_EXTENSIONS,
    DEFAULT_MAX_DOC_SIZE_MB,
)


@pytest.fixture
def sample_docs_dir(tmp_path: Path) -> Path:
    """Fixture providing a temporary folder for creating sample document files."""
    docs_dir = tmp_path / "test_docs"
    docs_dir.mkdir()
    return docs_dir


def test_txt_extraction_valid(sample_docs_dir: Path):
    """Verifies that a valid UTF-8 plain text file extracts cleanly with title and word count."""
    txt_file = sample_docs_dir / "creator_economy_guide.txt"
    content = (
        "Building Sustainable Content Distribution Workflows\n\n"
        "Modern creators face immense fatigue from manual distribution across multiple platforms. "
        "A systematic repurposing architecture transforms single recordings into long-form blogs, "
        "short video clips, swipeable carousels, and high-impact discussions."
    )
    txt_file.write_text(content, encoding="utf-8")

    doc = extract_document_content(txt_file)
    assert doc.format == "txt"
    assert doc.filename == "creator_economy_guide.txt"
    assert doc.word_count >= 15
    assert "Building Sustainable Content Distribution Workflows" in doc.title
    assert "repurposing architecture" in doc.text
    assert doc.sha256 is not None


def test_md_extraction_with_headings(sample_docs_dir: Path):
    """Verifies that Markdown extraction preserves heading structure and titles."""
    md_file = sample_docs_dir / "content_ops.md"
    content = (
        "# Content Operations Blueprint\n\n"
        "## Introduction to Automated Distribution\n\n"
        "Manual distribution is the biggest bottleneck in creator workflows today. "
        "Engineers and marketers must establish reliable operational procedures.\n\n"
        "## Core Repurposing Pillars\n\n"
        "1. Hook formulation\n"
        "2. Step-by-step breakdowns\n"
        "3. Multi-platform attribution measurement\n"
    )
    md_file.write_text(content, encoding="utf-8")

    doc = extract_document_content(md_file)
    assert doc.format == "md"
    assert doc.title == "Content Operations Blueprint"
    assert "Introduction to Automated Distribution" in doc.headings
    assert "Core Repurposing Pillars" in doc.headings
    assert doc.word_count >= 15


def test_docx_extraction_valid(sample_docs_dir: Path):
    """Creates a real DOCX file with headings and paragraphs, verifying extraction."""
    docx_file = sample_docs_dir / "article.docx"

    import docx
    doc_obj = docx.Document()
    doc_obj.add_heading("Advanced Video Repurposing Architecture", level=1)
    doc_obj.add_paragraph(
        "Creating high-impact short videos requires identifying core pedagogical moments. "
        "When long-form recordings are transcribed, algorithmic extraction isolates the most engaging soundbites."
    )
    doc_obj.add_heading("Distribution Channels", level=2)
    doc_obj.add_paragraph(
        "Targeting YouTube Shorts, LinkedIn, Instagram, and Twitter ensures broad organic reach. "
        "Each channel demands tailored formatting, hooks, and call-to-actions."
    )
    doc_obj.save(str(docx_file))

    extracted = extract_document_content(docx_file)
    assert extracted.format == "docx"
    assert "Advanced Video Repurposing Architecture" in extracted.title
    assert "Distribution Channels" in extracted.headings
    assert "algorithmic extraction" in extracted.text
    assert extracted.word_count >= 20


def test_pdf_extraction_valid(sample_docs_dir: Path):
    """Creates a real PDF file with selectable text using pypdf/reportlab or canvas."""
    from pypdf import PdfWriter

    pdf_file = sample_docs_dir / "marketing_whitepaper.pdf"
    
    # We can create a simple PDF with text using pypdf PageObject or standard minimal PDF stream
    # Minimal standard PDF stream containing text:
    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        b"5 0 obj << /Length 210 >> stream\n"
        b"BT\n/F1 14 Tf\n50 700 Td\n(Social Media Content Engine Whitepaper) Tj\n"
        b"0 -30 Td\n(Content repurposing transforms long webinars into bite-sized clips for LinkedIn and YouTube.) Tj\n"
        b"0 -20 Td\n(Consistent publishing systems prevent creator burnout and guarantee regular audience growth.) Tj\n"
        b"ET\nendstream\nendobj\nxref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000224 00000 n \n"
        b"0000000293 00000 n \n"
        b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n555\n%%EOF"
    )
    pdf_file.write_bytes(pdf_content)

    doc = extract_document_content(pdf_file)
    assert doc.format == "pdf"
    assert "Content repurposing transforms long webinars" in doc.text
    assert doc.page_or_section_count == 1
    assert doc.word_count >= 15


def test_empty_file_rejected(sample_docs_dir: Path):
    """Verifies that a 0-byte file raises ValueError."""
    empty_txt = sample_docs_dir / "empty.txt"
    empty_txt.write_bytes(b"")

    with pytest.raises(ValueError, match="empty \\(0 bytes\\)"):
        extract_document_content(empty_txt)


def test_whitespace_only_file_rejected(sample_docs_dir: Path):
    """Verifies that a file containing only whitespace raises ValueError."""
    blank_txt = sample_docs_dir / "blank.txt"
    blank_txt.write_text("   \n\n\t   \n  ", encoding="utf-8")

    with pytest.raises(ValueError, match="empty or contains only whitespace"):
        extract_document_content(blank_txt)


def test_insufficient_content_rejected(sample_docs_dir: Path):
    """Verifies that a document with fewer than 15 words raises ValueError."""
    short_txt = sample_docs_dir / "short.txt"
    short_txt.write_text("Too short to repurpose properly.", encoding="utf-8")

    with pytest.raises(ValueError, match="insufficient text"):
        extract_document_content(short_txt)


def test_corrupted_docx_rejected(sample_docs_dir: Path):
    """Verifies that a corrupted DOCX file raises ValueError."""
    corrupt_docx = sample_docs_dir / "corrupted.docx"
    corrupt_docx.write_bytes(b"PK\x03\x04This is not a valid zip archive corrupted bytes 1234567890")

    with pytest.raises(ValueError, match="Corrupted.*Word document"):
        extract_document_content(corrupt_docx)


def test_corrupted_pdf_rejected(sample_docs_dir: Path):
    """Verifies that a corrupted PDF file raises ValueError."""
    corrupt_pdf = sample_docs_dir / "corrupted.pdf"
    corrupt_pdf.write_bytes(b"%PDF-1.4 completely corrupted binary junk that cannot be parsed as a PDF")

    with pytest.raises(ValueError, match="Corrupted or invalid PDF file"):
        extract_document_content(corrupt_pdf)


def test_scanned_pdf_detection(sample_docs_dir: Path):
    """Verifies that a PDF with pages but no selectable text is detected as scanned."""
    scanned_pdf = sample_docs_dir / "scanned_doc.pdf"
    # PDF with 1 page and empty content stream (simulating a pure raster image page without OCR)
    pdf_no_text = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\n"
        b"4 0 obj << /Length 0 >> stream\nendstream\nendobj\n"
        b"xref\n0 5\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000196 00000 n \n"
        b"trailer << /Size 5 /Root 1 0 R >>\nstartxref\n245\n%%EOF"
    )
    scanned_pdf.write_bytes(pdf_no_text)

    with pytest.raises(ValueError, match="Scanned PDF or PDF without extractable text detected"):
        extract_document_content(scanned_pdf)


def test_unsupported_file_extension(sample_docs_dir: Path):
    """Verifies that unsupported file extensions are rejected."""
    bad_file = sample_docs_dir / "script.exe"
    bad_file.write_bytes(b"some binary data")

    with pytest.raises(ValueError, match="Unsupported document format"):
        extract_document_content(bad_file)


def test_very_long_document_handled(sample_docs_dir: Path):
    """Verifies that very long documents (>100,000 words) generate a warning and cap words gracefully."""
    long_txt = sample_docs_dir / "massive_book.txt"
    # Generate exactly 105,000 words
    words = ["word"] * 105_000
    long_txt.write_text("Long Document Title\n\n" + " ".join(words), encoding="utf-8")

    doc = extract_document_content(long_txt)
    assert doc.word_count == 100_000
    assert any("very long" in w.lower() for w in doc.warnings)
