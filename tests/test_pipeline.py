"""Unit and integration tests for Phase 3.6 End-to-End Content Pipeline."""

import csv
import io
import json
from pathlib import Path
import pytest

from app.core.pipeline import run_content_pipeline, PipelineResult
from app.core.review_workflow import ReviewWorkflowManager, ReviewStatusEnum
from app.models.asset import PlatformEnum, AssetFormatEnum, ClaimCategoryEnum


@pytest.fixture
def synthetic_fixture_path() -> Path:
    return Path("sample_inputs/repurposing_operations_guide.md")


# 1. Successful end-to-end execution with a local synthetic fixture
def test_successful_end_to_end_execution(synthetic_fixture_path: Path, tmp_path: Path):
    result = run_content_pipeline(
        source_path=synthetic_fixture_path,
        destination_url="https://app.incubrix.com/explore",
        output_dir=tmp_path / "runs",
        render_media=False  # Fast mode for unit test
    )

    assert isinstance(result, PipelineResult)
    assert result.total_segments == 3
    assert result.total_candidates == 12
    assert result.run_dir.exists()
    assert (result.run_dir / "calendars" / "complete_draft_calendar.csv").exists()
    assert (result.run_dir / "calendars" / "approved_calendar.csv").exists()
    assert (result.run_dir / "calendars" / "unapproved_calendar.csv").exists()
    assert (result.run_dir / "quality" / "quality_report.json").exists()
    assert (result.run_dir / "summaries" / "pipeline_summary.json").exists()
    assert (result.run_dir / "summaries" / "review_store.json").exists()


# 2. Invalid or missing source file
def test_invalid_or_missing_source_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Source file not found"):
        run_content_pipeline(
            source_path=tmp_path / "does_not_exist.md",
            output_dir=tmp_path / "runs"
        )


# 3. Empty or invalid source content
def test_empty_or_invalid_source_content(tmp_path: Path):
    empty_file = tmp_path / "empty_source.md"
    empty_file.write_text("   \n\n  ", encoding="utf-8")

    with pytest.raises(ValueError, match="empty or contains only whitespace"):
        run_content_pipeline(
            source_path=empty_file,
            output_dir=tmp_path / "runs"
        )


# 4. Candidate generation and platform counts
def test_candidate_generation_and_platform_counts(synthetic_fixture_path: Path, tmp_path: Path):
    # Test with platform filter: LinkedIn and YouTube Shorts only
    result = run_content_pipeline(
        source_path=synthetic_fixture_path,
        platforms=["linkedin", "youtube_shorts"],
        output_dir=tmp_path / "runs",
        render_media=False
    )

    assert result.total_candidates == 6  # 3 segments * 2 platforms
    assert result.platform_counts.get("linkedin") == 3
    assert result.platform_counts.get("youtube_shorts") == 3
    assert "twitter" not in result.platform_counts
    assert "instagram" not in result.platform_counts


# 5. Quality failures being preserved
def test_quality_failures_being_preserved(tmp_path: Path):
    # Source with overlength text causing LinkedIn post to exceed 3000 chars
    bad_source = tmp_path / "overlength_source.md"
    bad_source.write_text(
        "# Section Heading\n\n"
        "Here is a valid opening paragraph that has enough words to be ingested properly. "
        + ("Extremely long text content repeating " * 200),
        encoding="utf-8"
    )

    result = run_content_pipeline(
        source_path=bad_source,
        platforms=["linkedin"],  # Triggers LinkedIn 3000-char max limit failure
        output_dir=tmp_path / "runs",
        render_media=False
    )

    assert result.quality_counts.get("FAIL", 0) > 0
    # Confirm failed check reason is preserved in quality results
    failed_qr = next(qr for qr in result.quality_results if qr.overall_status.value == "FAIL")
    assert any("exceeds maximum character limit" in f for f in failed_qr.failed_checks)


# 6. No automatic approval
def test_no_automatic_approval(synthetic_fixture_path: Path, tmp_path: Path):
    result = run_content_pipeline(
        source_path=synthetic_fixture_path,
        output_dir=tmp_path / "runs",
        render_media=False
    )

    # 100% of generated candidates must be PENDING_REVIEW
    assert result.approved_export_count == 0
    assert result.unapproved_export_count == result.total_candidates
    assert result.review_status_counts["APPROVED"] == 0
    assert result.review_status_counts["PENDING_REVIEW"] == result.total_candidates

    # Invariant: is_ready_to_publish strictly False on every draft
    for d in result.drafts:
        assert d.is_ready_to_publish is False


