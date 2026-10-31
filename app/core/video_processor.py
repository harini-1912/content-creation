"""Video processing and audio extraction module for IncuBrix Content Engine.

Provides real long-form video validation, container and stream inspection,
mono 16 kHz WAV audio extraction via FFmpeg, and secure job storage isolation.
Never overwrites source videos and protects against path traversal.
"""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, Optional, Tuple, Union
import uuid
import wave

from app.core.media_renderer import compute_file_sha256, get_ffmpeg_executable

logger = logging.getLogger(__name__)

# Default limits
DEFAULT_MAX_VIDEO_SIZE_MB: float = 100.0
DEFAULT_MAX_VIDEO_DURATION_SEC: float = 600.0  # 10 minutes
DEFAULT_AUDIO_SAMPLE_RATE: int = 16000
DEFAULT_AUDIO_CHANNELS: int = 1
DEFAULT_VIDEO_JOBS_DIR: Path = Path("output/video_jobs")


# ============================================================================
# Safe Job Storage Utilities
# ============================================================================

def generate_job_id(prefix: str = "job") -> str:
    """Generates a URL-safe, filesystem-safe unique job identifier.

    Format: {prefix}_{YYYYMMDD_HHMMSS}_{uuid[:8]}
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:8]
    return f"{prefix}_{ts}_{uid}"


def validate_job_id(job_id: str) -> str:
    """Validates that a job ID contains only safe alphanumeric, underscore, or hyphen characters.

    Rejects path traversal attempts, directory separators, null bytes, and non-printable characters.
    """
    if not job_id or not isinstance(job_id, str):
        raise ValueError("Job ID must be a non-empty string.")

    job_id_clean = job_id.strip()
    if not re.match(r"^[a-zA-Z0-9_\-]+$", job_id_clean):
        raise ValueError(
            f"Invalid job ID '{job_id}'. Job IDs may only contain alphanumeric characters, underscores, and hyphens."
        )

    if ".." in job_id_clean:
        raise ValueError(f"Path traversal sequence detected in job ID: '{job_id}'.")

    return job_id_clean


def create_video_job_dir(
    job_id: Optional[str] = None,
    base_dir: Union[str, Path] = DEFAULT_VIDEO_JOBS_DIR,
    prefix: str = "job",
) -> Tuple[str, Path]:
    """Creates an isolated directory for a video processing job.

    Enforces path traversal protection and returns the validated job_id and resolved Path.
    """
    clean_id = validate_job_id(job_id) if job_id else generate_job_id(prefix=prefix)
    base_path = Path(base_dir).resolve()
    target_path = (base_path / clean_id).resolve()

    # Prevent path traversal outside base directory
    try:
        target_path.relative_to(base_path)
    except ValueError:
        raise ValueError(
            f"Path traversal detected: target directory '{target_path}' is outside base '{base_path}'."
        )

    target_path.mkdir(parents=True, exist_ok=True)
    logger.info("Created isolated video job directory at '%s'", target_path)
    return clean_id, target_path


def sanitize_filename(filename: str, fallback: str = "uploaded_video.mp4") -> str:
    """Sanitizes an uploaded filename to prevent directory traversal and illegal characters."""
    name = Path(filename).name.strip()
    stem = Path(name).stem
    suffix = Path(name).suffix.lower()
    
    # Strip dangerous characters and condense underscores
    safe_stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", stem)
    safe_stem = re.sub(r"_+", "_", safe_stem).strip("_")
    
    if not suffix or suffix != ".mp4":
        suffix = ".mp4"
        
    if not safe_stem:
        return fallback
    return f"{safe_stem}{suffix}"


def save_uploaded_video(
    source: Union[str, Path, bytes],
    original_filename: str,
    job_dir: Union[str, Path]
) -> Path:
    """Safely saves an uploaded video file or byte payload to the dedicated job directory.

    Guarantees destination stays within job_dir and ensures .mp4 extension.
    Never logs raw video bytes.
    """
    job_path = Path(job_dir).resolve()
    if not job_path.is_dir():
        job_path.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(original_filename)
    if not safe_name.lower().endswith(".mp4"):
        safe_name = f"{Path(safe_name).stem}.mp4"

    dest_file = (job_path / safe_name).resolve()

    # Path traversal verification
    try:
        dest_file.relative_to(job_path)
    except ValueError:
        raise ValueError(f"Path traversal detected in upload filename: '{original_filename}'.")

    if isinstance(source, bytes):
        dest_file.write_bytes(source)
    else:
        src_path = Path(source).resolve()
        if not src_path.is_file():
            raise FileNotFoundError(f"Source video file not found: '{src_path}'.")
        if src_path != dest_file:
            shutil.copy2(src_path, dest_file)

    logger.info("Saved uploaded video to '%s' (bytes=%d)", dest_file, dest_file.stat().st_size)
    return dest_file


# ============================================================================
# Video Inspection & Validation
# ============================================================================

def inspect_video(video_path: Union[str, Path]) -> Dict[str, Any]:
    """Inspects a video file using FFmpeg and extracts stream metadata and file digest.

    Returns:
        Dict[str, Any] containing duration, video stream presence, resolution,
        codecs, audio stream presence, sample rate, channels, file size, and SHA-256.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is empty, not a file, or corrupted/unparseable media.
        RuntimeError: If FFmpeg is not found.
    """
    path = Path(video_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: '{path}'")
    if not path.is_file():
        raise ValueError(f"Provided path is not a file: '{path}'")

    file_size_bytes = path.stat().st_size
    if file_size_bytes == 0:
        raise ValueError(f"Video file is empty (0 bytes): '{path.name}'")

    file_size_mb = round(file_size_bytes / (1024 * 1024), 3)
    file_sha256 = compute_file_sha256(path)

    ffmpeg_exe = get_ffmpeg_executable()
    if not ffmpeg_exe:
        raise RuntimeError(
            "FFmpeg executable not found. Ensure FFmpeg is installed or imageio-ffmpeg is available."
        )

    # Run FFmpeg inspection
    cmd = [ffmpeg_exe, "-hide_banner", "-i", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")

    stderr_text = proc.stderr or ""

    # Check for complete failure to parse container
    corrupt_markers = [
        "Invalid data found when processing input",
        "does not contain any stream",
        "unknown format",
        "Invalid argument"
    ]
    is_corrupt = any(marker in stderr_text for marker in corrupt_markers)

    # Parse Duration: hh:mm:ss.ff
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr_text)
    if dur_match:
        h = int(dur_match.group(1))
        m = int(dur_match.group(2))
        s = float(dur_match.group(3))
        duration_sec = round(h * 3600 + m * 60 + s, 3)
    else:
        duration_sec = 0.0

    # Parse Video Stream
    v_match = re.search(r"Stream\s+#\d+:\d+.*?: Video:\s*([a-zA-Z0-9_\-]+)", stderr_text)
    has_video_stream = bool(v_match)
    video_codec = v_match.group(1) if v_match else None

    # Parse Dimensions
    dim_match = re.search(r"Video:.*?(?:,\s*|\s+)(\d{2,5})x(\d{2,5})", stderr_text)
    width = int(dim_match.group(1)) if dim_match else None
    height = int(dim_match.group(2)) if dim_match else None

    # Parse FPS
    fps_match = re.search(r"Video:.*?,\s*(\d+(?:\.\d+)?)\s*fps", stderr_text)
    fps = float(fps_match.group(1)) if fps_match else None

    # Parse Audio Stream
    a_match = re.search(r"Stream\s+#\d+:\d+.*?: Audio:\s*([a-zA-Z0-9_\-]+)", stderr_text)
    has_audio_stream = bool(a_match)
    audio_codec = a_match.group(1) if a_match else None

    # Parse Sample Rate
    sr_match = re.search(r"Audio:.*?,\s*(\d+)\s*Hz", stderr_text)
    sample_rate = int(sr_match.group(1)) if sr_match else None

    # Parse Channels
    ch_match = re.search(r"Audio:.*?,\s*(\d+)\s*channels", stderr_text)
    if ch_match:
        channels = int(ch_match.group(1))
    elif re.search(r"Audio:.*?,\s*mono\b", stderr_text):
        channels = 1
    elif re.search(r"Audio:.*?,\s*stereo\b", stderr_text):
        channels = 2
    elif re.search(r"Audio:.*?,\s*5\.1", stderr_text):
        channels = 6
    elif re.search(r"Audio:.*?,\s*7\.1", stderr_text):
        channels = 8
    else:
        channels = None

    # If both streams are missing or corrupt marker is present with no streams
    if (not has_video_stream and not has_audio_stream) or (is_corrupt and not dur_match):
        raise ValueError(
            f"File '{path.name}' is corrupt or not a recognized media file: no valid media streams detected."
        )

    return {
        "video_path": str(path),
        "filename": path.name,
        "format": path.suffix.lstrip(".").lower(),
        "file_size_bytes": file_size_bytes,
        "file_size_mb": file_size_mb,
        "sha256": file_sha256,
        "duration_sec": duration_sec,
        "has_video_stream": has_video_stream,
        "video_codec": video_codec,
        "width": width,
        "height": height,
        "fps": fps,
        "has_audio_stream": has_audio_stream,
        "audio_codec": audio_codec,
        "sample_rate": sample_rate,
        "channels": channels,
    }


def validate_video(
    video_path: Union[str, Path],
    max_size_mb: float = DEFAULT_MAX_VIDEO_SIZE_MB,
    max_duration_sec: float = DEFAULT_MAX_VIDEO_DURATION_SEC,
) -> Path:
    """Validates an uploaded MP4 video according to strict engine constraints.

    Enforces:
    - File exists and is a regular file.
    - Suffix must be .mp4 (case-insensitive).
    - Non-empty file (size > 0 bytes).
    - File size <= max_size_mb (default 100 MB).
    - Contains both an active video stream and audio stream.
    - Duration > 0 and <= max_duration_sec (default 600s / 10 minutes).

    Returns:
        Resolved Path to the validated video file.

    Raises:
        FileNotFoundError: If the video file does not exist.
        ValueError: If any validation rule is violated.
    """
    path = Path(video_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: '{video_path}'")
    if not path.is_file():
        raise ValueError(f"Provided path is not a file: '{video_path}'")

    if path.suffix.lower() != ".mp4":
        raise ValueError(
            f"Unsupported file format '{path.suffix}'. Only .mp4 video files are accepted."
        )

    file_size_bytes = path.stat().st_size
    if file_size_bytes == 0:
        raise ValueError(f"Video file is empty (0 bytes): '{path.name}'")

    file_size_mb = file_size_bytes / (1024 * 1024)
    if file_size_mb > max_size_mb:
        raise ValueError(
            f"File size ({file_size_mb:.2f} MB) exceeds maximum allowed limit ({max_size_mb:.1f} MB)."
        )

    # Deep stream inspection
    info = inspect_video(path)

    if not info["has_video_stream"]:
        raise ValueError(
            f"Video validation failed: '{path.name}' does not contain an active video stream."
        )

    if not info["has_audio_stream"]:
        raise ValueError(
            f"Video validation failed: '{path.name}' does not contain an active audio stream."
        )

    dur = info.get("duration_sec", 0.0)
    if dur <= 0:
        raise ValueError(
            f"Video validation failed: '{path.name}' reported invalid or unmeasurable duration ({dur}s)."
        )

    if dur > max_duration_sec:
        raise ValueError(
            f"Video duration ({dur:.2f}s) exceeds maximum allowed limit "
            f"({max_duration_sec:.1f}s / {max_duration_sec / 60:.1f} minutes)."
        )

    logger.info(
        "Validated video '%s': duration=%.2fs, size=%.2fMB, video=%s (%sx%s), audio=%s (%dHz, ch=%s)",
        path.name,
        dur,
        file_size_mb,
        info.get("video_codec"),
        info.get("width"),
        info.get("height"),
        info.get("audio_codec"),
        info.get("sample_rate") or 0,
        info.get("channels") or 0,
    )
    return path


# ============================================================================
# Audio Extraction
# ============================================================================

def extract_audio(
    video_path: Union[str, Path],
    output_audio_path: Optional[Union[str, Path]] = None,
    sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE,
    channels: int = DEFAULT_AUDIO_CHANNELS,
) -> Tuple[Path, Dict[str, Any]]:
    """Extracts audio track from an MP4 video as a mono 16 kHz WAV file using FFmpeg.

    Guarantees:
    - Never overwrites the original video file.
    - Produces uncompressed PCM 16-bit mono 16 kHz WAV suitable for speech transcription.
    - Returns the verified output path and comprehensive audio metadata.

    Args:
        video_path: Path to the input MP4 video.
        output_audio_path: Optional destination path for the extracted .wav.
            If None, generated alongside the video with a .wav extension.
        sample_rate: Target audio sample rate in Hz (default: 16000).
        channels: Target channel count (1 for mono, default: 1).

    Returns:
        Tuple[Path, Dict[str, Any]]: Resolved Path to WAV and dictionary of audio metadata.

    Raises:
        FileNotFoundError: If input video does not exist.
        ValueError: If input/output paths conflict or invalid arguments.
        RuntimeError: If FFmpeg fails or produced audio is corrupt/empty.
    """
    v_path = Path(video_path).resolve()
    if not v_path.exists():
        raise FileNotFoundError(f"Input video file not found: '{video_path}'")
    if not v_path.is_file():
        raise ValueError(f"Input path is not a file: '{video_path}'")

    if output_audio_path is None:
        out_path = v_path.with_suffix(".wav").resolve()
    else:
        out_path = Path(output_audio_path).resolve()

    # Safety: Never overwrite the source video file
    if out_path == v_path:
        raise ValueError(
            "Output audio destination path cannot be identical to the source video path. "
            "Never overwrite the source video file."
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_exe = get_ffmpeg_executable()
    if not ffmpeg_exe:
        raise RuntimeError(
            "FFmpeg executable not found. Cannot extract audio track."
        )

    # Build FFmpeg command for 16 kHz mono PCM WAV
    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", str(v_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", str(channels),
        str(out_path)
    ]

    logger.info("Executing audio extraction: %s -> %s (ar=%d, ac=%d)", v_path.name, out_path.name, sample_rate, channels)
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")

    if proc.returncode != 0:
        err_excerpt = proc.stderr.strip()[:400] if proc.stderr else "Unknown error"
        raise RuntimeError(
            f"FFmpeg audio extraction failed (exit code {proc.returncode}): {err_excerpt}"
        )

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(
            f"FFmpeg audio extraction produced empty or missing file at '{out_path}'."
        )

    # Verify and inspect extracted WAV using standard wave module
    try:
        with wave.open(str(out_path), "rb") as wf:
            wav_channels = wf.getnchannels()
            wav_rate = wf.getframerate()
            n_frames = wf.getnframes()
            sampwidth = wf.getsampwidth()
            duration_sec = round(n_frames / float(wav_rate), 3) if wav_rate > 0 else 0.0
    except Exception as exc:
        raise RuntimeError(
            f"Extracted audio file at '{out_path}' could not be parsed as a valid WAV file: {exc}"
        ) from exc

    file_size_bytes = out_path.stat().st_size
    file_sha256 = compute_file_sha256(out_path)

    metadata: Dict[str, Any] = {
        "audio_path": str(out_path),
        "filename": out_path.name,
        "format": "wav",
        "codec": "pcm_s16le",
        "sample_rate": wav_rate,
        "channels": wav_channels,
        "sample_width_bytes": sampwidth,
        "duration_sec": duration_sec,
        "file_size_bytes": file_size_bytes,
        "file_size_kb": round(file_size_bytes / 1024, 2),
        "sha256": file_sha256,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "source_video_path": str(v_path),
        "source_video_sha256": compute_file_sha256(v_path),
    }

    logger.info(
        "Successfully extracted audio to '%s' (duration=%.2fs, rate=%dHz, channels=%d, sha256=%s...)",
        out_path.name,
        duration_sec,
        wav_rate,
        wav_channels,
        file_sha256[:12],
    )

    return out_path, metadata
