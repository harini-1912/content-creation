"""Deterministic offline draft generation module.

Converts validated source segments into platform-specific draft candidates
(LinkedIn, YouTube Shorts, Instagram, and Twitter) using strictly bounded
deterministic templates derived exclusively from the source text.

Maintains explicit separation between:
1. Source attribution (traceability to user-uploaded source text)
2. Factual verification (independent verification against evidence register)
3. Generated creative suggestions (opening hooks, CTAs, scene outlines, transitions)

Applies a rule-based warning scanner to detect known synthetic or prohibited
claim patterns (Tier D). Note: This scanner is a heuristic warning safeguard
and does NOT constitute independent fact-checking or guarantee factual truth.
"""

import hashlib
import re
from typing import List, Dict, Any, Optional

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

# Rule-based warning patterns for known synthetic or unverified claims (Tier D).
# This is a heuristic warning mechanism to assist human review, not an independent
# fact-checker or guarantee of factual correctness.
PROHIBITED_CLAIM_PATTERNS = [
    r"ScaleMedia",
    r"\$340,000",
    r"82%\s+reduction",
    r"144%\s+increase",
    r"4\.3x",
    r"game[- ]changer",
    r"supercharge",
    r"secret\s+sauce",
    r"skyrocket"
]


def detect_claim_warnings(text: str) -> List[str]:
    """Rule-based warning scanner for known synthetic patterns and unverified claims.

    Returns warning messages for detected patterns. Passing this check indicates
    that no prohibited patterns were found, but does NOT verify that remaining claims
    are factually true or independently verified.
    """
    warnings = []
    for pattern in PROHIBITED_CLAIM_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            warnings.append(
                f"Rule-based warning: flagged unverified pattern matching '{pattern}'. "
                "Requires human review before publication."
            )
    return warnings


def determine_pillar(segment: SourceSegment) -> PillarEnum:
    """Deterministically assigns one of the 5 strategy pillars based on source content."""
    combined = f"{segment.heading or ''} {segment.text}".lower()
    if any(k in combined for k in ["hook", "first 3 second", "retention", "swipe"]):
        return PillarEnum.HOOK_TUTORIALS
    if any(k in combined for k in ["repurpose", "one-to-many", "transform", "repurpose engine", "multiplication"]):
        return PillarEnum.ONE_TO_MANY
    if any(k in combined for k in ["cadence", "consistent", "schedule", "buffer", "calendar", "operations"]):
        return PillarEnum.CREATOR_OPERATIONS
    if any(k in combined for k in ["track", "attribution", "utm", "measure", "analytics"]):
        return PillarEnum.ATTRIBUTION_EXPERIMENTS
    return PillarEnum.WORKFLOW_EDUCATION


def generate_draft_id(doc_name: str, seg_id: str, platform: str, format_name: str) -> str:
    """Generates a stable, reproducible draft ID using SHA-256."""
    salt = f"{doc_name}:{seg_id}:{platform}:{format_name}".encode("utf-8")
    hash_digest = hashlib.sha256(salt).hexdigest()[:8]
    clean_platform = platform.lower().replace("_", "")
    return f"draft_{clean_platform}_{seg_id}_{hash_digest}"


