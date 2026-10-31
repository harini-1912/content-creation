"""Integration and unit tests for Custom Platform and Format Selection (Phase 4.4A).

Tests:
- Single-platform selection and format defaults
- Multiple-platform selection
- Custom individual format selection per platform
- Validation: rejecting empty platform lists (HTTP 400)
- Validation: rejecting empty format lists (HTTP 400)
- Validation: rejecting unsupported platform requests (HTTP 400)
- Validation: rejecting unsupported format requests (HTTP 400)
- Filtering: verifying that unselected platforms and formats are omitted from generated results
- Communication: clear messages for unsupported formats
"""

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.main import app, _ACTIVE_JOBS, _job_lock, process_video_job_task
from app.core.ai_repurposer import (
    SUPPORTED_PLATFORMS_FORMATS,
    CandidateMoment,
    GeminiMomentItem,
    RepurposingResult,
    validate_timestamps_and_moments,
    repurpose_audio_with_gemini,
)
from app.models.asset import PlatformEnum, AssetFormatEnum


@pytest.fixture
def client():
    return TestClient(app)


# ============================================================================
# 1. Platform & Format Catalog Introspection Tests
# ============================================================================

def test_config_status_includes_platform_and_format_catalog(client):
    """Verifies that GET /api/config-status includes the supported platform & format catalog."""
    resp = client.get("/api/config-status")
    assert resp.status_code == 200
    data = resp.json()

    assert "supported_platforms_and_formats" in data
    catalog = data["supported_platforms_and_formats"]

    # All 4 platforms must be present
    assert "youtube_shorts" in catalog
    assert "instagram" in catalog
    assert "linkedin" in catalog
    assert "twitter" in catalog

    # Formats verification
    yt_fmts = catalog["youtube_shorts"]["formats"]
    assert "short_video" in yt_fmts
    assert "captions_and_hooks" in yt_fmts

    ig_fmts = catalog["instagram"]["formats"]
    assert "reels" in ig_fmts
    assert "carousel" in ig_fmts
    assert "captions_and_hashtags" in ig_fmts

    li_fmts = catalog["linkedin"]["formats"]
    assert "text_post" in li_fmts
    assert "video_post" in li_fmts

    tw_fmts = catalog["twitter"]["formats"]
    assert "single_post" in tw_fmts
    assert "thread" in tw_fmts


# ============================================================================
# 2. Upload Validation Tests (Platforms & Formats)
# ============================================================================

def test_create_job_rejects_empty_platform_list(client):
    """Verifies that submitting an empty platforms list returns HTTP 400."""
    dummy_file = io.BytesIO(b"dummy mp4 video bytes")
    resp = client.post(
        "/api/jobs",
        files={"file": ("test.mp4", dummy_file, "video/mp4")},
        data={"platforms": "[]"}
    )
    assert resp.status_code == 400
    assert "At least one platform must be selected" in resp.json()["detail"]


def test_create_job_rejects_unsupported_platform(client):
    """Verifies that requesting an unsupported platform (e.g. TikTok) returns HTTP 400."""
    dummy_file = io.BytesIO(b"dummy mp4 video bytes")
    resp = client.post(
        "/api/jobs",
        files={"file": ("test.mp4", dummy_file, "video/mp4")},
        data={"platforms": json.dumps(["tiktok"])}
    )
    assert resp.status_code == 400
    assert "Platform 'tiktok' is not currently supported" in resp.json()["detail"]


def test_create_job_rejects_unsupported_format(client):
    """Verifies that requesting an unsupported format returns HTTP 400 with a clear error."""
    dummy_file = io.BytesIO(b"dummy mp4 video bytes")
    resp = client.post(
        "/api/jobs",
        files={"file": ("test.mp4", dummy_file, "video/mp4")},
        data={
            "platforms": json.dumps(["linkedin"]),
            "formats": json.dumps({"linkedin": ["interactive_poll"]}),
        }
    )
    assert resp.status_code == 400
    assert "Format 'interactive_poll' is unsupported for platform 'LinkedIn'" in resp.json()["detail"]


def test_create_job_rejects_empty_format_selection(client):
    """Verifies that selecting platforms but zero formats returns HTTP 400."""
    dummy_file = io.BytesIO(b"dummy mp4 video bytes")
    resp = client.post(
        "/api/jobs",
        files={"file": ("test.mp4", dummy_file, "video/mp4")},
        data={
            "platforms": json.dumps(["linkedin"]),
            "formats": json.dumps({"linkedin": []}),
        }
    )
    assert resp.status_code == 400
    assert "At least one content format must be selected" in resp.json()["detail"]


# ============================================================================
# 3. Valid Upload with Platform & Format Selections
# ============================================================================

def test_create_job_single_platform_selection(client):
    """Verifies submitting a single platform (e.g. LinkedIn only) registers correctly."""
    dummy_file = io.BytesIO(b"dummy mp4 video content")
    with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
        resp = client.post(
            "/api/jobs",
            files={"file": ("single_plat.mp4", dummy_file, "video/mp4")},
            data={"platforms": json.dumps(["linkedin"])}
        )

    assert resp.status_code == 202
    data = resp.json()
    assert data["selected_platforms"] == ["linkedin"]
    # LinkedIn formats should default to all available for LinkedIn
    assert "text_post" in data["selected_formats"]["linkedin"]
    assert "video_post" in data["selected_formats"]["linkedin"]


