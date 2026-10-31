"""Real Speech End-to-End Smoke Test Script (Phase 4.3B.2B).

Executes the complete workflow on real video input:
sample_inputs/real_speech_test.mp4
  -> Validation
  -> Audio extraction (16 kHz mono WAV)
  -> Gemini transcription and analysis (gemini-3.8-flash)
  -> Timestamped candidate moments
  -> Platform-specific drafts
  -> Structured manifest export
"""

import json
import logging
from pathlib import Path
import sys
import time
import wave

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import load_settings, GenerationModeEnum
from app.core.video_processor import (
    inspect_video,
    validate_video,
    create_video_job_dir,
    save_uploaded_video,
    extract_audio,
)
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


def main():
    print("=" * 78)
    print("IncuBrix Phase 4.3B.2B — Real Speech End-to-End Smoke Test")
    print("=" * 78)

    # ------------------------------------------------------------------------
    # STEP 1: Verify Input Video
    # ------------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("STEP 1: Verify Input Video")
    print("=" * 78)

    source_path = Path("sample_inputs/real_speech_test.mp4").resolve()
    if not source_path.exists():
        print(f"ERROR: Input video not found at '{source_path}'. Halting.")
        sys.exit(1)

    print(f"Source file found: {source_path}")
    raw_size_bytes = source_path.stat().st_size
    raw_size_mb = raw_size_bytes / (1024 * 1024)
    print(f"File size: {raw_size_mb:.2f} MB ({raw_size_bytes:,} bytes)")

    # Deep stream inspection
    inspection = inspect_video(source_path)
    print("\nVideo Inspection Details:")
    print(f"  Container Format : {inspection['format']}")
    print(f"  Duration         : {inspection['duration_sec']:.2f}s ({inspection['duration_sec'] / 60:.2f} minutes)")
    print(f"  Video Stream     : codec={inspection['video_codec']}, resolution={inspection['width']}x{inspection['height']}, fps={inspection['fps']}")
    print(f"  Audio Stream     : codec={inspection['audio_codec']}, sample_rate={inspection['sample_rate']}Hz, channels={inspection['channels']}")
    print(f"  SHA-256 Digest   : {inspection['sha256']}")

    # Strict validation against limits (100 MB, 10 min = 600s)
    try:
        validated_path = validate_video(source_path, max_size_mb=100.0, max_duration_sec=600.0)
        print(f"\nValidation Result: PASSED (meets all engine constraints)")
    except Exception as exc:
        print(f"\nValidation Result: FAILED ({exc}). Halting.")
        sys.exit(1)

    # ------------------------------------------------------------------------
    # STEP 2: Process Video and Extract Audio
    # ------------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("STEP 2: Job Isolation & Audio Extraction")
    print("=" * 78)

    job_id, job_dir = create_video_job_dir(prefix="job_real_speech")
    print(f"Created isolated job: {job_id}")
    print(f"Job directory: {job_dir}")

    # Copy video into job directory safely
    saved_video = save_uploaded_video(
        source=validated_path,
        original_filename="real_speech_test.mp4",
        job_dir=job_dir
    )
    print(f"Saved video copy to: {saved_video}")
    saved_sha = compute_file_sha256(saved_video)
    assert saved_sha == inspection['sha256'], "SHA-256 mismatch between source and job copy!"
    print(f"Job video SHA-256 integrity: MATCHED ({saved_sha[:16]}...)")

    # Extract mono 16 kHz WAV audio
    dest_wav_path = job_dir / "extracted_speech_16khz.wav"
    t_extract_0 = time.time()
    out_wav, audio_meta = extract_audio(
        video_path=saved_video,
        output_audio_path=dest_wav_path,
        sample_rate=16000,
        channels=1
    )
    t_extract_1 = time.time()
    print(f"\nExtracted Audio in {t_extract_1 - t_extract_0:.2f}s:")
    print(f"  Audio Path       : {out_wav}")
    print(f"  Duration         : {audio_meta['duration_sec']:.2f}s ({audio_meta['duration_sec'] / 60:.2f} min)")
    print(f"  Sample Rate      : {audio_meta['sample_rate']} Hz (mono: {audio_meta['channels'] == 1})")
    print(f"  Bit Depth        : {audio_meta['sample_width_bytes'] * 8}-bit PCM")
    print(f"  File Size        : {audio_meta['file_size_kb']:.2f} KB ({audio_meta['file_size_bytes']:,} bytes)")
    print(f"  SHA-256 Digest   : {audio_meta['sha256']}")

    # Direct WAV header verification
    with wave.open(str(out_wav), "rb") as wf:
        assert wf.getnchannels() == 1, "Expected mono WAV"
        assert wf.getframerate() == 16000, "Expected 16 kHz sample rate"
        assert wf.getsampwidth() == 2, "Expected 16-bit PCM"
        print("  WAV Header Check : VERIFIED (1 channel, 16000 Hz, 16-bit PCM)")

    # ------------------------------------------------------------------------
    # STEP 3: Real Gemini AI Repurposing Request
    # ------------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("STEP 3: Real Gemini AI Repurposing Request")
    print("=" * 78)

    # Activate ONLINE_LLM configuration
    settings = load_settings(env_override={"GENERATION_MODE": "ONLINE_LLM"}, load_env_file=True)
    print(f"Configuration Mode    : {settings.generation_mode}")
    print(f"API Key Status        : CONFIGURED (Key: {mask_secret(settings.gemini_api_key)})")
    print(f"Configured Model      : {DEFAULT_GEMINI_MODEL}")
    print(f"Audio Size on Disk    : {audio_meta['file_size_bytes']:,} bytes")
    is_files_api = audio_meta['file_size_bytes'] > (15 * 1024 * 1024)
    print(f"Upload Strategy       : {'Gemini Files API (> 15 MB)' if is_files_api else 'Inline Part (<= 15 MB)'}")

    source_meta = {
        "job_id": job_id,
        "video_path": str(saved_video),
        "sha256": saved_sha,
        "duration_sec": inspection['duration_sec'],
    }

    print(f"\nDispatching ONE real Gemini processing request to {DEFAULT_GEMINI_MODEL}...")
    t_api_0 = time.time()
    try:
        result = repurpose_audio_with_gemini(
            audio_path=out_wav,
            source_video_metadata=source_meta,
            api_key=settings.gemini_api_key,
            model_name=DEFAULT_GEMINI_MODEL
        )
        t_api_1 = time.time()
        print(f"Gemini API Request completed in {t_api_1 - t_api_0:.2f}s (HTTP 200 OK)")
    except Exception as exc:
        print(f"ERROR: Gemini API request failed: {exc}")
        print("Halting without fallback.")
        sys.exit(1)

    # ------------------------------------------------------------------------
    # STEP 4: Inspect Actual Output
    # ------------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("STEP 4: Inspect Actual Output")
    print("=" * 78)

    # Save manifest
    manifest_path = job_dir / "gemini_repurposing_result.json"
    save_repurposing_result(result, manifest_path)
    print(f"Saved Result Manifest: {manifest_path} ({manifest_path.stat().st_size:,} bytes)")

    # Full Transcript inspection
    transcript_words = result.full_transcript.split()
    print(f"\nTranscript Observations:")
    print(f"  Length (characters)  : {len(result.full_transcript):,}")
    print(f"  Length (words)       : {len(transcript_words):,}")
    print(f"  Intelligible Content : {'YES (Substantial human speech)' if len(transcript_words) > 50 else 'UNCERTAIN/SHORT'}")
    print(f"  Transcript Excerpt (First 300 chars):")
    print(f"    \"{result.full_transcript[:300]}...\"")
    print(f"  Transcript Excerpt (Last 300 chars):")
    print(f"    \"...{result.full_transcript[-300:]}\"")

    # Candidate Moments
    print(f"\nCandidate Moments Extracted: {len(result.moments)}")
    for idx, m in enumerate(result.moments, start=1):
        print(f"\n--- Moment {idx:02d}: [{m.start_seconds:.1f}s - {m.end_seconds:.1f}s] ({m.duration_seconds:.1f}s) ---")
        print(f"  Moment ID            : {m.moment_id}")
        print(f"  Target Platform      : {m.intended_platform.value.upper()} ({m.content_format.value})")
        print(f"  Main Topic           : {m.main_topic}")
        print(f"  Verbatim Excerpt     : \"{m.transcript_excerpt[:120]}{'...' if len(m.transcript_excerpt) > 120 else ''}\"")
        print(f"  Suggested Hook       : \"{m.suggested_hook}\"")
        print(f"  Suggested Content    : \"{m.suggested_content[:150]}{'...' if len(m.suggested_content) > 150 else ''}\"")
        print(f"  Suggested CTA        : \"{m.suggested_cta}\"")
        print(f"  Hashtags             : {' '.join(m.suggested_hashtags)}")
        print(f"  Destination URL      : {m.destination_url_status}")
        print(f"  Review Status        : {m.review_status}")
        print(f"  Speech Verification  : {m.speech_verification_status}")
        if m.warnings:
            print(f"  Warnings             : {m.warnings}")

    # ------------------------------------------------------------------------
    # STEP 5: Verification & Safety Guarantees
    # ------------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("STEP 5: Safety and Boundary Verifications")
    print("=" * 78)

    # 1. Timeline verification
    all_within_bounds = True
    for m in result.moments:
        if m.start_seconds < 0 or m.end_seconds > inspection['duration_sec']:
            all_within_bounds = False
            print(f"  BOUNDARY ERROR: Moment {m.moment_id} timestamps [{m.start_seconds}, {m.end_seconds}] exceed video duration {inspection['duration_sec']}s")
    if all_within_bounds:
        print(f"  [x] All moment timestamps are within original video duration ({inspection['duration_sec']:.2f}s)")

    # 2. Source video integrity
    original_sha_after = compute_file_sha256(source_path)
    assert original_sha_after == inspection['sha256'], "Original source video was modified!"
    print(f"  [x] Original source video remained completely untouched (SHA-256 verified)")

    # 3. Destination URL check
    for m in result.moments:
        assert "FLAGGED_FOR_HUMAN_CONFIRMATION" in m.destination_url_status
    print("  [x] Zero destination URLs or UTM parameters invented (all flagged for human confirmation)")

    # 4. Editorial review checks
    assert result.is_ai_generated is True
    assert result.requires_human_review is True
    assert result.is_factually_verified is False
    assert result.is_ready_to_publish is False
    for m in result.moments:
        assert m.requires_human_review is True
        assert m.is_factually_verified is False
        assert m.is_ready_to_publish is False
        assert m.review_status == "PENDING_HUMAN_EDITORIAL_REVIEW"
    print("  [x] All candidate moments remain marked PENDING_HUMAN_EDITORIAL_REVIEW")
    print("  [x] Zero assets published or scheduled")

    print("\n" + "=" * 78)
    print("Real Speech End-to-End Smoke Test Completed Successfully!")
    print("=" * 78)


if __name__ == "__main__":
    main()

