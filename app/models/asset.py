"""Asset and ingestion domain models for IncuBrix Content Engine.

Defines the Pydantic schemas for source segments, pre-publication draft
candidates, platform-specific content assets, tracking metadata,
evidence references, and lifecycle states.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class PlatformEnum(str, Enum):
    """Supported social media publishing platforms."""
    LINKEDIN = "linkedin"
    YOUTUBE_SHORTS = "youtube_shorts"
    INSTAGRAM = "instagram"
    TWITTER = "twitter"


class AssetFormatEnum(str, Enum):
    """Supported platform-native asset formats."""
    TEXT_POST = "text_post"
    CAROUSEL = "carousel"
    SHORT_VIDEO = "short_video"
    THREAD = "thread"
    # Extended formats for custom platform & format repurposing (Phase 4.4A)
    CAPTIONS_AND_HOOKS = "captions_and_hooks"
    REELS = "reels"
    CAPTIONS_AND_HASHTAGS = "captions_and_hashtags"
    VIDEO_POST = "video_post"
    SINGLE_POST = "single_post"


class PillarEnum(str, Enum):
    """The 5 Core Content Pillars established in Strategy Doc 2."""
    WORKFLOW_EDUCATION = "workflow_education"
    HOOK_TUTORIALS = "hook_tutorials"
    ONE_TO_MANY = "one_to_many"
    CREATOR_OPERATIONS = "creator_operations"
    ATTRIBUTION_EXPERIMENTS = "attribution_experiments"


class ClaimCategoryEnum(str, Enum):
    """Claim-verification categories defined in Strategy Doc 2 and updated in Phase 3.2A."""
    CAT_1_VERIFIED = "Cat 1"           # Verified factual claims with traceable external proof (EV-xxx)
    CAT_2_ADVERTISED = "Cat 2"         # Publicly advertised features (untested in product)
    CAT_3_HYPOTHESIS = "Cat 3"         # Proposed hypotheses or targets
    CAT_4_UNSUPPORTED = "Cat 4"        # Unsupported / fabricated claims (Must be blocked)
    SOURCE_ATTRIBUTED_UNVERIFIED = "SOURCE_ATTRIBUTED_UNVERIFIED"  # Faithfully extracted from user source, but not independently verified


class GenerationModeEnum(str, Enum):
    """Engine execution modes."""
    OFFLINE_DETERMINISTIC = "OFFLINE_DETERMINISTIC"
    ONLINE_LLM = "ONLINE_LLM"


class AssetLifecycleStatus(str, Enum):
    """Lifecycle statuses across development and publishing pipeline."""
    DESIGNED = "designed"
    IMPLEMENTED = "implemented"
    GENERATED = "generated"
    TESTED = "tested"
    VERIFIED = "verified"


# ==============================================================================
# Ingestion & Segment Models
# ==============================================================================

class SourceSegment(BaseModel):
    """Normalized text segment extracted deterministically from a source file."""
    segment_id: str = Field(..., min_length=5, description="Deterministic segment identifier e.g. seg_01_a1b2c3d4")
    source_document: str = Field(..., min_length=1, description="Basename of source document")
    segment_index: int = Field(..., ge=1, description="1-based chronological index")
    source_location: str = Field(..., min_length=1, description="Physical location e.g. 'Paragraph 2, Line 14'")
    heading: Optional[str] = Field(None, description="Preceding Markdown heading if present")
    text: str = Field(..., min_length=10, description="Full normalized text of the segment")
    word_count: int = Field(..., ge=1, description="Word count of segment")
    char_count: int = Field(..., ge=1, description="Character count of segment")
    sentences: List[str] = Field(default_factory=list, description="Extracted sentence units")

    @field_validator("segment_id")
    @classmethod
    def validate_segment_id(cls, v: str) -> str:
        v_clean = v.strip()
        if not v_clean or " " in v_clean:
            raise ValueError("segment_id must not be empty or contain spaces")
        return v_clean


# ==============================================================================
# Draft Candidate Model (Pre-publication intermediate representation)
# ==============================================================================

class DraftCandidate(BaseModel):
    """Early-stage draft candidate generated deterministically from source segments.

    Represents pre-publication copy requiring human editorial review.
    Maintains explicit separation between source attribution (traceability to source text)
    and factual verification (independent fact-checking).
    Clearly distinguishes generated creative suggestions (hooks, CTAs, formatting)
    from source-derived content.
    """
    draft_id: str = Field(..., min_length=5, description="Unique draft identifier e.g. draft_01_linkedin_a1b2c3d4")
    source_document: str = Field(..., min_length=1, description="Source input file name")
    source_segment_id: str = Field(..., min_length=1, description="ID of source segment used")
    source_excerpt: str = Field(..., min_length=5, description="Exact excerpt from source text for traceability")
    source_derived_text: str = Field(..., min_length=5, description="Exact source sentences forming the factual/conceptual basis")

    platform: PlatformEnum
    content_format: AssetFormatEnum
    pillar: PillarEnum
    intended_audience: str = Field(..., min_length=1)

    # Creative suggestions (clearly marked as generated suggestions, not source statements)
    draft_hook: str = Field(..., min_length=5, description="Generated opening hook suggestion (creative packaging, not source statement)")
    draft_caption: str = Field(..., min_length=10, description="Proposed body copy combining source text and suggested formatting/transitions")
    suggested_hashtags: List[str] = Field(default_factory=list, description="Generated hashtag recommendations")
    call_to_action: str = Field(..., min_length=3, description="Generated call-to-action suggestion (not from source)")
    generated_suggestions: Dict[str, str] = Field(
        default_factory=dict,
        description="Explicit mapping of generated creative elements (hook, CTA, transitions, layout)"
    )

    # Explicit Attribution and Verification Separation
    is_source_attributed: bool = Field(True, description="True if draft content is derived from and traceable to uploaded source")
    is_factually_verified: bool = Field(False, description="Explicit flag: Source attribution does not constitute factual verification")
    requires_human_review: bool = Field(True, description="Drafts always require human editorial review prior to publishing")
    is_ready_to_publish: bool = Field(False, description="Draft candidates are never marked ready to publish automatically")

    generation_mode: GenerationModeEnum = Field(default=GenerationModeEnum.OFFLINE_DETERMINISTIC)
    lifecycle_status: AssetLifecycleStatus = Field(default=AssetLifecycleStatus.GENERATED)
    claim_category: ClaimCategoryEnum = Field(default=ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED)
    video_scene_cues: Optional[List[Dict[str, Any]]] = None
    carousel_slide_outlines: Optional[List[Dict[str, Any]]] = None
    estimated_duration_seconds: Optional[float] = Field(None, ge=0.0, le=60.0)
    warnings: List[str] = Field(default_factory=list, description="Rule-based warning flags for human review")
    render_directory: Optional[str] = Field(default=None, description="Local directory path containing rendered preview media and manifest")

    @field_validator("draft_id")
    @classmethod
    def validate_draft_id(cls, v: str) -> str:
        v_clean = v.strip()
        if not v_clean or " " in v_clean:
            raise ValueError("draft_id must not be empty or contain spaces")
        return v_clean

    @field_validator("is_ready_to_publish")
    @classmethod
    def validate_not_ready_to_publish(cls, v: bool) -> bool:
        if v is True:
            raise ValueError("A DraftCandidate cannot be marked ready to publish automatically. Human verification is required.")
        return False

    @model_validator(mode="after")
    def validate_verification_safety(self) -> "DraftCandidate":
        """Ensures that source attribution is not conflated with independent verification."""
        if self.claim_category == ClaimCategoryEnum.CAT_1_VERIFIED and not self.is_factually_verified:
            raise ValueError(
                "Draft cannot be classified as CAT_1_VERIFIED without independent factual verification. "
                "Use SOURCE_ATTRIBUTED_UNVERIFIED for source-derived content."
            )
        return self


# ==============================================================================
# Full ContentAsset Model (Publishable Asset Specification)
# ==============================================================================

class UTMParameters(BaseModel):
    """Structured UTM query tracking parameters."""
    utm_source: str = Field(..., min_length=1, description="Publishing platform identifier")
    utm_medium: str = Field(..., min_length=1, description="Content format / channel medium")
    utm_campaign: str = Field(..., min_length=1, description="Campaign name")
    utm_content: str = Field(..., min_length=1, description="Deterministic asset identifier")


class VideoScene(BaseModel):
    """Scene breakdown for vertical short-form video assets."""
    scene_number: int = Field(..., ge=1, description="Chronological scene index")
    duration_seconds: float = Field(..., gt=0.0, le=60.0, description="Scene duration in seconds")
    visual_cue: str = Field(..., min_length=1, description="Visual description or kinetic text cue")
    voiceover_script: str = Field(..., min_length=1, description="Spoken narration for the scene")
    on_screen_text: str = Field(..., min_length=1, description="Burned-in text graphic for the scene")


class CarouselSlide(BaseModel):
    """Individual slide specification for document carousels."""
    slide_number: int = Field(..., ge=1, le=10, description="Slide position index")
    headline: str = Field(..., min_length=1, description="Primary slide header")
    body_text: str = Field(..., min_length=1, description="Main slide copy or bullet points")
    visual_layout: str = Field(..., min_length=1, description="Card layout archetype")
    rendered_image_path: Optional[str] = None


class ContentAsset(BaseModel):
    """Unified Pydantic contract for IncuBrix platform content assets."""

    # 1. Identity & Origin
    asset_id: str = Field(
        ...,
        min_length=5,
        description="Unique identifier e.g. asset_01_linkedin_a1b2c3d4"
    )
    source_document: str = Field(..., min_length=1, description="Source input file name")
    source_segment_id: str = Field(..., min_length=1, description="Extracted paragraph or section ID")

    # 2. Categorization & Targeting
    platform: PlatformEnum
    content_format: AssetFormatEnum
    pillar: PillarEnum
    intended_audience: str = Field(..., min_length=1, description="Primary vs Secondary audience")

    # 3. Core Content & Copy
    hook: str = Field(..., min_length=1, description="Opening line or first-3s hook")
    caption: str = Field(..., min_length=1, description="Full post body copy or thread content")
    hashtags: List[str] = Field(default_factory=list)
    call_to_action: str = Field(..., min_length=1, description="Contextual call to action")

    # 4. Tracking & Attribution
    destination_url: HttpUrl = Field(..., description="Verified target landing URL")
    utm_parameters: UTMParameters
    final_tracking_link: str = Field(..., min_length=10, description="Synthesized UTM tracking URL")

    # 5. Evidence & Claim Verification
    evidence_references: List[str] = Field(
        default_factory=list,
        description="IDs from evidence register e.g. EV-001"
    )
    claim_category: ClaimCategoryEnum = Field(
        ClaimCategoryEnum.CAT_1_VERIFIED,
        description="Claim verification tier"
    )
    rights_metadata: str = Field(
        "Original procedural typography & public domain audio",
        min_length=1,
        description="Copyright clearance metadata"
    )

    # 6. Generation & Lifecycle Metadata
    generation_mode: GenerationModeEnum = Field(
        GenerationModeEnum.OFFLINE_DETERMINISTIC,
        description="Active engine mode during creation"
    )
    lifecycle_status: AssetLifecycleStatus = Field(
        AssetLifecycleStatus.DESIGNED,
        description="Current asset pipeline lifecycle status"
    )

    # 7. Media Components (Optional until rendered)
    video_scenes: Optional[List[VideoScene]] = None
    carousel_slides: Optional[List[CarouselSlide]] = None
    estimated_duration_seconds: Optional[float] = Field(None, ge=0.0, le=60.0)
    rendered_media_path: Optional[str] = None
    editable_source_path: Optional[str] = None

    # 8. Evaluation & Targets
    target_metric: str = Field(..., min_length=1, description="Primary success metric")
    target_value: str = Field(..., min_length=1, description="Target hypothesis threshold")
    validation_passed: bool = Field(False, description="Whether schema and quality gates passed")
    validation_warnings: List[str] = Field(default_factory=list)

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id_format(cls, v: str) -> str:
        """Enforces clean identifier naming convention."""
        v_clean = v.strip()
        if not v_clean:
            raise ValueError("asset_id cannot be blank")
        if " " in v_clean:
            raise ValueError("asset_id must not contain spaces")
        return v_clean

    @field_validator("hashtags")
    @classmethod
    def validate_hashtags(cls, v: List[str]) -> List[str]:
        """Cleans and standardizes hashtags."""
        cleaned = []
        for tag in v:
            t = tag.strip()
            if t:
                cleaned.append(t if t.startswith("#") else f"#{t}")
        return cleaned

    @model_validator(mode="after")
    def check_platform_format_compatibility(self) -> "ContentAsset":
        """Ensures content format matches platform constraints."""
        if self.platform == PlatformEnum.YOUTUBE_SHORTS:
            if self.content_format != AssetFormatEnum.SHORT_VIDEO:
                raise ValueError("YouTube Shorts platform requires SHORT_VIDEO content format")
        return self