def test_create_job_multiple_platforms_and_custom_formats(client):
    """Verifies custom selection across multiple platforms (e.g. YouTube Shorts + Twitter)."""
    dummy_file = io.BytesIO(b"dummy mp4 video content")
    custom_formats = {
        "youtube_shorts": ["short_video"],
        "twitter": ["thread"]
    }
    with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
        resp = client.post(
            "/api/jobs",
            files={"file": ("multi_plat.mp4", dummy_file, "video/mp4")},
            data={
                "platforms": json.dumps(["youtube_shorts", "twitter"]),
                "formats": json.dumps(custom_formats),
                "format_mode": "custom",
            }
        )

    assert resp.status_code == 202
    data = resp.json()
    assert set(data["selected_platforms"]) == {"youtube_shorts", "twitter"}
    assert data["selected_formats"]["youtube_shorts"] == ["short_video"]
    assert data["selected_formats"]["twitter"] == ["thread"]


# ============================================================================
# 4. Pipeline Filtering & Generation Respects Selections
# ============================================================================

def test_validate_timestamps_and_moments_filters_unselected_platforms():
    """Verifies that moments for unselected platforms are excluded from the output."""
    m_yt = GeminiMomentItem(
        start_seconds=10.0,
        end_seconds=40.0,
        transcript_excerpt="Shorts clip excerpt",
        main_topic="Shorts topic",
        intended_platform="youtube_shorts",
        content_format="short_video",
        suggested_hook="Shorts Hook",
        suggested_content="Shorts Content",
        suggested_hashtags=[],
        suggested_cta="Subscribe",
    )
    m_li = GeminiMomentItem(
        start_seconds=50.0,
        end_seconds=80.0,
        transcript_excerpt="LinkedIn post excerpt",
        main_topic="LinkedIn topic",
        intended_platform="linkedin",
        content_format="text_post",
        suggested_hook="LinkedIn Hook",
        suggested_content="LinkedIn Content",
        suggested_hashtags=[],
        suggested_cta="Comment below",
    )

    # When user only selects LinkedIn, YouTube Shorts must be omitted
    validated = validate_timestamps_and_moments(
        raw_moments=[m_yt, m_li],
        source_duration_sec=120.0,
        selected_platforms=["linkedin"],
    )

    assert len(validated) == 1
    assert validated[0].intended_platform == PlatformEnum.LINKEDIN
    assert validated[0].content_format == AssetFormatEnum.TEXT_POST


def test_validate_timestamps_and_moments_filters_unselected_formats():
    """Verifies that moments for unselected formats are excluded even on selected platforms."""
    m_text = GeminiMomentItem(
        start_seconds=10.0,
        end_seconds=30.0,
        transcript_excerpt="Text post excerpt",
        main_topic="Text topic",
        intended_platform="linkedin",
        content_format="text_post",
        suggested_hook="Text Hook",
        suggested_content="Text Content",
        suggested_hashtags=[],
        suggested_cta="CTA",
    )
    m_video = GeminiMomentItem(
        start_seconds=40.0,
        end_seconds=70.0,
        transcript_excerpt="Video post excerpt",
        main_topic="Video topic",
        intended_platform="linkedin",
        content_format="video_post",
        suggested_hook="Video Hook",
        suggested_content="Video Content",
        suggested_hashtags=[],
        suggested_cta="CTA",
    )

    # User selected LinkedIn, but only "video_post" format
    validated = validate_timestamps_and_moments(
        raw_moments=[m_text, m_video],
        source_duration_sec=120.0,
        selected_platforms=["linkedin"],
        selected_formats={"linkedin": ["video_post"]},
    )

    assert len(validated) == 1
    assert validated[0].content_format == AssetFormatEnum.VIDEO_POST


def test_background_worker_stores_selected_platforms_in_result(tmp_path):
    """Verifies that the background worker records selected platforms & formats in the final result manifest."""
    job_id = "job_worker_platform_test_01"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    video_file = job_dir / "input.mp4"
    video_file.write_bytes(b"dummy mp4")

    with _job_lock:
        _ACTIVE_JOBS[job_id] = {
            "job_id": job_id,
            "status": "processing",
            "stage": "uploading",
        }

    mock_moment = CandidateMoment(
        moment_id="moment_01_youtube_shorts_test",
        start_seconds=5.0,
        end_seconds=25.0,
        duration_seconds=20.0,
        transcript_excerpt="Shorts excerpt",
        main_topic="Shorts Clip",
        intended_platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        suggested_hook="Hook",
        suggested_content="Content",
        suggested_hashtags=[],
        suggested_cta="CTA",
        requires_human_review=True,
        is_factually_verified=False,
        is_ready_to_publish=False,
    )

    mock_result = RepurposingResult(
        job_id=job_id,
        source_video_path=str(video_file),
        source_audio_path=str(job_dir / "audio.wav"),
        source_duration_seconds=60.0,
        full_transcript="Transcript text.",
        moments=[mock_moment],
        model_used="gemini-3.5-flash",
        generated_at="2026-10-31T12:00:00Z",
        generation_mode="ONLINE_LLM",
        selected_platforms=["youtube_shorts"],
        selected_formats={"youtube_shorts": ["short_video"]},
    )

    with patch("app.main.validate_video"), \
         patch("app.main.inspect_video", return_value={"duration_sec": 60.0, "has_video_stream": True, "has_audio_stream": True}), \
         patch("app.main.extract_audio", return_value=(job_dir / "audio.wav", {})), \
         patch("app.main.repurpose_audio_with_gemini", return_value=mock_result):

        process_video_job_task(
            job_id=job_id,
            video_path=video_file,
            job_dir=job_dir,
            selected_platforms=["youtube_shorts"],
            selected_formats={"youtube_shorts": ["short_video"]},
        )

    with _job_lock:
        job_state = _ACTIVE_JOBS[job_id]
        assert job_state["status"] == "completed"
        assert job_state["result"]["selected_platforms"] == ["youtube_shorts"]
        assert job_state["result"]["selected_formats"]["youtube_shorts"] == ["short_video"]
