"""FastAPI web application and background job pipeline for IncuBrix Content Engine.

Provides:
- GET /: Responsive Single Page Application (SPA) for long-form video upload and repurposing
- GET /api/config-status: Secret-masked runtime configuration and model readiness
- POST /api/jobs: Streaming multipart video upload, validation, and background processing
- GET /api/jobs/{job_id}: Real-time job status polling, progress stages, and final results
- GET /api/jobs: Recent video job history from memory and disk storage
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
import threading
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.config import load_settings, GenerationModeEnum
from app.core.media_renderer import get_ffmpeg_executable
from app.core.video_processor import (
    DEFAULT_MAX_VIDEO_SIZE_MB,
    DEFAULT_MAX_VIDEO_DURATION_SEC,
    DEFAULT_VIDEO_JOBS_DIR,
    create_video_job_dir,
    validate_job_id,
    sanitize_filename,
    validate_video,
    inspect_video,
    extract_audio,
)
from app.core.ai_repurposer import (
    DEFAULT_GEMINI_MODEL,
    SUPPORTED_PLATFORMS_FORMATS,
    get_gemini_api_key,
    mask_secret,
    repurpose_audio_with_gemini,
    repurpose_blog_with_gemini,
    save_repurposing_result,
    RepurposingResult,
)
from app.core.document_extractor import (
    extract_document_content,
    validate_document_file,
    SUPPORTED_BLOG_EXTENSIONS,
    DEFAULT_MAX_DOC_SIZE_MB,
    ExtractedDocument,
)

logger = logging.getLogger("incubrix.web")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="IncuBrix Content Engine",
    description="Real-time Video Ingestion, Audio Extraction, and AI Content Repurposing",
    version="4.4.0",
)

# In-memory registry for live and recent jobs (thread-safe)
_job_lock = threading.Lock()
_ACTIVE_JOBS: Dict[str, Dict[str, Any]] = {}

TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"


# ============================================================================
# Background Worker Task
# ============================================================================

def process_video_job_task(
    job_id: str,
    video_path: Path,
    job_dir: Path,
    selected_platforms: Optional[List[str]] = None,
    selected_formats: Optional[Dict[str, List[str]]] = None,
    unsupported_formats: Optional[List[str]] = None,
) -> None:
    """Synchronous background worker executed in a thread pool.

    Stages:
    1. Validating video container, duration, and streams
    2. Extracting mono 16 kHz WAV audio via FFmpeg
    3. Generating transcript and candidate platform drafts with Gemini AI
    4. Saving manifest to disk and updating in-memory status
    """
    logger.info(
        "Starting background processing for job '%s' (platforms=%s)...",
        job_id,
        selected_platforms or "all"
    )
    try:
        # --- Stage 1: Validation ---
        with _job_lock:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["stage"] = "validating"
                _ACTIVE_JOBS[job_id]["stage_message"] = "Validating video container, codecs, and streams..."

        validate_video(
            video_path,
            max_size_mb=DEFAULT_MAX_VIDEO_SIZE_MB,
            max_duration_sec=DEFAULT_MAX_VIDEO_DURATION_SEC,
        )
        video_metadata = inspect_video(video_path)
        video_metadata["job_id"] = job_id

        # --- Stage 2: Audio Extraction ---
        with _job_lock:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["stage"] = "extracting_audio"
                _ACTIVE_JOBS[job_id]["stage_message"] = (
                    f"Extracting 16 kHz mono WAV audio from {video_metadata.get('duration_sec', 0):.1f}s video..."
                )
                _ACTIVE_JOBS[job_id]["video_metadata"] = video_metadata

        audio_dest = job_dir / "extracted_speech_16khz.wav"
        extracted_audio_path, audio_info = extract_audio(
            video_path=video_path,
            output_audio_path=audio_dest,
        )

        with _job_lock:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["audio_metadata"] = audio_info

        # --- Stage 3: Gemini Speech Transcription & AI Repurposing ---
        with _job_lock:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["stage"] = "analyzing"
                _ACTIVE_JOBS[job_id]["stage_message"] = (
                    f"Transcribing speech audio and generating platform drafts with Gemini ({DEFAULT_GEMINI_MODEL})..."
                )

        settings = load_settings()
        result = repurpose_audio_with_gemini(
            audio_path=extracted_audio_path,
            source_video_metadata=video_metadata,
            model_name=DEFAULT_GEMINI_MODEL,
            api_key=settings.gemini_api_key,
            selected_platforms=selected_platforms,
            selected_formats=selected_formats,
            unsupported_formats=unsupported_formats,
        )

        # Save result JSON to disk
        manifest_dest = job_dir / "gemini_repurposing_result.json"
        save_repurposing_result(result, manifest_dest)

        # --- Stage 4: Completed ---
        with _job_lock:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["status"] = "completed"
                _ACTIVE_JOBS[job_id]["stage"] = "completed"
                _ACTIVE_JOBS[job_id]["stage_message"] = "Content generation completed successfully."
                _ACTIVE_JOBS[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
                _ACTIVE_JOBS[job_id]["error"] = None
                _ACTIVE_JOBS[job_id]["result"] = result.model_dump()

        logger.info(
            "Job '%s' completed successfully: %d moments generated.",
            job_id,
            len(result.moments)
        )

    except Exception as exc:
        logger.error("Job '%s' failed during processing: %s", job_id, exc, exc_info=True)
        # Never leak secrets or sensitive API credentials in error messages
        safe_error = str(exc)
        api_key = get_gemini_api_key()
        if api_key and api_key in safe_error:
            safe_error = safe_error.replace(api_key, "[REDACTED_API_KEY]")

        with _job_lock:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["status"] = "failed"
                _ACTIVE_JOBS[job_id]["stage"] = "failed"
                _ACTIVE_JOBS[job_id]["stage_message"] = f"Processing failed: {safe_error}"
                _ACTIVE_JOBS[job_id]["error"] = safe_error
                _ACTIVE_JOBS[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()


def process_blog_job_task(
    job_id: str,
    doc_path: Path,
    job_dir: Path,
    selected_platforms: Optional[List[str]] = None,
    selected_formats: Optional[Dict[str, List[str]]] = None,
    unsupported_formats: Optional[List[str]] = None,
) -> None:
    """Synchronous background worker executed for blog / article repurposing.

    Stages:
    1. Validating document format, size, and structure
    2. Extracting text, headings, and sections
    3. Generating platform-specific suggestions with Gemini AI (>= 10 suggestions)
    4. Saving manifest to disk and updating in-memory status
    """
    logger.info(
        "Starting background processing for blog job '%s' (platforms=%s)...",
        job_id,
        selected_platforms or "all"
    )
    try:
        # --- Stage 1: Validation ---
        with _job_lock:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["stage"] = "validating"
                _ACTIVE_JOBS[job_id]["stage_message"] = "Validating document format and structure..."

        valid_path = validate_document_file(doc_path, max_size_mb=DEFAULT_MAX_DOC_SIZE_MB)

        # --- Stage 2: Content & Structure Extraction ---
        with _job_lock:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["stage"] = "extracting_structure"
                _ACTIVE_JOBS[job_id]["stage_message"] = f"Extracting headings and structure from {doc_path.name}..."

        extracted_doc = extract_document_content(valid_path)

        with _job_lock:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["document_metadata"] = extracted_doc.to_dict()

        # --- Stage 3: Gemini Content Repurposing (>= 10 suggestions) ---
        with _job_lock:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["stage"] = "analyzing"
                _ACTIVE_JOBS[job_id]["stage_message"] = (
                    f"Repurposing blog content into 10+ platform drafts with Gemini ({DEFAULT_GEMINI_MODEL})..."
                )

        settings = load_settings()
        result = repurpose_blog_with_gemini(
            document=extracted_doc,
            model_name=DEFAULT_GEMINI_MODEL,
            api_key=settings.gemini_api_key,
            selected_platforms=selected_platforms,
            selected_formats=selected_formats,
            unsupported_formats=unsupported_formats,
            job_id=job_id,
        )

        # Save result JSON to disk
        manifest_dest = job_dir / "gemini_repurposing_result.json"
        save_repurposing_result(result, manifest_dest)

        # --- Stage 4: Completed ---
        with _job_lock:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["status"] = "completed"
                _ACTIVE_JOBS[job_id]["stage"] = "completed"
                _ACTIVE_JOBS[job_id]["stage_message"] = "Content generation completed successfully."
                _ACTIVE_JOBS[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
                _ACTIVE_JOBS[job_id]["error"] = None
                _ACTIVE_JOBS[job_id]["result"] = result.model_dump()

        logger.info(
            "Blog job '%s' completed successfully: %d suggestions generated.",
            job_id,
            len(result.moments)
        )

    except Exception as exc:
        logger.error("Blog job '%s' failed during processing: %s", job_id, exc, exc_info=True)
        safe_error = str(exc)
        api_key = get_gemini_api_key()
        if api_key and api_key in safe_error:
            safe_error = safe_error.replace(api_key, "[REDACTED_API_KEY]")

        with _job_lock:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["status"] = "failed"
                _ACTIVE_JOBS[job_id]["stage"] = "failed"
                _ACTIVE_JOBS[job_id]["stage_message"] = f"Processing failed: {safe_error}"
                _ACTIVE_JOBS[job_id]["error"] = safe_error
                _ACTIVE_JOBS[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()


# ============================================================================
# Routes
# ============================================================================

def sanitize_upload_filename(filename: str, default_suffix: str = ".mp4") -> str:
    """Sanitizes an uploaded filename to prevent directory traversal while preserving valid extensions."""
    import re
    name = Path(filename).name.strip()
    stem = Path(name).stem
    suffix = Path(name).suffix.lower()
    safe_stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", stem)
    safe_stem = re.sub(r"_+", "_", safe_stem).strip("_")
    if not suffix:
        suffix = default_suffix
    if not safe_stem:
        safe_stem = "uploaded_file"
    return f"{safe_stem}{suffix}"


@app.get("/", response_class=HTMLResponse)
def get_frontend_page() -> HTMLResponse:
    """Renders the single-page video upload and repurposing web application."""
    if not TEMPLATE_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Frontend template index.html not found.",
        )
    html_content = TEMPLATE_PATH.read_text(encoding="utf-8")
    return HTMLResponse(
        content=html_content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/config-status")
def get_config_status() -> Dict[str, Any]:
    """Returns safe runtime configuration and model status without leaking secrets."""
    settings = load_settings()
    raw_key = get_gemini_api_key(settings.gemini_api_key)
    ffmpeg_exe = get_ffmpeg_executable()

    # Public serializable view of supported platforms and formats
    catalog: Dict[str, Any] = {}
    for p_key, p_meta in SUPPORTED_PLATFORMS_FORMATS.items():
        catalog[p_key] = {
            "label": p_meta["label"],
            "platform_key": p_key,
            "formats": {
                f_key: {
                    "format_key": f_key,
                    "label": f_meta["label"],
                    "description": f_meta["description"],
                }
                for f_key, f_meta in p_meta["formats"].items()
            }
        }

    return {
        "app_env": settings.app_env.value,
        "generation_mode": settings.generation_mode.value,
        "gemini_api_key_configured": bool(raw_key),
        "gemini_api_key_masked": mask_secret(raw_key),
        "active_model": DEFAULT_GEMINI_MODEL,
        "max_upload_size_mb": DEFAULT_MAX_VIDEO_SIZE_MB,
        "max_duration_seconds": DEFAULT_MAX_VIDEO_DURATION_SEC,
        "max_blog_size_mb": DEFAULT_MAX_DOC_SIZE_MB,
        "supported_blog_extensions": sorted(list(SUPPORTED_BLOG_EXTENSIONS)),
        "supported_input_types": ["video", "blog"],
        "ffmpeg_available": bool(ffmpeg_exe),
        "supported_platforms_and_formats": catalog,
    }


@app.post("/api/jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    file: UploadFile = File(...),
    input_type: Optional[str] = Form("video"),
    platforms: Optional[str] = Form(None),
    formats: Optional[str] = Form(None),
    format_mode: Optional[str] = Form("all"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> Dict[str, Any]:
    """Streams an uploaded video or blog document, validates choices, and begins background processing.

    Enforces:
    - If video: extension .mp4, size <= 100 MB
    - If blog: extension in (.txt, .md, .docx, .pdf), size <= 10 MB
    - Streams in 1 MB chunks to prevent memory blowup
    - Path traversal protection on filenames
    - Validates platform & format choices (Phase 4.4A/B)
    """
    raw_input_type = (input_type or "video").strip().lower()
    if raw_input_type not in ("video", "blog"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported input type '{input_type}'. Must be 'video' or 'blog'.",
        )

    filename = file.filename or ("uploaded_video.mp4" if raw_input_type == "video" else "uploaded_document.txt")
    suffix = Path(filename).suffix.lower()

    if raw_input_type == "video":
        if suffix != ".mp4":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file format '{suffix}'. Only .mp4 video files are accepted for video upload.",
            )
        max_mb = DEFAULT_MAX_VIDEO_SIZE_MB
    else:  # blog
        if suffix not in SUPPORTED_BLOG_EXTENSIONS:
            supported_str = ", ".join(sorted(SUPPORTED_BLOG_EXTENSIONS))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported document format '{suffix}'. Only {supported_str} files are accepted for blog upload.",
            )
        max_mb = DEFAULT_MAX_DOC_SIZE_MB

    # 1. Parse and validate selected platforms (Phase 4.4A)
    selected_platforms_list: List[str] = []
    if platforms is not None:
        raw_p = platforms.strip()
        if not raw_p:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one platform must be selected.",
            )
        try:
            parsed = json.loads(raw_p)
            if isinstance(parsed, list):
                selected_platforms_list = [str(p).strip().lower() for p in parsed if str(p).strip()]
            elif isinstance(parsed, str):
                selected_platforms_list = [p.strip().lower() for p in parsed.split(",") if p.strip()]
        except json.JSONDecodeError:
            selected_platforms_list = [p.strip().lower() for p in raw_p.split(",") if p.strip()]

        if not selected_platforms_list:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one platform must be selected.",
            )

        # Validate each platform against catalog
        normalized_platforms = []
        for p in selected_platforms_list:
            norm_p = "twitter" if p in ("x", "twitter") else ("youtube_shorts" if p in ("shorts", "youtube_shorts") else p)
            if norm_p not in SUPPORTED_PLATFORMS_FORMATS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Platform '{p}' is not currently supported. "
                        f"Supported platforms: {', '.join(v['label'] for v in SUPPORTED_PLATFORMS_FORMATS.values())}."
                    ),
                )
            normalized_platforms.append(norm_p)
        selected_platforms_list = list(dict.fromkeys(normalized_platforms))
    else:
        selected_platforms_list = list(SUPPORTED_PLATFORMS_FORMATS.keys())

    # 2. Parse and validate selected formats per platform (Phase 4.4A)
    selected_formats_dict: Dict[str, List[str]] = {}
    unsupported_formats_list: List[str] = []

    if formats is not None and formats.strip():
        raw_f = formats.strip()
        try:
            parsed_fmts = json.loads(raw_f)
            if isinstance(parsed_fmts, dict):
                for plat_k, fmt_vals in parsed_fmts.items():
                    norm_k = "twitter" if plat_k in ("x", "twitter") else ("youtube_shorts" if plat_k in ("shorts", "youtube_shorts") else plat_k)
                    if isinstance(fmt_vals, list):
                        selected_formats_dict[norm_k] = [str(f).strip().lower() for f in fmt_vals if str(f).strip()]
            elif isinstance(parsed_fmts, list):
                flat_list = [str(f).strip().lower() for f in parsed_fmts if str(f).strip()]
                for p in selected_platforms_list:
                    selected_formats_dict[p] = flat_list
        except json.JSONDecodeError:
            pass

    # Validate format selections against catalog
    for plat in selected_platforms_list:
        avail_formats = SUPPORTED_PLATFORMS_FORMATS[plat]["formats"]
        req_fmts = selected_formats_dict.get(plat)

        if req_fmts is not None:
            for fmt in req_fmts:
                if fmt not in avail_formats:
                    unsupported_notice = (
                        f"Format '{fmt}' is unsupported for platform '{SUPPORTED_PLATFORMS_FORMATS[plat]['label']}'. "
                        f"Supported formats: {', '.join(avail_formats.keys())}."
                    )
                    unsupported_formats_list.append(unsupported_notice)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=unsupported_notice,
                    )
        else:
            selected_formats_dict[plat] = list(avail_formats.keys())

    total_formats_count = sum(len(fmts) for fmts in selected_formats_dict.values())
    if total_formats_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one content format must be selected for the chosen platforms.",
        )

    # Allocate isolated job directory
    job_id, job_dir = create_video_job_dir(prefix="job_web")
    safe_name = sanitize_upload_filename(filename, default_suffix=suffix)
    dest_file_path = job_dir / safe_name

    # Stream file to disk in 1 MB chunks
    chunk_size = 1024 * 1024  # 1 MB
    max_bytes = int(max_mb * 1024 * 1024)
    total_bytes = 0

    try:
        with open(dest_file_path, "wb") as f_out:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    f_out.close()
                    dest_file_path.unlink(missing_ok=True)
                    shutil.rmtree(job_dir, ignore_errors=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=(
                            f"File size exceeds maximum allowed limit of {max_mb:.1f} MB."
                        ),
                    )
                f_out.write(chunk)

        if total_bytes == 0:
            dest_file_path.unlink(missing_ok=True)
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Uploaded file '{filename}' is empty (0 bytes).",
            )

    except HTTPException:
        raise
    except Exception as exc:
        dest_file_path.unlink(missing_ok=True)
        shutil.rmtree(job_dir, ignore_errors=True)
        logger.error("Failed while streaming uploaded file: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error while saving uploaded file.",
        ) from exc

    # Register in-memory job status
    now_iso = datetime.now(timezone.utc).isoformat()
    job_record = {
        "job_id": job_id,
        "input_type": raw_input_type,
        "filename": safe_name,
        "file_size_bytes": total_bytes,
        "status": "processing",
        "stage": "uploading",
        "stage_message": f"Uploaded {total_bytes / (1024*1024):.2f} MB. Initializing background pipeline...",
        "created_at": now_iso,
        "completed_at": None,
        "error": None,
        "result": None,
        "file_path": str(dest_file_path),
        "video_path": str(dest_file_path) if raw_input_type == "video" else None,
        "document_path": str(dest_file_path) if raw_input_type == "blog" else None,
        "job_dir": str(job_dir),
        "selected_platforms": selected_platforms_list,
        "selected_formats": selected_formats_dict,
    }

    with _job_lock:
        _ACTIVE_JOBS[job_id] = job_record

    # Schedule background processing worker according to input type
    if raw_input_type == "video":
        background_tasks.add_task(
            process_video_job_task,
            job_id=job_id,
            video_path=dest_file_path,
            job_dir=job_dir,
            selected_platforms=selected_platforms_list,
            selected_formats=selected_formats_dict,
            unsupported_formats=unsupported_formats_list,
        )
    else:  # blog
        background_tasks.add_task(
            process_blog_job_task,
            job_id=job_id,
            doc_path=dest_file_path,
            job_dir=job_dir,
            selected_platforms=selected_platforms_list,
            selected_formats=selected_formats_dict,
            unsupported_formats=unsupported_formats_list,
        )

    logger.info(
        "Accepted %s upload for job '%s' (%s, %d bytes, platforms=%s)",
        raw_input_type,
        job_id,
        safe_name,
        total_bytes,
        selected_platforms_list
    )

    return {
        "job_id": job_id,
        "input_type": raw_input_type,
        "status": "processing",
        "stage": "uploading",
        "filename": safe_name,
        "file_size_bytes": total_bytes,
        "created_at": now_iso,
        "selected_platforms": selected_platforms_list,
        "selected_formats": selected_formats_dict,
    }


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str) -> Dict[str, Any]:
    """Retrieves current job status, progress stage, and results.

    Supports on-disk manifest recovery for previously completed runs.
    """
    try:
        clean_id = validate_job_id(job_id)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )

    # 1. Check in-memory store
    with _job_lock:
        if clean_id in _ACTIVE_JOBS:
            return _ACTIVE_JOBS[clean_id]

    # 2. Check disk for completed manifest
    job_dir = (DEFAULT_VIDEO_JOBS_DIR / clean_id).resolve()
    manifest_path = job_dir / "gemini_repurposing_result.json"

    if manifest_path.exists() and manifest_path.is_file():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            input_type = manifest_data.get("input_type", "video")
            filename = (
                manifest_data.get("source_document_name")
                or (Path(manifest_data.get("source_video_path")).name if manifest_data.get("source_video_path") else "uploaded_file")
            )
            restored_record = {
                "job_id": clean_id,
                "input_type": input_type,
                "filename": filename,
                "file_size_bytes": None,
                "status": "completed",
                "stage": "completed",
                "stage_message": "Loaded completed job manifest from disk storage.",
                "created_at": manifest_data.get("generated_at"),
                "completed_at": manifest_data.get("generated_at"),
                "error": None,
                "result": manifest_data,
                "file_path": manifest_data.get("source_document_path") or manifest_data.get("source_video_path"),
                "video_path": manifest_data.get("source_video_path"),
                "document_path": manifest_data.get("source_document_path"),
                "job_dir": str(job_dir),
            }
            with _job_lock:
                _ACTIVE_JOBS[clean_id] = restored_record
            return restored_record
        except Exception as exc:
            logger.warning("Failed to parse disk manifest for job '%s': %s", clean_id, exc)

    # 3. Check if job directory exists without completed manifest
    if job_dir.exists() and job_dir.is_dir():
        return {
            "job_id": clean_id,
            "filename": "unknown",
            "file_size_bytes": None,
            "status": "failed",
            "stage": "failed",
            "stage_message": "Job directory found on disk but no completed result manifest exists.",
            "created_at": None,
            "completed_at": None,
            "error": "Incomplete or interrupted job on disk.",
            "result": None,
        }

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Job '{clean_id}' not found.",
    )


@app.get("/api/jobs")
def list_recent_jobs() -> List[Dict[str, Any]]:
    """Returns a list of recent video and blog jobs discovered in memory and on disk."""
    discovered: Dict[str, Dict[str, Any]] = {}

    # 1. Disk scan
    if DEFAULT_VIDEO_JOBS_DIR.exists() and DEFAULT_VIDEO_JOBS_DIR.is_dir():
        for job_folder in DEFAULT_VIDEO_JOBS_DIR.iterdir():
            if not job_folder.is_dir():
                continue
            manifest = job_folder / "gemini_repurposing_result.json"
            if manifest.exists():
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    filename = (
                        data.get("source_document_name")
                        or (Path(data.get("source_video_path")).name if data.get("source_video_path") else None)
                    )
                    discovered[job_folder.name] = {
                        "job_id": job_folder.name,
                        "input_type": data.get("input_type", "video"),
                        "filename": filename,
                        "status": "completed",
                        "stage": "completed",
                        "created_at": data.get("generated_at"),
                        "duration_seconds": data.get("source_duration_seconds"),
                        "moments_count": len(data.get("moments", [])),
                        "model_used": data.get("model_used"),
                    }
                except Exception:
                    pass

    # 2. Overlay in-memory state
    with _job_lock:
        for j_id, j_data in _ACTIVE_JOBS.items():
            res = j_data.get("result") or {}
            discovered[j_id] = {
                "job_id": j_id,
                "input_type": j_data.get("input_type", "video"),
                "filename": j_data.get("filename"),
                "status": j_data.get("status"),
                "stage": j_data.get("stage"),
                "created_at": j_data.get("created_at"),
                "duration_seconds": res.get("source_duration_seconds"),
                "moments_count": len(res.get("moments", [])) if res else None,
                "model_used": res.get("model_used"),
            }

    # Sort newest first by created_at or job_id
    sorted_jobs = sorted(
        discovered.values(),
        key=lambda j: j.get("created_at") or j.get("job_id") or "",
        reverse=True,
    )
    return sorted_jobs
