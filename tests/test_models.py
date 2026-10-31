"""Automated unit tests for ContentAsset and DraftCandidate data models.

Verifies strict typing, schema validations, platform-format constraints,
and claim categorization using clearly labeled test fixtures.
"""

import pytest
from pydantic import ValidationError

from app.models.asset import (
    ContentAsset,
    DraftCandidate,
    PlatformEnum,
    AssetFormatEnum,
    PillarEnum,
    ClaimCategoryEnum,
    GenerationModeEnum,
    AssetLifecycleStatus,
    UTMParameters
)


@pytest.fixture
def valid_asset_payload():
    """Provides a minimal, strictly valid asset payload for testing."""
    return {
        "asset_id": "asset_01_linkedin_a1b2c3d4",
        "source_document": "sample_technical_brief.md",
        "source_segment_id": "seg_01_workflow_overview",
        "platform": PlatformEnum.LINKEDIN,
        "content_format": AssetFormatEnum.CAROUSEL,
        "pillar": PillarEnum.WORKFLOW_EDUCATION,
        "intended_audience": "Solo Creators and Agency Leads",
        "hook": "If you need 5 different tools open just to publish one video, your workflow has a bottleneck.",
        "caption": "A breakdown of disconnected multi-tool stacks versus a unified repurposing workflow.",
        "hashtags": ["creatorops", "#workflow"],
        "call_to_action": "Explore IncuBrix Creator Studio on the Free exploration tier.",
        "destination_url": "https://app.incubrix.com/",
        "utm_parameters": {
            "utm_source": "linkedin",
            "utm_medium": "carousel",
            "utm_campaign": "creator_repurpose_2026",
            "utm_content": "asset_01_linkedin_a1b2c3d4"
        },
        "final_tracking_link": "https://app.incubrix.com/?utm_source=linkedin&utm_medium=carousel&utm_campaign=creator_repurpose_2026&utm_content=asset_01_linkedin_a1b2c3d4",
        "evidence_references": ["EV-001", "EV-002"],
        "claim_category": ClaimCategoryEnum.CAT_1_VERIFIED,
        "rights_metadata": "Original procedural typography & public domain audio",
        "generation_mode": GenerationModeEnum.OFFLINE_DETERMINISTIC,
        "lifecycle_status": AssetLifecycleStatus.DESIGNED,
        "target_metric": "Post Saves / Bookmarks",
        "target_value": ">= 10.0% Save Rate Hypothesis"
    }


def test_valid_asset_creation(valid_asset_payload):
    """Verifies that a well-formed payload instantiates ContentAsset without error."""
    asset = ContentAsset(**valid_asset_payload)
    assert asset.asset_id == "asset_01_linkedin_a1b2c3d4"
    assert asset.platform == PlatformEnum.LINKEDIN
    assert asset.content_format == AssetFormatEnum.CAROUSEL
    assert asset.claim_category == ClaimCategoryEnum.CAT_1_VERIFIED
    assert asset.generation_mode == GenerationModeEnum.OFFLINE_DETERMINISTIC
    assert asset.lifecycle_status == AssetLifecycleStatus.DESIGNED
    assert asset.hashtags == ["#creatorops", "#workflow"]


def test_missing_required_fields(valid_asset_payload):
    """Verifies that omitting mandatory fields raises Pydantic ValidationError."""
    # Omit hook
    payload_no_hook = valid_asset_payload.copy()
    del payload_no_hook["hook"]
    with pytest.raises(ValidationError) as exc_info:
        ContentAsset(**payload_no_hook)
    assert "hook" in str(exc_info.value)

    # Omit call_to_action
    payload_no_cta = valid_asset_payload.copy()
    del payload_no_cta["call_to_action"]
    with pytest.raises(ValidationError) as exc_info:
        ContentAsset(**payload_no_cta)
    assert "call_to_action" in str(exc_info.value)

    # Omit destination_url
    payload_no_dest = valid_asset_payload.copy()
    del payload_no_dest["destination_url"]
    with pytest.raises(ValidationError) as exc_info:
        ContentAsset(**payload_no_dest)
    assert "destination_url" in str(exc_info.value)


def test_invalid_platform(valid_asset_payload):
    """Verifies that an unsupported platform string is rejected."""
    payload = valid_asset_payload.copy()
    payload["platform"] = "unsupported_platform"
    with pytest.raises(ValidationError) as exc_info:
        ContentAsset(**payload)
    assert "platform" in str(exc_info.value)


