"""Unit tests for speech transcription and AI audio repurposing module.

All tests are 100% offline and use mocked API clients to guarantee
deterministic execution without making paid or external network calls.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import wave

import pytest

from app.core.ai_repurposer import (
    CandidateMoment,
    RepurposingResult,
    GeminiMomentItem,
    GeminiRepurposingPayload,
    get_gemini_api_key,
    mask_secret,
    normalize_platform,
    normalize_timestamp_value,
    validate_timestamps_and_moments,
    repurpose_audio_with_gemini,
    save_repurposing_result,
)
from app.models.asset import PlatformEnum, AssetFormatEnum


@pytest.fixture
def synthetic_wav_file(tmp_path: Path) -> Path:
    """Creates a small 3-second 16 kHz mono PCM WAV file offline using standard wave module."""
    wav_path = tmp_path / "test_audio_16k.wav"
    sample_rate = 16000
    duration_sec = 3
    num_frames = sample_rate * duration_sec

    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)  # mono
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        # 3 seconds of silence / zeroed PCM frames
        wf.writeframes(b"\x00\x00" * num_frames)

    return wav_path


@pytest.fixture
def sample_gemini_payload_dict():
    """Sample valid structured payload simulating a faithful Gemini transcription & repurpose."""
    return {
        "full_transcript": (
            "When creators switch between five different production tools, cognitive fatigue sets in quickly. "
            "A structured repurposing pipeline transforms one recording into multi-platform assets reliably. "
            "Every asset needs careful human editorial review before publication."
        ),
        "moments": [
            {
                "start_seconds": 0.0,
                "end_seconds": 8.5,
                "transcript_excerpt": "When creators switch between five different production tools, cognitive fatigue sets in quickly.",
                "main_topic": "Tooling fragmentation and cognitive fatigue",
                "intended_platform": "linkedin",
                "suggested_hook": "How disconnected production tools slow down creative engineering teams.",
                "suggested_content": "Context switching between disparate apps adds unnecessary friction to media operations.",
                "suggested_hashtags": ["#ContentOps", "#MediaEngineering"],
                "suggested_cta": "What tools currently bottleneck your team's publishing workflow?"
            },
            {
                "start_seconds": 8.5,
                "end_seconds": 18.0,
                "transcript_excerpt": "A structured repurposing pipeline transforms one recording into multi-platform assets reliably.",
                "main_topic": "Repurposing architecture",
                "intended_platform": "youtube_shorts",
                "suggested_hook": "Turn one core video into ten platform-ready drafts.",
                "suggested_content": "A repeatable workflow helps distribute content across channels without recording new footage every day.",
                "suggested_hashtags": ["#Shorts", "#ContentStrategy"],
                "suggested_cta": "Subscribe for more content systems breakdowns."
            },
            {
                "start_seconds": 18.0,
                "end_seconds": 26.0,
                "transcript_excerpt": "Every asset needs careful human editorial review before publication.",
                "main_topic": "Human in the loop quality control",
                "intended_platform": "twitter",
                "suggested_hook": "Why autonomous publishing without human review is a brand risk.",
                "suggested_content": "AI can identify soundbites, but editorial sign-off ensures factual accuracy and brand alignment.",
                "suggested_hashtags": ["#AIContent", "#EditorialStandards"],
                "suggested_cta": "Review your draft assets before pushing them live."
            }
        ]
    }


def make_mock_gemini_client(response_text: str):
    """Creates a mock genai.Client returning the specified response text."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


# ============================================================================
# API Key Management Tests
# ============================================================================

def test_get_gemini_api_key_explicit():
    assert get_gemini_api_key("custom_key_123") == "custom_key_123"


def test_get_gemini_api_key_empty():
    with patch.dict("os.environ", {}, clear=True), patch("dotenv.dotenv_values", return_value={}):
        assert get_gemini_api_key(None) is None
        assert get_gemini_api_key("") is None
        assert get_gemini_api_key("   ") is None


def test_mask_secret():
    assert mask_secret(None) == "[NOT_SET]"
    assert mask_secret("") == "[NOT_SET]"
    assert mask_secret("short") == "********[MASKED]"
    masked = mask_secret("AIzaSyD-1234567890abcdef-CONFIDENTIAL")
    assert "CONFIDENTIAL" not in masked
    assert masked.startswith("AIza")
    assert masked.endswith("[MASKED]")


# ============================================================================
# Input Validation Tests
# ============================================================================

