"""Document text and structure extraction engine for IncuBrix.

Supports:
- Plain Text (.txt): UTF-8 text with whitespace normalization.
- Markdown (.md): Markdown documents with heading structure preserved.
- Word Documents (.docx): Heading hierarchy and paragraph extraction.
- PDF Documents (.pdf): Selectable text extraction with scanned-document detection.

Security & Integrity:
- Never sends raw binary files to LLMs; normalizes and cleans text first.
- Rejects empty, corrupted, encrypted, or scanned documents with clear errors.
- Enforces strict file-size and word-count thresholds.
- Preserves document title, headings, and structural section boundaries.
"""

from dataclasses import dataclass, field
import hashlib
import io
import logging
from pathlib import Path
import re
from typing import Dict, List, Optional, Set, Tuple, Union
import zipfile
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

SUPPORTED_BLOG_EXTENSIONS: Set[str] = {".txt", ".md", ".docx", ".pdf"}
DEFAULT_MAX_DOC_SIZE_MB: float = 10.0  # 10 MB maximum for documents
MIN_DOCUMENT_WORDS: int = 15
MAX_DOCUMENT_WORDS: int = 100_000


@dataclass
class ExtractedDocument:
    """Normalized structured content extracted from an uploaded document."""
    filename: str
    format: str
    file_size_bytes: int
    sha256: str
    title: str
    text: str
    headings: List[str] = field(default_factory=list)
    word_count: int = 0
    char_count: int = 0
    page_or_section_count: int = 1
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Union[str, int, List[str]]]:
        return {
            "filename": self.filename,
            "format": self.format,
            "file_size_bytes": self.file_size_bytes,
            "sha256": self.sha256,
            "title": self.title,
            "text": self.text,
            "headings": self.headings,
            "word_count": self.word_count,
            "char_count": self.char_count,
            "page_or_section_count": self.page_or_section_count,
            "warnings": self.warnings,
        }


def compute_bytes_sha256(data: bytes) -> str:
    """Computes SHA-256 hex digest of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()


def compute_file_sha256(file_path: Union[str, Path]) -> str:
    """Computes SHA-256 hex digest of a file on disk."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def normalize_extracted_text(raw_text: str) -> str:
    """Normalizes line endings, tabs, non-breaking spaces, and excess blank lines."""
    if not raw_text:
        return ""
    # Standardize line endings
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    # Replace non-breaking spaces
    text = text.replace("\u00a0", " ")
    # Replace horizontal tabs
    text = text.replace("\t", "    ")
    # Remove trailing whitespace per line
    lines = [re.sub(r"[ ]+$", "", line) for line in text.split("\n")]
    joined = "\n".join(lines)
    # Collapse 3+ consecutive newlines to 2 newlines (paragraph boundary)
    collapsed = re.sub(r"\n{3,}", "\n\n", joined)
    return collapsed.strip()


def validate_document_file(
    file_path: Union[str, Path],
    max_size_mb: float = DEFAULT_MAX_DOC_SIZE_MB,
) -> Path:
    """Validates that a document file exists, is a regular file, is not empty, and has a supported extension."""
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Document file not found: '{file_path}'.")
    if not path.is_file():
        raise ValueError(f"Specified path is not a regular file: '{file_path}'.")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_BLOG_EXTENSIONS:
        supported_str = ", ".join(sorted(SUPPORTED_BLOG_EXTENSIONS))
        raise ValueError(
            f"Unsupported document format '{ext}'. Only {supported_str} files are supported."
        )

    size_bytes = path.stat().st_size
    if size_bytes == 0:
        raise ValueError(f"Document file '{path.name}' is empty (0 bytes).")

    size_mb = size_bytes / (1024 * 1024)
    if size_mb > max_size_mb:
        raise ValueError(
            f"Document file size ({size_mb:.2f} MB) exceeds maximum allowed limit of {max_size_mb:.1f} MB."
        )

    return path


def extract_text_from_txt(path: Path) -> Tuple[str, List[str], str]:
    """Extracts text from a plain text file, inferring title from first non-empty line."""
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Fallback to utf-8-sig or latin-1 with notification
        try:
            raw = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                raw = path.read_text(encoding="latin-1")
            except Exception as exc:
                raise ValueError(f"Failed to decode text file '{path.name}': {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Error reading text file '{path.name}': {exc}") from exc

    cleaned = normalize_extracted_text(raw)
    if not cleaned:
        raise ValueError(f"Text file '{path.name}' is empty or contains only whitespace.")

    lines = cleaned.split("\n")
    title = path.stem.replace("_", " ").title()
    headings: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped:
            title = stripped[:80]
            headings.append(title)
            break

    return cleaned, headings, title


