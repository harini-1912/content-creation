"""Tests for video processing and audio extraction module.

Covers:
- Safe job directory creation and job ID validation
- Path traversal and malicious filename protection
- File validation: missing file, non-file, empty file, corrupt format, unsupported extension
- Size limit and duration limit constraints
- Stream validation: missing video stream, missing audio stream
- Successful inspection and WAV audio extraction (mono 16 kHz PCM)
- Subprocess error handling and source protection
"""

from pathlib import Path
import subprocess
from unittest.mock import patch
import wave

import pytest

from app.core.media_renderer import get_ffmpeg_executable
from app.core.video_processor import (
    DEFAULT_MAX_VIDEO_SIZE_MB,
    DEFAULT_MAX_VIDEO_DURATION_SEC,
    DEFAULT_AUDIO_SAMPLE_RATE,
    DEFAULT_AUDIO_CHANNELS,
    generate_job_id,
    validate_job_id,
    create_video_job_dir,
    sanitize_filename,
    save_uploaded_video,
    inspect_video,
    validate_video,
    extract_audio,
)


@pytest.fixture(scope="session")
def ffmpeg_bin():
    exe = get_ffmpeg_executable()
    assert exe is not None, "FFmpeg executable is required for video processor tests."
    return exe


@pytest.fixture
def synthetic_valid_mp4(ffmpeg_bin, tmp_path: Path) -> Path:
    """Creates a small 1-second synthetic MP4 with video (160x120) and audio (AAC sine tone)."""
    out_file = tmp_path / "valid_sample.mp4"
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(out_file)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_file


@pytest.fixture
def synthetic_video_only_mp4(ffmpeg_bin, tmp_path: Path) -> Path:
    """Creates a 1-second synthetic MP4 with video stream but NO audio stream."""
    out_file = tmp_path / "video_only.mp4"
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(out_file)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_file


@pytest.fixture
def synthetic_audio_only_mp4(ffmpeg_bin, tmp_path: Path) -> Path:
    """Creates a 1-second synthetic MP4 container with audio stream but NO video stream."""
    out_file = tmp_path / "audio_only.mp4"
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-vn", "-c:a", "aac",
        str(out_file)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_file


# ============================================================================
# Job Storage and Sanitization Tests
# ============================================================================

def test_generate_and_validate_job_id():
    job_id = generate_job_id()
    assert job_id.startswith("job_")
    validated = validate_job_id(job_id)
    assert validated == job_id

    # Custom prefix
    custom_id = generate_job_id(prefix="test_run")
    assert custom_id.startswith("test_run_")
    assert validate_job_id(custom_id) == custom_id


def test_validate_job_id_rejections():
    with pytest.raises(ValueError, match="non-empty string"):
        validate_job_id("")

    with pytest.raises(ValueError, match="alphanumeric"):
        validate_job_id("job/with/slashes")

    with pytest.raises(ValueError, match="alphanumeric"):
        validate_job_id("job\\with\\backslashes")

    with pytest.raises(ValueError, match="alphanumeric"):
        validate_job_id("job with spaces")

    with pytest.raises(ValueError, match="alphanumeric"):
        validate_job_id("job$bad!chars*")


def test_create_video_job_dir(tmp_path: Path):
    base_dir = tmp_path / "jobs"
    job_id, job_path = create_video_job_dir(base_dir=base_dir)

    assert job_path.exists()
    assert job_path.is_dir()
    assert job_path.parent == base_dir.resolve()
    assert job_id in str(job_path)


def test_sanitize_filename():
    assert sanitize_filename("my video clip.mp4") == "my_video_clip.mp4"
    assert sanitize_filename("../../../etc/passwd.mp4") == "passwd.mp4"
    assert sanitize_filename("special!@#$%^&*().mp4") == "special.mp4"
    assert sanitize_filename("") == "uploaded_video.mp4"


def test_save_uploaded_video_from_bytes(tmp_path: Path):
    job_dir = tmp_path / "job_001"
    raw_data = b"synthetic video content bytes"
    saved = save_uploaded_video(raw_data, "client upload.mp4", job_dir)

    assert saved.exists()
    assert saved.name == "client_upload.mp4"
    assert saved.read_bytes() == raw_data


def test_save_uploaded_video_from_file(synthetic_valid_mp4: Path, tmp_path: Path):
    job_dir = tmp_path / "job_002"
    saved = save_uploaded_video(synthetic_valid_mp4, "renamed_video.mp4", job_dir)

    assert saved.exists()
    assert saved.name == "renamed_video.mp4"
    assert saved.stat().st_size == synthetic_valid_mp4.stat().st_size
    # Original remains untouched
    assert synthetic_valid_mp4.exists()


# ============================================================================
# Validation and Inspection Tests
# ============================================================================

def test_validate_video_missing_file(tmp_path: Path):
    missing = tmp_path / "non_existent.mp4"
    with pytest.raises(FileNotFoundError, match="not found"):
        validate_video(missing)


def test_validate_video_not_a_file(tmp_path: Path):
    with pytest.raises(ValueError, match="not a file"):
        validate_video(tmp_path)


def test_validate_video_unsupported_format(tmp_path: Path):
    avi_file = tmp_path / "recording.avi"
    avi_file.write_bytes(b"some content")
    with pytest.raises(ValueError, match="Only .mp4 video files are accepted"):
        validate_video(avi_file)