def test_missing_api_key_raises_error(synthetic_wav_file: Path):
    with patch.dict("os.environ", {}, clear=True), patch("dotenv.dotenv_values", return_value={}):
        with pytest.raises(ValueError, match="GEMINI_API_KEY is not configured"):
            repurpose_audio_with_gemini(
                audio_path=synthetic_wav_file,
                source_video_metadata={"duration_sec": 30.0},
                api_key=None,
                client=None
            )


def test_invalid_wav_path_raises_error():
    with pytest.raises(FileNotFoundError, match="not found"):
        repurpose_audio_with_gemini(
            audio_path="non_existent_audio.wav",
            source_video_metadata={"duration_sec": 30.0},
            api_key="dummy_key"
        )


def test_invalid_audio_input_not_wav(tmp_path: Path):
    txt_file = tmp_path / "audio.txt"
    txt_file.write_text("not an audio file", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a .wav file"):
        repurpose_audio_with_gemini(
            audio_path=txt_file,
            source_video_metadata={"duration_sec": 30.0},
            api_key="dummy_key"
        )


def test_invalid_source_video_duration(synthetic_wav_file: Path):
    with pytest.raises(ValueError, match="Invalid source video duration"):
        repurpose_audio_with_gemini(
            audio_path=synthetic_wav_file,
            source_video_metadata={"duration_sec": 0.0},
            api_key="dummy_key"
        )


# ============================================================================
# API Error Handling and No-Fallback Enforcement
# ============================================================================

def test_gemini_api_failure_raises_runtime_error(synthetic_wav_file: Path):
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("ResourceExhausted: 429 Rate limit exceeded")

    with pytest.raises(RuntimeError, match="AI processing failed during Gemini API request"):
        repurpose_audio_with_gemini(
            audio_path=synthetic_wav_file,
            source_video_metadata={"duration_sec": 30.0},
            client=mock_client
        )


def test_no_fabricated_fallback_on_api_error(synthetic_wav_file: Path):
    """Ensures that when the API fails, the system strictly halts rather than returning synthetic drafts."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = ConnectionError("Connection refused by host")

    with pytest.raises(RuntimeError):
        repurpose_audio_with_gemini(
            audio_path=synthetic_wav_file,
            source_video_metadata={"duration_sec": 30.0},
            client=mock_client
        )


def test_malformed_gemini_response_empty_text(synthetic_wav_file: Path):
    mock_client = make_mock_gemini_client(response_text="")

    with pytest.raises(ValueError, match="received empty response text"):
        repurpose_audio_with_gemini(
            audio_path=synthetic_wav_file,
            source_video_metadata={"duration_sec": 30.0},
            client=mock_client
        )


def test_malformed_gemini_response_invalid_json(synthetic_wav_file: Path):
    mock_client = make_mock_gemini_client(response_text="{broken json: missing quotes")

    with pytest.raises(ValueError, match="failed to validate JSON schema"):
        repurpose_audio_with_gemini(
            audio_path=synthetic_wav_file,
            source_video_metadata={"duration_sec": 30.0},
            client=mock_client
        )


def test_malformed_gemini_response_empty_transcript(synthetic_wav_file: Path):
    payload = {"full_transcript": "   ", "moments": []}
    mock_client = make_mock_gemini_client(response_text=json.dumps(payload))

    with pytest.raises(ValueError, match="full_transcript is missing or empty"):
        repurpose_audio_with_gemini(
            audio_path=synthetic_wav_file,
            source_video_metadata={"duration_sec": 30.0},
            client=mock_client
        )


# ============================================================================
# Timestamp Handling & Boundary Tests
# ============================================================================

def test_invalid_timestamps_negative_start():
    item = GeminiMomentItem(
        start_seconds=-1.5,
        end_seconds=10.0,
        transcript_excerpt="Some spoken words",
        main_topic="Topic",
        intended_platform="linkedin",
        suggested_hook="Hook",
        suggested_content="Body copy",
        suggested_hashtags=[],
        suggested_cta="CTA"
    )
    with pytest.raises(ValueError, match="must be non-negative"):
        validate_timestamps_and_moments([item], source_duration_sec=30.0)


def test_invalid_timestamps_inverted_interval():
    item = GeminiMomentItem(
        start_seconds=15.0,
        end_seconds=10.0,
        transcript_excerpt="Some spoken words",
        main_topic="Topic",
        intended_platform="linkedin",
        suggested_hook="Hook",
        suggested_content="Body copy",
        suggested_hashtags=[],
        suggested_cta="CTA"
    )
    with pytest.raises(ValueError, match="must be strictly greater than start_seconds"):
        validate_timestamps_and_moments([item], source_duration_sec=30.0)


def test_timestamps_beyond_source_duration():
    item = GeminiMomentItem(
        start_seconds=10.0,
        end_seconds=45.0,
        transcript_excerpt="Some spoken words",
        main_topic="Topic",
        intended_platform="linkedin",
        suggested_hook="Hook",
        suggested_content="Body copy",
        suggested_hashtags=[],
        suggested_cta="CTA"
    )
    with pytest.raises(ValueError, match="exceeds source video duration"):
        validate_timestamps_and_moments([item], source_duration_sec=30.0)


def test_auto_convert_mmss_timestamps_within_bounds():
    """Verifies that MMSS-packed timestamps like 715.0 (7m15s) are converted to 435s on long videos."""
    item = GeminiMomentItem(
        start_seconds=630.0,  # 6m 30s -> 390.0s
        end_seconds=715.0,    # 7m 15s -> 435.0s
        transcript_excerpt="Speech from the seven minute mark",
        main_topic="Advanced Architecture",
        intended_platform="youtube_shorts",
        suggested_hook="Architecture tips",
        suggested_content="Summary of spoken segment",
        suggested_hashtags=["#Tech"],
        suggested_cta="Subscribe"
    )
    validated = validate_timestamps_and_moments([item], source_duration_sec=508.07)
    assert len(validated) == 1
    assert validated[0].start_seconds == 390.0
    assert validated[0].end_seconds == 435.0
    assert validated[0].duration_seconds == 45.0
    # Confirm timing note is recorded in warnings
    assert any("Auto-converted MMSS timestamp (715.00) to elapsed seconds (435.00s)" in w for w in validated[0].warnings)
    assert any("Auto-converted MMSS timestamp (630.00) to elapsed seconds (390.00s)" in w for w in validated[0].warnings)


def test_normalize_timestamp_value_helper():
    """Tests unit behavior of normalize_timestamp_value."""
    # Standard seconds within bounds -> no change
    val, warn = normalize_timestamp_value(45.0, 100.0)
    assert val == 45.0
    assert warn is None

    # MMSS converted when fits
    val, warn = normalize_timestamp_value(715.0, 508.07)
    assert val == 435.0
    assert "Auto-converted MMSS timestamp" in warn

    # Out of bounds and not MMSS -> leaves as-is for validation to reject
    val, warn = normalize_timestamp_value(45.0, 30.0)
    assert val == 45.0
    assert warn is None


def test_missing_transcript_excerpt():
    item = GeminiMomentItem(
        start_seconds=0.0,
        end_seconds=10.0,
        transcript_excerpt="   ",
        main_topic="Topic",
        intended_platform="linkedin",
        suggested_hook="Hook",
        suggested_content="Body copy",
        suggested_hashtags=[],
        suggested_cta="CTA"
    )
    with pytest.raises(ValueError, match="transcript excerpt cannot be empty"):
        validate_timestamps_and_moments([item], source_duration_sec=30.0)


def test_overlapping_moments_flagged_in_warnings():
    m1 = GeminiMomentItem(
        start_seconds=0.0,
        end_seconds=12.0,
        transcript_excerpt="First segment words",
        main_topic="Topic 1",
        intended_platform="linkedin",
        suggested_hook="Hook 1",
        suggested_content="Content 1",
        suggested_hashtags=[],
        suggested_cta="CTA 1"
    )
    m2 = GeminiMomentItem(
        start_seconds=8.0,  # Overlaps with m1 (0-12s)
        end_seconds=20.0,
        transcript_excerpt="Second segment words",
        main_topic="Topic 2",
        intended_platform="twitter",
        suggested_hook="Hook 2",
        suggested_content="Content 2",
        suggested_hashtags=[],
        suggested_cta="CTA 2"
    )
    validated = validate_timestamps_and_moments([m1, m2], source_duration_sec=30.0)
    assert len(validated) == 2
    # Second moment should carry a timeline overlap warning
    overlap_warns = [w for w in validated[1].warnings if "Timeline overlap" in w]
    assert len(overlap_warns) >= 1
    assert "starts at 8.0s before previous" in overlap_warns[0]


# ============================================================================
# Valid Structured Repurposing & Safety Constraints
# ============================================================================

def test_valid_structured_response_success(synthetic_wav_file: Path, sample_gemini_payload_dict):
    mock_client = make_mock_gemini_client(response_text=json.dumps(sample_gemini_payload_dict))

    result = repurpose_audio_with_gemini(
        audio_path=synthetic_wav_file,
        source_video_metadata={
            "duration_sec": 30.0,
            "video_path": "source/recording.mp4",
            "sha256": "abc123sha",
            "job_id": "job_demo_001"
        },
        client=mock_client
    )

    # 1. Result Structure & Traceability
    assert isinstance(result, RepurposingResult)
    assert result.job_id == "job_demo_001"
    assert result.source_video_path == "source/recording.mp4"
    assert result.source_duration_seconds == 30.0
    assert "When creators switch between five different production tools" in result.full_transcript
    assert len(result.moments) == 3

    # 2. Separation of Transcript Text and Generated Suggestions
    m1 = result.moments[0]
    assert m1.start_seconds == 0.0
    assert m1.end_seconds == 8.5
    assert m1.duration_seconds == 8.5
    assert m1.intended_platform == PlatformEnum.LINKEDIN
    assert m1.content_format == AssetFormatEnum.TEXT_POST
    # Transcript text is separate from generated creative suggestions
    assert m1.transcript_excerpt == "When creators switch between five different production tools, cognitive fatigue sets in quickly."
    assert m1.suggested_hook == "How disconnected production tools slow down creative engineering teams."
    assert m1.suggested_content == "Context switching between disparate apps adds unnecessary friction to media operations."
    assert m1.suggested_cta == "What tools currently bottleneck your team's publishing workflow?"
    assert "#ContentOps" in m1.suggested_hashtags

    # 3. Explicit Safety & Human Review Flags
    assert m1.is_source_attributed is True
    assert m1.is_factually_verified is False
    assert m1.requires_human_review is True
    assert m1.is_ready_to_publish is False
    assert m1.review_status == "PENDING_HUMAN_EDITORIAL_REVIEW"
    assert "FLAGGED_FOR_HUMAN_CONFIRMATION" in m1.destination_url_status

    # 4. Top-level AI generation flags
    assert result.is_ai_generated is True
    assert result.requires_human_review is True
    assert result.is_factually_verified is False
    assert result.is_ready_to_publish is False


def test_cannot_mark_moment_ready_to_publish_automatically():
    """Verifies that Pydantic validation rejects marking candidate moments as ready to publish."""
    with pytest.raises(ValueError, match="cannot be marked ready to publish automatically"):
        CandidateMoment(
            moment_id="moment_test_01",
            start_seconds=0.0,
            end_seconds=5.0,
            duration_seconds=5.0,
            transcript_excerpt="Verbatim words",
            main_topic="Topic",
            intended_platform=PlatformEnum.LINKEDIN,
            content_format=AssetFormatEnum.TEXT_POST,
            suggested_hook="Hook",
            suggested_content="Content",
            suggested_hashtags=[],
            suggested_cta="CTA",
            is_ready_to_publish=True  # STRICTLY PROHIBITED
        )


def test_prohibited_claims_trigger_warnings(synthetic_wav_file: Path):
    """Verifies that heuristic claim patterns (e.g. game-changer, supercharge) trigger review warnings."""
    payload = {
        "full_transcript": "We built a system that completely transforms content operations.",
        "moments": [
            {
                "start_seconds": 0.0,
                "end_seconds": 5.0,
                "transcript_excerpt": "We built a system that completely transforms content operations.",
                "main_topic": "Workflow",
                "intended_platform": "linkedin",
                "suggested_hook": "This is a total game-changer for content creators.",
                "suggested_content": "Supercharge your workflow by 4.3x with this secret sauce.",
                "suggested_hashtags": [],
                "suggested_cta": "Try it now"
            }
        ]
    }
    mock_client = make_mock_gemini_client(response_text=json.dumps(payload))
    result = repurpose_audio_with_gemini(
        audio_path=synthetic_wav_file,
        source_video_metadata={"duration_sec": 10.0},
        client=mock_client
    )

    warnings = result.moments[0].warnings
    assert len(warnings) >= 3
    assert any("game[- ]changer" in w for w in warnings)
    assert any("supercharge" in w for w in warnings)
    assert any("secret\\s+sauce" in w or "secret" in w for w in warnings)


def test_save_repurposing_result(tmp_path: Path, synthetic_wav_file: Path, sample_gemini_payload_dict):
    mock_client = make_mock_gemini_client(response_text=json.dumps(sample_gemini_payload_dict))
    result = repurpose_audio_with_gemini(
        audio_path=synthetic_wav_file,
        source_video_metadata={"duration_sec": 30.0},
        client=mock_client
    )

    out_file = tmp_path / "repurpose_manifest.json"
    saved_path = save_repurposing_result(result, out_file)

    assert saved_path.exists()
    data = json.loads(saved_path.read_text(encoding="utf-8"))
    assert data["source_duration_seconds"] == 30.0
    assert len(data["moments"]) == 3
    assert data["requires_human_review"] is True
    assert data["is_factually_verified"] is False