def generate_linkedin_draft(segment: SourceSegment, pillar: PillarEnum) -> DraftCandidate:
    """Generates a deterministic LinkedIn text draft from source segment sentences.

    Extracts source sentences for the body and labels opening hook, transitions,
    and CTA as creative suggestions requiring human editorial review.
    """
    key_sentence = segment.sentences[0] if segment.sentences else segment.text
    supporting = segment.sentences[1:4] if len(segment.sentences) > 1 else []
    source_derived_text = " ".join([key_sentence] + supporting).strip()

    hook_prefix = "Operational perspective on content production: "
    hook = f"{hook_prefix}{key_sentence.strip()}"
    cta = "What operating procedures does your team rely on to keep publishing steady?"
    
    body_lines = [
        hook,
        "",
        "When analyzing content workflows, the operational structure dictates consistency:",
        ""
    ]
    for s in supporting:
        body_lines.append(f"• {s.strip()}")
    body_lines.append("")
    body_lines.append("Building predictable distribution systems prevents creative burnout.")

    caption = "\n".join(body_lines)
    excerpt = segment.text[:150].strip() + ("..." if len(segment.text) > 150 else "")
    warnings = detect_claim_warnings(segment.text)

    # Source-derived text is SOURCE_ATTRIBUTED_UNVERIFIED (never automatically CAT_1_VERIFIED).
    # Warnings are preserved in draft.warnings for human review, rather than pre-judging
    # the claim as CAT_4_UNSUPPORTED automatically.
    claim_cat = ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED

    generated_suggestions = {
        "hook": hook,
        "hook_prefix": hook_prefix,
        "call_to_action": cta,
        "transition_intro": "When analyzing content workflows, the operational structure dictates consistency:",
        "transition_outro": "Building predictable distribution systems prevents creative burnout.",
        "suggested_hashtags": "#CreatorOperations, #ContentStrategy, #Workflow"
    }

    return DraftCandidate(
        draft_id=generate_draft_id(segment.source_document, segment.segment_id, "linkedin", "post"),
        source_document=segment.source_document,
        source_segment_id=segment.segment_id,
        source_excerpt=excerpt,
        source_derived_text=source_derived_text,
        platform=PlatformEnum.LINKEDIN,
        content_format=AssetFormatEnum.TEXT_POST,
        pillar=pillar,
        intended_audience="B2B Growth Marketers & Agency Leads",
        draft_hook=hook,
        draft_caption=caption,
        suggested_hashtags=["#CreatorOperations", "#ContentStrategy", "#Workflow"],
        call_to_action=cta,
        generated_suggestions=generated_suggestions,
        is_source_attributed=True,
        is_factually_verified=False,
        requires_human_review=True,
        is_ready_to_publish=False,
        generation_mode=GenerationModeEnum.OFFLINE_DETERMINISTIC,
        lifecycle_status=AssetLifecycleStatus.GENERATED,
        claim_category=claim_cat,
        warnings=warnings
    )


def generate_shorts_draft(segment: SourceSegment, pillar: PillarEnum) -> DraftCandidate:
    """Generates a deterministic vertical short video script (<=60s) from source sentences.

    Extracts spoken narration from source sentences. Labels visual scene cues,
    on-screen text, and save prompt CTA as creative suggestions.
    """
    sentences = segment.sentences[:3] if segment.sentences else [segment.text]
    hook_sentence = sentences[0].strip()
    value_sentence = " ".join(sentences[1:]).strip() if len(sentences) > 1 else hook_sentence
    source_derived_text = f"{hook_sentence} {value_sentence}".strip()

    spoken_script = f"Stop overcomplicating your workflow. Here is the reality: {hook_sentence} {value_sentence}"
    words = spoken_script.split()
    estimated_duration = round(len(words) / 2.3, 1)  # ~138 words per minute

    scene_cues = [
        {
            "scene": 1,
            "duration_seconds": 3.0,
            "visual_cue": "[Fast Zoom + Kinetic Text Header: WORKFLOW REALITY]",
            "voiceover": "Stop overcomplicating your workflow.",
            "on_screen_text": "STOP OVERCOMPLICATING THIS",
            "is_generated_suggestion": True
        },
        {
            "scene": 2,
            "duration_seconds": max(5.0, estimated_duration - 6.0),
            "visual_cue": "[Dark-mode card display with highlighted sentence bullets]",
            "voiceover": f"{hook_sentence} {value_sentence}",
            "on_screen_text": hook_sentence[:45] + ("..." if len(hook_sentence) > 45 else ""),
            "is_generated_suggestion": False,
            "source_segment_id": segment.segment_id
        },
        {
            "scene": 3,
            "duration_seconds": 3.0,
            "visual_cue": "[Final Takeaway Card + Save Prompt]",
            "voiceover": "Focus on the core idea, then distribute.",
            "on_screen_text": "SAVE FOR LATER",
            "is_generated_suggestion": True
        }
    ]

    hook = f"[0-3s Kinetic Card] Stop overcomplicating your workflow: {hook_sentence[:50]}"
    cta = "Save this video for your next production session."
    excerpt = segment.text[:150].strip() + ("..." if len(segment.text) > 150 else "")
    warnings = detect_claim_warnings(segment.text)

    # Source-derived text is SOURCE_ATTRIBUTED_UNVERIFIED (never automatically CAT_1_VERIFIED).
    # Warnings are preserved in draft.warnings for human review, rather than pre-judging
    # the claim as CAT_4_UNSUPPORTED automatically.
    claim_cat = ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED

    generated_suggestions = {
        "hook": hook,
        "call_to_action": cta,
        "opening_hook_voiceover": "Stop overcomplicating your workflow.",
        "closing_takeaway_voiceover": "Focus on the core idea, then distribute.",
        "visual_scene_cues": "3-scene vertical short outline"
    }

    return DraftCandidate(
        draft_id=generate_draft_id(segment.source_document, segment.segment_id, "shorts", "video"),
        source_document=segment.source_document,
        source_segment_id=segment.segment_id,
        source_excerpt=excerpt,
        source_derived_text=source_derived_text,
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=pillar,
        intended_audience="Solo Creators & Video Editors",
        draft_hook=hook,
        draft_caption=spoken_script,
        suggested_hashtags=["#Shorts", "#CreatorOps", "#VideoEditing"],
        call_to_action=cta,
        generated_suggestions=generated_suggestions,
        is_source_attributed=True,
        is_factually_verified=False,
        requires_human_review=True,
        is_ready_to_publish=False,
        generation_mode=GenerationModeEnum.OFFLINE_DETERMINISTIC,
        lifecycle_status=AssetLifecycleStatus.GENERATED,
        claim_category=claim_cat,
        video_scene_cues=scene_cues,
        estimated_duration_seconds=min(60.0, estimated_duration + 6.0),
        warnings=warnings
    )


