"""Unit tests for blog and article repurposing engine (Phase 4.4B).

Verifies:
- Offline deterministic suggestion generation (>= 10 suggestions across platforms).
- Platform & format filtering on blog suggestions.
- Source traceability (preserves document name, headings, and excerpts).
- Mocked Gemini online workflow with structured response schema.
- Supplementing with deterministic suggestions when model returns fewer than 10.
- Safety flags: requires_human_review=True, is_factually_verified=False, is_ready_to_publish=False.
"""

from pathlib import Path
import pytest
from unittest.mock import MagicMock

from app.core.document_extractor import ExtractedDocument
from app.core.ai_repurposer import (
    generate_blog_suggestions_offline,
    repurpose_blog_with_gemini,
    CandidateMoment,
    RepurposingResult,
    GeminiBlogSuggestionItem,
    GeminiBlogRepurposingPayload,
)
from app.models.asset import PlatformEnum, AssetFormatEnum


@pytest.fixture
def sample_extracted_doc() -> ExtractedDocument:
    """Provides a realistic sample extracted document with headings and paragraphs."""
    text = (
        "# System Architecture for High-Scale Content Distribution\n\n"
        "## The Cognitive Overhead of Multi-Platform Publishing\n\n"
        "Creators and media engineering teams face severe cognitive fatigue from switching between disparate utilities. "
        "Disconnected apps create redundant manual handoffs, scattered files, and erratic distribution rhythms that drain creative energy.\n\n"
        "## Centralizing the Repurposing Pipeline\n\n"
        "A consolidated content engine centralizes ingestion, transcription, draft derivation, and link tagging into one unified editorial environment. "
        "By enforcing repeatable operating procedures, media engineering teams preserve consistent production velocity without sacrificing quality.\n\n"
        "## Multi-Channel Attribution and Audience Feedback\n\n"
        "Tracking UTM parameters and measuring performance metrics like retention rate, save rate, and repost rate establishes a closed-loop feedback mechanism. "
        "Teams can systematically identify which content formats resonate best with technical audiences across YouTube Shorts, LinkedIn, Instagram, and X."
    )
    return ExtractedDocument(
        filename="content_architecture.md",
        format="md",
        file_size_bytes=len(text.encode("utf-8")),
        sha256="abcdef1234567890",
        title="System Architecture for High-Scale Content Distribution",
        text=text,
        headings=[
            "The Cognitive Overhead of Multi-Platform Publishing",
            "Centralizing the Repurposing Pipeline",
            "Multi-Channel Attribution and Audience Feedback",
        ],
        word_count=len(text.split()),
        char_count=len(text),
        page_or_section_count=3,
        warnings=[],
    )


def test_offline_blog_suggestions_generates_at_least_10(sample_extracted_doc: ExtractedDocument):
    """Verifies that offline blog repurposing generates at least 10 platform-specific suggestions."""
    suggestions = generate_blog_suggestions_offline(
        doc=sample_extracted_doc,
        selected_platforms=["youtube_shorts", "instagram", "linkedin", "twitter"],
        target_count=10,
    )

    assert len(suggestions) >= 10
    # Check that platforms are covered
    platforms_present = {s.intended_platform.value for s in suggestions}
    assert "linkedin" in platforms_present
    assert "youtube_shorts" in platforms_present
    assert "instagram" in platforms_present
    assert "twitter" in platforms_present


def test_offline_blog_suggestions_traceability_and_safeguards(sample_extracted_doc: ExtractedDocument):
    """Verifies source traceability and editorial safeguards across all generated suggestions."""
    suggestions = generate_blog_suggestions_offline(
        doc=sample_extracted_doc,
        target_count=10,
    )

    for s in suggestions:
        assert s.source_document == "content_architecture.md"
        assert s.source_heading is not None
        assert len(s.transcript_excerpt) > 10
        assert s.is_source_attributed is True
        assert s.is_factually_verified is False
        assert s.requires_human_review is True
        assert s.is_ready_to_publish is False
        assert s.review_status == "PENDING_HUMAN_EDITORIAL_REVIEW"
        assert "FLAGGED_FOR_HUMAN_CONFIRMATION" in s.destination_url_status
        assert s.target_metric is not None


def test_offline_blog_suggestions_single_platform_generates_10(sample_extracted_doc: ExtractedDocument):
    """Verifies that even if only one platform is selected, at least 10 distinct suggestions are generated."""
    suggestions = generate_blog_suggestions_offline(
        doc=sample_extracted_doc,
        selected_platforms=["linkedin"],
        selected_formats={"linkedin": ["text_post"]},
        target_count=10,
    )

    assert len(suggestions) >= 10
    for s in suggestions:
        assert s.intended_platform == PlatformEnum.LINKEDIN
        assert s.content_format == AssetFormatEnum.TEXT_POST


