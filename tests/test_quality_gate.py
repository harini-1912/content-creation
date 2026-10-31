"""Unit tests for the objective quality gate validation engine."""

import pytest
from pathlib import Path
from PIL import Image

from app.core.quality_gate import (
    evaluate_asset_quality,
    check_required_content_fields,
    check_platform_specific_rules,
    check_claim_and_evidence_rules,
    check_rendered_media_artifacts,
    QualityGateStatusEnum,
    PlatformQualityLimits
)
from app.core.generator import generate_draft_candidates
from app.core.media_renderer import (
    render_video_preview,
    render_carousel_preview,
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    CAROUSEL_SIZE
)
from app.models.asset import (
    SourceSegment,
    DraftCandidate,
    PlatformEnum,
    AssetFormatEnum,
    PillarEnum,
    ClaimCategoryEnum
)


@pytest.fixture
def clean_drafts() -> list[DraftCandidate]:
    seg = SourceSegment(
        segment_id="seg_01_a1b2c3d4",
        source_document="operations_brief.md",
        segment_index=1,
        source_location="Paragraph 1, Line 1",
        heading="Content Distribution Framework",
        text=(
            "Creating multi-channel content without a structured system often causes severe creative fatigue. "
            "A repeatable repurpose engine turns one core long-form recording into ten platform-specific assets. "
            "Teams can maintain regular distribution schedules without having to record net-new footage daily."
        ),
        word_count=37,
        char_count=264,
        sentences=[
            "Creating multi-channel content without a structured system often causes severe creative fatigue.",
            "A repeatable repurpose engine turns one core long-form recording into ten platform-specific assets.",
            "Teams can maintain regular distribution schedules without having to record net-new footage daily."
        ]
    )
    return generate_draft_candidates([seg])


def test_valid_clean_draft_evaluates_to_pass(clean_drafts):
    """Clean deterministic draft passes automated quality checks."""
    li_draft = next(d for d in clean_drafts if d.platform == PlatformEnum.LINKEDIN)
    result = evaluate_asset_quality(li_draft)

    assert result.overall_status == QualityGateStatusEnum.PASS
    assert len(result.failed_checks) == 0
    assert result.requires_human_review is True
    assert result.is_ready_to_publish is False
    assert result.is_factually_verified is False


def test_missing_required_hook_fails(clean_drafts):
    """Omission of opening hook triggers quality gate failure."""
    draft = clean_drafts[0].model_copy(update={"draft_hook": "   "})
    result = evaluate_asset_quality(draft)

    assert result.overall_status == QualityGateStatusEnum.FAIL
    assert any("opening hook" in f for f in result.failed_checks)
    assert result.is_ready_to_publish is False


def test_missing_caption_body_fails(clean_drafts):
    """Omission of caption body triggers quality gate failure."""
    draft = clean_drafts[0].model_copy(update={"draft_caption": "short"})
    result = evaluate_asset_quality(draft)

    assert result.overall_status == QualityGateStatusEnum.FAIL
    assert any("caption/script body" in f for f in result.failed_checks)


def test_missing_source_references_fails(clean_drafts):
    """Missing source document or segment triggers failure."""
    draft_no_doc = clean_drafts[0].model_copy(update={"source_document": " "})
    res_doc = evaluate_asset_quality(draft_no_doc)
    assert res_doc.overall_status == QualityGateStatusEnum.FAIL
    assert any("source document" in f for f in res_doc.failed_checks)

    draft_no_seg = clean_drafts[0].model_copy(update={"source_segment_id": " "})
    res_seg = evaluate_asset_quality(draft_no_seg)
    assert res_seg.overall_status == QualityGateStatusEnum.FAIL
    assert any("source segment identifier" in f for f in res_seg.failed_checks)


def test_linkedin_overlength_fails(clean_drafts):
    """LinkedIn post exceeding 3000 chars triggers failure."""
    li_draft = next(d for d in clean_drafts if d.platform == PlatformEnum.LINKEDIN)
    long_caption = "A" * 3005
    draft = li_draft.model_copy(update={"draft_caption": long_caption})
    result = evaluate_asset_quality(draft)

    assert result.overall_status == QualityGateStatusEnum.FAIL
    assert any("LinkedIn post exceeds maximum character limit" in f for f in result.failed_checks)


def test_twitter_overlength_tweet_fails(clean_drafts):
    """Twitter thread where any tweet exceeds 280 chars triggers failure."""
    x_draft = next(d for d in clean_drafts if d.platform == PlatformEnum.TWITTER)
    bad_thread = "1/2 Valid short tweet\n\n---\n\n2/2 " + ("B" * 285)
    draft = x_draft.model_copy(update={"draft_caption": bad_thread})
    result = evaluate_asset_quality(draft)

    assert result.overall_status == QualityGateStatusEnum.FAIL
    assert any("Tweet character limit exceeded" in f for f in result.failed_checks)


