"""Demonstration script for Phase 4.3B.1: Video Upload and Audio Extraction.

Generates a synthetic demo MP4 video, validates it against engine constraints,
extracts 16 kHz mono WAV audio using FFmpeg, and displays complete metadata.
"""

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import wave

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.media_renderer import get_ffmpeg_executable, compute_file_sha256
from app.core.video_processor import (
    create_video_job_dir,
    save_uploaded_video,
    validate_video,
    inspect_video,
    extract_audio,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def run_demo():
    print("=" * 70)
    print("IncuBrix Phase 4.3B.1 — Video Upload & Audio Extraction Demonstration")
    print("=" * 70)

    # 1. Resolve FFmpeg
    ffmpeg_exe = get_ffmpeg_executable()
    print(f"\n[1] FFmpeg Resolver: {ffmpeg_exe}")
    if not ffmpeg_exe:
        raise RuntimeError("FFmpeg executable could not be resolved.")

    # 2. Create isolated job directory
    job_id, job_dir = create_video_job_dir(prefix="demo_job")
    print(f"\n[2] Job Created: {job_id}")
    print(f"    Job Directory: {job_dir}")

    # 3. Synthesize a 3-second test MP4 (640x360, 25fps, 440Hz audio tone)
    raw_synth_path = job_dir / "incoming_raw.mp4"
    cmd_synth = [
        ffmpeg_exe, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=640x360:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(raw_synth_path)
    ]
    subprocess.run(cmd_synth, check=True, capture_output=True)
    print(f"\n[3] Synthesized Source MP4: {raw_synth_path.name}")
    print(f"    Raw file size: {raw_synth_path.stat().st_size} bytes")

    # 4. Save through secure upload handler
    safe_video_path = save_uploaded_video(
        source=raw_synth_path,
        original_filename="Client Masterclass Recording.mp4",
        job_dir=job_dir
    )
    print(f"\n[4] Saved Upload Video: {safe_video_path.name}")
    print(f"    Stored path: {safe_video_path}")

    # 5. Deep stream inspection
    inspection = inspect_video(safe_video_path)
    print(f"\n[5] Video Inspection:")
    print(f"    Container Format: {inspection['format']}")
    print(f"    File Size: {inspection['file_size_mb']} MB ({inspection['file_size_bytes']} bytes)")
    print(f"    SHA-256: {inspection['sha256']}")
    print(f"    Duration: {inspection['duration_sec']} seconds")
    print(f"    Video Stream: codec={inspection['video_codec']}, resolution={inspection['width']}x{inspection['height']}, fps={inspection['fps']}")
    print(f"    Audio Stream: codec={inspection['audio_codec']}, sample_rate={inspection['sample_rate']}Hz, channels={inspection['channels']}")

    # 6. Strict validation against engine constraints
    validated_path = validate_video(safe_video_path, max_size_mb=100.0, max_duration_sec=600.0)
    print(f"\n[6] Validation: PASSED ({validated_path.name})")

    # 7. Extract mono 16 kHz WAV audio
    dest_wav_path = job_dir / "extracted_speech_16khz.wav"
    out_wav, audio_meta = extract_audio(
        video_path=validated_path,
        output_audio_path=dest_wav_path,
        sample_rate=16000,
        channels=1
    )
    print(f"\n[7] Audio Extraction: PASSED")
    print(f"    WAV Output: {out_wav}")
    print(f"    Duration: {audio_meta['duration_sec']} seconds")
    print(f"    Sample Rate: {audio_meta['sample_rate']} Hz")
    print(f"    Channels: {audio_meta['channels']} (mono)")
    print(f"    Bit Depth: {audio_meta['sample_width_bytes'] * 8}-bit PCM")
    print(f"    File Size: {audio_meta['file_size_kb']} KB ({audio_meta['file_size_bytes']} bytes)")
    print(f"    SHA-256: {audio_meta['sha256']}")

    # 8. Verify WAV headers directly
    with wave.open(str(out_wav), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16000
        assert wf.getsampwidth() == 2
        print(f"\n[8] Direct WAV Header Verification: OK (Mono, 16000 Hz, 16-bit PCM)")

    # 9. Verify original video integrity
    assert safe_video_path.exists()
    assert compute_file_sha256(safe_video_path) == inspection['sha256']
    print(f"\n[9] Source Video Integrity: VERIFIED (Original video completely untouched)")

    print("\n" + "=" * 70)
    print("Demonstration Completed Successfully!")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