def extract_text_from_md(path: Path) -> Tuple[str, List[str], str]:
    """Extracts text from Markdown, preserving heading structure and extracting titles."""
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            raw = path.read_text(encoding="utf-8-sig")
        except Exception as exc:
            raise ValueError(f"Markdown file '{path.name}' is not valid UTF-8 text: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Error reading Markdown file '{path.name}': {exc}") from exc

    cleaned = normalize_extracted_text(raw)
    if not cleaned:
        raise ValueError(f"Markdown file '{path.name}' is empty or contains only whitespace.")

    # Find Markdown headings
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    headings: List[str] = []
    title = path.stem.replace("_", " ").title()

    for match in heading_pattern.finditer(cleaned):
        h_text = match.group(2).strip()
        headings.append(h_text)
        if match.group(1) == "#" and title == path.stem.replace("_", " ").title():
            title = h_text

    if not headings:
        # Check first non-empty line
        for line in cleaned.split("\n"):
            stripped = line.strip()
            if stripped:
                title = stripped[:80]
                break

    return cleaned, headings, title


def extract_text_from_docx(path: Path) -> Tuple[str, List[str], str]:
    """Extracts paragraphs and headings from a Word (.docx) document."""
    # First attempt: python-docx if installed
    try:
        import docx
        doc = docx.Document(str(path))
        lines: List[str] = []
        headings: List[str] = []
        title: Optional[str] = None

        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue

            style_name = p.style.name.lower() if p.style and p.style.name else ""
            if "heading 1" in style_name:
                lines.append(f"# {text}")
                headings.append(text)
                if not title:
                    title = text
            elif "heading 2" in style_name:
                lines.append(f"## {text}")
                headings.append(text)
            elif "heading 3" in style_name:
                lines.append(f"### {text}")
                headings.append(text)
            elif "title" in style_name:
                lines.append(f"# {text}")
                headings.append(text)
                title = text
            else:
                lines.append(text)

        # Also extract table text if present
        for table in doc.tables:
            for row in table.rows:
                row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_cells:
                    lines.append(" | ".join(row_cells))

        joined = "\n\n".join(lines)
        cleaned = normalize_extracted_text(joined)
        if not cleaned:
            raise ValueError(f"Word document '{path.name}' contains no readable text.")

        resolved_title = title or (headings[0] if headings else path.stem.replace("_", " ").title())
        return cleaned, headings, resolved_title

    except (zipfile.BadZipFile, IOError) as exc:
        raise ValueError(f"Corrupted or invalid Word document '{path.name}': {exc}") from exc
    except Exception as exc:
        if "contains no readable text" in str(exc) or "Corrupted" in str(exc):
            raise
        # Fallback to direct XML parsing via zipfile
        return _extract_docx_xml_fallback(path)