def test_youtube_shorts_format_mismatch_fails(clean_drafts):
    """Shorts draft declared with non-video format triggers failure."""
    shorts_draft = next(d for d in clean_drafts if d.platform == PlatformEnum.YOUTUBE_SHORTS)
    draft = shorts_draft.model_copy(update={"content_format": AssetFormatEnum.TEXT_POST})
    result = evaluate_asset_quality(draft)

    assert result.overall_status == QualityGateStatusEnum.FAIL
    assert any("YouTube Shorts platform requires SHORT_VIDEO" in f for f in result.failed_checks)


def test_instagram_carousel_slide_count_out_of_bounds_fails(clean_drafts):
    """Instagram carousel with fewer than 3 slides triggers failure."""
    ig_draft = next(d for d in clean_drafts if d.platform == PlatformEnum.INSTAGRAM)
    two_slides = [
        {"slide": 1, "headline": "H1", "body": "B1"},
        {"slide": 2, "headline": "H2", "body": "B2"}
    ]
    draft = ig_draft.model_copy(update={"carousel_slide_outlines": two_slides})
    result = evaluate_asset_quality(draft)

    assert result.overall_status == QualityGateStatusEnum.FAIL
    assert any("Carousel slide count out of bounds" in f for f in result.failed_checks)


def test_prohibited_pattern_evaluates_to_fail(clean_drafts):
    """Draft flagged with CAT_4_UNSUPPORTED triggers quality gate failure."""
    draft = clean_drafts[0].model_copy(update={
        "claim_category": ClaimCategoryEnum.CAT_4_UNSUPPORTED,
        "warnings": ["Rule-based warning: flagged unverified pattern matching 'ScaleMedia'"]
    })
    result = evaluate_asset_quality(draft)

    assert result.overall_status == QualityGateStatusEnum.FAIL
    assert any("Category 4 unsupported/prohibited claim" in f for f in result.failed_checks)


def test_no_hashtags_evaluates_to_pass_with_warnings(clean_drafts):
    """Missing hashtags results in PASS_WITH_WARNINGS rather than hard failure."""
    draft = clean_drafts[0].model_copy(update={"suggested_hashtags": []})
    result = evaluate_asset_quality(draft)

    assert result.overall_status == QualityGateStatusEnum.PASS_WITH_WARNINGS
    assert len(result.failed_checks) == 0
    assert any("No hashtags provided" in w for w in result.warnings)


def test_human_review_and_ready_to_publish_enforcement(clean_drafts):
    """Quality gate results must NEVER mark an asset as ready to publish or remove human review requirement."""
    for d in clean_drafts:
        res = evaluate_asset_quality(d)
        assert res.requires_human_review is True
        assert res.is_ready_to_publish is False
        assert res.is_factually_verified is False


def test_media_checks_on_nonexistent_directory(clean_drafts, tmp_path: Path):
    """Media checks handle missing render directories gracefully with warnings."""
    non_existent = tmp_path / "does_not_exist"
    p, f, w = check_rendered_media_artifacts(clean_drafts[0], non_existent)
    assert any("Render directory does not exist" in warning for warning in w)


# ==============================================================================
# Phase 3.4B Targeted Regression Tests (Section 5 Requirements)
# ==============================================================================

def test_keyword_warning_does_not_assign_cat_4():
    """1. A keyword warning does not automatically assign CAT_4_UNSUPPORTED."""
    seg = SourceSegment(
        segment_id="seg_warn_01",
        source_document="suspicious_claims.md",
        segment_index=1,
        source_location="Paragraph 1, Line 1",
        heading="Unverified Case Study",
        text=(
            "IncuBrix guaranteed a 10x ROI improvement and saved 8-10 hours weekly compared to ScaleMedia. "
            "Our automated video pipeline completely eliminates human editing friction."
        ),
        word_count=23,
        char_count=180,
        sentences=[
            "IncuBrix guaranteed a 10x ROI improvement and saved 8-10 hours weekly compared to ScaleMedia.",
            "Our automated video pipeline completely eliminates human editing friction."
        ]
    )
    drafts = generate_draft_candidates([seg])
    assert len(drafts) == 4
    for d in drafts:
        # Must retain warnings for human review
        assert len(d.warnings) > 0
        assert any("Rule-based warning" in w for w in d.warnings)
        # Must NOT automatically be marked CAT_4_UNSUPPORTED or CAT_1_VERIFIED
        assert d.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
        assert d.claim_category != ClaimCategoryEnum.CAT_4_UNSUPPORTED
        assert d.claim_category != ClaimCategoryEnum.CAT_1_VERIFIED
        assert d.is_factually_verified is False


