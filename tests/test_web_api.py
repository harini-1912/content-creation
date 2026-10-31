"""Integration and unit tests for the IncuBrix web API and frontend endpoints (Phase 4.4).

Tests:
- Frontend single-page application rendering (GET /)
- Safe runtime configuration and secret masking (GET /api/config-status)
- Video upload validation: format checking, empty files, size constraints (POST /api/jobs)
- Job status polling and disk manifest recovery (GET /api/jobs/{job_id})
- Recent job listing (GET /api/jobs)
- Background processing worker lifecycle, state transitions, and error handling
"""

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.main import app, _ACTIVE_JOBS, _job_lock, process_video_job_task
from app.core.ai_repurposer import CandidateMoment, RepurposingResult
from app.models.asset import PlatformEnum, AssetFormatEnum


@pytest.fixture
def client():
    """Provides a Starlette/FastAPI TestClient instance."""
    return TestClient(app)


# ============================================================================
# 1. Frontend Route Tests
# ============================================================================

def test_get_frontend_page_renders_html(client):
    """Verifies that GET / returns 200 OK and serves the IncuBrix single-page app."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

    html_text = response.text
    # Check essential UI landmarks
    assert "IncuBrix Content Engine" in html_text
    assert "Generate Platform Content" in html_text
    assert "Video Streaming" in html_text
    assert "Gemini Repurposing" in html_text
    assert "Verbatim Speech Transcript" in html_text
    assert "Recent Jobs" in html_text
    assert "PENDING HUMAN REVIEW" in html_text or "PENDING_HUMAN_EDITORIAL_REVIEW" in html_text


# ============================================================================
# 2. Config Status Endpoint Tests
# ============================================================================

def test_get_config_status_structure_and_masking(client):
    """Verifies GET /api/config-status reports environment details without exposing raw secrets."""
    response = client.get("/api/config-status")
    assert response.status_code == 200
    data = response.json()

    assert "app_env" in data
    assert "generation_mode" in data
    assert "gemini_api_key_configured" in data
    assert "gemini_api_key_masked" in data
    assert "active_model" in data
    assert "max_upload_size_mb" in data
    assert "max_duration_seconds" in data
    assert "ffmpeg_available" in data

    assert data["max_upload_size_mb"] == 100.0
    assert data["max_duration_seconds"] == 600.0
    assert data["active_model"] == "gemini-3.5-flash"

    masked = data["gemini_api_key_masked"]
    if data["gemini_api_key_configured"]:
        assert "[MASKED]" in masked
    else:
        assert masked == "[NOT_SET]"


# ============================================================================
# 3. Job Upload & Validation Tests
# ============================================================================

def test_create_job_rejects_non_mp4_extension(client):
    """Verifies that non-MP4 files are rejected with HTTP 400 Bad Request."""
    dummy_file = io.BytesIO(b"fake avi content")
    response = client.post(
        "/api/jobs",
        files={"file": ("video.avi", dummy_file, "video/x-msvideo")}
    )
    assert response.status_code == 400
    assert "Only .mp4 video files are accepted" in response.json()["detail"]

    txt_file = io.BytesIO(b"not a video")
    response_txt = client.post(
        "/api/jobs",
        files={"file": ("document.txt", txt_file, "text/plain")}
    )
    assert response_txt.status_code == 400


def test_create_job_rejects_empty_file(client):
    """Verifies that an empty (0 bytes) MP4 file upload is rejected with HTTP 400."""
    empty_file = io.BytesIO(b"")
    response = client.post(
        "/api/jobs",
        files={"file": ("empty.mp4", empty_file, "video/mp4")}
    )
    assert response.status_code == 400
    assert "empty (0 bytes)" in response.json()["detail"]


def test_create_job_rejects_oversized_file(client, monkeypatch):
    """Verifies that uploads exceeding the maximum size limit return HTTP 413."""
    # Temporarily set limit to 0.001 MB (approx 1 KB)
    import app.main as app_main
    monkeypatch.setattr(app_main, "DEFAULT_MAX_VIDEO_SIZE_MB", 0.001)

    big_content = io.BytesIO(b"A" * 5000)
    response = client.post(
        "/api/jobs",
        files={"file": ("oversized.mp4", big_content, "video/mp4")}
    )
    assert response.status_code == 413
    assert "exceeds maximum allowed limit" in response.json()["detail"]


def test_create_job_accepts_valid_mp4(client):
    """Verifies that a valid MP4 upload returns HTTP 202 Accepted and registers the job."""
    content = io.BytesIO(b"dummy valid mp4 video binary data for upload testing")

    # Prevent background task from executing in this test
    with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
        response = client.post(
            "/api/jobs",
            files={"file": ("sample_upload.mp4", content, "video/mp4")}
        )

    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert data["job_id"].startswith("job_web_")
    assert data["status"] == "processing"
    assert data["stage"] == "uploading"
    assert data["filename"] == "sample_upload.mp4"
    assert data["file_size_bytes"] > 0

    # Verify job is tracked in memory
    job_id = data["job_id"]
    with _job_lock:
        assert job_id in _ACTIVE_JOBS
        assert _ACTIVE_JOBS[job_id]["status"] == "processing"


# ============================================================================
# 4. Job Polling & Lookup Tests
# ============================================================================

def test_get_job_status_rejects_invalid_job_id(client):
    """Verifies invalid or unsafe job_id characters return HTTP 400."""
    response = client.get("/api/jobs/job..invalid_traversal")
    assert response.status_code == 400
    assert "Invalid job ID" in response.json()["detail"] or "traversal" in response.json()["detail"]

    response2 = client.get("/api/jobs/invalid@char!")
    assert response2.status_code == 400
    assert "Invalid job ID" in response2.json()["detail"]


def test_get_job_status_returns_404_for_unknown_job(client):
    """Verifies non-existent job ID returns HTTP 404 Not Found."""
    response = client.get("/api/jobs/job_unknown_nonexistent_9999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_get_job_status_active_in_memory(client):
    """Verifies retrieval of an active job stored in memory."""
    test_id = "job_test_active_001"
    with _job_lock:
        _ACTIVE_JOBS[test_id] = {
            "job_id": test_id,
            "filename": "test.mp4",
            "file_size_bytes": 1024,
            "status": "processing",
            "stage": "validating",
            "stage_message": "Checking codecs...",
            "created_at": "2026-10-31T12:00:00Z",
            "completed_at": None,
            "error": None,
            "result": None,
        }

    response = client.get(f"/api/jobs/{test_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == test_id
    assert data["status"] == "processing"
    assert data["stage"] == "validating"


def test_get_job_status_recovers_from_disk(client, tmp_path, monkeypatch):
    """Verifies that an on-disk completed job manifest is recovered when not in memory."""
    import app.main as app_main
    monkeypatch.setattr(app_main, "DEFAULT_VIDEO_JOBS_DIR", tmp_path)

    test_job_id = "job_disk_recovery_test_01"
    job_dir = tmp_path / test_job_id
    job_dir.mkdir(parents=True)

    manifest_file = job_dir / "gemini_repurposing_result.json"
    dummy_manifest = {
        "job_id": test_job_id,
        "source_video_path": str(job_dir / "source.mp4"),
        "source_duration_seconds": 120.0,
        "full_transcript": "This is a recovered test transcript from disk.",
        "moments": [
            {
                "moment_id": "moment_01_linkedin_1234",
                "start_seconds": 0.0,
                "end_seconds": 30.0,
                "duration_seconds": 30.0,
                "transcript_excerpt": "Recovered excerpt",
                "main_topic": "Architecture",
                "intended_platform": "linkedin",
                "content_format": "text_post",
                "suggested_hook": "Recovered Hook",
                "suggested_content": "Recovered Content",
                "suggested_hashtags": ["#AI"],
                "suggested_cta": "Read more",
                "requires_human_review": True,
                "is_factually_verified": False,
                "is_ready_to_publish": False,
            }
        ],
        "model_used": "gemini-3.5-flash",
        "generated_at": "2026-10-31T08:00:00Z",
        "generation_mode": "ONLINE_LLM",
    }
    manifest_file.write_text(json.dumps(dummy_manifest), encoding="utf-8")

    # Remove from memory if present
    with _job_lock:
        _ACTIVE_JOBS.pop(test_job_id, None)

    response = client.get(f"/api/jobs/{test_job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == test_job_id
    assert data["status"] == "completed"
    assert data["stage"] == "completed"
    assert data["result"]["full_transcript"] == "This is a recovered test transcript from disk."
    assert len(data["result"]["moments"]) == 1


# ============================================================================
# 5. List Jobs Endpoint Tests
# ============================================================================

def test_list_recent_jobs(client):
    """Verifies GET /api/jobs returns a list of jobs."""
    response = client.get("/api/jobs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ============================================================================
# 6. Background Worker Task Lifecycle Tests
# ============================================================================

def test_background_worker_task_success(tmp_path):
    """Verifies full execution lifecycle of background worker task with mocked processor."""
    job_id = "job_worker_test_success_01"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    video_file = job_dir / "test.mp4"
    video_file.write_bytes(b"dummy video bytes")

    with _job_lock:
        _ACTIVE_JOBS[job_id] = {
            "job_id": job_id,
            "status": "processing",
            "stage": "uploading",
        }

    mock_moment = CandidateMoment(
        moment_id="moment_01_linkedin_test",
        start_seconds=10.0,
        end_seconds=40.0,
        duration_seconds=30.0,
        transcript_excerpt="Verbatim moment transcript",
        main_topic="Scalable Architecture",
        intended_platform=PlatformEnum.LINKEDIN,
        content_format=AssetFormatEnum.TEXT_POST,
        suggested_hook="Why architecture matters",
        suggested_content="Detailed post copy...",
        suggested_hashtags=["#Engineering"],
        suggested_cta="Check the docs",
        requires_human_review=True,
        is_factually_verified=False,
        is_ready_to_publish=False,
    )

    mock_result = RepurposingResult(
        job_id=job_id,
        source_video_path=str(video_file),
        source_video_sha256="abc123sha",
        source_audio_path=str(job_dir / "extracted_speech_16khz.wav"),
        source_audio_sha256="wav123sha",
        source_duration_seconds=60.0,
        full_transcript="Full transcript of spoken words in test video.",
        moments=[mock_moment],
        model_used="gemini-3.5-flash",
        generated_at="2026-10-31T12:00:00Z",
        generation_mode="ONLINE_LLM",
        is_ai_generated=True,
        requires_human_review=True,
        is_factually_verified=False,
        is_ready_to_publish=False,
    )

    with patch("app.main.validate_video") as mock_val, \
         patch("app.main.inspect_video") as mock_insp, \
         patch("app.main.extract_audio") as mock_ext, \
         patch("app.main.repurpose_audio_with_gemini") as mock_rep:

        mock_insp.return_value = {
            "duration_sec": 60.0,
            "has_video_stream": True,
            "has_audio_stream": True,
            "video_codec": "h264",
            "audio_codec": "aac",
        }
        mock_ext.return_value = (job_dir / "extracted_speech_16khz.wav", {"sample_rate": 16000})
        mock_rep.return_value = mock_result

        process_video_job_task(job_id, video_file, job_dir)

    with _job_lock:
        job_state = _ACTIVE_JOBS[job_id]
        assert job_state["status"] == "completed"
        assert job_state["stage"] == "completed"
        assert job_state["error"] is None
        assert job_state["result"] is not None
        assert len(job_state["result"]["moments"]) == 1

    # Check that disk manifest was written
    manifest = job_dir / "gemini_repurposing_result.json"
    assert manifest.exists()


def test_background_worker_task_failure_and_sanitization(tmp_path):
    """Verifies that worker catches exceptions, marks job as failed, and redacts sensitive keys."""
    job_id = "job_worker_test_failure_01"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    video_file = job_dir / "bad_video.mp4"
    video_file.write_bytes(b"bad content")

    secret_key = "AIzaSySecretApiKey12345"

    with _job_lock:
        _ACTIVE_JOBS[job_id] = {
            "job_id": job_id,
            "status": "processing",
            "stage": "uploading",
        }

    with patch("app.main.validate_video", side_effect=ValueError(f"Corrupt video file! Key was {secret_key}")), \
         patch("app.main.get_gemini_api_key", return_value=secret_key):

        process_video_job_task(job_id, video_file, job_dir)

    with _job_lock:
        job_state = _ACTIVE_JOBS[job_id]
        assert job_state["status"] == "failed"
        assert job_state["stage"] == "failed"
        assert job_state["error"] is not None
        # Verify secret key was redacted from the error message
        assert secret_key not in job_state["error"]
        assert "[REDACTED_API_KEY]" in job_state["error"]
