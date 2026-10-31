"""Unit tests for media preview renderer module (video and carousel)."""

import json
from pathlib import Path
import pytest
from PIL import Image

from app.core.media_renderer import (
    get_ffmpeg_executable,
    get_ffprobe_executable,
    probe_media_duration,
    probe_media_dimensions,
    get_system_font,
    wrap_text,
    render_carousel_preview,
    render_video_preview,
    CAROUSEL_SIZE,
    VIDEO_WIDTH,
    VIDEO_HEIGHT
)
from app.core.generator import generate_draft_candidates
from app.models.asset import SourceSegment, PlatformEnum, AssetFormatEnum


@pytest.fixture
def synthetic_drafts():
    seg = SourceSegment(
        segment_id="seg_01_a1b2c3d4",
        source_document="workflow_guide.md",
        segment_index=1,
        source_location="Paragraph 1, Line 1",
        heading="Repurposing Systems",
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
    return generate_draft_candidates([seg])


def test_get_ffmpeg_executable():
    exe = get_ffmpeg_executable()
    # imageio-ffmpeg is installed in this environment
    assert exe is not None
    assert "ffmpeg" in exe.lower()


def test_get_system_font():
    font = get_system_font(32)
    assert font is not None


def test_wrap_text():
    text = "Creating multi-channel content without a structured system often causes severe creative fatigue."
    wrapped = wrap_text(text, max_chars_per_line=30)
    lines = wrapped.split("\n")
    assert len(lines) >= 3
    for line in lines:
        assert len(line) <= 35


def test_render_carousel_preview(synthetic_drafts, tmp_path: Path):
    ig_draft = next(d for d in synthetic_drafts if d.platform == PlatformEnum.INSTAGRAM)
    out_dir = tmp_path / "renders" / ig_draft.draft_id

    slide_paths, sheet_path, manifest = render_carousel_preview(ig_draft, out_dir)

    # 1. Slide count and existence
    assert len(slide_paths) == 5
    for p in slide_paths:
        assert p.exists()
        # Verify 1080x1080 dimensions
        with Image.open(p) as img:
            assert img.size == (CAROUSEL_SIZE, CAROUSEL_SIZE)

    # 2. Contact sheet
    assert sheet_path.exists()
    with Image.open(sheet_path) as sheet_img:
        assert sheet_img.size == (1800, 1350)

    # 3. Manifest integrity
    manifest_file = out_dir / "render_manifest.json"
    assert manifest_file.exists()
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["asset_id"] == ig_draft.draft_id
    assert manifest_data["platform"] == "instagram"
    assert manifest_data["content_format"] == "carousel"
    assert manifest_data["dimensions"] == f"{CAROUSEL_SIZE}x{CAROUSEL_SIZE}"
    assert manifest_data["slide_count"] == 5
    assert manifest_data["source_segment_id"] == ig_draft.source_segment_id
    assert manifest_data["review_status"] == "DRAFT_PREVIEW_REQUIRES_HUMAN_REVIEW"


def test_render_carousel_preview_missing_outlines_raises_error(synthetic_drafts, tmp_path: Path):
    ig_draft = next(d for d in synthetic_drafts if d.platform == PlatformEnum.INSTAGRAM)
    # Clone draft without carousel slide outlines
    empty_draft = ig_draft.model_copy(update={"carousel_slide_outlines": []})

    with pytest.raises(ValueError, match="contains no carousel slide outlines"):
        render_carousel_preview(empty_draft, tmp_path / "renders" / "empty")


def test_render_video_preview(synthetic_drafts, tmp_path: Path):
    shorts_draft = next(d for d in synthetic_drafts if d.platform == PlatformEnum.YOUTUBE_SHORTS)
    out_dir = tmp_path / "renders" / shorts_draft.draft_id

    mp4_path, manifest = render_video_preview(shorts_draft, out_dir)

    # 1. Output video existence and file size
    assert mp4_path.exists()
    assert mp4_path.stat().st_size > 0

    # 2. Manifest integrity
    manifest_file = out_dir / "render_manifest.json"
    assert manifest_file.exists()
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["asset_id"] == shorts_draft.draft_id
    assert manifest_data["platform"] == "youtube_shorts"
    assert manifest_data["content_format"] == "short_video"
    assert manifest_data["dimensions"] == f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}"
    assert manifest_data["duration_seconds"] > 0
    assert manifest_data["is_silent"] is True
    assert "Silent preview" in manifest_data["audio_notice"]
    assert manifest_data["source_segment_id"] == shorts_draft.source_segment_id
    assert manifest_data["review_status"] == "DRAFT_PREVIEW_REQUIRES_HUMAN_REVIEW"


