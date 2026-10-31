"""Deterministic source document ingestion and segmentation module.

Reads user-provided UTF-8 text/Markdown documents, validates file integrity,
normalizes whitespace, and segments content using deterministic paragraph
and sentence rules. Assigns stable, collision-free segment IDs for traceability.
"""

import hashlib
import re
from pathlib import Path
from typing import List, Union, Optional

from app.models.asset import SourceSegment

SUPPORTED_EXTENSIONS = {".txt", ".md"}
MIN_DOCUMENT_WORDS = 15
MIN_SEGMENT_WORDS = 8


def validate_source_path(file_path: Union[str, Path]) -> Path:
    """Validates that the source path exists, is a regular file, and has a supported extension."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Source path is not a regular file: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file extension '{path.suffix}'. Only .txt and .md files are supported."
        )
    return path


def read_source_file(path: Path) -> str:
    """Reads UTF-8 text from disk, raising explicit errors on empty or unreadable content."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"File '{path.name}' is not valid UTF-8 text: {e}")
    except Exception as e:
        raise IOError(f"Failed to read file '{path.name}': {e}")

    stripped = raw_text.strip()
    if not stripped:
        raise ValueError(f"Source file '{path.name}' is empty or contains only whitespace.")

    word_count = len(stripped.split())
    if word_count < MIN_DOCUMENT_WORDS:
        raise ValueError(
            f"Source file '{path.name}' contains insufficient content ({word_count} words). "
            f"Minimum {MIN_DOCUMENT_WORDS} words required for ingestion."
        )
    return raw_text


def normalize_whitespace(text: str) -> str:
    """Normalizes line breaks and whitespace while strictly preserving paragraph boundaries."""
    # Standardize line endings to Unix format
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    # Replace non-breaking spaces with standard space
    normalized = normalized.replace("\u00a0", " ")
    # Replace tabs with spaces
    normalized = normalized.replace("\t", " ")
    # Strip trailing horizontal whitespace from each line
    lines = [re.sub(r"[ ]+$", "", line) for line in normalized.split("\n")]
    joined = "\n".join(lines)
    # Collapse 3+ consecutive newlines to double newlines (standard paragraph boundary)
    collapsed = re.sub(r"\n{3,}", "\n\n", joined)
    return collapsed.strip()


def split_into_sentences(text: str) -> List[str]:
    """Deterministically splits text into sentence units using punctuation boundaries."""
    # Split on periods, exclamation marks, or question marks followed by whitespace and a capital letter/quote
    raw_sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“‘])", text)
    sentences = [s.strip() for s in raw_sentences if s.strip()]
    if not sentences and text.strip():
        sentences = [text.strip()]
    return sentences


def generate_segment_id(doc_name: str, index: int, text: str) -> str:
    """Generates a stable, reproducible segment ID using SHA-256 hash."""
    clean_text = re.sub(r"\s+", " ", text.strip())
    hash_salt = f"{doc_name}:{index}:{clean_text}".encode("utf-8")
    hash_digest = hashlib.sha256(hash_salt).hexdigest()[:8]
    return f"seg_{index:02d}_{hash_digest}"


def ingest_source_document(file_path: Union[str, Path]) -> List[SourceSegment]:
    """Ingests, validates, normalizes, and segments a local source text/markdown document.

    Guarantees deterministic, reproducible segmentation across runs on identical files.
    Never downloads external content or silently substitutes data.
    """
    path = validate_source_path(file_path)
    raw_text = read_source_file(path)
    normalized = normalize_whitespace(raw_text)

    doc_name = path.name
    paragraphs = normalized.split("\n\n")

    segments: List[SourceSegment] = []
    current_heading: Optional[str] = None
    line_cursor = 1
    segment_counter = 1

    for para_idx, para in enumerate(paragraphs, start=1):
        clean_para = para.strip()
        if not clean_para:
            continue

        # Check for Markdown heading lines
        heading_match = re.match(r"^#{1,6}\s+(.+)$", clean_para)
        if heading_match:
            current_heading = heading_match.group(1).strip()
            line_cursor += clean_para.count("\n") + 2
            continue

        # Check if the paragraph has sufficient substance
        words = clean_para.split()
        if len(words) < MIN_SEGMENT_WORDS:
            # If paragraph is too short, retain line count and move forward
            line_cursor += clean_para.count("\n") + 2
            continue

        sentences = split_into_sentences(clean_para)
        segment_id = generate_segment_id(doc_name, segment_counter, clean_para)
        location_label = f"Paragraph {para_idx}, Approx Line {line_cursor}"

        segment = SourceSegment(
            segment_id=segment_id,
            source_document=doc_name,
            segment_index=segment_counter,
            source_location=location_label,
            heading=current_heading,
            text=clean_para,
            word_count=len(words),
            char_count=len(clean_para),
            sentences=sentences
        )
        segments.append(segment)
        segment_counter += 1
        line_cursor += clean_para.count("\n") + 2

    if not segments:
        raise ValueError(
            f"Source file '{doc_name}' contained text, but no valid segments met the "
            f"minimum length threshold ({MIN_SEGMENT_WORDS} words)."
        )

    return segments