def test_warning_produces_human_review_rather_than_unsupported_verdict():
    """2. A warning produces human review (PASS_WITH_WARNINGS) rather than an unsupported-claim verdict."""
    seg = SourceSegment(
        segment_id="seg_warn_02",
        source_document="marketing_copy.md",
        segment_index=1,
        source_location="Paragraph 1, Line 1",
        heading="Growth Claims",
        text=(
            "Adopting the workflow will supercharge your output and act as a game-changer across modern channels. "
            "Teams maintain consistent publishing cadence without extra creator headcount."
        ),
        word_count=23,
        char_count=175,
        sentences=[
            "Adopting the workflow will supercharge your output and act as a game-changer across modern channels.",
            "Teams maintain consistent publishing cadence without extra creator headcount."
        ]
    )
    drafts = generate_draft_candidates([seg])
    li_draft = next(d for d in drafts if d.platform == PlatformEnum.LINKEDIN)

    result = evaluate_asset_quality(li_draft)

    # Heuristic warning produces PASS_WITH_WARNINGS because structure is valid and not explicitly Cat 4
    assert result.overall_status == QualityGateStatusEnum.PASS_WITH_WARNINGS
    assert result.overall_status != QualityGateStatusEnum.FAIL
    assert len(result.failed_checks) == 0
    assert len(result.warnings) > 0
    assert any("Rule-based scanner flag" in w for w in result.warnings)
    # Review invariant maintained
    assert result.requires_human_review is True
    assert result.is_ready_to_publish is False


def test_explicitly_assigned_cat_4_unsupported_claim_still_fails(clean_drafts):
    """3. An explicitly assigned CAT_4_UNSUPPORTED claim still fails."""
    draft = clean_drafts[0].model_copy(update={
        "claim_category": ClaimCategoryEnum.CAT_4_UNSUPPORTED,
        "warnings": ["Human auditor flag: verified fabricated competitor statistic"]
    })
    result = evaluate_asset_quality(draft)

    assert result.overall_status == QualityGateStatusEnum.FAIL
    assert any("Category 4 unsupported/prohibited claim" in f for f in result.failed_checks)
    assert result.requires_human_review is True
    assert result.is_ready_to_publish is False


def test_clean_source_attributed_claim_remains_source_attributed_unverified(clean_drafts):
    """4. A clean source-attributed claim remains SOURCE_ATTRIBUTED_UNVERIFIED."""
    draft = clean_drafts[0]
    assert draft.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
    assert draft.claim_category != ClaimCategoryEnum.CAT_1_VERIFIED
    assert draft.is_factually_verified is False
    assert len(draft.warnings) == 0

    result = evaluate_asset_quality(draft)
    assert result.overall_status == QualityGateStatusEnum.PASS
    assert result.claim_category == "SOURCE_ATTRIBUTED_UNVERIFIED"
    assert result.requires_human_review is True
    assert result.is_ready_to_publish is False


def test_real_1080x1920_video_passes_dimension_validation(clean_drafts, tmp_path: Path):
    """5. A real 1080 x 1920 video passes dimension validation."""
    shorts_draft = next(d for d in clean_drafts if d.platform == PlatformEnum.YOUTUBE_SHORTS)
    out_dir = tmp_path / "renders" / shorts_draft.draft_id
    render_video_preview(shorts_draft, out_dir)

    passed, failed, warnings = check_rendered_media_artifacts(shorts_draft, out_dir)

    assert len(failed) == 0
    assert any("Probed MP4 dimensions comply with 9:16 vertical video (1080x1920)" in p for p in passed)
    assert any("Actual probed MP4 dimensions: 1080x1920" in p for p in passed)


def test_video_with_incorrect_dimensions_fails(clean_drafts, tmp_path: Path, monkeypatch):
    """6. A video with incorrect dimensions fails."""
    shorts_draft = next(d for d in clean_drafts if d.platform == PlatformEnum.YOUTUBE_SHORTS)
    out_dir = tmp_path / "renders" / shorts_draft.draft_id
    render_video_preview(shorts_draft, out_dir)

    # 1. Simulate incorrect stream dimensions (e.g. 720x1280)
    monkeypatch.setattr("app.core.quality_gate.probe_media_dimensions", lambda p: (720, 1280))
    passed, failed, warnings = check_rendered_media_artifacts(shorts_draft, out_dir)

    assert any("Probed MP4 dimensions (720x1280) do not match expected vertical format (1080x1920)" in f for f in failed)

    # 2. Simulate dimension inspection tool failure
    def mock_fail(p):
        raise RuntimeError("Corrupted video container stream header")
    monkeypatch.setattr("app.core.quality_gate.probe_media_dimensions", mock_fail)
    passed2, failed2, warnings2 = check_rendered_media_artifacts(shorts_draft, out_dir)

    assert any("Dimension inspection failed on preview.mp4: Corrupted video container stream header" in f for f in failed2)


