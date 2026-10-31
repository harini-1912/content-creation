"""Original media preview renderer for video and carousel drafts.

Renders offline text-based preview media without external cloud services or network TTS:
1. YouTube Shorts vertical video previews (1080x1920 MP4) via Pillow + FFmpeg.
2. Instagram carousel slide decks (5 x 1080x1080 PNG) + contact sheet via Pillow.
3. Generates complete render manifests maintaining source traceability.
4. Cryptographic SHA-256 integrity digests for all rendered media artifacts.

TRUST BOUNDARY & ARCHITECTURAL LIMITATION (Phase 3.9):
- SHA-256 digests in render_manifest.json record the precise state of rendered media files at output time.
- SHA-256 verifies that on-disk files match the manifest hashes (tamper and bit-rot detection).
- An unsigned JSON manifest can be replaced or fabricated by an actor with local filesystem write access.
- Matching file hashes do not provide cryptographic non-repudiation or prove that IncuBrix generated the media.
- The renderer_engine and media_provenance fields are descriptive checks, not authenticated identity.
- Secure asymmetric signing with key management infrastructure is documented as future work.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageFont

from app.models.asset import DraftCandidate, PlatformEnum, AssetFormatEnum

# Default Dimensions
VIDEO_WIDTH, VIDEO_HEIGHT = 1080, 1920
CAROUSEL_SIZE = 1080

# Visual Palette (Dark Mode Editorial Theme)
COLOR_BG = (11, 15, 25)           # Dark Slate Canvas
COLOR_CARD = (17, 24, 39)         # Deep Gray Container
COLOR_BORDER = (30, 41, 59)       # Subtle Slate Border
COLOR_TEXT_MAIN = (248, 250, 252) # Clean Off-White
COLOR_TEXT_MUTED = (148, 163, 184)# Slate Gray Muted
COLOR_ACCENT = (99, 102, 241)     # Indigo Accent
COLOR_CYAN = (56, 189, 248)       # Sky Blue Accent
COLOR_WARNING = (245, 158, 11)    # Amber Warning Accent


def compute_file_sha256(file_path: Union[str, Path]) -> str:
    """Computes deterministic SHA-256 hex digest for a file on disk."""
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(f"Cannot compute hash: file '{p}' does not exist.")
    hasher = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_ffmpeg_executable() -> Optional[str]:
    """Resolves FFmpeg executable path from imageio_ffmpeg or system PATH."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    system_exe = shutil.which("ffmpeg")
    if system_exe:
        return system_exe

    return None


def get_ffprobe_executable() -> Optional[str]:
    """Resolves ffprobe executable path if available in system PATH or adjacent to ffmpeg."""
    ffprobe_sys = shutil.which("ffprobe")
    if ffprobe_sys:
        return ffprobe_sys

    ffmpeg_exe = get_ffmpeg_executable()
    if ffmpeg_exe:
        candidate = Path(ffmpeg_exe).parent / "ffprobe.exe"
        if candidate.exists():
            return str(candidate)

    return None