def _extract_docx_xml_fallback(path: Path) -> Tuple[str, List[str], str]:
    """Fallback DOCX extractor using standard library zipfile and XML element tree."""
    try:
        with zipfile.ZipFile(str(path)) as zf:
            if "word/document.xml" not in zf.namelist():
                raise ValueError(f"Invalid DOCX structure in '{path.name}': missing word/document.xml.")
            xml_content = zf.read("word/document.xml")

        root = ET.fromstring(xml_content)
        # XML namespace for WordprocessingML
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

        paragraphs: List[str] = []
        headings: List[str] = []
        title: Optional[str] = None

        for p in root.iterfind(".//w:p", ns):
            # Check paragraph style
            p_style = p.find(".//w:pPr/w:pStyle", ns)
            style_val = (p_style.attrib.get(f"{{{ns['w']}}}val") or "").lower() if p_style is not None else ""

            # Extract run texts
            runs = [node.text for node in p.iterfind(".//w:t", ns) if node.text]
            p_text = "".join(runs).strip()
            if not p_text:
                continue

            if "heading1" in style_val or "heading 1" in style_val:
                paragraphs.append(f"# {p_text}")
                headings.append(p_text)
                if not title:
                    title = p_text
            elif "heading2" in style_val or "heading 2" in style_val:
                paragraphs.append(f"## {p_text}")
                headings.append(p_text)
            elif "heading" in style_val or "title" in style_val:
                paragraphs.append(f"# {p_text}")
                headings.append(p_text)
                if not title:
                    title = p_text
            else:
                paragraphs.append(p_text)

        cleaned = normalize_extracted_text("\n\n".join(paragraphs))
        if not cleaned:
            raise ValueError(f"Word document '{path.name}' contains no readable text.")

        resolved_title = title or (headings[0] if headings else path.stem.replace("_", " ").title())
        return cleaned, headings, resolved_title

    except ET.ParseError as exc:
        raise ValueError(f"Corrupted XML in Word document '{path.name}': {exc}") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Corrupted Word document (bad ZIP archive) '{path.name}': {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Failed to extract Word document '{path.name}': {exc}") from exc


def extract_text_from_pdf(path: Path) -> Tuple[str, List[str], str, int]:
    """Extracts selectable text from a PDF file using pypdf.

    Detects:
    - Empty or 0-page PDFs
    - Password-protected / encrypted PDFs
    - Scanned PDFs without extractable text streams
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pypdf library is required for PDF text extraction.")

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise ValueError(f"Corrupted or invalid PDF file '{path.name}': {exc}") from exc

    if reader.is_encrypted:
        raise ValueError(f"PDF file '{path.name}' is password-protected or encrypted.")

    num_pages = len(reader.pages)
    if num_pages == 0:
        raise ValueError(f"PDF file '{path.name}' has 0 pages.")

    pages_text: List[str] = []
    headings: List[str] = []

    for page_idx, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
            text_clean = text.strip()
            if text_clean:
                pages_text.append(text_clean)
        except Exception as exc:
            logger.warning("Error extracting page %d from '%s': %s", page_idx, path.name, exc)

    combined_text = "\n\n".join(pages_text)
    cleaned = normalize_extracted_text(combined_text)

    # Scanned PDF Detection Rule:
    # If the document has pages, but total extracted characters across all pages < 15
    if len(cleaned.replace(" ", "").replace("\n", "")) < 15:
        raise ValueError(
            f"Scanned PDF or PDF without extractable text detected in '{path.name}'. "
            f"The document contains {num_pages} page(s) but no selectable text stream. "
            "Optical Character Recognition (OCR) is required."
        )

    # Infer title and headings from outline/bookmarks or text formatting
    title = path.stem.replace("_", " ").title()
    try:
        outline = reader.outline
        if outline:
            for item in outline:
                if hasattr(item, "title") and item.title:
                    headings.append(item.title.strip())
            if headings:
                title = headings[0]
    except Exception:
        pass

    if not headings:
        # Heuristic: look for lines that look like section titles (short, capitalized, followed by newline)
        lines = cleaned.split("\n")
        for line in lines[:20]:
            stripped = line.strip()
            if 3 <= len(stripped) <= 80 and not stripped.endswith("."):
                headings.append(stripped)
                if title == path.stem.replace("_", " ").title():
                    title = stripped
                if len(headings) >= 5:
                    break

    return cleaned, headings, title, num_pages


def extract_document_content(file_path: Union[str, Path]) -> ExtractedDocument:
    """Unified entry point for document validation, extraction, and normalization.

    Supports:
    - .txt
    - .md
    - .docx
    - .pdf

    Raises descriptive ValueError on corrupted, empty, scanned, or unsupported files.
    """
    valid_path = validate_document_file(file_path)
    file_bytes = valid_path.read_bytes()
    sha256 = compute_bytes_sha256(file_bytes)
    size_bytes = len(file_bytes)
    ext = valid_path.suffix.lower()

    num_pages = 1
    warnings: List[str] = []

    if ext == ".txt":
        cleaned_text, headings, title = extract_text_from_txt(valid_path)
    elif ext == ".md":
        cleaned_text, headings, title = extract_text_from_md(valid_path)
    elif ext == ".docx":
        cleaned_text, headings, title = extract_text_from_docx(valid_path)
    elif ext == ".pdf":
        cleaned_text, headings, title, num_pages = extract_text_from_pdf(valid_path)
    else:
        raise ValueError(f"Unsupported document format '{ext}'.")

    # Word count check
    words = cleaned_text.split()
    word_count = len(words)
    if word_count < MIN_DOCUMENT_WORDS:
        raise ValueError(
            f"Document '{valid_path.name}' contains insufficient text ({word_count} words). "
            f"At least {MIN_DOCUMENT_WORDS} words are required to generate content suggestions."
        )

    if word_count > MAX_DOCUMENT_WORDS:
        warnings.append(
            f"Document is very long ({word_count:,} words). "
            f"Content will be analyzed focusing on the primary sections (first {MAX_DOCUMENT_WORDS:,} words)."
        )
        words = words[:MAX_DOCUMENT_WORDS]
        cleaned_text = " ".join(words)
        word_count = len(words)

    char_count = len(cleaned_text)

    return ExtractedDocument(
        filename=valid_path.name,
        format=ext.lstrip("."),
        file_size_bytes=size_bytes,
        sha256=sha256,
        title=title,
        text=cleaned_text,
        headings=headings,
        word_count=word_count,
        char_count=char_count,
        page_or_section_count=num_pages,
        warnings=warnings,
    )