def test_validate_video_empty_file(tmp_path: Path):
    empty_file = tmp_path / "empty.mp4"
    empty_file.write_bytes(b"")
    with pytest.raises(ValueError, match="empty \\(0 bytes\\)"):
        validate_video(empty_file)


def test_validate_video_corrupt_file(tmp_path: Path):
    corrupt_file = tmp_path / "corrupt.mp4"
    corrupt_file.write_bytes(b"This is completely corrupt non-media text content.")
    with pytest.raises(ValueError, match="corrupt or not a recognized media file"):
        validate_video(corrupt_file)


def test_validate_video_size_limit_exceeded(synthetic_valid_mp4: Path):
    # Pass an artificially tiny size limit (e.g. 0.0001 MB = 100 bytes)
    with pytest.raises(ValueError, match="exceeds maximum allowed limit"):
        validate_video(synthetic_valid_mp4, max_size_mb=0.0001)


def test_validate_video_duration_limit_exceeded(synthetic_valid_mp4: Path):
    # The synthetic video is 1.0 second; pass limit of 0.5s
    with pytest.raises(ValueError, match="duration .* exceeds maximum allowed limit"):
        validate_video(synthetic_valid_mp4, max_duration_sec=0.5)


def test_validate_video_missing_video_stream(synthetic_audio_only_mp4: Path):
    with pytest.raises(ValueError, match="does not contain an active video stream"):
        validate_video(synthetic_audio_only_mp4)


def test_validate_video_missing_audio_stream(synthetic_video_only_mp4: Path):
    with pytest.raises(ValueError, match="does not contain an active audio stream"):
        validate_video(synthetic_video_only_mp4)


def test_validate_video_success(synthetic_valid_mp4: Path):
    validated = validate_video(synthetic_valid_mp4)
    assert validated == synthetic_valid_mp4.resolve()


def test_inspect_video_metadata(synthetic_valid_mp4: Path):
    info = inspect_video(synthetic_valid_mp4)

    assert info["filename"] == "valid_sample.mp4"
    assert info["format"] == "mp4"
    assert info["file_size_bytes"] > 0
    assert info["file_size_mb"] > 0
    assert len(info["sha256"]) == 64
    assert 0.9 <= info["duration_sec"] <= 1.2
    assert info["has_video_stream"] is True
    assert info["video_codec"] is not None
    assert info["width"] == 160
    assert info["height"] == 120
    assert info["has_audio_stream"] is True
    assert info["audio_codec"] is not None
    assert info["sample_rate"] is not None
    assert info["channels"] in (1, 2)


# ============================================================================
# Audio Extraction Tests
# ============================================================================

def test_extract_audio_success(synthetic_valid_mp4: Path, tmp_path: Path):
    dest_wav = tmp_path / "extracted_speech.wav"
    out_path, meta = extract_audio(
        video_path=synthetic_valid_mp4,
        output_audio_path=dest_wav,
        sample_rate=16000,
        channels=1,
    )

    # 1. Output file verification
    assert out_path.exists()
    assert out_path == dest_wav.resolve()
    assert out_path.stat().st_size > 0

    # 2. Verify with standard wave module
    with wave.open(str(out_path), "rb") as wf:
        assert wf.getnchannels() == 1  # mono
        assert wf.getframerate() == 16000  # 16 kHz
        assert wf.getsampwidth() == 2  # 16-bit PCM (pcm_s16le)
        frames = wf.getnframes()
        assert frames > 14000  # ~1 second at 16 kHz

    # 3. Verify returned metadata structure
    assert meta["format"] == "wav"
    assert meta["codec"] == "pcm_s16le"
    assert meta["sample_rate"] == 16000
    assert meta["channels"] == 1
    assert meta["sample_width_bytes"] == 2
    assert 0.9 <= meta["duration_sec"] <= 1.2
    assert len(meta["sha256"]) == 64
    assert meta["source_video_path"] == str(synthetic_valid_mp4.resolve())

    # 4. Source video remained intact and untouched
    assert synthetic_valid_mp4.exists()
    assert synthetic_valid_mp4.stat().st_size > 0


def test_extract_audio_default_output_path(synthetic_valid_mp4: Path):
    # Output path not specified -> creates .wav alongside source
    out_path, meta = extract_audio(video_path=synthetic_valid_mp4)
    expected_wav = synthetic_valid_mp4.with_suffix(".wav")

    try:
        assert out_path == expected_wav
        assert out_path.exists()
        assert meta["sample_rate"] == DEFAULT_AUDIO_SAMPLE_RATE
        assert meta["channels"] == DEFAULT_AUDIO_CHANNELS
    finally:
        expected_wav.unlink(missing_ok=True)


def test_extract_audio_cannot_overwrite_source(synthetic_valid_mp4: Path):
    with pytest.raises(ValueError, match="cannot be identical to the source video path"):
        extract_audio(synthetic_valid_mp4, output_audio_path=synthetic_valid_mp4)


def test_extract_audio_ffmpeg_error_handling(synthetic_valid_mp4: Path, tmp_path: Path):
    dest_wav = tmp_path / "failed.wav"
    failing_proc = subprocess.CompletedProcess(
        args=["ffmpeg"],
        returncode=1,
        stdout="",
        stderr="Simulated FFmpeg stream decoding failure"
    )

    with patch("subprocess.run", return_value=failing_proc):
        with pytest.raises(RuntimeError, match="FFmpeg audio extraction failed"):
            extract_audio(synthetic_valid_mp4, output_audio_path=dest_wav)