def probe_media_duration(media_path: Union[str, Path]) -> float:
    """Probes the exact duration in seconds from a rendered media file.

    Uses ffprobe if available; falls back to ffmpeg -i inspection.
    Raises RuntimeError if neither probe tool is available or if probing fails.
    Never returns an unverified theoretical estimate.
    """
    path = Path(media_path)
    if not path.exists():
        raise FileNotFoundError(f"Media file not found for duration probing: {path}")

    # Method 1: ffprobe if present
    ffprobe_exe = get_ffprobe_executable()
    if ffprobe_exe:
        cmd = [
            ffprobe_exe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path)
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            output = res.stdout.strip()
            if output:
                return round(float(output), 2)
        except Exception:
            pass

    # Method 2: ffmpeg -i inspection
    ffmpeg_exe = get_ffmpeg_executable()
    if ffmpeg_exe:
        cmd = [ffmpeg_exe, "-i", str(path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr)
        if m:
            hours = int(m.group(1))
            minutes = int(m.group(2))
            seconds = float(m.group(3))
            total = hours * 3600 + minutes * 60 + seconds
            return round(total, 2)

    raise RuntimeError(
        f"Unable to probe actual media duration for '{path.name}'. "
        "Neither ffprobe nor ffmpeg inspection was able to determine the rendered duration. "
        "Estimated durations are not written to the manifest."
    )


def probe_media_dimensions(media_path: Union[str, Path]) -> Tuple[int, int]:
    """Probes the exact (width, height) resolution in pixels from a rendered video file.

    Uses ffprobe if available; falls back to ffmpeg -i stream inspection.
    Raises RuntimeError if neither probe tool is available or if probing fails.
    Never returns an unverified theoretical estimate.
    """
    path = Path(media_path)
    if not path.exists():
        raise FileNotFoundError(f"Media file not found for dimension probing: {path}")

    # Method 1: ffprobe if present
    ffprobe_exe = get_ffprobe_executable()
    if ffprobe_exe:
        cmd = [
            ffprobe_exe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            str(path)
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            output = res.stdout.strip()
            if output and "x" in output:
                parts = output.split("x")
                return int(parts[0]), int(parts[1])
        except Exception:
            pass

    # Method 2: ffmpeg -i inspection
    ffmpeg_exe = get_ffmpeg_executable()
    if ffmpeg_exe:
        cmd = [ffmpeg_exe, "-i", str(path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        m = re.search(r"Video:.*?(?:,\s*|\s+)(\d{2,5})x(\d{2,5})", res.stderr)
        if m:
            return int(m.group(1)), int(m.group(2))

    raise RuntimeError(
        f"Unable to probe actual media dimensions for '{path.name}'. "
        "Neither ffprobe nor ffmpeg inspection was able to determine video stream dimensions."
    )


def get_system_font(size: int) -> ImageFont.ImageFont:
    """Loads system font (Arial/Segoe/Calibri) with safe fallback to default font."""
    candidate_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc"
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                continue

    return ImageFont.load_default(size=size)


def wrap_text(text: str, max_chars_per_line: int = 38) -> str:
    """Wraps text into readable line lengths without splitting words."""
    lines: List[str] = []
    for paragraph in text.split("\n"):
        p_clean = paragraph.strip()
        if not p_clean:
            lines.append("")
            continue
        words = p_clean.split()
        curr_line: List[str] = []
        curr_len = 0
        for w in words:
            if curr_len + len(w) + 1 <= max_chars_per_line:
                curr_line.append(w)
                curr_len += len(w) + 1
            else:
                lines.append(" ".join(curr_line))
                curr_line = [w]
                curr_len = len(w)
        if curr_line:
            lines.append(" ".join(curr_line))
    return "\n".join(lines)


# ==============================================================================
# 1. YouTube Shorts Video Preview (1080x1920)
# ==============================================================================

def render_video_scene_card(
    scene_idx: int,
    total_scenes: int,
    duration: float,
    on_screen_text: str,
    voiceover: str,
    visual_cue: str,
    source_segment_id: str,
    is_generated_suggestion: bool = True
) -> Image.Image:
    """Renders a single 1080x1920 text-card frame for vertical video preview."""
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), color=COLOR_BG)
    draw = ImageDraw.Draw(img)

    font_badge = get_system_font(26)
    font_cue = get_system_font(28)
    font_title = get_system_font(52)
    font_body = get_system_font(34)
    font_footer = get_system_font(22)

    # Outer decorative margin
    draw.rounded_rectangle([(40, 60), (1040, 1860)], radius=32, outline=COLOR_BORDER, width=4)

    # Top Header Box
    draw.rectangle([(40, 60), (1040, 220)], fill=COLOR_CARD)
    badge_label = f"SCENE {scene_idx:02d} / {total_scenes:02d}  •  {duration:.1f}s"
    draw.text((80, 100), badge_label, font=font_badge, fill=COLOR_CYAN)

    review_label = "[PREVIEW — REQUIRES HUMAN REVIEW]"
    draw.text((80, 150), review_label, font=font_badge, fill=COLOR_WARNING)

    # Middle Box: On-Screen Text Graphic
    center_y = 520
    draw.rounded_rectangle([(80, center_y), (1000, center_y + 450)], radius=24, fill=COLOR_CARD, outline=COLOR_ACCENT, width=3)
    
    draw.text((120, center_y + 30), "ON-SCREEN TEXT GRAPHIC:", font=font_badge, fill=COLOR_TEXT_MUTED)
    wrapped_ost = wrap_text(on_screen_text, max_chars_per_line=30)
    draw.text((120, center_y + 80), wrapped_ost, font=font_title, fill=COLOR_TEXT_MAIN, spacing=12)

    # Visual Cue Box
    cue_y = center_y + 480
    draw.rounded_rectangle([(80, cue_y), (1000, cue_y + 160)], radius=18, fill=COLOR_CARD, outline=COLOR_BORDER, width=2)
    draw.text((120, cue_y + 25), "VISUAL CUE:", font=font_badge, fill=COLOR_CYAN)
    wrapped_cue = wrap_text(visual_cue, max_chars_per_line=45)
    draw.text((120, cue_y + 65), wrapped_cue, font=font_cue, fill=COLOR_TEXT_MAIN, spacing=8)

    # Bottom Box: Voiceover Script Narration
    vo_y = cue_y + 190
    draw.rounded_rectangle([(80, vo_y), (1000, vo_y + 360)], radius=24, fill=COLOR_CARD, outline=COLOR_BORDER, width=2)
    draw.text((120, vo_y + 25), "SPOKEN VOICEOVER SCRIPT:", font=font_badge, fill=COLOR_CYAN)
    wrapped_vo = wrap_text(voiceover, max_chars_per_line=38)
    draw.text((120, vo_y + 75), wrapped_vo, font=font_body, fill=COLOR_TEXT_MAIN, spacing=10)

    # Provenance Footer
    provenance_tag = "[GENERATED SCENE OUTLINE]" if is_generated_suggestion else "[SOURCE-DERIVED SCRIPT]"
    footer_text = f"Source: {source_segment_id}  •  {provenance_tag}  •  IncuBrix Offline Engine"
    draw.text((80, 1800), footer_text, font=font_footer, fill=COLOR_TEXT_MUTED)

    return img


def render_video_preview(
    draft: DraftCandidate,
    output_dir: Union[str, Path]
) -> Tuple[Path, Dict[str, Any]]:
    """Renders a vertical 9:16 (1080x1920) text-card MP4 video preview from scene cues.

    Preserves source segment ID and outputs render manifest.
    Raises RuntimeError if FFmpeg executable is missing.
    """
    ffmpeg_exe = get_ffmpeg_executable()
    if not ffmpeg_exe:
        raise RuntimeError(
            "FFmpeg executable not found. Cannot render MP4 video preview. "
            "Please ensure imageio-ffmpeg is installed or ffmpeg is on system PATH."
        )

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    cues = draft.video_scene_cues or []
    if not cues:
        # Construct fallback single-scene preview from caption if cues are absent
        cues = [
            {
                "scene": 1,
                "duration_seconds": 6.0,
                "visual_cue": "[Procedural Text Card Display]",
                "voiceover": draft.draft_caption,
                "on_screen_text": draft.draft_hook[:50],
                "is_generated_suggestion": True
            }
        ]

    total_scenes = len(cues)
    total_duration = sum(float(c.get("duration_seconds", 3.0)) for c in cues)

    with tempfile.TemporaryDirectory() as temp_dir:
        concat_entries: List[str] = []
        scene_files: List[str] = []

        for idx, cue in enumerate(cues, start=1):
            dur = float(cue.get("duration_seconds", 3.0))
            ost = cue.get("on_screen_text", f"Scene {idx}")
            vo = cue.get("voiceover", draft.draft_caption)
            cue_text = cue.get("visual_cue", "[Visual Sequence]")
            is_suggestion = cue.get("is_generated_suggestion", True)

            img = render_video_scene_card(
                scene_idx=idx,
                total_scenes=total_scenes,
                duration=dur,
                on_screen_text=ost,
                voiceover=vo,
                visual_cue=cue_text,
                source_segment_id=draft.source_segment_id,
                is_generated_suggestion=is_suggestion
            )

            scene_png = os.path.join(temp_dir, f"scene_{idx:02d}.png").replace("\\", "/")
            img.save(scene_png, format="PNG")
            scene_files.append(scene_png)
            concat_entries.append(f"file '{scene_png}'\nduration {dur:.2f}\n")

        # Concat demuxer requirement: repeat the last file entry without duration
        if scene_files:
            concat_entries.append(f"file '{scene_files[-1]}'\n")

        concat_script_path = os.path.join(temp_dir, "concat.txt")
        with open(concat_script_path, "w", encoding="utf-8") as f:
            f.writelines(concat_entries)

        mp4_dest = out_path / "preview.mp4"

        cmd = [
            ffmpeg_exe,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_script_path,
            "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},format=yuv420p",
            "-r", "24",
            "-c:v", "libx264",
            str(mp4_dest)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg render failed with exit code {result.returncode}: {result.stderr}")

    # Probe actual rendered duration from the completed MP4 file
    actual_duration = probe_media_duration(mp4_dest)
    probe_method = "ffprobe" if get_ffprobe_executable() else "ffmpeg_inspection"
    mp4_hash = compute_file_sha256(mp4_dest)

    manifest_data = {
        "asset_id": draft.draft_id,
        "platform": draft.platform.value,
        "content_format": draft.content_format.value,
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "permission_evidence_reference": None,
        "dimensions": f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}",
        "duration_seconds": actual_duration,
        "estimated_duration_seconds": round(total_duration, 1),
        "duration_probe_method": probe_method,
        "scene_count": total_scenes,
        "source_document": draft.source_document,
        "source_segment_id": draft.source_segment_id,
        "generation_mode": draft.generation_mode.value,
        "review_status": "DRAFT_PREVIEW_REQUIRES_HUMAN_REVIEW",
        "is_silent": True,
        "audio_notice": "Silent preview: procedural text cards with no voiceover synthesized (offline mode).",
        "output_files": ["preview.mp4"],
        "file_hashes": {
            "preview.mp4": mp4_hash
        },
        "integrity_algorithm": "SHA-256",
        "rendered_at": datetime.now(timezone.utc).isoformat()
    }

    manifest_path = out_path / "render_manifest.json"
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    return mp4_dest, manifest_data


# ==============================================================================
# 2. Instagram Carousel Preview (5 slides at 1080x1080 + Contact Sheet)
# ==============================================================================

def render_carousel_slide(
    slide_num: int,
    total_slides: int,
    headline: str,
    body: str,
    layout: str,
    source_segment_id: str,
    is_generated_suggestion: bool
) -> Image.Image:
    """Renders an individual 1080x1080 PNG slide for document carousel."""
    img = Image.new("RGB", (CAROUSEL_SIZE, CAROUSEL_SIZE), color=COLOR_BG)
    draw = ImageDraw.Draw(img)

    font_badge = get_system_font(24)
    font_headline = get_system_font(46)
    font_body = get_system_font(30)
    font_footer = get_system_font(20)

    # Outer border container
    draw.rounded_rectangle([(36, 36), (1044, 1044)], radius=28, outline=COLOR_BORDER, width=3)

    # Top Bar Header
    counter_label = f"SLIDE {slide_num:02d} / {total_slides:02d}"
    draw.text((70, 70), counter_label, font=font_badge, fill=COLOR_ACCENT)

    tag_label = "[GENERATED SUGGESTION]" if is_generated_suggestion else f"[SOURCE-DERIVED BASIS — {source_segment_id}]"
    tag_color = COLOR_WARNING if is_generated_suggestion else COLOR_CYAN
    draw.text((70, 110), tag_label, font=font_badge, fill=tag_color)

    # Card Content Box
    draw.rounded_rectangle([(70, 170), (1010, 940)], radius=20, fill=COLOR_CARD, outline=COLOR_BORDER, width=2)

    # Headline
    wrapped_headline = wrap_text(headline, max_chars_per_line=32)
    draw.text((110, 220), wrapped_headline, font=font_headline, fill=COLOR_TEXT_MAIN, spacing=10)

    # Separator Line
    draw.line([(110, 360), (970, 360)], fill=COLOR_BORDER, width=2)

    # Body Content
    wrapped_body = wrap_text(body, max_chars_per_line=38)
    draw.text((110, 400), wrapped_body, font=font_body, fill=COLOR_TEXT_MUTED, spacing=14)

    # Bottom Footer
    footer_left = f"Archetype: {layout}"
    footer_right = "[DRAFT PREVIEW — REQUIRES HUMAN REVIEW]"
    draw.text((70, 970), footer_left, font=font_footer, fill=COLOR_TEXT_MUTED)
    draw.text((540, 970), footer_right, font=font_footer, fill=COLOR_WARNING)

    return img


def render_carousel_contact_sheet(
    slides: List[Image.Image],
    asset_id: str,
    source_segment_id: str
) -> Image.Image:
    """Generates a composite contact sheet summarizing all carousel slides."""
    sheet_w, sheet_h = 1800, 1350
    sheet = Image.new("RGB", (sheet_w, sheet_h), color=COLOR_BG)
    draw = ImageDraw.Draw(sheet)

    font_title = get_system_font(32)
    font_meta = get_system_font(22)

    # Header
    draw.text((50, 40), f"CAROUSEL PREVIEW CONTACT SHEET • {asset_id}", font=font_title, fill=COLOR_TEXT_MAIN)
    draw.text((50, 85), f"Source Segment: {source_segment_id} • STATUS: DRAFT PREVIEW (REQUIRES HUMAN REVIEW)", font=font_meta, fill=COLOR_CYAN)
    draw.line([(50, 125), (1750, 125)], fill=COLOR_BORDER, width=2)

    # 3-column x 2-row grid for 5 slides
    thumb_size = 480
    grid_coords = [
        (80, 160),
        (660, 160),
        (1240, 160),
        (370, 720),
        (950, 720)
    ]

    for idx, (img, (x, y)) in enumerate(zip(slides, grid_coords)):
        resized = img.resize((thumb_size, thumb_size), Image.Resampling.LANCZOS)
        sheet.paste(resized, (x, y))
        draw.rectangle([(x, y), (x + thumb_size, y + thumb_size)], outline=COLOR_ACCENT, width=3)
        draw.text((x + 10, y + thumb_size + 8), f"Slide {idx + 1:02d}", font=font_meta, fill=COLOR_TEXT_MUTED)

    return sheet


def render_carousel_preview(
    draft: DraftCandidate,
    output_dir: Union[str, Path]
) -> Tuple[List[Path], Path, Dict[str, Any]]:
    """Renders 5 square 1080x1080 PNG slides and a contact sheet.

    Preserves source segment ID and outputs complete render manifest.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    outlines = draft.carousel_slide_outlines or []
    if not outlines:
        raise ValueError(f"Draft '{draft.draft_id}' contains no carousel slide outlines to render.")

    slide_images: List[Image.Image] = []
    slide_file_paths: List[Path] = []
    total_slides = len(outlines)

    for idx, s in enumerate(outlines, start=1):
        headline = s.get("headline", f"Slide {idx}")
        body = s.get("body", "")
        layout = s.get("layout", "content_card")
        is_suggestion = s.get("is_generated_suggestion", idx in (1, total_slides))

        slide_img = render_carousel_slide(
            slide_num=idx,
            total_slides=total_slides,
            headline=headline,
            body=body,
            layout=layout,
            source_segment_id=draft.source_segment_id,
            is_generated_suggestion=is_suggestion
        )
        slide_images.append(slide_img)

        slide_filename = f"slide_{idx:02d}.png"
        slide_path = out_path / slide_filename
        slide_img.save(slide_path, format="PNG")
        slide_file_paths.append(slide_path)

    # Render contact sheet
    contact_sheet = render_carousel_contact_sheet(
        slide_images,
        asset_id=draft.draft_id,
        source_segment_id=draft.source_segment_id
    )
    contact_sheet_path = out_path / "carousel_contact_sheet.png"
    contact_sheet.save(contact_sheet_path, format="PNG")

    file_hashes: Dict[str, str] = {}
    for p in slide_file_paths:
        file_hashes[p.name] = compute_file_sha256(p)
    file_hashes["carousel_contact_sheet.png"] = compute_file_sha256(contact_sheet_path)

    manifest_data = {
        "asset_id": draft.draft_id,
        "platform": draft.platform.value,
        "content_format": draft.content_format.value,
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow)",
        "media_rights_status": "NOT_APPLICABLE",
        "permission_evidence_reference": None,
        "dimensions": f"{CAROUSEL_SIZE}x{CAROUSEL_SIZE}",
        "slide_count": total_slides,
        "source_document": draft.source_document,
        "source_segment_id": draft.source_segment_id,
        "generation_mode": draft.generation_mode.value,
        "review_status": "DRAFT_PREVIEW_REQUIRES_HUMAN_REVIEW",
        "output_files": [p.name for p in slide_file_paths] + ["carousel_contact_sheet.png"],
        "file_hashes": file_hashes,
        "integrity_algorithm": "SHA-256",
        "rendered_at": datetime.now(timezone.utc).isoformat()
    }

    manifest_path = out_path / "render_manifest.json"
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    return slide_file_paths, contact_sheet_path, manifest_data

