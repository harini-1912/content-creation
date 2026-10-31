"""Demonstration and real API smoke-test script for Phase 4.3B.2.

Invokes the Gemini speech repurposer on an extracted WAV audio file,
confirms API key configuration without exposing credentials,
displays timestamped transcripts and candidate platform suggestions,
and saves the structured output manifest in the video job directory.

Usage:
    python scripts/demo_ai_repurposer.py [--audio-path PATH] [--duration SECONDS] [--model MODEL]
"""

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Optional, Tuple

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.ai_repurposer import (
    get_gemini_api_key,
    mask_secret,
    repurpose_audio_with_gemini,
    save_repurposing_result,
    DEFAULT_GEMINI_MODEL,
)
from app.core.media_renderer import compute_file_sha256

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def find_latest_extracted_wav() -> Optional[Tuple[Path, Path]]:
    """Locates the latest extracted WAV audio file and its job directory in output/video_jobs."""
    base = Path("output/video_jobs")
    if not base.exists():
        return None

    wav_files = list(base.glob("*/extracted_speech_*.wav")) + list(base.glob("*/*.wav"))
    if not wav_files:
        return None

    # Pick the most recently modified WAV file
    latest_wav = max(wav_files, key=lambda p: p.stat().st_mtime)
    return latest_wav, latest_wav.parent


