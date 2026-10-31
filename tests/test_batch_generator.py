"""Unit tests for batch content generation and quality reporting module."""

import json
from pathlib import Path
import pytest

from app.core.batch_generator import (
    run_batch_generation,
    export_quality_report_json,
    BatchGenerationResult
)
from app.core.calendar_export import export_calendar_csv_string
from app.models.asset import SourceSegment, PlatformEnum
from app.core.quality_gate import QualityGateStatusEnum


@pytest.fixture
def multi_segment_source() -> list[SourceSegment]:
    """Provides 3 distinct source segments (capable of producing 12 platform assets)."""
    return [
        SourceSegment(
            segment_id=f"seg_{idx:02d}_abc{idx}",
            source_document="operations_masterclass.md",
            segment_index=idx,
            source_location=f"Paragraph {idx}, Line {idx * 10}",
            heading=f"Section {idx}: Content Operations Pillar {idx}",
            text=(
                f"Operational principle {idx} for systematic content distribution across modern B2B channels. "
                "Establishing consistent production procedures removes guesswork and creative friction. "
                "Teams can reliably multiply core long-form assets without burning out creators."
            ),
            word_count=34,
            char_count=240,
            sentences=[
                f"Operational principle {idx} for systematic content distribution across modern B2B channels.",
                "Establishing consistent production procedures removes guesswork and creative friction.",
                "Teams can reliably multiply core long-form assets without burning out creators."
            ]
        )
        for idx in range(1, 4)
    ]


@pytest.fixture
def single_segment_source() -> list[SourceSegment]:
    """Provides 1 single segment (produces only 4 assets, demonstrating honest shortfall)."""
    return [
        SourceSegment(
            segment_id="seg_01_solo",
            source_document="short_memo.md",
            segment_index=1,
            source_location="Paragraph 1, Line 1",
            heading="Brief Note",
            text=(
                "A brief standalone note on content operations and video repurposing techniques. "
                "This single segment contains enough words for ingestion but not enough material for 10 assets."
            ),
            word_count=26,
            char_count=175,
            sentences=[
                "A brief standalone note on content operations and video repurposing techniques.",
                "This single segment contains enough words for ingestion but not enough material for 10 assets."
            ]
        )
    ]


def test_batch_generation_multi_segment(multi_segment_source):
    """3 segments yield 12 unique assets, satisfying target_count=10 without duplication."""
    result = run_batch_generation(multi_segment_source, target_count=10)

    assert isinstance(result, BatchGenerationResult)
    assert result.total_segments_ingested == 3
    assert result.total_assets_generated == 12
    assert result.target_met is True
    assert result.shortfall == 0

    # Ensure all draft IDs are unique
    draft_ids = [d.draft_id for d in result.drafts]
    assert len(draft_ids) == len(set(draft_ids))

    # Check platform distribution: 3 of each platform
    assert result.platform_counts.get("linkedin") == 3
    assert result.platform_counts.get("youtube_shorts") == 3
    assert result.platform_counts.get("twitter") == 3
    assert result.platform_counts.get("instagram") == 3

    # Check quality results count
    assert len(result.quality_results) == 12
    for qr in result.quality_results:
        assert qr.requires_human_review is True
        assert qr.is_ready_to_publish is False


def test_batch_generation_insufficient_source_material_reports_shortfall(single_segment_source):
    """When source material yields fewer than target assets, shortfall is reported honestly."""
    result = run_batch_generation(single_segment_source, target_count=10)

    # 1 segment -> exactly 4 assets
    assert result.total_assets_generated == 4
    assert result.target_met is False
    assert result.shortfall == 6

    # Verify no synthetic duplicate padding was applied
    assert len(result.drafts) == 4
    report = result.to_report_dict()
    assert report["generation_metrics"]["duplicate_padding_applied"] is False
    assert "Shortfall of 6 assets" in report["generation_metrics"]["shortfall_notice"]


def test_batch_generation_from_file_path(tmp_path: Path):
    """Tests batch generation passing a real file path."""
    doc_path = tmp_path / "long_form_guide.md"
    content = (
        "# Editorial Procedures\n\n"
        "First major section discussing structured content distribution and multi-channel publication frameworks. "
        "Standardizing recording schedules prevents team exhaustion and maintains output quality.\n\n"
        "## Second Tactical Section\n\n"
        "Second major section discussing retention-focused hook structures and opening video sequences. "
        "Immediate kinetic disruption prevents audience drop-off in the first three seconds."
    )
    doc_path.write_text(content, encoding="utf-8")

    result = run_batch_generation(doc_path, target_count=8)
    assert result.total_segments_ingested == 2
    assert result.total_assets_generated == 8
    assert result.target_met is True
    assert result.source_document == "long_form_guide.md"


def test_batch_generation_empty_input_raises_value_error():
    with pytest.raises(ValueError, match="Cannot run batch generation"):
        run_batch_generation([])


def test_export_quality_report_json(multi_segment_source, tmp_path: Path):
    """Verifies that export_quality_report_json creates valid, structured JSON report."""
    batch_res = run_batch_generation(multi_segment_source, target_count=10)
    out_file = tmp_path / "reports" / "quality_audit_report.json"

    created = export_quality_report_json(batch_res, out_file)
    assert created.exists()

    data = json.loads(created.read_text(encoding="utf-8"))
    assert data["generation_metrics"]["total_unique_assets_generated"] == 12
    assert data["generation_metrics"]["target_goal_satisfied"] is True
    assert data["quality_gate_summary"]["ready_to_publish"] == 0
    assert data["quality_gate_summary"]["requiring_human_review"] == 12
    assert len(data["asset_evaluations"]) == 12


def test_batch_results_integrate_with_calendar_csv(multi_segment_source):
    """Quality results from batch generation pass into CSV export cleanly."""
    import csv
    import io

    batch_res = run_batch_generation(multi_segment_source, target_count=10)
    csv_str = export_calendar_csv_string(
        drafts=batch_res.drafts,
        quality_results=batch_res.quality_results
    )

    assert "quality_gate_status" in csv_str
    # Verify all 12 rows are parsed properly by RFC 4180 CSV reader
    reader = csv.DictReader(io.StringIO(csv_str))
    rows = list(reader)
    assert len(rows) == 12  # exactly 12 asset records
    for r in rows:
        assert r["publication_status"] == "DRAFT_PENDING_REVIEW"
        assert r["requires_human_review"] == "TRUE"
        assert r["quality_gate_status"] in ("PASS", "PASS_WITH_WARNINGS", "FAIL")