def generate_twitter_thread_draft(segment: SourceSegment, pillar: PillarEnum) -> DraftCandidate:
    """Generates a deterministic 3-to-4 tweet thread strictly under 280 chars per tweet.

    Extracts thread content from source sentences. Labels opening thread hook,
    takeaway tweet, and retweet CTA as creative suggestions.
    """
    sentences = segment.sentences if segment.sentences else [segment.text]
    source_derived_text = " ".join(sentences[:2]).strip()
    tweets = []
    
    # Opening tweet
    t1 = f"1/3 Most content bottlenecks come down to one issue:\n\n{sentences[0].strip()}"
    tweets.append(t1[:275])

    # Body tweet
    if len(sentences) > 1:
        t2 = f"2/3 Here is why:\n\n{sentences[1].strip()}"
        tweets.append(t2[:275])
    else:
        tweets.append("2/3 When production relies on manual steps, consistency drops.")

    # Concluding tweet
    t3 = "3/3 Takeaway: Build a reliable operating procedure before scaling output."
    tweets.append(t3)

    caption = "\n\n---\n\n".join(tweets)
    hook = tweets[0]
    cta = "Retweet the first post if you found this operational perspective useful."
    excerpt = segment.text[:150].strip() + ("..." if len(segment.text) > 150 else "")
    warnings = detect_claim_warnings(segment.text)

    # Source-derived text is SOURCE_ATTRIBUTED_UNVERIFIED (never automatically CAT_1_VERIFIED).
    # Warnings are preserved in draft.warnings for human review, rather than pre-judging
    # the claim as CAT_4_UNSUPPORTED automatically.
    claim_cat = ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED

    generated_suggestions = {
        "hook": hook,
        "call_to_action": cta,
        "thread_framing": "1/3 Most content bottlenecks come down to one issue:",
        "takeaway_tweet": t3
    }

    return DraftCandidate(
        draft_id=generate_draft_id(segment.source_document, segment.segment_id, "twitter", "thread"),
        source_document=segment.source_document,
        source_segment_id=segment.segment_id,
        source_excerpt=excerpt,
        source_derived_text=source_derived_text,
        platform=PlatformEnum.TWITTER,
        content_format=AssetFormatEnum.THREAD,
        pillar=pillar,
        intended_audience="Tech Founders & Media Creators",
        draft_hook=hook,
        draft_caption=caption,
        suggested_hashtags=["#ContentStrategy", "#BuildInPublic"],
        call_to_action=cta,
        generated_suggestions=generated_suggestions,
        is_source_attributed=True,
        is_factually_verified=False,
        requires_human_review=True,
        is_ready_to_publish=False,
        generation_mode=GenerationModeEnum.OFFLINE_DETERMINISTIC,
        lifecycle_status=AssetLifecycleStatus.GENERATED,
        claim_category=claim_cat,
        warnings=warnings
    )


