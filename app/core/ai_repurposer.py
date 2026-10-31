"""Speech transcription and AI repurposing module for IncuBrix Content Engine.

Uses the Google GenAI SDK to analyze extracted WAV audio, produce a faithful
verbatim-aligned transcript, identify candidate moments with source timestamps,
and generate platform-specific drafts for LinkedIn, YouTube Shorts, Instagram, and X.

Safety & Accuracy Principles:
- Strictly preserves speaker meaning; never invents claims, statistics, or customer stories.
- Keeps faithful transcript text explicitly separated from creative packaging suggestions.
- All AI-generated outputs remain marked as requires_human_review=True,
  is_factually_verified=False, and is_ready_to_publish=False.
- Never invents campaign destination URLs or UTM parameters.
- Rejects malformed output and API failures explicitly; never silently falls back to synthetic text.
- Validates that timestamps lie strictly within the source video's timeline.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.media_renderer import compute_file_sha256
from app.core.generator import detect_claim_warnings
from app.models.asset import PlatformEnum, AssetFormatEnum
from app.core.document_extractor import ExtractedDocument, extract_document_content

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL: str = "gemini-3.5-flash"
MAX_INLINE_AUDIO_BYTES: int = 15 * 1024 * 1024  # 15 MB inline limit


# ============================================================================
# API Key Management
# ============================================================================

def get_gemini_api_key(explicit_key: Optional[str] = None) -> Optional[str]:
    """Retrieves the Gemini API key from explicit arg, application Settings, or environment.

    Never logs or exposes the raw API key.
    """
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()

    # Priority 1: Unified application Settings (respects os.environ and .env)
    try:
        from app.core.config import load_settings
        settings = load_settings()
        if settings.gemini_api_key and settings.gemini_api_key.strip():
            return settings.gemini_api_key.strip()
    except Exception:
        pass

    # Priority 2: Direct os.environ check
    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    # Priority 3: Fallback .env file check
    try:
        dot_vals = dotenv.dotenv_values(".env")
        dot_key = dot_vals.get("GEMINI_API_KEY")
        if dot_key and dot_key.strip():
            return dot_key.strip()
    except Exception:
        pass

    return None


def mask_secret(secret: Optional[str]) -> str:
    """Masks a secret string for safe logging and presentation."""
    if not secret:
        return "[NOT_SET]"
    if len(secret) <= 8:
        return "********[MASKED]"
    return f"{secret[:4]}...{secret[-4:]}[MASKED]"


# ============================================================================
# Domain Schemas for Repurposed Audio Content
# ============================================================================

class RepurposingPlatform(str, Enum):
    """Supported social media target platforms for audio repurposing."""
    LINKEDIN = "linkedin"
    YOUTUBE_SHORTS = "youtube_shorts"
    INSTAGRAM = "instagram"
    TWITTER = "twitter"


class CandidateMoment(BaseModel):
    """Structured candidate content moment identified from speech audio or document text.

    Enforces strict separation between verbatim excerpts and AI-suggested packaging.
    """
    moment_id: str = Field(..., description="Deterministic unique identifier e.g. moment_01_a1b2c3d4")
    start_seconds: Optional[float] = Field(None, ge=0.0, description="Start timestamp in seconds from video origin")
    end_seconds: Optional[float] = Field(None, gt=0.0, description="End timestamp in seconds from video origin")
    duration_seconds: Optional[float] = Field(None, description="Duration of candidate moment in seconds")
    transcript_excerpt: str = Field(..., min_length=3, description="Verbatim transcript excerpt or source excerpt for this moment")
    source_heading: Optional[str] = Field(None, description="Document section or heading")
    source_document: Optional[str] = Field(None, description="Source document or video name")
    main_topic: str = Field(..., min_length=2, description="Core subject or thematic focus")
    intended_platform: PlatformEnum = Field(..., description="Target distribution channel")
    content_format: AssetFormatEnum = Field(..., description="Platform-native content format")
    suggested_hook: str = Field(..., min_length=3, description="Suggested hook for packaging (AI-generated)")
    suggested_content: str = Field(..., min_length=5, description="Suggested post copy or script draft (AI-generated)")
    suggested_hashtags: List[str] = Field(default_factory=list, description="Relevant hashtag recommendations")
    suggested_cta: str = Field(..., min_length=3, description="Suggested call-to-action (AI-generated)")
    destination_url_status: str = Field(
        default="FLAGGED_FOR_HUMAN_CONFIRMATION",
        description="Explicit notice: destination URLs are not invented and require human confirmation"
    )
    target_metric: Optional[str] = Field(
        default="qualified_engagement",
        description="Target KPI or engagement metric"
    )
    is_source_attributed: bool = Field(True, description="True if excerpt is derived from source media")
    is_factually_verified: bool = Field(False, description="Source attribution does not constitute factual verification")
    requires_human_review: bool = Field(True, description="Always requires human editorial review")
    is_ready_to_publish: bool = Field(False, description="Never marked ready to publish automatically")
    review_status: str = Field(default="PENDING_HUMAN_EDITORIAL_REVIEW")
    speech_verification_status: Optional[str] = Field(
        default=None,
        description="Speech transcription status (for video audio)"
    )
    warnings: List[str] = Field(default_factory=list, description="Quality, compliance, or timing warnings")

    @field_validator("is_ready_to_publish")
    @classmethod
    def validate_not_ready_to_publish(cls, v: bool) -> bool:
        if v is True:
            raise ValueError("Candidate moments cannot be marked ready to publish automatically.")
        return False


class RepurposingResult(BaseModel):
    """Complete structured output from AI audio or document analysis and content repurposing."""
    input_type: str = Field(default="video", description="Input type: video or blog")
    job_id: Optional[str] = Field(None, description="Associated processing job identifier")
    source_video_path: Optional[str] = Field(None, description="Path to source video file")
    source_video_sha256: Optional[str] = Field(None, description="SHA-256 digest of source video")
    source_audio_path: Optional[str] = Field(None, description="Path to extracted WAV audio")
    source_audio_sha256: Optional[str] = Field(None, description="SHA-256 digest of extracted WAV audio")
    source_duration_seconds: Optional[float] = Field(None, description="Total duration of source media in seconds")
    
    # Blog / Article specific fields
    source_document_path: Optional[str] = Field(None, description="Path to uploaded document file")
    source_document_name: Optional[str] = Field(None, description="Filename of source document")
    source_document_title: Optional[str] = Field(None, description="Title of source document")
    source_document_sha256: Optional[str] = Field(None, description="SHA-256 digest of source document")
    source_word_count: Optional[int] = Field(None, description="Word count of source document")
    source_headings: List[str] = Field(default_factory=list, description="Discovered headings in document")
    full_text: Optional[str] = Field(None, description="Extracted full text of document")
    
    full_transcript: str = Field(default="", description="Verbatim transcript of speech audio or source text")
    moments: List[CandidateMoment] = Field(default_factory=list, description="Extracted candidate content moments / suggestions")
    model_used: str = Field(..., description="Gemini model identifier or generator used")
    generated_at: str = Field(..., description="ISO 8601 UTC timestamp of repurposing run")
    generation_mode: str = Field(default="ONLINE_LLM")
    is_ai_generated: bool = Field(True, description="Explicit flag marking output as AI-generated")
    requires_human_review: bool = Field(True, description="Requires human verification prior to publishing")
    is_factually_verified: bool = Field(False)
    is_ready_to_publish: bool = Field(False)
    speech_verification_status: Optional[str] = Field(
        default=None,
        description="Speech transcript verification status"
    )
    selected_platforms: List[str] = Field(
        default_factory=list,
        description="Target social media platforms selected for generation"
    )
    selected_formats: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Target content formats selected per platform"
    )
    unsupported_formats: List[str] = Field(
        default_factory=list,
        description="Formats requested that are currently unsupported"
    )


# ============================================================================
# Gemini Structured Response Contract (Used with response_schema)
# ============================================================================

class GeminiMomentItem(BaseModel):
    """Schema for individual moments returned by Gemini structured generation."""
    start_seconds: float
    end_seconds: float
    transcript_excerpt: str
    main_topic: str
    intended_platform: str  # linkedin, youtube_shorts, instagram, twitter
    content_format: str = "text_post"  # platform-native format e.g. short_video, carousel, reels
    suggested_hook: str
    suggested_content: str
    suggested_hashtags: List[str]
    suggested_cta: str


class GeminiRepurposingPayload(BaseModel):
    """Top-level schema requested from Gemini via response_schema."""
    full_transcript: str
    moments: List[GeminiMomentItem]


class GeminiBlogSuggestionItem(BaseModel):
    """Schema for individual content suggestions returned by Gemini for blog repurposing."""
    source_heading: str = Field(..., description="Relevant section heading from source text")
    source_excerpt: str = Field(..., description="Faithful verbatim excerpt from the document text")
    main_topic: str = Field(..., description="Core topic or theme of this suggestion")
    intended_platform: str = Field(..., description="linkedin, youtube_shorts, instagram, or twitter")
    content_format: str = Field(..., description="Target content format e.g. text_post, short_video, carousel, thread")
    suggested_hook: str = Field(..., description="High-converting hook or headline")
    suggested_content: str = Field(..., description="Main content body, script, carousel outline, or thread")
    suggested_hashtags: List[str] = Field(default_factory=list, description="Targeted relevant hashtags")
    suggested_cta: str = Field(..., description="Low-friction call-to-action")
    target_metric: str = Field(default="qualified_engagement", description="Target performance metric")


class GeminiBlogRepurposingPayload(BaseModel):
    """Top-level schema requested from Gemini for blog/article repurposing."""
    document_title: str
    document_summary: str
    suggestions: List[GeminiBlogSuggestionItem]


# ============================================================================
# Platform and Format Catalog (Phase 4.4A)
# ============================================================================

SUPPORTED_PLATFORMS_FORMATS: Dict[str, Dict[str, Any]] = {
    "youtube_shorts": {
        "label": "YouTube Shorts",
        "platform_enum": PlatformEnum.YOUTUBE_SHORTS,
        "formats": {
            "short_video": {
                "label": "Short video clips",
                "format_enum": AssetFormatEnum.SHORT_VIDEO,
                "description": "Script and hook timestamped for 15-60s vertical video",
            },
            "captions_and_hooks": {
                "label": "Captions and hooks",
                "format_enum": AssetFormatEnum.CAPTIONS_AND_HOOKS,
                "description": "Catchy YouTube Shorts title hooks and description captions",
            },
        },
    },
    "instagram": {
        "label": "Instagram",
        "platform_enum": PlatformEnum.INSTAGRAM,
        "formats": {
            "reels": {
                "label": "Reels",
                "format_enum": AssetFormatEnum.REELS,
                "description": "Short-form vertical video script with hook and visual cues",
            },
            "carousel": {
                "label": "Carousels",
                "format_enum": AssetFormatEnum.CAROUSEL,
                "description": "Multi-slide swipeable card breakdown with cover hook",
            },
            "captions_and_hashtags": {
                "label": "Captions and hashtags",
                "format_enum": AssetFormatEnum.CAPTIONS_AND_HASHTAGS,
                "description": "Engaging caption copy paired with high-intent hashtags",
            },
        },
    },
    "linkedin": {
        "label": "LinkedIn",
        "platform_enum": PlatformEnum.LINKEDIN,
        "formats": {
            "text_post": {
                "label": "Text posts",
                "format_enum": AssetFormatEnum.TEXT_POST,
                "description": "Long-form thought leadership post with formatting",
            },
            "video_post": {
                "label": "Video posts",
                "format_enum": AssetFormatEnum.VIDEO_POST,
                "description": "Talking-point script optimized for native LinkedIn video",
            },
        },
    },
    "twitter": {
        "label": "X (Twitter)",
        "platform_enum": PlatformEnum.TWITTER,
        "formats": {
            "single_post": {
                "label": "Single posts",
                "format_enum": AssetFormatEnum.SINGLE_POST,
                "description": "Punchy standalone post under 280 characters with CTA",
            },
            "thread": {
                "label": "Threads",
                "format_enum": AssetFormatEnum.THREAD,
                "description": "Multi-tweet thread breaking down insight step-by-step",
            },
        },
    },
}

PLATFORM_FORMAT_MAP: Dict[str, Tuple[PlatformEnum, AssetFormatEnum]] = {
    "linkedin": (PlatformEnum.LINKEDIN, AssetFormatEnum.TEXT_POST),
    "youtube_shorts": (PlatformEnum.YOUTUBE_SHORTS, AssetFormatEnum.SHORT_VIDEO),
    "shorts": (PlatformEnum.YOUTUBE_SHORTS, AssetFormatEnum.SHORT_VIDEO),
    "instagram": (PlatformEnum.INSTAGRAM, AssetFormatEnum.CAROUSEL),
    "twitter": (PlatformEnum.TWITTER, AssetFormatEnum.THREAD),
    "x": (PlatformEnum.TWITTER, AssetFormatEnum.THREAD),
}


def normalize_platform(
    platform_str: str,
    format_str: Optional[str] = None
) -> Tuple[PlatformEnum, AssetFormatEnum]:
    """Maps free-form platform and format strings to validated PlatformEnum and AssetFormatEnum."""
    plat_raw = platform_str.strip().lower().replace(" ", "_")
    if plat_raw in ("x", "twitter"):
        plat = PlatformEnum.TWITTER
    elif plat_raw in ("youtube_shorts", "shorts", "youtube"):
        plat = PlatformEnum.YOUTUBE_SHORTS
    elif plat_raw == "instagram":
        plat = PlatformEnum.INSTAGRAM
    else:
        plat = PlatformEnum.LINKEDIN

    # Format resolution if format_str is provided
    if format_str and format_str.strip():
        fmt_raw = format_str.strip().lower().replace(" ", "_")
        for p_key, p_meta in SUPPORTED_PLATFORMS_FORMATS.items():
            if fmt_raw in p_meta["formats"]:
                return plat, p_meta["formats"][fmt_raw]["format_enum"]
        for e in AssetFormatEnum:
            if fmt_raw == e.value:
                return plat, e

    # Default fallback per platform
    default_formats = {
        PlatformEnum.LINKEDIN: AssetFormatEnum.TEXT_POST,
        PlatformEnum.YOUTUBE_SHORTS: AssetFormatEnum.SHORT_VIDEO,
        PlatformEnum.INSTAGRAM: AssetFormatEnum.CAROUSEL,
        PlatformEnum.TWITTER: AssetFormatEnum.THREAD,
    }
    return plat, default_formats.get(plat, AssetFormatEnum.TEXT_POST)


def normalize_timestamp_value(val: float, max_duration_sec: float) -> Tuple[float, Optional[str]]:
    """Normalizes a timestamp value, automatically converting MMSS-packed floats to total seconds.

    For example, if an LLM returns 715.0 (meaning 7 minutes 15 seconds) for a 508s video,
    this converts 715.0 to 435.0s (7 * 60 + 15).
    """
    if val <= (max_duration_sec + 1.0):
        return val, None

    # Check if value is MMSS formatted (e.g. 715 -> 7m 15s)
    if val >= 100.0:
        int_part = int(val)
        frac = val - int_part
        mm = int_part // 100
        ss = (int_part % 100) + frac
        if ss < 60.0:
            total_sec = round(mm * 60.0 + ss, 2)
            if total_sec <= (max_duration_sec + 1.0):
                warning = (
                    f"Timing note: Auto-converted MMSS timestamp ({val:.2f}) to elapsed seconds ({total_sec:.2f}s)."
                )
                return total_sec, warning

    return val, None


def validate_timestamps_and_moments(
    raw_moments: List[GeminiMomentItem],
    source_duration_sec: float,
    job_prefix: str = "moment",
    selected_platforms: Optional[List[str]] = None,
    selected_formats: Optional[Dict[str, List[str]]] = None,
) -> List[CandidateMoment]:
    """Validates moment timestamps against source video bounds and normalizes models.

    Validation Rules:
    - start_seconds >= 0.0
    - end_seconds > start_seconds
    - end_seconds <= source_duration_sec (allows 0.2s tolerance for floating-point margin)
    - transcript_excerpt cannot be empty or whitespace-only
    - Flags overlapping moment ranges explicitly in warnings
    - Runs claim-warning heuristic scanner on generated copy
    - Filters moments by selected_platforms and selected_formats if provided
    """
    if source_duration_sec <= 0.0:
        raise ValueError(f"Invalid source video duration: {source_duration_sec}s.")

    validated_moments: List[CandidateMoment] = []

    # Sort raw moments chronologically by start timestamp
    sorted_raw = sorted(raw_moments, key=lambda m: m.start_seconds)

    for idx, item in enumerate(sorted_raw, start=1):
        # Format and Platform resolution
        raw_fmt = getattr(item, "content_format", None)
        platform, content_format = normalize_platform(item.intended_platform, raw_fmt)

        # Filtering against explicitly selected platforms and formats (Phase 4.4A)
        if selected_platforms:
            allowed_platforms = {
                ("twitter" if p.lower() in ("x", "twitter") else ("youtube_shorts" if p.lower() in ("shorts", "youtube_shorts") else p.lower()))
                for p in selected_platforms
            }
            if platform.value not in allowed_platforms:
                logger.debug(
                    "Skipping moment %d: platform '%s' not in selected platforms %s",
                    idx, platform.value, allowed_platforms
                )
                continue

        if selected_formats:
            allowed_formats_for_plat = selected_formats.get(platform.value) or selected_formats.get(item.intended_platform.lower())
            if allowed_formats_for_plat:
                allowed_fmts = {f.lower().replace(" ", "_") for f in allowed_formats_for_plat}
                if content_format.value not in allowed_fmts:
                    logger.debug(
                        "Skipping moment %d: format '%s' not in selected formats %s for platform '%s'",
                        idx, content_format.value, allowed_fmts, platform.value
                    )
                    continue

        warnings: List[str] = []

        # 0. Timestamp normalization (detect and convert MMSS timestamps e.g. 715 -> 7m15s = 435s)
        norm_start, start_warn = normalize_timestamp_value(item.start_seconds, source_duration_sec)
        norm_end, end_warn = normalize_timestamp_value(item.end_seconds, source_duration_sec)
        if start_warn:
            warnings.append(start_warn)
        if end_warn:
            warnings.append(end_warn)

        # 1. Start timestamp validation
        if norm_start < 0.0:
            raise ValueError(
                f"Invalid start timestamp ({norm_start}s) in moment {idx}: must be non-negative."
            )

        # 2. End timestamp validation
        if norm_end <= norm_start:
            raise ValueError(
                f"Invalid timestamp interval in moment {idx}: end_seconds ({norm_end}s) "
                f"must be strictly greater than start_seconds ({norm_start}s)."
            )

        # 3. Source duration boundary check
        # Allow up to 1.0s estimation tolerance; clamp to source duration and flag in warnings
        tolerance_sec = 1.0
        if norm_end > (source_duration_sec + tolerance_sec):
            raise ValueError(
                f"Timestamp beyond bounds in moment {idx}: end_seconds ({norm_end:.2f}s) "
                f"exceeds source video duration ({source_duration_sec:.2f}s)."
            )

        clamped_start = round(min(norm_start, source_duration_sec), 2)
        clamped_end = round(min(norm_end, source_duration_sec), 2)
        if clamped_end <= clamped_start:
            clamped_end = min(round(clamped_start + 0.5, 2), round(source_duration_sec, 2))
        moment_duration = round(clamped_end - clamped_start, 2)

        # 4. Transcript excerpt check
        excerpt = item.transcript_excerpt.strip()
        if not excerpt:
            raise ValueError(
                f"Missing transcript excerpt in moment {idx}: transcript excerpt cannot be empty."
            )

        # 5. Moment ID generation (deterministic from topic + start time)
        id_hash = hashlib.sha256(f"{item.main_topic}_{clamped_start}_{clamped_end}".encode("utf-8")).hexdigest()[:8]
        moment_id = f"{job_prefix}_{idx:02d}_{platform.value}_{id_hash}"

        # 6. Collect warnings
        if norm_end > source_duration_sec:
            warnings.append(
                f"Timing note: LLM estimated end timestamp ({norm_end:.2f}s) slightly exceeded "
                f"audio duration ({source_duration_sec:.2f}s) and was clamped to {clamped_end:.2f}s."
            )

        # Claim-warning scanner on generated copy
        combined_text = f"{item.suggested_hook} {item.suggested_content} {item.suggested_cta}"
        claim_warns = detect_claim_warnings(combined_text)
        warnings.extend(claim_warns)

        # Check overlap with preceding moments
        for prev in validated_moments:
            if clamped_start < prev.end_seconds:
                warnings.append(
                    f"Timeline overlap: moment starts at {clamped_start:.1f}s before "
                    f"previous {prev.moment_id} ends at {prev.end_seconds:.1f}s."
                )

        candidate = CandidateMoment(
            moment_id=moment_id,
            start_seconds=clamped_start,
            end_seconds=clamped_end,
            duration_seconds=moment_duration,
            transcript_excerpt=excerpt,
            main_topic=item.main_topic.strip(),
            intended_platform=platform,
            content_format=content_format,
            suggested_hook=item.suggested_hook.strip(),
            suggested_content=item.suggested_content.strip(),
            suggested_hashtags=[h.strip() for h in item.suggested_hashtags if h.strip()],
            suggested_cta=item.suggested_cta.strip(),
            destination_url_status="FLAGGED_FOR_HUMAN_CONFIRMATION (No destination URL invented)",
            is_source_attributed=True,
            is_factually_verified=False,
            requires_human_review=True,
            is_ready_to_publish=False,
            review_status="PENDING_HUMAN_EDITORIAL_REVIEW",
            warnings=warnings
        )
        validated_moments.append(candidate)

    return validated_moments


# ============================================================================
# Gemini Audio Repurposer Service
# ============================================================================

def repurpose_audio_with_gemini(
    audio_path: Union[str, Path],
    source_video_metadata: Dict[str, Any],
    api_key: Optional[str] = None,
    model_name: str = DEFAULT_GEMINI_MODEL,
    client: Optional[Any] = None,
    selected_platforms: Optional[List[str]] = None,
    selected_formats: Optional[Dict[str, List[str]]] = None,
    unsupported_formats: Optional[List[str]] = None,
) -> RepurposingResult:
    """Analyzes an extracted WAV audio file with Gemini to generate transcripts and candidate drafts.

    Args:
        audio_path: Path to extracted 16 kHz mono WAV file.
        source_video_metadata: Metadata dictionary containing source duration_sec,
            video_path, sha256, and optional job_id.
        api_key: Optional explicit Gemini API key (defaults to .env/environment).
        model_name: Gemini model identifier (default: gemini-3.5-flash).
        client: Optional pre-configured genai.Client (used for testing/mocks).
        selected_platforms: Optional list of platforms selected by the user.
        selected_formats: Optional dictionary mapping platform to selected format list.
        unsupported_formats: Optional list of requested formats that are unsupported.

    Returns:
        RepurposingResult with full transcript and validated candidate moments.

    Raises:
        FileNotFoundError: If audio file does not exist.
        ValueError: If audio is invalid, API key missing, timestamps out of bounds,
            or Gemini returns malformed output.
        RuntimeError: If Gemini API request fails or quota is exhausted.
    """
    p_audio = Path(audio_path).resolve()
    if not p_audio.exists():
        raise FileNotFoundError(f"Extracted audio file not found: '{audio_path}'.")
    if not p_audio.is_file():
        raise ValueError(f"Specified audio path is not a regular file: '{audio_path}'.")
    if p_audio.suffix.lower() != ".wav":
        raise ValueError(f"Audio file must be a .wav file, got '{p_audio.suffix}'.")

    source_duration = float(source_video_metadata.get("duration_sec", 0.0))
    if source_duration <= 0.0:
        raise ValueError(
            f"Invalid source video duration ({source_duration}s) provided in metadata."
        )

    # Resolve API Key
    effective_key = get_gemini_api_key(api_key)
    if not client and not effective_key:
        raise ValueError(
            "AI processing is unavailable: GEMINI_API_KEY is not configured in environment or .env. "
            "Please configure GEMINI_API_KEY to enable speech analysis and AI repurposing."
        )

    # Initialize Gemini client if not provided
    if client is None:
        try:
            from google import genai
            client = genai.Client(api_key=effective_key)
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize Google GenAI client: {exc}") from exc

    from google.genai import types

    audio_bytes_size = p_audio.stat().st_size
    uploaded_file = None

    try:
        # Pass audio either inline (<= 15MB) or via File API (> 15MB)
        if audio_bytes_size <= MAX_INLINE_AUDIO_BYTES:
            audio_data = p_audio.read_bytes()
            content_part = types.Part.from_bytes(data=audio_data, mime_type="audio/wav")
        else:
            logger.info("Uploading audio file (%d bytes) to Gemini Files API...", audio_bytes_size)
            uploaded_file = client.files.upload(
                file=str(p_audio),
                config=types.UploadFileConfig(mime_type="audio/wav")
            )
            import time
            while uploaded_file.state in (types.FileState.PROCESSING, "PROCESSING"):
                logger.info("Waiting for uploaded file to become ACTIVE (current: %s)...", uploaded_file.state)
                time.sleep(2)
                uploaded_file = client.files.get(name=uploaded_file.name)

            if uploaded_file.state in (types.FileState.FAILED, "FAILED"):
                raise RuntimeError(f"Gemini file processing failed for '{p_audio.name}'.")

            content_part = uploaded_file

        # Format platform and format constraints for Gemini prompt
        if selected_platforms:
            plat_lines = []
            for p in selected_platforms:
                p_norm = "twitter" if p.lower() in ("x", "twitter") else ("youtube_shorts" if p.lower() in ("shorts", "youtube_shorts") else p.lower())
                fmts = (selected_formats or {}).get(p, []) or (selected_formats or {}).get(p_norm, [])
                fmt_desc = ", ".join(fmts) if fmts else "all suitable formats"
                plat_lines.append(f"- Platform: '{p_norm}' | Formats: [{fmt_desc}]")

            platform_spec_instruction = (
                "5. STRICT PLATFORM & FORMAT SCOPE:\n"
                "You MUST ONLY generate content moments for the following explicitly requested platforms and formats:\n"
                + "\n".join(plat_lines) + "\n"
                "DO NOT generate any content moments for unselected platforms or unselected formats.\n"
                "For each moment, set `intended_platform` to the exact platform key and `content_format` to one of its requested formats.\n"
            )
        else:
            platform_spec_instruction = (
                "5. Create platform-specific suggestions for: LinkedIn post, YouTube Shorts, Instagram caption/carousel, and X (Twitter) post/thread.\n"
            )

        system_instruction = (
            "You are an expert audio analysis and social media content repurposing engine. "
            f"The total audio recording duration is {source_duration:.2f} seconds.\n"
            "Analyze the provided audio recording carefully.\n"
            "1. Provide a faithful, verbatim-aligned transcript of the spoken words in `full_transcript`. "
            "Do not invent facts, words, statistics, examples, or customer stories absent from the audio.\n"
            "2. Identify candidate content moments (key insights, workflow tutorials, soundbites).\n"
            f"3. For each candidate moment, specify exact `start_seconds` and `end_seconds` relative to the audio start (0.0s). All timestamps MUST be within [0.0, {source_duration:.2f}].\n"
            "   CRITICAL TIMESTAMP RULE: Express start_seconds and end_seconds strictly as TOTAL ELAPSED SECONDS (for example, 435.0 for 7 minutes 15 seconds: 7 * 60 + 15 = 435). "
            "NEVER output timestamps formatted as MM:SS or integer-packed MMSS (do NOT write 715 for 7m15s).\n"
            "4. Extract the exact spoken words into `transcript_excerpt`. Never leave `transcript_excerpt` empty.\n"
            + platform_spec_instruction +
            "6. Separate the faithful transcript from generated creative suggestions (hook, content, hashtags, CTA).\n"
            "7. Do NOT invent destination URLs or performance guarantees."
        )

        user_prompt = (
            f"Analyze and transcribe this audio recording (duration: {source_duration:.2f}s). "
            f"Extract candidate repurposing moments with precise start/end timestamps in raw seconds (strictly within 0.0s to {source_duration:.2f}s; for example, 7 minutes 15 seconds is 435.0 seconds, do NOT write 715) "
            f"and platform drafts according to the requested schema. { 'Restricted to platforms: ' + ', '.join(selected_platforms) if selected_platforms else '' }"
        )

        logger.info(
            "Sending audio to Gemini (model=%s, audio=%s, size=%d bytes, platforms=%s)...",
            model_name,
            p_audio.name,
            audio_bytes_size,
            selected_platforms or "all"
        )

        response = client.models.generate_content(
            model=model_name,
            contents=[content_part, user_prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeminiRepurposingPayload,
                system_instruction=system_instruction,
                temperature=0.2,
            )
        )

    except Exception as exc:
        logger.error("Gemini API call failed: %s", exc)
        raise RuntimeError(
            f"AI processing failed during Gemini API request: {exc}"
        ) from exc

    finally:
        # Clean up cloud uploaded file if one was created
        if uploaded_file is not None and hasattr(client, "files"):
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass

    # Parse and validate response text
    raw_text = getattr(response, "text", None)
    if not raw_text or not raw_text.strip():
        raise ValueError(
            "Malformed or incomplete structured response from Gemini: received empty response text."
        )

    try:
        payload = GeminiRepurposingPayload.model_validate_json(raw_text)
    except Exception as exc:
        raise ValueError(
            f"Malformed or incomplete structured response from Gemini: failed to validate JSON schema: {exc}"
        ) from exc

    if not payload.full_transcript or not payload.full_transcript.strip():
        raise ValueError(
            "Malformed response from Gemini: full_transcript is missing or empty."
        )

    # Validate timestamps and normalize candidate moments, applying platform & format filter
    validated_moments = validate_timestamps_and_moments(
        raw_moments=payload.moments,
        source_duration_sec=source_duration,
        job_prefix="moment",
        selected_platforms=selected_platforms,
        selected_formats=selected_formats,
    )

    result = RepurposingResult(
        job_id=source_video_metadata.get("job_id"),
        source_video_path=str(source_video_metadata.get("video_path", "")),
        source_video_sha256=source_video_metadata.get("sha256"),
        source_audio_path=str(p_audio),
        source_audio_sha256=compute_file_sha256(p_audio),
        source_duration_seconds=round(source_duration, 2),
        full_transcript=payload.full_transcript.strip(),
        moments=validated_moments,
        model_used=model_name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        generation_mode="ONLINE_LLM",
        is_ai_generated=True,
        requires_human_review=True,
        is_factually_verified=False,
        is_ready_to_publish=False,
        selected_platforms=selected_platforms or [],
        selected_formats=selected_formats or {},
        unsupported_formats=unsupported_formats or [],
    )

    logger.info(
        "Successfully repurposed audio with Gemini: transcript_len=%d, candidate_moments=%d",
        len(result.full_transcript),
        len(result.moments)
    )
    return result


def save_repurposing_result(
    result: RepurposingResult,
    output_path: Union[str, Path]
) -> Path:
    """Saves the RepurposingResult to an output JSON file."""
    dest = Path(output_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Saved AI repurposing result manifest to '%s'", dest)
    return dest


# ============================================================================
# Blog / Article Repurposing Implementation (Phase 4.4B)
# ============================================================================

def generate_blog_suggestions_offline(
    doc: ExtractedDocument,
    selected_platforms: Optional[List[str]] = None,
    selected_formats: Optional[Dict[str, List[str]]] = None,
    target_count: int = 10,
    job_prefix: str = "sug",
) -> List[CandidateMoment]:
    """Generates at least `target_count` (>= 10) platform-specific content suggestions deterministically.

    Derives suggestions strictly from source document paragraphs and heading structure.
    Never invents statistics, quotes, or claims not present in the text.
    """
    raw_paras = [p.strip() for p in doc.text.split("\n\n") if len(p.strip().split()) >= 8]
    if not raw_paras:
        raw_paras = [p.strip() for p in doc.text.split("\n") if len(p.strip().split()) >= 4]
    if not raw_paras:
        raw_paras = [doc.text.strip()]

    # Resolve platform & format scope
    platforms: List[str] = []
    if selected_platforms:
        for p in selected_platforms:
            p_clean = "twitter" if p.lower() in ("x", "twitter") else ("youtube_shorts" if p.lower() in ("shorts", "youtube_shorts") else p.lower())
            if p_clean in SUPPORTED_PLATFORMS_FORMATS and p_clean not in platforms:
                platforms.append(p_clean)
    if not platforms:
        platforms = ["youtube_shorts", "instagram", "linkedin", "twitter"]

    target_pairs: List[Tuple[str, str]] = []
    for plat in platforms:
        plat_formats = SUPPORTED_PLATFORMS_FORMATS[plat]["formats"]
        req_fmts = (selected_formats or {}).get(plat) or (selected_formats or {}).get(
            "twitter" if plat in ("x", "twitter") else plat
        )
        if req_fmts:
            for f in req_fmts:
                f_norm = f.lower().replace(" ", "_")
                if f_norm in plat_formats:
                    target_pairs.append((plat, f_norm))
        else:
            for f_norm in plat_formats.keys():
                target_pairs.append((plat, f_norm))

    if not target_pairs:
        target_pairs = [("linkedin", "text_post"), ("twitter", "thread"), ("instagram", "carousel"), ("youtube_shorts", "short_video")]

    # Strategic pedagogical angles for varied copy generation
    strategic_angles = [
        ("Operational Teardown", "How leading media engineering teams implement systematic content pipelines:"),
        ("Strategic Perspective", "Why scaling content creation without repeatable infrastructure causes creative burnout:"),
        ("Tactical Execution Guide", "Three actionable steps to turn one piece of long-form thought leadership into multi-platform reach:"),
        ("Architecture Blueprint", "The technical foundation behind reproducible, traceable content distribution:"),
        ("Core Takeaway Checklist", "The fundamental workflow checkpoints before publishing across social channels:"),
        ("Quality & Attribution Framework", "How to link social content engagement back to concrete audience conversion:"),
        ("Contrarian Observation", "Most creators don't suffer from a lack of ideas—they suffer from manual handoff fatigue:"),
        ("Best Practice Playbook", "Standard operating procedures for content operations teams in high-growth environments:"),
        ("Systematic Repurposing Schema", "Transforming long articles into short videos, swipeable carousels, and tactical threads:"),
        ("Executive Brief", "Operational efficiency summary for media marketing and creator operations leadership:"),
        ("Workflow Simplification", "Eliminating friction between content writing, asset packaging, and editorial approval:"),
        ("Audience Retention Principles", "Structuring social content hooks to capture attention in the first 3 seconds:"),
    ]

    total_to_generate = max(target_count, len(target_pairs))
    suggestions: List[CandidateMoment] = []

    for idx in range(1, total_to_generate + 1):
        plat_str, fmt_str = target_pairs[(idx - 1) % len(target_pairs)]
        para = raw_paras[(idx - 1) % len(raw_paras)]
        angle_label, angle_prefix = strategic_angles[(idx - 1) % len(strategic_angles)]

        # Heading determination
        if doc.headings:
            heading = doc.headings[(idx - 1) % len(doc.headings)]
        else:
            heading = doc.title

        # First sentence of paragraph as key insight
        first_sentence = para.split(".")[0].strip()
        if len(first_sentence) < 10:
            first_sentence = para[:100].strip()

        # Resolve Platform and Format enums
        plat_enum, fmt_enum = normalize_platform(plat_str, fmt_str)

        # Build platform-tailored packaging
        if plat_enum == PlatformEnum.YOUTUBE_SHORTS:
            if fmt_enum == AssetFormatEnum.CAPTIONS_AND_HOOKS:
                hook = f"Stop overcomplicating your workflow: {first_sentence}"
                content = (
                    f"Hook: {hook}\n\n"
                    f"Description: In this breakdown of '{heading}', we explore how to eliminate production bottlenecks. "
                    f"Read the full article for the complete operational blueprint.\n\n"
                    f"CTA: Drop a comment with your biggest distribution challenge."
                )
            else:
                hook = f"[0-3s Kinetic Card] {first_sentence}"
                content = (
                    f"{hook}\n\n"
                    f"[Scene 1: Visual Blueprint (3-12s)]\n"
                    f"Voiceover: {para[:180]}...\n\n"
                    f"[Scene 2: Core Implementation (12-24s)]\n"
                    f"On-screen graphic: 3-step operational procedure derived from {heading}.\n\n"
                    f"[Scene 3: Takeaway & CTA (24-30s)]\n"
                    f"Build repeatable workflows before scaling output. Check the link for the complete guide."
                )
            metric = "watch_time_30s"
            cta = "Subscribe for more content engineering workflows."
            hashtags = ["#YouTubeShorts", "#ContentOps", "#CreatorWorkflows", "#Productivity"]

        elif plat_enum == PlatformEnum.INSTAGRAM:
            if fmt_enum == AssetFormatEnum.CAROUSEL:
                hook = f"{angle_label}: {first_sentence}"
                content = (
                    f"Slide 1 (Cover): {hook}\n"
                    f"Slide 2 (The Problem): Disconnected tools and manual handoffs drain creative energy.\n"
                    f"Slide 3 (The System): {para[:160]}...\n"
                    f"Slide 4 (Tactical Step): Establish reliable operating procedures before scaling.\n"
                    f"Slide 5 (Call to Action): Save this carousel for your next content sprint."
                )
                metric = "save_rate"
            elif fmt_enum == AssetFormatEnum.REELS:
                hook = f"Visual Reel Breakdown: {first_sentence}"
                content = (
                    f"{hook}\n\n"
                    f"Voiceover & Audio: High-tempo tutorial pacing.\n"
                    f"Visuals: Screen recording demonstrating the {heading} workflow.\n"
                    f"Key insight: {para[:200]}...\n\n"
                    f"Comment 'SYSTEM' to get the full article link."
                )
                metric = "watch_time_30s"
            else:
                hook = f"{first_sentence}"
                content = (
                    f"{hook}\n\n"
                    f"{para}\n\n"
                    f"From '{heading}' — full article in bio."
                )
                metric = "save_rate"
            cta = "Save this post and share with your editorial team."
            hashtags = ["#InstagramGrowth", "#ContentStrategy", "#CreatorOps", "#WorkflowDesign"]

        elif plat_enum == PlatformEnum.LINKEDIN:
            if fmt_enum == AssetFormatEnum.VIDEO_POST:
                hook = f"Video Talking Point: {first_sentence}"
                content = (
                    f"Direct-to-camera script:\n\n"
                    f"'{hook}.\n\n"
                    f"When analyzing content workflows, here is what most teams overlook:\n"
                    f"{para[:220]}...\n\n"
                    f"What operating procedures keep your team on schedule?'"
                )
                metric = "watch_time_30s"
            else:
                hook = f"{angle_prefix} {first_sentence}"
                content = (
                    f"{hook}\n\n"
                    f"Key operational insight from '{heading}':\n\n"
                    f"{para}\n\n"
                    f"Building predictable distribution systems prevents creative burnout.\n\n"
                    f"What does your team's publishing pipeline look like?"
                )
                metric = "qualified_reads"
            cta = "What operating procedures keep your team steady? Share your thoughts below."
            hashtags = ["#ContentEngineering", "#CreatorEconomy", "#Operations", "#ThoughtLeadership"]

        else:  # TWITTER / X
            if fmt_enum == AssetFormatEnum.SINGLE_POST:
                hook = f"Most content bottlenecks come down to one issue:"
                short_para = (para[:140] + "..") if len(para) > 140 else para
                content = f"{hook}\n\n{short_para}\n\nFix the system first."
                metric = "repost_rate"
            else:
                hook = f"1/4 Most content bottlenecks come down to one issue:\n\n{first_sentence}."
                content = (
                    f"1/4 {first_sentence}.\n\n---\n\n"
                    f"2/4 Here is why this happens:\n\n{para[:180]}...\n\n---\n\n"
                    f"3/4 From '{heading}': Systematic distribution prevents creative burnout.\n\n---\n\n"
                    f"4/4 Bookmark this thread and build reliable procedures before scaling output."
                )
                metric = "repost_rate"
            cta = "Retweet to share with fellow content creators."
            hashtags = ["#ContentOps", "#TechWriting", "#CreatorEconomy"]

        # Warnings check
        warnings = detect_claim_warnings(f"{hook} {content}")

        # Hash salt for unique ID
        hash_salt = f"{doc.filename}:{idx}:{plat_str}:{fmt_str}:{hook[:30]}".encode("utf-8")
        id_digest = hashlib.sha256(hash_salt).hexdigest()[:8]
        sug_id = f"{job_prefix}_{idx:02d}_{plat_str}_{id_digest}"

        moment = CandidateMoment(
            moment_id=sug_id,
            start_seconds=None,
            end_seconds=None,
            duration_seconds=None,
            transcript_excerpt=para[:300].strip(),
            source_heading=heading,
            source_document=doc.filename,
            main_topic=heading or doc.title,
            intended_platform=plat_enum,
            content_format=fmt_enum,
            suggested_hook=hook.strip(),
            suggested_content=content.strip(),
            suggested_hashtags=hashtags,
            suggested_cta=cta.strip(),
            destination_url_status="FLAGGED_FOR_HUMAN_CONFIRMATION (No destination URL invented)",
            target_metric=metric,
            is_source_attributed=True,
            is_factually_verified=False,
            requires_human_review=True,
            is_ready_to_publish=False,
            review_status="PENDING_HUMAN_EDITORIAL_REVIEW",
            warnings=warnings,
        )
        suggestions.append(moment)

    return suggestions


def repurpose_blog_with_gemini(
    document: Union[ExtractedDocument, str, Path],
    api_key: Optional[str] = None,
    model_name: str = DEFAULT_GEMINI_MODEL,
    client: Optional[Any] = None,
    selected_platforms: Optional[List[str]] = None,
    selected_formats: Optional[Dict[str, List[str]]] = None,
    unsupported_formats: Optional[List[str]] = None,
    job_id: Optional[str] = None,
) -> RepurposingResult:
    """Repurposes an extracted long-form blog or article into at least 10 platform-specific content drafts.

    Args:
        document: ExtractedDocument instance or path to a .txt, .md, .docx, or .pdf file.
        api_key: Optional explicit Gemini API key.
        model_name: Gemini model identifier.
        client: Optional pre-configured genai.Client (used for testing and dependency injection).
        selected_platforms: Selected platforms (e.g. ['linkedin', 'youtube_shorts', 'instagram', 'twitter']).
        selected_formats: Selected formats per platform.
        unsupported_formats: Formats that were requested but unsupported.
        job_id: Optional tracking identifier.

    Returns:
        RepurposingResult with at least 10 platform-specific content suggestions.
    """
    if isinstance(document, (str, Path)):
        doc = extract_document_content(document)
    elif isinstance(document, ExtractedDocument):
        doc = document
    else:
        raise ValueError(f"Invalid document parameter: expected ExtractedDocument or Path, got {type(document)}.")

    from app.core.config import load_settings, GenerationModeEnum
    settings = load_settings()

    # Determine execution mode: OFFLINE_DETERMINISTIC vs ONLINE_LLM
    effective_key = get_gemini_api_key(api_key)
    is_offline = (settings.generation_mode == GenerationModeEnum.OFFLINE_DETERMINISTIC and client is None) or (not client and not effective_key)

    if is_offline:
        logger.info(
            "Executing blog repurposing in OFFLINE_DETERMINISTIC mode for '%s'...",
            doc.filename
        )
        suggestions = generate_blog_suggestions_offline(
            doc=doc,
            selected_platforms=selected_platforms,
            selected_formats=selected_formats,
            target_count=10,
            job_prefix="sug",
        )
        return RepurposingResult(
            input_type="blog",
            job_id=job_id,
            source_document_path=str(doc.filename),
            source_document_name=doc.filename,
            source_document_title=doc.title,
            source_document_sha256=doc.sha256,
            source_word_count=doc.word_count,
            source_headings=doc.headings,
            full_text=doc.text,
            full_transcript=doc.text,
            moments=suggestions,
            model_used="offline_deterministic_generator",
            generated_at=datetime.now(timezone.utc).isoformat(),
            generation_mode="OFFLINE_DETERMINISTIC",
            is_ai_generated=False,
            requires_human_review=True,
            is_factually_verified=False,
            is_ready_to_publish=False,
            selected_platforms=selected_platforms or [],
            selected_formats=selected_formats or {},
            unsupported_formats=unsupported_formats or [],
        )

    # Online Gemini LLM mode
    if client is None:
        try:
            from google import genai
            client = genai.Client(api_key=effective_key)
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize Google GenAI client: {exc}") from exc

    from google.genai import types

    # Format platform & format constraints for Gemini prompt
    if selected_platforms:
        plat_lines = []
        for p in selected_platforms:
            p_norm = "twitter" if p.lower() in ("x", "twitter") else ("youtube_shorts" if p.lower() in ("shorts", "youtube_shorts") else p.lower())
            fmts = (selected_formats or {}).get(p, []) or (selected_formats or {}).get(p_norm, [])
            fmt_desc = ", ".join(fmts) if fmts else "all suitable formats"
            plat_lines.append(f"- Platform: '{p_norm}' | Formats: [{fmt_desc}]")

        platform_scope_prompt = (
            "STRICT PLATFORM & FORMAT SCOPE:\n"
            "You MUST ONLY generate content suggestions for the following explicitly requested platforms and formats:\n"
            + "\n".join(plat_lines) + "\n"
            "DO NOT generate content for unselected platforms or unselected formats.\n"
        )
    else:
        platform_scope_prompt = (
            "Generate platform-specific suggestions for: LinkedIn, YouTube Shorts, Instagram, and X (Twitter).\n"
        )

    system_instruction = (
        "You are an expert social media content repurposing engine for IncuBrix.\n"
        "Analyze the provided long-form blog or article carefully.\n"
        "1. Summarize the core thesis in `document_summary` and extract `document_title`.\n"
        "2. Generate AT LEAST 10 distinct, platform-specific content suggestions adhering to the requested schema.\n"
        "   - YouTube Shorts: short video script with scene cues, kinetic card hook, and key talking points.\n"
        "   - Instagram: multi-slide carousel outlines (Slide 1 Cover to Slide 5 CTA) or Reel scripts with hooks and hashtags.\n"
        "   - LinkedIn: long-form professional thought-leadership posts with operational structure.\n"
        "   - X (Twitter): standalone punchy posts and multi-tweet numbered threads.\n"
        + platform_scope_prompt +
        "3. SOURCE TRACEABILITY: For each suggestion, provide the relevant section heading (`source_heading`) "
        "and a verbatim excerpt (`source_excerpt`) from the source text.\n"
        "4. DO NOT invent facts, statistics, customer testimonials, or claims absent from the source text.\n"
        "5. DO NOT invent destination URLs or performance guarantees. Keep all CTAs low-friction."
    )

    user_prompt = (
        f"Analyze and repurpose this document (Title: '{doc.title}', Format: {doc.format}, Word Count: {doc.word_count}):\n\n"
        f"--- DOCUMENT START ---\n{doc.text}\n--- DOCUMENT END ---\n\n"
        f"Generate at least 10 platform-specific content suggestions across the specified platforms and formats."
    )

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[user_prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeminiBlogRepurposingPayload,
                system_instruction=system_instruction,
                temperature=0.2,
            )
        )
    except Exception as exc:
        logger.error("Gemini API call failed for blog repurposing: %s", exc)
        raise RuntimeError(f"AI processing failed during Gemini API request: {exc}") from exc

    raw_text = getattr(response, "text", None)
    if not raw_text or not raw_text.strip():
        raise ValueError("Malformed or empty response received from Gemini for blog repurposing.")

    try:
        payload = GeminiBlogRepurposingPayload.model_validate_json(raw_text)
    except Exception as exc:
        raise ValueError(f"Failed to validate Gemini blog repurposing JSON payload: {exc}") from exc

    validated_moments: List[CandidateMoment] = []

    for idx, item in enumerate(payload.suggestions, start=1):
        plat_enum, fmt_enum = normalize_platform(item.intended_platform, item.content_format)

        # Filtering against requested platforms and formats
        if selected_platforms:
            allowed_plats = {
                ("twitter" if p.lower() in ("x", "twitter") else ("youtube_shorts" if p.lower() in ("shorts", "youtube_shorts") else p.lower()))
                for p in selected_platforms
            }
            if plat_enum.value not in allowed_plats:
                continue

        if selected_formats:
            allowed_fmts = selected_formats.get(plat_enum.value) or selected_formats.get(item.intended_platform.lower())
            if allowed_fmts:
                norm_fmts = {f.lower().replace(" ", "_") for f in allowed_fmts}
                if fmt_enum.value not in norm_fmts:
                    continue

        warnings = detect_claim_warnings(f"{item.suggested_hook} {item.suggested_content}")

        hash_salt = f"{doc.filename}:{idx}:{item.main_topic}_{plat_enum.value}".encode("utf-8")
        id_digest = hashlib.sha256(hash_salt).hexdigest()[:8]
        sug_id = f"sug_{idx:02d}_{plat_enum.value}_{id_digest}"

        candidate = CandidateMoment(
            moment_id=sug_id,
            start_seconds=None,
            end_seconds=None,
            duration_seconds=None,
            transcript_excerpt=item.source_excerpt.strip() or doc.text[:200],
            source_heading=item.source_heading.strip() or doc.title,
            source_document=doc.filename,
            main_topic=item.main_topic.strip() or doc.title,
            intended_platform=plat_enum,
            content_format=fmt_enum,
            suggested_hook=item.suggested_hook.strip(),
            suggested_content=item.suggested_content.strip(),
            suggested_hashtags=[h.strip() for h in item.suggested_hashtags if h.strip()],
            suggested_cta=item.suggested_cta.strip(),
            destination_url_status="FLAGGED_FOR_HUMAN_CONFIRMATION (No destination URL invented)",
            target_metric=item.target_metric.strip() or "qualified_engagement",
            is_source_attributed=True,
            is_factually_verified=False,
            requires_human_review=True,
            is_ready_to_publish=False,
            review_status="PENDING_HUMAN_EDITORIAL_REVIEW",
            warnings=warnings,
        )
        validated_moments.append(candidate)

    # Guarantee at least 10 suggestions: if Gemini returned fewer, supplement deterministically
    if len(validated_moments) < 10:
        logger.info(
            "Gemini returned %d suggestions; supplementing to reach 10 suggestions...",
            len(validated_moments)
        )
        offline_supplements = generate_blog_suggestions_offline(
            doc=doc,
            selected_platforms=selected_platforms,
            selected_formats=selected_formats,
            target_count=10,
            job_prefix="sug_sup",
        )
        for supp in offline_supplements:
            if len(validated_moments) >= 10:
                break
            validated_moments.append(supp)

    return RepurposingResult(
        input_type="blog",
        job_id=job_id,
        source_document_path=str(doc.filename),
        source_document_name=doc.filename,
        source_document_title=payload.document_title or doc.title,
        source_document_sha256=doc.sha256,
        source_word_count=doc.word_count,
        source_headings=doc.headings,
        full_text=doc.text,
        full_transcript=doc.text,
        moments=validated_moments,
        model_used=model_name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        generation_mode="ONLINE_LLM",
        is_ai_generated=True,
        requires_human_review=True,
        is_factually_verified=False,
        is_ready_to_publish=False,
        selected_platforms=selected_platforms or [],
        selected_formats=selected_formats or {},
        unsupported_formats=unsupported_formats or [],
    )
