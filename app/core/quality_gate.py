"""Objective quality gate validation engine for IncuBrix content assets.

Enforces structural, platform-specific, claim-integrity, and media checks:
1. Required content field completeness.
2. Platform-specific constraints (character limits, duration limits, slide counts).
3. Claim-verification and source-traceability standards.
4. Media artifact validation (video duration, slide dimensions, manifests).

Important principles:
- Passing automated checks does NOT constitute independent factual verification.
- Passing automated checks does NOT constitute publication approval.
- All assets strictly require human review prior to publication.
- is_ready_to_publish remains False until approved by an authorized human reviewer.
"""

from dataclasses import dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image

from app.models.asset import (
    DraftCandidate,
    PlatformEnum,
    AssetFormatEnum,
    ClaimCategoryEnum,
    PillarEnum
)
from app.core.media_renderer import (
    probe_media_duration,
    probe_media_dimensions,
    CAROUSEL_SIZE,
    VIDEO_WIDTH,
    VIDEO_HEIGHT
)


class QualityGateStatusEnum(str, Enum):
    """Automated quality gate evaluation statuses."""
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"


@dataclass
class PlatformQualityLimits:
    """Configurable quality validation limits by platform."""
    max_linkedin_chars: int = 3000
    min_linkedin_hook_chars: int = 10
    max_twitter_tweet_chars: int = 280
    max_shorts_duration_seconds: float = 60.0
    max_shorts_words: int = 140
    min_carousel_slides: int = 3
    max_carousel_slides: int = 10


DEFAULT_LIMITS = PlatformQualityLimits()