def test_offline_blog_suggestions_format_filtering(sample_extracted_doc: ExtractedDocument):
    """Verifies that requested formats are strictly respected in generated suggestions."""
    suggestions = generate_blog_suggestions_offline(
        doc=sample_extracted_doc,
        selected_platforms=["instagram", "twitter"],
        selected_formats={"instagram": ["carousel"], "twitter": ["thread"]},
        target_count=10,
    )

    assert len(suggestions) >= 10
    for s in suggestions:
        if s.intended_platform == PlatformEnum.INSTAGRAM:
            assert s.content_format == AssetFormatEnum.CAROUSEL
        elif s.intended_platform == PlatformEnum.TWITTER:
            assert s.content_format == AssetFormatEnum.THREAD


def test_repurpose_blog_offline_mode_returns_repurposing_result(sample_extracted_doc: ExtractedDocument):
    """Verifies that repurpose_blog_with_gemini in offline mode returns a populated RepurposingResult."""
    result = repurpose_blog_with_gemini(
        document=sample_extracted_doc,
        selected_platforms=["linkedin", "twitter"],
        job_id="test_blog_job_001",
    )

    assert isinstance(result, RepurposingResult)
    assert result.input_type == "blog"
    assert result.job_id == "test_blog_job_001"
    assert result.source_document_name == "content_architecture.md"
    assert result.source_document_title == "System Architecture for High-Scale Content Distribution"
    assert len(result.moments) >= 10
    assert result.generation_mode == "OFFLINE_DETERMINISTIC"


def test_repurpose_blog_with_mocked_gemini_client(sample_extracted_doc: ExtractedDocument):
    """Verifies that repurpose_blog_with_gemini correctly interacts with the Gemini Client and response schema."""
    # Build 10 mock Gemini items
    mock_items = []
    platforms = ["linkedin", "youtube_shorts", "instagram", "twitter"]
    formats = ["text_post", "short_video", "carousel", "thread"]

    for i in range(1, 11):
        plat = platforms[(i - 1) % len(platforms)]
        fmt = formats[(i - 1) % len(formats)]
        mock_items.append(
            GeminiBlogSuggestionItem(
                source_heading="Centralizing the Repurposing Pipeline",
                source_excerpt="A consolidated content engine centralizes ingestion...",
                main_topic=f"Pipeline Optimization Step {i}",
                intended_platform=plat,
                content_format=fmt,
                suggested_hook=f"Hook for item {i}: Eliminate distribution friction.",
                suggested_content=f"Content body for item {i} explaining systematic distribution.",
                suggested_hashtags=["#ContentEngineering", "#CreatorOps"],
                suggested_cta="Check out the complete architecture guide.",
                target_metric="qualified_engagement",
            )
        )

    mock_payload = GeminiBlogRepurposingPayload(
        document_title="System Architecture for High-Scale Content Distribution",
        document_summary="Centralizing content operations eliminates creator burnout.",
        suggestions=mock_items,
    )

    # Mock client and response
    mock_response = MagicMock()
    mock_response.text = mock_payload.model_dump_json()

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    result = repurpose_blog_with_gemini(
        document=sample_extracted_doc,
        client=mock_client,
        selected_platforms=["linkedin", "youtube_shorts", "instagram", "twitter"],
        job_id="mock_gemini_blog_job",
    )

    assert result.input_type == "blog"
    assert result.generation_mode == "ONLINE_LLM"
    assert len(result.moments) == 10
    mock_client.models.generate_content.assert_called_once()
    assert result.moments[0].suggested_hook == "Hook for item 1: Eliminate distribution friction."


def test_repurpose_blog_gemini_supplements_when_fewer_than_10(sample_extracted_doc: ExtractedDocument):
    """Verifies that if Gemini returns fewer than 10 suggestions, the engine supplements to meet the requirement."""
    # Only 3 suggestions from mock Gemini
    mock_items = [
        GeminiBlogSuggestionItem(
            source_heading="Centralizing the Repurposing Pipeline",
            source_excerpt="A consolidated content engine centralizes ingestion...",
            main_topic=f"Pipeline Step {i}",
            intended_platform="linkedin",
            content_format="text_post",
            suggested_hook=f"Gemini Hook {i}",
            suggested_content=f"Gemini Content {i}",
            suggested_hashtags=["#ContentEngineering"],
            suggested_cta="Read the full guide.",
            target_metric="qualified_reads",
        )
        for i in range(1, 4)
    ]

    mock_payload = GeminiBlogRepurposingPayload(
        document_title="System Architecture for High-Scale Content Distribution",
        document_summary="Summary",
        suggestions=mock_items,
    )

    mock_response = MagicMock()
    mock_response.text = mock_payload.model_dump_json()
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    result = repurpose_blog_with_gemini(
        document=sample_extracted_doc,
        client=mock_client,
        job_id="supplemented_blog_job",
    )

    assert len(result.moments) >= 10
    assert result.moments[0].suggested_hook == "Gemini Hook 1"