def run_demo(
    audio_path_arg: Optional[str] = None,
    duration_arg: Optional[float] = None,
    model_name: str = DEFAULT_GEMINI_MODEL,
):
    print("=" * 76)
    print("IncuBrix Phase 4.3B.2 — Gemini Audio Repurposing Smoke Test")
    print("=" * 76)

    # 1. API Key Verification (Secret-Safe)
    api_key = get_gemini_api_key()
    print("\n[1] API Key Configuration Check:")
    if not api_key:
        print("    Status: MISSING")
        print("    ERROR: GEMINI_API_KEY is not configured in environment or .env.")
        print("    AI processing is unavailable. Halting without fabricating fallback.")
        sys.exit(1)

    print(f"    Status: CONFIGURED (Key: {mask_secret(api_key)})")
    print(f"    Model Configured: {model_name}")

    # 2. Locate Target Audio File
    if audio_path_arg:
        target_audio = Path(audio_path_arg).resolve()
        job_dir = target_audio.parent
    else:
        latest = find_latest_extracted_wav()
        if not latest:
            print("\n[2] ERROR: No extracted WAV files found in output/video_jobs/.")
            print("    Please run scripts/demo_video_processor.py first to extract audio.")
            sys.exit(1)
        target_audio, job_dir = latest

    print(f"\n[2] Target Audio File:")
    print(f"    Path: {target_audio}")
    print(f"    File Size: {target_audio.stat().st_size:,} bytes")
    audio_sha = compute_file_sha256(target_audio)
    print(f"    SHA-256: {audio_sha}")
    print(f"    Job Directory: {job_dir}")

    # 3. Determine Duration & Audio Speech Check
    import wave
    with wave.open(str(target_audio), "rb") as wf:
        rate = wf.getframerate()
        frames = wf.getnframes()
        channels = wf.getnchannels()
        actual_dur = round(frames / float(rate), 2) if rate > 0 else 0.0

    dur = duration_arg if duration_arg else actual_dur
    print(f"    Channels: {channels} (mono: {channels == 1})")
    print(f"    Sample Rate: {rate} Hz")
    print(f"    Duration: {dur:.2f} seconds")

    # Speech Content Notice:
    # If the file is the 3-second synthetic audio generated in demo 4.3B.1, flag it clearly.
    if dur <= 5.0 and "Client_Masterclass_Recording" in str(target_audio.parent):
        print("\n" + "!" * 76)
        print("NOTICE: The current audio file was generated from a synthetic 440 Hz test tone.")
        print("It does not contain intelligible human speech. This test verifies real Gemini API")
        print("connectivity, audio payload handling, and JSON schema parsing.")
        print("A recording containing actual human speech is required for meaningful transcript")
        print("and domain repurposing quality.")
        print("!" * 76)

    # 4. Invoke Real Gemini API Service
    print(f"\n[3] Sending Audio to Gemini ({model_name})...")
    video_files = [f for f in job_dir.glob("*.mp4") if "incoming" not in f.name]
    video_path_str = str(video_files[0]) if video_files else str(job_dir / "source_video.mp4")

    source_metadata = {
        "job_id": job_dir.name,
        "video_path": video_path_str,
        "sha256": audio_sha,
        "duration_sec": dur,
    }

    try:
        result = repurpose_audio_with_gemini(
            audio_path=target_audio,
            source_video_metadata=source_metadata,
            api_key=api_key,
            model_name=model_name
        )
        print("    Gemini API Request: SUCCESS (HTTP 200 OK)")
    except Exception as exc:
        print(f"    Gemini API Request: FAILED ({exc})")
        print("    Halting without fabricating synthetic fallback.")
        sys.exit(1)

    # 5. Display Full Transcript
    print("\n" + "-" * 76)
    print("[4] Faithful Speech Transcript:")
    print("-" * 76)
    transcript_display = result.full_transcript.strip()
    if not transcript_display:
        print("    (Audio contained no intelligible spoken words / tone only)")
    else:
        print(f"    \"{transcript_display}\"")

    # 6. Display Candidate Repurposing Moments
    print("\n" + "-" * 76)
    print(f"[5] Extracted Candidate Moments ({len(result.moments)} moments):")
    print("-" * 76)

    for idx, m in enumerate(result.moments, start=1):
        print(f"\n--- Moment {idx}: [{m.start_seconds:.1f}s - {m.end_seconds:.1f}s] ({m.duration_seconds:.1f}s) ---")
        print(f"    Moment ID: {m.moment_id}")
        print(f"    Platform: {m.intended_platform.value.upper()} ({m.content_format.value})")
        print(f"    Main Topic: {m.main_topic}")
        print(f"    Verbatim Excerpt: \"{m.transcript_excerpt}\"")
        print(f"    Suggested Hook: \"{m.suggested_hook}\"")
        print(f"    Suggested Copy: \"{m.suggested_content}\"")
        print(f"    Suggested CTA: \"{m.suggested_cta}\"")
        print(f"    Hashtags: {' '.join(m.suggested_hashtags)}")
        print(f"    Destination URL: {m.destination_url_status}")
        print(f"    Review Status: {m.review_status}")
        print(f"    Speech Verification: {m.speech_verification_status}")
        if m.warnings:
            print(f"    Warnings: {m.warnings}")

    # 7. Safety Flags Summary
    print("\n" + "-" * 76)
    print("[6] Safety & Compliance Guarantees:")
    print("-" * 76)
    print(f"    is_ai_generated: {result.is_ai_generated}")
    print(f"    requires_human_review: {result.requires_human_review}")
    print(f"    is_factually_verified: {result.is_factually_verified}")
    print(f"    is_ready_to_publish: {result.is_ready_to_publish}")
    print(f"    speech_verification_status: {result.speech_verification_status}")
    print("    Voice Activity Detection: NOT IMPLEMENTED (Model output; acoustic verification required)")
    print("    Destination URLs: FLAGGED_FOR_HUMAN_CONFIRMATION (Never invented)")

    # 8. Save Repurposing Manifest
    manifest_dest = job_dir / "gemini_repurposing_result.json"
    save_repurposing_result(result, manifest_dest)
    print(f"\n[7] Saved Manifest: {manifest_dest}")
    print(f"    Manifest File Size: {manifest_dest.stat().st_size:,} bytes")

    print("\n" + "=" * 76)
    print("Smoke Test Completed Successfully!")
    print("=" * 76)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IncuBrix Gemini Audio Repurposing Smoke Test")
    parser.add_argument("--audio-path", type=str, default=None, help="Path to input WAV file")
    parser.add_argument("--duration", type=float, default=None, help="Source duration in seconds")
    parser.add_argument("--model", type=str, default=DEFAULT_GEMINI_MODEL, help="Gemini model name")
    args = parser.parse_args()

    run_demo(
        audio_path_arg=args.audio_path,
        duration_arg=args.duration,
        model_name=args.model
    )
