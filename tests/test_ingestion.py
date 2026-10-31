"""Unit tests for app.core.ingestion module."""

from pathlib import Path
import pytest

from app.core.ingestion import (
    validate_source_path,
    read_source_file,
    normalize_whitespace,
    split_into_sentences,
    generate_segment_id,
    ingest_source_document,
    SUPPORTED_EXTENSIONS,
    MIN_DOCUMENT_WORDS,
    MIN_SEGMENT_WORDS
)
from app.models.asset import SourceSegment


def test_validate_source_path_nonexistent(tmp_path: Path):
    non_existent = tmp_path / "missing_file.md"
    with pytest.raises(FileNotFoundError, match="Source file not found"):
        validate_source_path(non_existent)


def test_validate_source_path_unsupported_extension(tmp_path: Path):
    bad_ext_file = tmp_path / "document.pdf"
    bad_ext_file.write_text("Test content for unsupported file.", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        validate_source_path(bad_ext_file)


def test_validate_source_path_is_directory(tmp_path: Path):
    dir_path = tmp_path / "test_dir"
    dir_path.mkdir()
    with pytest.raises(ValueError, match="not a regular file"):
        validate_source_path(dir_path)


def test_validate_source_path_valid(tmp_path: Path):
    md_file = tmp_path / "valid.md"
    md_file.write_text("Valid text content with sufficient words to pass the ingestion test check.", encoding="utf-8")
    result = validate_source_path(md_file)
    assert result == md_file


def test_read_source_file_empty(tmp_path: Path):
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("   \n\t  \n  ", encoding="utf-8")
    with pytest.raises(ValueError, match="empty or contains only whitespace"):
        read_source_file(empty_file)


def test_read_source_file_insufficient_words(tmp_path: Path):
    short_file = tmp_path / "short.txt"
    short_file.write_text("Only seven words in this tiny test file.", encoding="utf-8")
    with pytest.raises(ValueError, match="insufficient content"):
        read_source_file(short_file)


def test_normalize_whitespace():
    raw = "Line 1   \r\n\r\nLine 2 with \u00a0nbsp and \ttab.   \r\n\r\n\r\n\r\nLine 3."
    normalized = normalize_whitespace(raw)
    assert "\r" not in normalized
    assert "\u00a0" not in normalized
    assert "\t" not in normalized
    assert "Line 1\n\nLine 2 with  nbsp and  tab.\n\nLine 3." == normalized


def test_split_into_sentences():
    text = "First operational principle. Second sentence has more detail! Is this the third sentence? Yes."
    sentences = split_into_sentences(text)
    assert len(sentences) == 4
    assert sentences[0] == "First operational principle."
    assert sentences[1] == "Second sentence has more detail!"
    assert sentences[2] == "Is this the third sentence?"
    assert sentences[3] == "Yes."


def test_generate_segment_id_deterministic():
    id1 = generate_segment_id("guide.md", 1, "Content production requires disciplined planning.")
    id2 = generate_segment_id("guide.md", 1, "Content production requires disciplined planning.")
    id3 = generate_segment_id("guide.md", 2, "Content production requires disciplined planning.")

    assert id1 == id2
    assert id1 != id3
    assert id1.startswith("seg_01_")


def test_ingest_source_document_markdown(tmp_path: Path):
    md_file = tmp_path / "strategy_guide.md"
    content = (
        "# Editorial Operations Guide\n\n"
        "Content marketing teams often face severe bottlenecks when attempting to publish daily across multiple social channels. "
        "Standardizing the recording and distribution process removes guesswork and prevents creator exhaustion.\n\n"
        "## Repurposing Workflow\n\n"
        "Every primary video or long-form article should be segmented into standalone tactical lessons before formatting. "
        "This ensures that each derivative asset communicates a clear takeaway rather than an incomplete summary."
    )
    md_file.write_text(content, encoding="utf-8")

    segments = ingest_source_document(md_file)
    assert len(segments) == 2
    assert isinstance(segments[0], SourceSegment)
    assert segments[0].source_document == "strategy_guide.md"
    assert segments[0].segment_index == 1
    assert segments[0].heading == "Editorial Operations Guide"
    assert len(segments[0].sentences) == 2
    assert segments[0].word_count > MIN_SEGMENT_WORDS

    assert segments[1].segment_index == 2
    assert segments[1].heading == "Repurposing Workflow"
    assert len(segments[1].sentences) == 2


def test_ingest_source_document_txt(tmp_path: Path):
    txt_file = tmp_path / "brief.txt"
    content = (
        "Content marketing teams often face severe bottlenecks when attempting to publish daily across multiple social channels. "
        "Standardizing the recording and distribution process removes guesswork and prevents creator exhaustion."
    )
    txt_file.write_text(content, encoding="utf-8")

    segments = ingest_source_document(txt_file)
    assert len(segments) == 1
    assert segments[0].source_document == "brief.txt"
    assert segments[0].heading is None
    assert segments[0].segment_index == 1


def test_ingest_source_document_short_paragraphs_filtered(tmp_path: Path):
    md_file = tmp_path / "mixed.md"
    content = (
        "# Section Header\n\n"
        "Too short.\n\n"
        "This paragraph is substantially longer and contains enough words to qualify as a valid operational segment for extraction and drafting."
    )
    md_file.write_text(content, encoding="utf-8")

    segments = ingest_source_document(md_file)
    assert len(segments) == 1
    assert "substantially longer" in segments[0].text


def test_ingest_source_document_no_qualifying_segments(tmp_path: Path):
    md_file = tmp_path / "no_segments.md"
    content = "Word one word two. \n\nWord three word four. \n\nWord five word six. \n\nWord seven word eight. \n\nWord nine word ten."
    md_file.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="no valid segments met the minimum length threshold"):
        ingest_source_document(md_file)