def test_render_video_preview_missing_ffmpeg_raises_runtime_error(synthetic_drafts, monkeypatch, tmp_path: Path):
    shorts_draft = next(d for d in synthetic_drafts if d.platform == PlatformEnum.YOUTUBE_SHORTS)
    # Simulate missing FFmpeg executable
    monkeypatch.setattr("app.core.media_renderer.get_ffmpeg_executable", lambda: None)

    with pytest.raises(RuntimeError, match="FFmpeg executable not found"):
        render_video_preview(shorts_draft, tmp_path / "renders" / "test_no_ffmpeg")


def test_video_manifest_reports_actual_duration_within_tolerance(synthetic_drafts, tmp_path: Path):
    """Regression test: manifest duration must reflect actual MP4 duration within 0.1s tolerance."""
    shorts_draft = next(d for d in synthetic_drafts if d.platform == PlatformEnum.YOUTUBE_SHORTS)
    out_dir = tmp_path / "renders" / shorts_draft.draft_id

    mp4_path, manifest = render_video_preview(shorts_draft, out_dir)

    # 1. Probe actual duration of rendered MP4
    probed_duration = probe_media_duration(mp4_path)

    # 2. Manifest duration_seconds must match the actual probed duration within 0.1s tolerance
    manifest_duration = manifest["duration_seconds"]
    assert abs(manifest_duration - probed_duration) <= 0.1

    # 3. Manifest must distinguish estimated vs actual rendered duration
    assert "estimated_duration_seconds" in manifest
    assert "duration_probe_method" in manifest
    # Actual duration must be a positive float
    assert manifest_duration > 0.0


def test_probe_media_duration_missing_file():
    with pytest.raises(FileNotFoundError, match="Media file not found"):
        probe_media_duration("non_existent_video_path.mp4")


def test_probe_media_duration_missing_tools_raises_runtime_error(tmp_path: Path, monkeypatch):
    dummy_file = tmp_path / "test.mp4"
    dummy_file.write_bytes(b"dummy")

    # Simulate both probe tools missing
    monkeypatch.setattr("app.core.media_renderer.get_ffprobe_executable", lambda: None)
    monkeypatch.setattr("app.core.media_renderer.get_ffmpeg_executable", lambda: None)

    with pytest.raises(RuntimeError, match="Neither ffprobe nor ffmpeg inspection was able to determine"):
        probe_media_duration(dummy_file)


def test_probe_media_dimensions_real_video(synthetic_drafts, tmp_path: Path):
    """Probes actual (1080, 1920) dimensions from rendered MP4 container stream."""
    shorts_draft = next(d for d in synthetic_drafts if d.platform == PlatformEnum.YOUTUBE_SHORTS)
    out_dir = tmp_path / "renders" / shorts_draft.draft_id
    mp4_path, _ = render_video_preview(shorts_draft, out_dir)

    width, height = probe_media_dimensions(mp4_path)
    assert (width, height) == (1080, 1920)


def test_probe_media_dimensions_missing_file():
    with pytest.raises(FileNotFoundError, match="Media file not found for dimension probing"):
        probe_media_dimensions("non_existent_video_path.mp4")


def test_probe_media_dimensions_missing_tools_raises_runtime_error(tmp_path: Path, monkeypatch):
    dummy_file = tmp_path / "test.mp4"
    dummy_file.write_bytes(b"dummy")

    # Simulate both probe tools missing
    monkeypatch.setattr("app.core.media_renderer.get_ffprobe_executable", lambda: None)
    monkeypatch.setattr("app.core.media_renderer.get_ffmpeg_executable", lambda: None)

    with pytest.raises(RuntimeError, match="Neither ffprobe nor ffmpeg inspection was able to determine video stream dimensions"):
        probe_media_dimensions(dummy_file)


