"""Unit tests for content calendar CSV exporter module."""

import csv
import io
from pathlib import Path
import pytest

from app.core.calendar_export import (
    CALENDAR_CSV_COLUMNS,
    convert_draft_to_calendar_row,
    export_calendar_csv_string,
    export_calendar_csv_file
)
from app.core.generator import generate_draft_candidates
from app.models.asset import (
    SourceSegment,
    DraftCandidate,
    PlatformEnum,
    AssetFormatEnum,
    PillarEnum,
    ClaimCategoryEnum
)


@pytest.fixture
def sample_drafts() -> list[DraftCandidate]:
    seg = SourceSegment(
        segment_id="seg_01_a1b2c3d4",
        source_document="workflow_guide.md",
        segment_index=1,
        source_location="Paragraph 1, Line 1",
        heading="Repurposing Systems",
        text=(
            "Creating multi-channel content without a structured system often causes severe creative fatigue. "
            "A repeatable repurpose engine turns one core long-form recording into ten platform-specific assets, "
            "allowing \"creators\" to scale output."
        ),
        word_count=32,
        char_count=230,
        sentences=[
            "Creating multi-channel content without a structured system often causes severe creative fatigue.",
            "A repeatable repurpose engine turns one core long-form recording into ten platform-specific assets, allowing \"creators\" to scale output."
        ]
    )
    return generate_draft_candidates([seg])


def test_calendar_headers_count_and_order():
    assert len(CALENDAR_CSV_COLUMNS) == 20
    assert CALENDAR_CSV_COLUMNS[0] == "asset_id"
    assert CALENDAR_CSV_COLUMNS[1] == "platform"
    assert CALENDAR_CSV_COLUMNS[8] == "destination_url"
    assert CALENDAR_CSV_COLUMNS[9] == "tracking_url"
    assert CALENDAR_CSV_COLUMNS[17] == "publication_status"
    assert CALENDAR_CSV_COLUMNS[18] == "warnings"
    assert CALENDAR_CSV_COLUMNS[19] == "quality_gate_status"


def test_convert_draft_to_calendar_row_blank_urls(sample_drafts):
    draft = sample_drafts[0]
    row = convert_draft_to_calendar_row(draft, destination_url=None)

    assert row["asset_id"] == draft.draft_id
    assert row["platform"] == draft.platform.value
    assert row["destination_url"] == ""
    assert row["tracking_url"] == ""
    assert row["scheduled_date"] == ""
    assert row["scheduled_time"] == ""
    assert row["publication_status"] == "DRAFT_PENDING_REVIEW"
    assert row["requires_human_review"] == "TRUE"
    assert row["source_segment_id"] == draft.source_segment_id
    assert row["source_document"] == draft.source_document
    assert row["quality_gate_status"] == "NOT_EVALUATED"


def test_calendar_csv_with_quality_results_integration(sample_drafts):
    # Test quality status integration
    quality_mock = [{"asset_id": sample_drafts[0].draft_id, "overall_status": "PASS"}]
    csv_str = export_calendar_csv_string(sample_drafts, quality_results=quality_mock)
    reader = csv.DictReader(io.StringIO(csv_str))
    rows = list(reader)
    assert rows[0]["quality_gate_status"] == "PASS"
    assert rows[1]["quality_gate_status"] == "NOT_EVALUATED"
    # Publication status remains draft
    assert rows[0]["publication_status"] == "DRAFT_PENDING_REVIEW"


def test_convert_draft_to_calendar_row_with_destination_url(sample_drafts):
    draft = sample_drafts[0]
    dest = "https://app.incubrix.com/explore"
    row = convert_draft_to_calendar_row(draft, destination_url=dest)

    assert row["destination_url"] == dest
    assert "utm_source=" in row["tracking_url"]
    assert "utm_medium=" in row["tracking_url"]
    assert "utm_content=" in row["tracking_url"]


def test_export_calendar_csv_string_empty():
    csv_str = export_calendar_csv_string([])
    lines = csv_str.strip().split("\n")
    assert len(lines) == 1  # Header row only
    reader = csv.reader(io.StringIO(csv_str))
    header = next(reader)
    assert header == CALENDAR_CSV_COLUMNS


def test_export_calendar_csv_multiple_platforms(sample_drafts):
    dest = "https://app.incubrix.com/"
    csv_str = export_calendar_csv_string(sample_drafts, destination_url=dest)

    reader = csv.DictReader(io.StringIO(csv_str))
    rows = list(reader)
    assert len(rows) == 4

    platforms = {r["platform"] for r in rows}
    assert platforms == {"linkedin", "youtube_shorts", "twitter", "instagram"}

    for r in rows:
        assert r["publication_status"] == "DRAFT_PENDING_REVIEW"
        assert r["requires_human_review"] == "TRUE"
        assert r["source_document"] == "workflow_guide.md"
        assert r["source_segment_id"] == "seg_01_a1b2c3d4"
        assert r["claim_category"] == "SOURCE_ATTRIBUTED_UNVERIFIED"
        assert "utm_source=" in r["tracking_url"]


def test_csv_escapes_commas_quotes_and_newlines(sample_drafts):
    # Caption has embedded newlines and quotes
    draft = sample_drafts[0]
    assert "\n" in draft.draft_caption

    csv_str = export_calendar_csv_string([draft])
    reader = csv.DictReader(io.StringIO(csv_str))
    row = next(reader)
    # The reader properly parses the multi-line caption back
    assert row["caption_or_script"] == draft.draft_caption
    assert row["asset_id"] == draft.draft_id


def test_export_calendar_csv_file(sample_drafts, tmp_path: Path):
    out_file = tmp_path / "export" / "content_calendar.csv"
    dest = "https://app.incubrix.com/"
    created_path = export_calendar_csv_file(sample_drafts, out_file, destination_url=dest)

    assert created_path.exists()
    assert created_path == out_file

    # Verify utf-8-sig encoding (starts with BOM \ufeff when read as utf-8)
    raw_bytes = created_path.read_bytes()
    assert raw_bytes.startswith(b"\xef\xbb\xbf")

    # Read with utf-8-sig
    content = created_path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    assert len(rows) == 4
    assert rows[0]["asset_id"] == sample_drafts[0].draft_id