# 7. Review registration and persistence
def test_review_registration_and_persistence(synthetic_fixture_path: Path, tmp_path: Path):
    result = run_content_pipeline(
        source_path=synthetic_fixture_path,
        output_dir=tmp_path / "runs",
        render_media=False
    )

    review_store_path = result.run_dir / "summaries" / "review_store.json"
    assert review_store_path.exists()

    # Reload directly via ReviewWorkflowManager
    reloaded_mgr = ReviewWorkflowManager(storage_path=review_store_path)
    assert len(reloaded_mgr.assets) == result.total_candidates
    first_asset = list(reloaded_mgr.assets.values())[0]
    assert first_asset.review_status == ReviewStatusEnum.PENDING_REVIEW


# 8. Approved and unapproved exports remaining separate
def test_approved_and_unapproved_exports_remain_separate(synthetic_fixture_path: Path, tmp_path: Path):
    result = run_content_pipeline(
        source_path=synthetic_fixture_path,
        output_dir=tmp_path / "runs",
        render_media=False
    )

    appr_cal = result.run_dir / "calendars" / "approved_calendar.csv"
    unappr_cal = result.run_dir / "calendars" / "unapproved_calendar.csv"

    # Initially: approved calendar is empty (0 rows), unapproved contains all 12
    with open(appr_cal, encoding="utf-8-sig") as f:
        appr_rows = list(csv.DictReader(f))
        assert len(appr_rows) == 0

    with open(unappr_cal, encoding="utf-8-sig") as f:
        unappr_rows = list(csv.DictReader(f))
        assert len(unappr_rows) == 12

    # Now manually approve 1 asset using Phase 3.5 workflow manager
    mgr = ReviewWorkflowManager(storage_path=result.run_dir / "summaries" / "review_store.json")
    target_id = unappr_rows[0]["asset_id"]
    mgr.approve_asset(target_id, reviewer_id="Reviewer_Test", confirm_claims_reviewed=True)

    # Re-export calendars
    mgr.export_approved_assets_calendar_csv(output_path=appr_cal)
    mgr.export_unapproved_assets_calendar_csv(output_path=unappr_cal)

    with open(appr_cal, encoding="utf-8-sig") as f:
        new_appr_rows = list(csv.DictReader(f))
        assert len(new_appr_rows) == 1
        assert new_appr_rows[0]["asset_id"] == target_id
        assert new_appr_rows[0]["human_review_status"] == "APPROVED"

    with open(unappr_cal, encoding="utf-8-sig") as f:
        new_unappr_rows = list(csv.DictReader(f))
        assert len(new_unappr_rows) == 11
        assert target_id not in {r["asset_id"] for r in new_unappr_rows}