def test_real_1080x1080_carousel_slide_passes(clean_drafts, tmp_path: Path):
    """7. Real 1080 x 1080 carousel slides pass."""
    ig_draft = next(d for d in clean_drafts if d.platform == PlatformEnum.INSTAGRAM)
    out_dir = tmp_path / "renders" / ig_draft.draft_id
    render_carousel_preview(ig_draft, out_dir)

    passed, failed, warnings = check_rendered_media_artifacts(ig_draft, out_dir)

    assert len(failed) == 0
    assert any("slide_01.png is a readable 1080x1080 image" in p for p in passed)
    assert any("slide_05.png is a readable 1080x1080 image" in p for p in passed)
    assert any("All 5 carousel slide PNGs exist on disk" in p for p in passed)


def test_incorrectly_sized_carousel_slide_fails(clean_drafts, tmp_path: Path):
    """8. An incorrectly sized carousel slide fails."""
    ig_draft = next(d for d in clean_drafts if d.platform == PlatformEnum.INSTAGRAM)
    out_dir = tmp_path / "renders" / ig_draft.draft_id
    render_carousel_preview(ig_draft, out_dir)

    # Overwrite slide_03.png with 800x600 image
    bad_slide = out_dir / "slide_03.png"
    Image.new("RGB", (800, 600)).save(bad_slide, format="PNG")

    passed, failed, warnings = check_rendered_media_artifacts(ig_draft, out_dir)

    assert any("slide_03.png dimension mismatch: expected 1080x1080, got 800x600" in f for f in failed)


def test_unreadable_carousel_image_fails(clean_drafts, tmp_path: Path):
    """9. An unreadable carousel image fails."""
    ig_draft = next(d for d in clean_drafts if d.platform == PlatformEnum.INSTAGRAM)
    out_dir = tmp_path / "renders" / ig_draft.draft_id
    render_carousel_preview(ig_draft, out_dir)

    # Overwrite slide_02.png with corrupted bytes
    bad_slide = out_dir / "slide_02.png"
    bad_slide.write_bytes(b"corrupted_non_image_payload")

    passed, failed, warnings = check_rendered_media_artifacts(ig_draft, out_dir)

    assert any("Unreadable carousel image slide_02.png" in f for f in failed)


def test_all_outcomes_retain_human_review_invariant(clean_drafts, tmp_path: Path):
    """10. All outcomes retain the human-review invariant (requires_human_review=True, is_ready_to_publish=False)."""
    # Outcome 1: PASS
    clean = clean_drafts[0]
    res_pass = evaluate_asset_quality(clean)
    assert res_pass.overall_status == QualityGateStatusEnum.PASS
    assert res_pass.requires_human_review is True
    assert res_pass.is_ready_to_publish is False

    # Outcome 2: PASS_WITH_WARNINGS
    warned = clean.model_copy(update={"suggested_hashtags": []})
    res_warn = evaluate_asset_quality(warned)
    assert res_warn.overall_status == QualityGateStatusEnum.PASS_WITH_WARNINGS
    assert res_warn.requires_human_review is True
    assert res_warn.is_ready_to_publish is False

    # Outcome 3: FAIL (Prohibited Category 4)
    cat4 = clean.model_copy(update={"claim_category": ClaimCategoryEnum.CAT_4_UNSUPPORTED})
    res_cat4 = evaluate_asset_quality(cat4)
    assert res_cat4.overall_status == QualityGateStatusEnum.FAIL
    assert res_cat4.requires_human_review is True
    assert res_cat4.is_ready_to_publish is False

    # Outcome 4: FAIL (Missing structural hook)
    bad_hook = clean.model_copy(update={"draft_hook": "   "})
    res_bad_hook = evaluate_asset_quality(bad_hook)
    assert res_bad_hook.overall_status == QualityGateStatusEnum.FAIL
    assert res_bad_hook.requires_human_review is True
    assert res_bad_hook.is_ready_to_publish is False

    # Outcome 5: FAIL (Media dimension failure)
    ig_draft = next(d for d in clean_drafts if d.platform == PlatformEnum.INSTAGRAM)
    out_dir = tmp_path / "renders" / ig_draft.draft_id
    render_carousel_preview(ig_draft, out_dir)
    Image.new("RGB", (600, 600)).save(out_dir / "slide_01.png", format="PNG")
    res_bad_media = evaluate_asset_quality(ig_draft, render_dir=out_dir)
    assert res_bad_media.overall_status == QualityGateStatusEnum.FAIL
    assert res_bad_media.requires_human_review is True
    assert res_bad_media.is_ready_to_publish is False


