"""Unit tests for app.core.generator module.

Verifies deterministic offline draft generation, explicit separation between
source attribution and factual verification, identification of generated creative
suggestions, and rule-based claim warning scanning.
"""

import pytest

from app.core.generator import (
    detect_claim_warnings,
    determine_pillar,
    generate_draft_id,
    generate_linkedin_draft,
    generate_shorts_draft,
    generate_twitter_thread_draft,
    generate_instagram_carousel_draft,
    generate_draft_candidates,
    PROHIBITED_CLAIM_PATTERNS
)
from app.models.asset import (
    SourceSegment,
    DraftCandidate,
    PlatformEnum,
    AssetFormatEnum,
    PillarEnum,
    ClaimCategoryEnum,
    GenerationModeEnum,
    AssetLifecycleStatus
)


@pytest.fixture
def clean_segment() -> SourceSegment:
    return SourceSegment(
        segment_id="seg_01_a1b2c3d4",
        source_document="workflow_guide.md",
        segment_index=1,
        source_location="Paragraph 1, Approx Line 1",
        heading="Content Repurposing Systems",
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


@pytest.fixture
def synthetic_claim_segment() -> SourceSegment:
    return SourceSegment(
        segment_id="seg_02_e5f6g7h8",
        source_document="unverified_notes.md",
        segment_index=2,
        source_location="Paragraph 2, Approx Line 15",
        heading="Unverified Case Study",
        text=(
            "ScaleMedia achieved an 82% reduction in editing turnaround time and grew by 4.3x to hit $340,000 ARR "
            "using this secret sauce to supercharge their output."
        ),
        word_count=26,
        char_count=168,
        sentences=[
            "ScaleMedia achieved an 82% reduction in editing turnaround time and grew by 4.3x to hit $340,000 ARR using this secret sauce to supercharge their output."
        ]
    )


def test_detect_claim_warnings_clean(clean_segment: SourceSegment):
    warnings = detect_claim_warnings(clean_segment.text)
    assert warnings == []


def test_detect_claim_warnings_flagged(synthetic_claim_segment: SourceSegment):
    warnings = detect_claim_warnings(synthetic_claim_segment.text)
    assert len(warnings) >= 4  # ScaleMedia, 82% reduction, 4.3x, $340,000, secret sauce, supercharge
    assert any("ScaleMedia" in w for w in warnings)
    assert any("$340,000" in w for w in warnings)
    # Ensure warnings describe rule-based flags accurately
    assert any("Rule-based warning" in w for w in warnings)


def test_determine_pillar(clean_segment: SourceSegment):
    # Segment has "repurpose engine", should route to ONE_TO_MANY
    assert determine_pillar(clean_segment) == PillarEnum.ONE_TO_MANY

    # Test hook routing
    hook_seg = SourceSegment(
        segment_id="seg_03_12345678",
        source_document="doc.md",
        segment_index=3,
        source_location="P3",
        heading="Optimizing the Hook",
        text="The first 3 second window dictates audience retention and prevents swipe away.",
        word_count=12,
        char_count=78,
        sentences=["The first 3 second window dictates audience retention and prevents swipe away."]
    )
    assert determine_pillar(hook_seg) == PillarEnum.HOOK_TUTORIALS


def test_generate_draft_id_deterministic(clean_segment: SourceSegment):
    id1 = generate_draft_id(clean_segment.source_document, clean_segment.segment_id, "linkedin", "post")
    id2 = generate_draft_id(clean_segment.source_document, clean_segment.segment_id, "linkedin", "post")
    id3 = generate_draft_id(clean_segment.source_document, clean_segment.segment_id, "shorts", "video")

    assert id1 == id2
    assert id1 != id3
    assert "linkedin" in id1


def test_generate_linkedin_draft(clean_segment: SourceSegment):
    draft = generate_linkedin_draft(clean_segment, PillarEnum.ONE_TO_MANY)

    assert isinstance(draft, DraftCandidate)
    assert draft.platform == PlatformEnum.LINKEDIN
    assert draft.content_format == AssetFormatEnum.TEXT_POST
    assert draft.pillar == PillarEnum.ONE_TO_MANY
    assert draft.generation_mode == GenerationModeEnum.OFFLINE_DETERMINISTIC
    assert draft.lifecycle_status == AssetLifecycleStatus.GENERATED
    # Provenance and claim corrections:
    assert draft.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
    assert draft.claim_category != ClaimCategoryEnum.CAT_1_VERIFIED
    assert draft.is_source_attributed is True
    assert draft.is_factually_verified is False
    assert draft.requires_human_review is True
    assert draft.is_ready_to_publish is False
    assert draft.warnings == []
    assert draft.source_segment_id == clean_segment.segment_id
    assert clean_segment.sentences[0] in draft.source_derived_text
    assert len(draft.suggested_hashtags) > 0


def test_generate_shorts_draft(clean_segment: SourceSegment):
    draft = generate_shorts_draft(clean_segment, PillarEnum.ONE_TO_MANY)

    assert draft.platform == PlatformEnum.YOUTUBE_SHORTS
    assert draft.content_format == AssetFormatEnum.SHORT_VIDEO
    assert draft.video_scene_cues is not None
    assert len(draft.video_scene_cues) == 3
    assert draft.estimated_duration_seconds <= 60.0
    assert draft.generation_mode == GenerationModeEnum.OFFLINE_DETERMINISTIC
    assert draft.source_segment_id == clean_segment.segment_id
    assert draft.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
    assert draft.is_factually_verified is False


def test_generate_twitter_thread_draft(clean_segment: SourceSegment):
    draft = generate_twitter_thread_draft(clean_segment, PillarEnum.ONE_TO_MANY)

    assert draft.platform == PlatformEnum.TWITTER
    assert draft.content_format == AssetFormatEnum.THREAD
    assert "1/3" in draft.draft_caption
    assert "2/3" in draft.draft_caption
    assert "3/3" in draft.draft_caption
    # Check that individual tweets stay bounded
    tweets = draft.draft_caption.split("\n\n---\n\n")
    for t in tweets:
        assert len(t) <= 280
    assert draft.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
    assert draft.is_factually_verified is False


def test_generate_instagram_carousel_draft(clean_segment: SourceSegment):
    draft = generate_instagram_carousel_draft(clean_segment, PillarEnum.ONE_TO_MANY)

    assert draft.platform == PlatformEnum.INSTAGRAM
    assert draft.content_format == AssetFormatEnum.CAROUSEL
    assert draft.carousel_slide_outlines is not None
    assert len(draft.carousel_slide_outlines) == 5
    assert draft.carousel_slide_outlines[0]["layout"] == "title_card"
    assert draft.carousel_slide_outlines[4]["layout"] == "cta_card"
    assert draft.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
    assert draft.is_factually_verified is False


def test_generate_draft_candidates_full(clean_segment: SourceSegment):
    drafts = generate_draft_candidates([clean_segment])

    # 4 drafts generated per segment: LinkedIn, Shorts, Twitter, Instagram
    assert len(drafts) == 4
    platforms = {d.platform for d in drafts}
    assert platforms == {
        PlatformEnum.LINKEDIN,
        PlatformEnum.YOUTUBE_SHORTS,
        PlatformEnum.TWITTER,
        PlatformEnum.INSTAGRAM
    }
    for d in drafts:
        assert d.source_segment_id == clean_segment.segment_id
        assert d.generation_mode == GenerationModeEnum.OFFLINE_DETERMINISTIC
        assert d.lifecycle_status == AssetLifecycleStatus.GENERATED
        assert d.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
        assert d.claim_category != ClaimCategoryEnum.CAT_1_VERIFIED
        assert d.is_source_attributed is True
        assert d.is_factually_verified is False
        assert d.requires_human_review is True
        assert d.is_ready_to_publish is False


def test_generate_draft_candidates_empty_input():
    with pytest.raises(ValueError, match="segment list is empty"):
        generate_draft_candidates([])


def test_generate_draft_with_flagged_claim(synthetic_claim_segment: SourceSegment):
    drafts = generate_draft_candidates([synthetic_claim_segment])
    assert len(drafts) == 4
    for d in drafts:
        # Phase 3.4B: Rule-based warnings are preserved, but do not automatically prejudge the claim as CAT_4_UNSUPPORTED
        assert d.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
        assert d.claim_category != ClaimCategoryEnum.CAT_4_UNSUPPORTED
        assert len(d.warnings) > 0
        assert d.is_factually_verified is False


# ==============================================================================
# Phase 3.2A Specific Validation Tests (Section 5 Requirements)
# ==============================================================================

def test_clean_source_not_classified_as_verified(clean_segment: SourceSegment):
    """1. Clean source-derived content is not automatically classified as verified."""
    drafts = generate_draft_candidates([clean_segment])
    for d in drafts:
        assert d.claim_category != ClaimCategoryEnum.CAT_1_VERIFIED
        assert d.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
        assert d.is_factually_verified is False


def test_source_attribution_and_factual_verification_represented_separately(clean_segment: SourceSegment):
    """2. Source attribution and factual verification are represented separately."""
    draft = generate_linkedin_draft(clean_segment, PillarEnum.ONE_TO_MANY)
    # Attribution is True (we know what source it came from)
    assert draft.is_source_attributed is True
    assert draft.source_document == clean_segment.source_document
    assert draft.source_segment_id == clean_segment.segment_id
    # Factual verification is False (extracting text does not independently verify facts)
    assert draft.is_factually_verified is False
    assert draft.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED


def test_generated_elements_identified_as_suggestions(clean_segment: SourceSegment):
    """3. Generated hooks and CTAs are identifiable as suggestions, not source statements."""
    draft = generate_linkedin_draft(clean_segment, PillarEnum.ONE_TO_MANY)
    assert "hook" in draft.generated_suggestions
    assert "call_to_action" in draft.generated_suggestions
    # CTA is a generated suggestion and is NOT part of the source segment text
    assert draft.call_to_action not in clean_segment.text
    # Generated suggestion is explicitly tracked
    assert draft.generated_suggestions["call_to_action"] == draft.call_to_action


def test_generated_suggestions_never_automatically_verified(clean_segment: SourceSegment):
    """4. Generated suggestions do not receive a verified status automatically."""
    drafts = generate_draft_candidates([clean_segment])
    for d in drafts:
        # None of the creative suggestions are marked as factually verified
        assert d.is_factually_verified is False
        assert d.claim_category != ClaimCategoryEnum.CAT_1_VERIFIED


def test_source_traceability_retained(clean_segment: SourceSegment):
    """5. Every source-derived draft retains valid source segment traceability."""
    drafts = generate_draft_candidates([clean_segment])
    for d in drafts:
        assert d.source_segment_id == clean_segment.segment_id
        assert d.source_document == clean_segment.source_document
        # Excerpt prefix originates from segment text
        raw_excerpt_text = d.source_excerpt.rstrip(".").strip()
        assert raw_excerpt_text in clean_segment.text
        assert len(d.source_derived_text) > 0


def test_draft_never_ready_to_publish_automatically(clean_segment: SourceSegment):
    """6. No draft is marked ready to publish automatically."""
    drafts = generate_draft_candidates([clean_segment])
    for d in drafts:
        assert d.is_ready_to_publish is False
        assert d.requires_human_review is True
        assert d.lifecycle_status != AssetLifecycleStatus.VERIFIED


def test_rule_based_warning_scanner_preserves_safeguards(synthetic_claim_segment: SourceSegment):
    """7. Existing claim-pattern warnings continue to work as a rule-based warning scanner without auto-assigning Cat 4."""
    drafts = generate_draft_candidates([synthetic_claim_segment])
    for d in drafts:
        assert d.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
        assert d.claim_category != ClaimCategoryEnum.CAT_4_UNSUPPORTED
        assert len(d.warnings) > 0
        assert any("Rule-based warning" in w for w in d.warnings)