# 9. Blank destination URL remaining blank
def test_blank_destination_url_remains_blank(synthetic_fixture_path: Path, tmp_path: Path):
    result = run_content_pipeline(
        source_path=synthetic_fixture_path,
        destination_url=None,  # No destination URL supplied
        output_dir=tmp_path / "runs",
        render_media=False
    )

    assert result.has_destination_url is False
    assert result.destination_url is None

    # Check complete calendar CSV
    complete_cal = result.run_dir / "calendars" / "complete_draft_calendar.csv"
    with open(complete_cal, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        for r in rows:
            assert r["destination_url"] == ""
            assert r["tracking_url"] == ""


# 10. UTM generation when a valid destination URL is supplied
def test_utm_generation_when_destination_url_supplied(synthetic_fixture_path: Path, tmp_path: Path):
    dest = "https://app.incubrix.com/explore"
    result = run_content_pipeline(
        source_path=synthetic_fixture_path,
        destination_url=dest,
        campaign="spring_2026",
        output_dir=tmp_path / "runs",
        render_media=False
    )

    assert result.has_destination_url is True
    assert result.destination_url == dest

    complete_cal = result.run_dir / "calendars" / "complete_draft_calendar.csv"
    with open(complete_cal, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        for r in rows:
            assert r["destination_url"] == dest
            assert "utm_source=" in r["tracking_url"]
            assert "utm_campaign=spring_2026" in r["tracking_url"]


# 11. Media rendering success and failure reporting
def test_media_rendering_reporting(synthetic_fixture_path: Path, tmp_path: Path):
    # Render media for youtube_shorts only
    result = run_content_pipeline(
        source_path=synthetic_fixture_path,
        platforms=["youtube_shorts"],
        output_dir=tmp_path / "runs",
        render_media=True
    )

    # 3 shorts candidates -> 3 rendered videos
    assert result.media_rendered_count == 3
    assert result.media_failed_count == 0

    # Verify actual mp4 files on disk
    for d in result.drafts:
        video_file = result.run_dir / "media" / d.draft_id / "preview.mp4"
        assert video_file.exists()
        assert video_file.stat().st_size > 0


# 12. Traceability from source segments to generated assets
def test_traceability_from_source_segments_to_generated_assets(synthetic_fixture_path: Path, tmp_path: Path):
    result = run_content_pipeline(
        source_path=synthetic_fixture_path,
        output_dir=tmp_path / "runs",
        render_media=False
    )

    assert result.source_document == "repurposing_operations_guide.md"
    for d in result.drafts:
        assert d.source_document == "repurposing_operations_guide.md"
        assert d.source_segment_id.startswith("seg_")
        assert len(d.source_excerpt) > 10


# 13. Unique output directories across separate runs
def test_unique_output_directories_across_separate_runs(synthetic_fixture_path: Path, tmp_path: Path):
    r1 = run_content_pipeline(
        source_path=synthetic_fixture_path,
        output_dir=tmp_path / "runs",
        render_media=False
    )
    r2 = run_content_pipeline(
        source_path=synthetic_fixture_path,
        output_dir=tmp_path / "runs",
        render_media=False
    )

    assert r1.run_id != r2.run_id
    assert r1.run_dir != r2.run_dir
    assert r1.run_dir.exists()
    assert r2.run_dir.exists()


# 14. Existing review records remaining intact
def test_existing_review_records_remain_intact(synthetic_fixture_path: Path, tmp_path: Path):
    # Run 1 creates its own review store
    r1 = run_content_pipeline(
        source_path=synthetic_fixture_path,
        output_dir=tmp_path / "runs",
        render_media=False
    )
    store_r1 = r1.run_dir / "summaries" / "review_store.json"
    mgr1 = ReviewWorkflowManager(storage_path=store_r1)
    first_id = list(mgr1.assets.keys())[0]
    mgr1.approve_asset(first_id, reviewer_id="Reviewer_A", confirm_claims_reviewed=True)

    # Run 2 creates another run in the same base output directory
    r2 = run_content_pipeline(
        source_path=synthetic_fixture_path,
        output_dir=tmp_path / "runs",
        render_media=False
    )
    store_r2 = r2.run_dir / "summaries" / "review_store.json"

    # Verify Run 1's store was untouched and still contains the approval
    mgr1_reloaded = ReviewWorkflowManager(storage_path=store_r1)
    assert mgr1_reloaded.get_asset(first_id).review_status == ReviewStatusEnum.APPROVED

    # Verify Run 2's store has clean PENDING_REVIEW assets
    mgr2 = ReviewWorkflowManager(storage_path=store_r2)
    assert mgr2.get_asset(first_id).review_status == ReviewStatusEnum.PENDING_REVIEW


# 15. Pipeline summary accuracy
def test_pipeline_summary_accuracy(synthetic_fixture_path: Path, tmp_path: Path):
    result = run_content_pipeline(
        source_path=synthetic_fixture_path,
        target_count=10,
        output_dir=tmp_path / "runs",
        render_media=False
    )

    summary_file = result.run_dir / "summaries" / "pipeline_summary.json"
    assert summary_file.exists()

    data = json.loads(summary_file.read_text(encoding="utf-8"))
    assert data["run_id"] == result.run_id
    assert data["source_provenance"]["source_document"] == "repurposing_operations_guide.md"
    assert data["source_provenance"]["total_segments_ingested"] == 3
    assert data["generation_metrics"]["total_candidates_generated"] == 12
    assert data["generation_metrics"]["target_met"] is True
    assert data["generation_metrics"]["shortfall"] == 0
    assert data["review_workflow_summary"]["approved_export_count"] == 0
    assert data["review_workflow_summary"]["unapproved_export_count"] == 12
    assert data["execution_duration_seconds"] > 0.0


# 16. Failure handling without fabricated output
def test_failure_handling_without_fabricated_output(tmp_path: Path):
    corrupt_source = tmp_path / "corrupt_file.md"
    # Write only 5 words, which fails the MIN_DOCUMENT_WORDS (15 words) threshold
    corrupt_source.write_text("Too few words here.", encoding="utf-8")

    with pytest.raises(ValueError, match="insufficient content"):
        run_content_pipeline(
            source_path=corrupt_source,
            output_dir=tmp_path / "runs"
        )