def generate_instagram_carousel_draft(segment: SourceSegment, pillar: PillarEnum) -> DraftCandidate:
    """Generates a deterministic 5-slide visual carousel outline from source sentences.

    Extracts slide body copy from source sentences. Labels slide layout archetypes,
    cover slide title, and save prompt CTA as creative suggestions.
    """
    sentences = segment.sentences if segment.sentences else [segment.text]
    source_derived_text = " ".join(sentences[:3]).strip()
    title = segment.heading or "Content Production Breakdown"

    slides = [
        {
            "slide": 1,
            "layout": "title_card",
            "headline": title[:40],
            "body": "A structured walkthrough based on practical workflow principles.",
            "is_generated_suggestion": True
        },
        {
            "slide": 2,
            "layout": "problem_card",
            "headline": "The Friction Point",
            "body": sentences[0][:120] if sentences else segment.text[:120],
            "is_generated_suggestion": False,
            "source_segment_id": segment.segment_id
        },
        {
            "slide": 3,
            "layout": "solution_card",
            "headline": "The Operating Principle",
            "body": sentences[1][:120] if len(sentences) > 1 else "Standardize the workflow into repeatable phases.",
            "is_generated_suggestion": False,
            "source_segment_id": segment.segment_id
        },
        {
            "slide": 4,
            "layout": "takeaway_card",
            "headline": "Core Insight",
            "body": sentences[2][:120] if len(sentences) > 2 else "Focus creative energy on recording, not reformatting.",
            "is_generated_suggestion": False,
            "source_segment_id": segment.segment_id
        },
        {
            "slide": 5,
            "layout": "cta_card",
            "headline": "Summary",
            "body": "Save this carousel to reference during your next content planning sprint.",
            "is_generated_suggestion": True
        }
    ]

    hook = f"Slide 1 Cover: {title} (5-Slide Visual Walkthrough)"
    caption = f"{title}\n\nA 5-slide visual teardown on maintaining output consistency without production burnout."
    cta = "Save this post to revisit when planning your editorial calendar."
    excerpt = segment.text[:150].strip() + ("..." if len(segment.text) > 150 else "")
    warnings = detect_claim_warnings(segment.text)

    # Source-derived text is SOURCE_ATTRIBUTED_UNVERIFIED (never automatically CAT_1_VERIFIED).
    # Warnings are preserved in draft.warnings for human review, rather than pre-judging
    # the claim as CAT_4_UNSUPPORTED automatically.
    claim_cat = ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED

    generated_suggestions = {
        "hook": hook,
        "call_to_action": cta,
        "cover_slide": slides[0]["headline"],
        "cta_slide": slides[4]["body"]
    }

    return DraftCandidate(
        draft_id=generate_draft_id(segment.source_document, segment.segment_id, "instagram", "carousel"),
        source_document=segment.source_document,
        source_segment_id=segment.segment_id,
        source_excerpt=excerpt,
        source_derived_text=source_derived_text,
        platform=PlatformEnum.INSTAGRAM,
        content_format=AssetFormatEnum.CAROUSEL,
        pillar=pillar,
        intended_audience="Visual Creators & Agency Operators",
        draft_hook=hook,
        draft_caption=caption,
        suggested_hashtags=["#ContentRepurposing", "#CreatorOps", "#CarouselDesign"],
        call_to_action=cta,
        generated_suggestions=generated_suggestions,
        is_source_attributed=True,
        is_factually_verified=False,
        requires_human_review=True,
        is_ready_to_publish=False,
        generation_mode=GenerationModeEnum.OFFLINE_DETERMINISTIC,
        lifecycle_status=AssetLifecycleStatus.GENERATED,
        claim_category=claim_cat,
        carousel_slide_outlines=slides,
        warnings=warnings
    )


def generate_draft_candidates(segments: List[SourceSegment]) -> List[DraftCandidate]:
    """Generates candidate platform drafts from a list of validated source segments.

    Applies deterministic templates without external API calls or hallucinated facts.
    Returns drafts mapped across LinkedIn, YouTube Shorts, Twitter, and Instagram.
    All drafts are marked as SOURCE_ATTRIBUTED_UNVERIFIED and require human review.
    """
    if not segments:
        raise ValueError("Cannot generate draft candidates: segment list is empty.")

    drafts: List[DraftCandidate] = []

    for seg in segments:
        pillar = determine_pillar(seg)

        # Generate candidates tailored to the segment's substance
        li_draft = generate_linkedin_draft(seg, pillar)
        shorts_draft = generate_shorts_draft(seg, pillar)
        x_draft = generate_twitter_thread_draft(seg, pillar)
        ig_draft = generate_instagram_carousel_draft(seg, pillar)

        drafts.extend([li_draft, shorts_draft, x_draft, ig_draft])

    return drafts