def test_invalid_lifecycle_status(valid_asset_payload):
    """Verifies that an invalid lifecycle status is rejected."""
    payload = valid_asset_payload.copy()
    payload["lifecycle_status"] = "published_live_on_web"
    with pytest.raises(ValidationError) as exc_info:
        ContentAsset(**payload)
    assert "lifecycle_status" in str(exc_info.value)


def test_invalid_claim_category(valid_asset_payload):
    """Verifies that non-standard claim tiers are rejected."""
    payload = valid_asset_payload.copy()
    payload["claim_category"] = "Category 99 (Invented)"
    with pytest.raises(ValidationError) as exc_info:
        ContentAsset(**payload)
    assert "claim_category" in str(exc_info.value)


def test_malformed_asset_id_spaces(valid_asset_payload):
    """Verifies that asset_id with spaces is rejected."""
    payload = valid_asset_payload.copy()
    payload["asset_id"] = "asset 01 with invalid spaces"
    with pytest.raises(ValidationError) as exc_info:
        ContentAsset(**payload)
    assert "asset_id must not contain spaces" in str(exc_info.value)


def test_empty_asset_id(valid_asset_payload):
    """Verifies that an empty or whitespace asset_id is rejected."""
    payload = valid_asset_payload.copy()
    payload["asset_id"] = "   "
    with pytest.raises(ValidationError) as exc_info:
        ContentAsset(**payload)
    assert "asset_id" in str(exc_info.value)


def test_youtube_shorts_format_constraint(valid_asset_payload):
    """Verifies that YouTube Shorts requires SHORT_VIDEO content format."""
    payload = valid_asset_payload.copy()
    payload["platform"] = PlatformEnum.YOUTUBE_SHORTS
    payload["content_format"] = AssetFormatEnum.THREAD  # Incompatible!
    with pytest.raises(ValidationError) as exc_info:
        ContentAsset(**payload)
    assert "YouTube Shorts platform requires SHORT_VIDEO content format" in str(exc_info.value)


# ==============================================================================
# DraftCandidate Model Tests (Phase 3.2A Provenance & Verification)
# ==============================================================================

@pytest.fixture
def valid_draft_payload():
    return {
        "draft_id": "draft_linkedin_seg_01_a1b2c3d4",
        "source_document": "workflow_guide.md",
        "source_segment_id": "seg_01_a1b2c3d4",
        "source_excerpt": "Creating multi-channel content without a structured system causes fatigue.",
        "source_derived_text": "Creating multi-channel content without a structured system causes fatigue.",
        "platform": PlatformEnum.LINKEDIN,
        "content_format": AssetFormatEnum.TEXT_POST,
        "pillar": PillarEnum.WORKFLOW_EDUCATION,
        "intended_audience": "B2B Marketers",
        "draft_hook": "Operational perspective on content production: Creating multi-channel content...",
        "draft_caption": "Full body text...",
        "suggested_hashtags": ["#Workflow"],
        "call_to_action": "What operating procedures does your team rely on?",
        "generated_suggestions": {
            "hook": "Operational perspective...",
            "call_to_action": "What operating procedures does your team rely on?"
        }
    }


def test_draft_candidate_defaults(valid_draft_payload):
    """Verifies that DraftCandidate defaults to SOURCE_ATTRIBUTED_UNVERIFIED and requires human review."""
    draft = DraftCandidate(**valid_draft_payload)
    assert draft.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
    assert draft.is_source_attributed is True
    assert draft.is_factually_verified is False
    assert draft.requires_human_review is True
    assert draft.is_ready_to_publish is False


def test_draft_candidate_rejects_cat1_without_factual_verification(valid_draft_payload):
    """Verifies that DraftCandidate cannot be CAT_1_VERIFIED if is_factually_verified is False."""
    payload = valid_draft_payload.copy()
    payload["claim_category"] = ClaimCategoryEnum.CAT_1_VERIFIED
    payload["is_factually_verified"] = False

    with pytest.raises(ValidationError) as exc_info:
        DraftCandidate(**payload)
    assert "Draft cannot be classified as CAT_1_VERIFIED without independent factual verification" in str(exc_info.value)


def test_draft_candidate_rejects_is_ready_to_publish_true(valid_draft_payload):
    """Verifies that DraftCandidate cannot be marked ready to publish automatically."""
    payload = valid_draft_payload.copy()
    payload["is_ready_to_publish"] = True

    with pytest.raises(ValidationError) as exc_info:
        DraftCandidate(**payload)
    assert "cannot be marked ready to publish automatically" in str(exc_info.value)