@dataclass
class QualityCheckResult:
    """Structured result of automated quality gate evaluation."""
    asset_id: str
    overall_status: QualityGateStatusEnum
    passed_checks: List[str] = field(default_factory=list)
    failed_checks: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    requires_human_review: bool = True
    is_factually_verified: bool = False
    is_ready_to_publish: bool = False
    platform: Optional[str] = None
    content_format: Optional[str] = None
    source_segment_id: Optional[str] = None
    claim_category: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Converts result to clean serializable dictionary."""
        return {
            "asset_id": self.asset_id,
            "overall_status": self.overall_status.value,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "warnings": self.warnings,
            "requires_human_review": self.requires_human_review,
            "is_factually_verified": self.is_factually_verified,
            "is_ready_to_publish": self.is_ready_to_publish,
            "platform": self.platform,
            "content_format": self.content_format,
            "source_segment_id": self.source_segment_id,
            "claim_category": self.claim_category,
            "metadata": self.metadata
        }


def check_required_content_fields(draft: DraftCandidate) -> Tuple[List[str], List[str], List[str]]:
    """Checks presence and substance of mandatory content fields.

    Never invents missing information to force a pass.
    """
    passed: List[str] = []
    failed: List[str] = []
    warnings: List[str] = []

    # 1. Platform & Format
    if draft.platform:
        passed.append(f"Platform declared: {draft.platform.value}")
    else:
        failed.append("Missing required field: platform")

    if draft.content_format:
        passed.append(f"Content format declared: {draft.content_format.value}")
    else:
        failed.append("Missing required field: content_format")

    # 2. Hook / Opening
    if draft.draft_hook and len(draft.draft_hook.strip()) >= 5:
        passed.append("Hook present and meets minimum length threshold (>=5 chars)")
    else:
        failed.append("Missing or insufficient opening hook (<5 chars)")

    # 3. Caption / Script Body
    if draft.draft_caption and len(draft.draft_caption.strip()) >= 10:
        passed.append("Body copy/script present and meets minimum substance (>=10 chars)")
    else:
        failed.append("Missing or empty caption/script body (<10 chars)")

    # 4. Call to Action
    if draft.call_to_action and len(draft.call_to_action.strip()) >= 3:
        passed.append("Call to action present")
    else:
        failed.append("Missing call to action")

    # 5. Hashtags
    if draft.suggested_hashtags and len(draft.suggested_hashtags) > 0:
        passed.append(f"Hashtags provided ({len(draft.suggested_hashtags)} tags)")
    else:
        warnings.append("No hashtags provided for asset")

    # 6. Intended Audience & Content Pillar
    if draft.intended_audience and draft.intended_audience.strip():
        passed.append("Target audience explicitly identified")
    else:
        failed.append("Missing target audience specification")

    if draft.pillar:
        passed.append(f"Strategic content pillar mapped: {draft.pillar.value}")
    else:
        failed.append("Missing content pillar mapping")

    # 7. Human Review Requirement Flag
    if draft.requires_human_review is True:
        passed.append("Human review mandate enforced (requires_human_review == True)")
    else:
        failed.append("Safety violation: requires_human_review must not be False on draft candidates")

    # 8. Publication Ready Flag
    if draft.is_ready_to_publish is False:
        passed.append("Publication gate enforced (is_ready_to_publish == False)")
    else:
        failed.append("Safety violation: is_ready_to_publish must not be True on automated drafts")

    return passed, failed, warnings


def check_platform_specific_rules(
    draft: DraftCandidate,
    limits: PlatformQualityLimits = DEFAULT_LIMITS
) -> Tuple[List[str], List[str], List[str]]:
    """Enforces objective platform and format constraints."""
    passed: List[str] = []
    failed: List[str] = []
    warnings: List[str] = []

    platform = draft.platform
    format_type = draft.content_format

    if platform == PlatformEnum.LINKEDIN:
        caption_len = len(draft.draft_caption)
        if caption_len <= limits.max_linkedin_chars:
            passed.append(f"LinkedIn character length within limit ({caption_len}/{limits.max_linkedin_chars})")
        else:
            failed.append(
                f"LinkedIn post exceeds maximum character limit ({caption_len}/{limits.max_linkedin_chars})"
            )
        if len(draft.draft_hook) >= limits.min_linkedin_hook_chars:
            passed.append("LinkedIn opening hook meets minimum depth")
        else:
            warnings.append("LinkedIn opening hook is brief (<10 chars)")

    elif platform == PlatformEnum.YOUTUBE_SHORTS:
        if format_type != AssetFormatEnum.SHORT_VIDEO:
            failed.append("YouTube Shorts platform requires SHORT_VIDEO content format")
        else:
            passed.append("Format matches YouTube Shorts constraint (SHORT_VIDEO)")

        word_count = len(draft.draft_caption.split())
        if word_count <= limits.max_shorts_words:
            passed.append(f"Shorts spoken word count acceptable ({word_count}/{limits.max_shorts_words} words)")
        else:
            warnings.append(
                f"Shorts spoken word count high ({word_count}/{limits.max_shorts_words} words); may exceed 60s"
            )

        if draft.video_scene_cues and len(draft.video_scene_cues) >= 1:
            passed.append(f"Video scene cues structured ({len(draft.video_scene_cues)} scenes)")
        else:
            warnings.append("No video scene cues defined for Shorts script")

        if draft.estimated_duration_seconds is not None:
            if draft.estimated_duration_seconds <= limits.max_shorts_duration_seconds:
                passed.append(f"Estimated duration within vertical limit ({draft.estimated_duration_seconds:.1f}s <= 60.0s)")
            else:
                failed.append(f"Estimated duration exceeds 60s limit ({draft.estimated_duration_seconds:.1f}s)")

    elif platform == PlatformEnum.TWITTER:
        if format_type in (AssetFormatEnum.THREAD, AssetFormatEnum.TEXT_POST):
            passed.append("Format compatible with X (Thread or Post)")
        else:
            warnings.append(f"Unexpected format '{format_type.value}' for X distribution")

        tweets = draft.draft_caption.split("\n\n---\n\n")
        over_length_tweets = []
        for idx, t in enumerate(tweets, start=1):
            t_len = len(t.strip())
            if t_len > limits.max_twitter_tweet_chars:
                over_length_tweets.append(f"Tweet {idx} length {t_len}/{limits.max_twitter_tweet_chars}")

        if not over_length_tweets:
            passed.append(f"All tweets in thread within {limits.max_twitter_tweet_chars} characters ({len(tweets)} tweets)")
        else:
            failed.append(f"Tweet character limit exceeded: {', '.join(over_length_tweets)}")

    elif platform == PlatformEnum.INSTAGRAM:
        if format_type == AssetFormatEnum.CAROUSEL:
            outlines = draft.carousel_slide_outlines or []
            slide_count = len(outlines)
            if limits.min_carousel_slides <= slide_count <= limits.max_carousel_slides:
                passed.append(f"Carousel slide count acceptable ({slide_count} slides)")
            else:
                failed.append(
                    f"Carousel slide count out of bounds ({slide_count} slides; required {limits.min_carousel_slides}-{limits.max_carousel_slides})"
                )

            # Check individual slide structures
            incomplete_slides = []
            for s_idx, slide in enumerate(outlines, start=1):
                if not slide.get("headline") or not slide.get("body"):
                    incomplete_slides.append(f"Slide {s_idx}")
            if not incomplete_slides:
                passed.append("All carousel slides possess headline and body copy")
            else:
                failed.append(f"Incomplete carousel slides missing headline or body: {', '.join(incomplete_slides)}")
        elif format_type == AssetFormatEnum.SHORT_VIDEO:
            passed.append("Instagram Reels short video format acknowledged")
        else:
            warnings.append(f"Format '{format_type.value}' should be verified for Instagram feed compliance")

    return passed, failed, warnings


def check_claim_and_evidence_rules(draft: DraftCandidate) -> Tuple[List[str], List[str], List[str]]:
    """Enforces claim classification, source attribution, and evidence traceability.

    Key principles:
    - Source attribution does not equal factual verification.
    - Clean source text is SOURCE_ATTRIBUTED_UNVERIFIED.
    - Prohibited pattern warning flags must be investigated.
    """
    passed: List[str] = []
    failed: List[str] = []
    warnings: List[str] = []

    # 1. Source Document & Segment Traceability
    if draft.source_document and draft.source_document.strip():
        passed.append(f"Source document referenced: '{draft.source_document}'")
    else:
        failed.append("Missing source document reference")

    if draft.source_segment_id and draft.source_segment_id.strip():
        passed.append(f"Source segment ID traceable: '{draft.source_segment_id}'")
    else:
        failed.append("Missing source segment identifier")

    if draft.source_derived_text and len(draft.source_derived_text.strip()) >= 5:
        passed.append("Source-derived core text isolated for factual audit")
    else:
        failed.append("Source-derived basis text missing or empty")

    # 2. Separation of Generated Suggestions
    if draft.generated_suggestions and isinstance(draft.generated_suggestions, dict):
        passed.append(f"Generated suggestions explicitly mapped ({len(draft.generated_suggestions)} elements)")
        # Verify CTA is marked as suggestion and not passed off as verified source fact
        if "call_to_action" in draft.generated_suggestions:
            passed.append("Call to action correctly categorized as generated suggestion")
    else:
        warnings.append("Draft lacks explicit generated_suggestions mapping")

    # 3. Claim Category Verification Safeguards
    claim_cat = draft.claim_category
    if not claim_cat:
        failed.append("Missing claim category classification")
    else:
        passed.append(f"Claim category classified: {claim_cat.value}")

        if claim_cat == ClaimCategoryEnum.CAT_1_VERIFIED:
            # An asset must NOT claim CAT_1_VERIFIED without independent factual verification
            if not draft.is_factually_verified:
                failed.append(
                    "Integrity violation: CAT_1_VERIFIED claimed without independent factual verification"
                )
            else:
                passed.append("Factual verification confirmed with registered evidence")

        elif claim_cat == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED:
            passed.append("Correctly classified as SOURCE_ATTRIBUTED_UNVERIFIED (faithful source copy pending review)")

        elif claim_cat == ClaimCategoryEnum.CAT_4_UNSUPPORTED:
            # Prohibited claim pattern detected
            failed.append("Asset flagged with Category 4 unsupported/prohibited claim; publication blocked")

    # 4. Warnings Evaluation
    if draft.warnings:
        for w in draft.warnings:
            warnings.append(f"Rule-based scanner flag: {w}")

    return passed, failed, warnings


def check_rendered_media_artifacts(
    draft: DraftCandidate,
    render_dir: Union[str, Path]
) -> Tuple[List[str], List[str], List[str]]:
    """Inspects rendered media artifacts on disk when available.

    Validates actual MP4 duration via probing and checks slide dimensions.
    """
    passed: List[str] = []
    failed: List[str] = []
    warnings: List[str] = []

    dir_path = Path(render_dir)
    if not dir_path.exists():
        warnings.append(f"Render directory does not exist: {dir_path}")
        return passed, failed, warnings

    manifest_path = dir_path / "render_manifest.json"
    if not manifest_path.exists():
        warnings.append(f"No render_manifest.json found in {dir_path.name}")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            passed.append("Render manifest exists and contains valid JSON")

            # Check source segment traceability in manifest
            if manifest.get("source_segment_id") == draft.source_segment_id:
                passed.append(f"Manifest source segment matches draft ({draft.source_segment_id})")
            else:
                failed.append(
                    f"Manifest source segment mismatch: expected {draft.source_segment_id}, got {manifest.get('source_segment_id')}"
                )

            # Check review status in manifest
            if "REQUIRES_HUMAN_REVIEW" in manifest.get("review_status", ""):
                passed.append("Manifest enforces draft review status")
            else:
                warnings.append("Manifest review status does not indicate pending human review")

        except Exception as e:
            failed.append(f"Failed to read render manifest: {e}")

    # Video-specific media checks
    if draft.content_format == AssetFormatEnum.SHORT_VIDEO:
        video_path = dir_path / "preview.mp4"
        if not video_path.exists():
            warnings.append("preview.mp4 has not been rendered yet")
        else:
            file_size = video_path.stat().st_size
            if file_size > 0:
                passed.append(f"preview.mp4 exists on disk ({file_size} bytes)")
            else:
                failed.append("preview.mp4 is an empty 0-byte file")

            # Probe actual container duration
            try:
                actual_duration = probe_media_duration(video_path)
                passed.append(f"Actual probed MP4 duration: {actual_duration:.2f}s")
                if actual_duration <= 60.0:
                    passed.append("Probed MP4 duration complies with vertical video <=60s limit")
                else:
                    failed.append(f"Probed MP4 duration ({actual_duration:.2f}s) exceeds 60s limit")
            except Exception as e:
                failed.append(f"Duration inspection failed on preview.mp4: {e}")

            # Probe actual container dimensions
            try:
                width, height = probe_media_dimensions(video_path)
                passed.append(f"Actual probed MP4 dimensions: {width}x{height}")
                if width == VIDEO_WIDTH and height == VIDEO_HEIGHT:
                    passed.append(f"Probed MP4 dimensions comply with 9:16 vertical video ({VIDEO_WIDTH}x{VIDEO_HEIGHT})")
                else:
                    failed.append(
                        f"Probed MP4 dimensions ({width}x{height}) do not match expected vertical format ({VIDEO_WIDTH}x{VIDEO_HEIGHT})"
                    )
            except Exception as e:
                failed.append(f"Dimension inspection failed on preview.mp4: {e}")

    # Carousel-specific media checks
    if draft.content_format == AssetFormatEnum.CAROUSEL:
        outlines = draft.carousel_slide_outlines or []
        slide_count = len(outlines)
        found_slides = sorted(list(dir_path.glob("slide_*.png")))
        if not found_slides:
            warnings.append("Carousel slide images have not been rendered yet")
        else:
            if len(found_slides) == slide_count:
                passed.append(f"All {slide_count} carousel slide PNGs exist on disk")
            else:
                failed.append(f"Slide count mismatch: expected {slide_count}, found {len(found_slides)}")

            # Check individual slide files for existence, readability, and dimensions
            for idx in range(1, slide_count + 1):
                expected_filename = f"slide_{idx:02d}.png"
                slide_path = dir_path / expected_filename
                if not slide_path.exists():
                    alt_path = dir_path / f"slide_{idx}.png"
                    if alt_path.exists():
                        slide_path = alt_path
                        expected_filename = f"slide_{idx}.png"
                    else:
                        failed.append(f"Missing carousel slide file: {expected_filename}")
                        continue

                try:
                    with Image.open(slide_path) as img:
                        img.load()  # Verifies file integrity and readability
                        w, h = img.size
                        if (w, h) == (CAROUSEL_SIZE, CAROUSEL_SIZE):
                            passed.append(f"{expected_filename} is a readable {w}x{h} image")
                        else:
                            failed.append(
                                f"{expected_filename} dimension mismatch: expected {CAROUSEL_SIZE}x{CAROUSEL_SIZE}, got {w}x{h}"
                            )
                except Exception as e:
                    failed.append(f"Unreadable carousel image {expected_filename}: {e}")

        contact_sheet = dir_path / "carousel_contact_sheet.png"
        if contact_sheet.exists() and contact_sheet.stat().st_size > 0:
            passed.append("Carousel contact sheet exists")
        else:
            warnings.append("carousel_contact_sheet.png not found")

    return passed, failed, warnings


def evaluate_asset_quality(
    draft: DraftCandidate,
    render_dir: Optional[Union[str, Path]] = None,
    limits: PlatformQualityLimits = DEFAULT_LIMITS
) -> QualityCheckResult:
    """Evaluates an individual DraftCandidate across all objective quality dimensions.

    Returns a structured QualityCheckResult.
    Overall Status Rules:
    - Any failed check -> FAIL
    - Any warning flag (with zero failures) -> PASS_WITH_WARNINGS
    - All passed with zero warnings -> PASS
    In ALL cases, requires_human_review is True and is_ready_to_publish is False.
    """
    passed_all: List[str] = []
    failed_all: List[str] = []
    warnings_all: List[str] = []

    # 1. Required Content Fields
    p1, f1, w1 = check_required_content_fields(draft)
    passed_all.extend(p1)
    failed_all.extend(f1)
    warnings_all.extend(w1)

    # 2. Platform-Specific Checks
    p2, f2, w2 = check_platform_specific_rules(draft, limits=limits)
    passed_all.extend(p2)
    failed_all.extend(f2)
    warnings_all.extend(w2)

    # 3. Claim and Evidence Checks
    p3, f3, w3 = check_claim_and_evidence_rules(draft)
    passed_all.extend(p3)
    failed_all.extend(f3)
    warnings_all.extend(w3)

    # 4. Media Checks (if render directory supplied or discoverable)
    if render_dir:
        p4, f4, w4 = check_rendered_media_artifacts(draft, render_dir)
        passed_all.extend(p4)
        failed_all.extend(f4)
        warnings_all.extend(w4)

    # Calculate overall status
    if len(failed_all) > 0:
        overall_status = QualityGateStatusEnum.FAIL
    elif len(warnings_all) > 0:
        overall_status = QualityGateStatusEnum.PASS_WITH_WARNINGS
    else:
        overall_status = QualityGateStatusEnum.PASS

    return QualityCheckResult(
        asset_id=draft.draft_id,
        overall_status=overall_status,
        passed_checks=passed_all,
        failed_checks=failed_all,
        warnings=warnings_all,
        requires_human_review=True,       # Never bypassed
        is_factually_verified=draft.is_factually_verified,
        is_ready_to_publish=False,        # Never set automatically
        platform=draft.platform.value if draft.platform else None,
        content_format=draft.content_format.value if draft.content_format else None,
        source_segment_id=draft.source_segment_id,
        claim_category=draft.claim_category.value if draft.claim_category else None,
        metadata={
            "source_document": draft.source_document,
            "pillar": draft.pillar.value if draft.pillar else None,
            "passed_checks_count": len(passed_all),
            "failed_checks_count": len(failed_all),
            "warnings_count": len(warnings_all)
        }
    )

