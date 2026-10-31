"""Integration tests for Blog/Article Upload and Repurposing Web API (Phase 4.4B).

Tests:
- GET /api/config-status includes supported blog extensions and max size
- POST /api/jobs with input_type='blog' and TXT upload (202 Accepted, >= 10 suggestions generated)
- POST /api/jobs with input_type='blog' and MD upload
- POST /api/jobs with input_type='blog' and DOCX upload
- POST /api/jobs with input_type='blog' and PDF upload
- POST /api/jobs with unsupported format (.zip) returns 400 Bad Request
- POST /api/jobs with 0-byte file returns 400 Bad Request
- POST /api/jobs with size exceeding 10 MB returns 413 Content Too Large
- Preservation of video upload validation (rejects non-MP4 for video)
- GET /api/jobs/{job_id} retrieves blog job details and results
"""

import io
import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from app.main import app, _ACTIVE_JOBS, _job_lock


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_config_status_includes_blog_support(client: TestClient):
    """Verifies that config-status returns supported blog formats and size limits."""
    res = client.get("/api/config-status")
    assert res.status_code == 200
    data = res.json()
    assert "supported_blog_extensions" in data
    assert ".txt" in data["supported_blog_extensions"]
    assert ".md" in data["supported_blog_extensions"]
    assert ".docx" in data["supported_blog_extensions"]
    assert ".pdf" in data["supported_blog_extensions"]
    assert data.get("max_blog_size_mb") == 10.0
    assert "supported_input_types" in data
    assert "blog" in data["supported_input_types"]
    assert "video" in data["supported_input_types"]


def test_blog_upload_txt_success(client: TestClient):
    """Verifies that uploading a valid TXT blog generates >= 10 suggestions."""
    txt_content = (
        "Operating Systems for Digital Content Creation\n\n"
        "Creators face continuous friction when managing disconnected distribution channels. "
        "A systematic repurposing architecture transforms single recordings into long-form blogs, "
        "short video clips, swipeable carousels, and high-impact discussions.\n\n"
        "By enforcing repeatable operating procedures, media engineering teams preserve consistent "
        "production velocity without sacrificing quality across YouTube Shorts, LinkedIn, Instagram, and Twitter."
    )
    file_bytes = txt_content.encode("utf-8")

    response = client.post(
        "/api/jobs",
        data={"input_type": "blog", "platforms": json.dumps(["linkedin", "twitter"])},
        files={"file": ("operating_systems.txt", file_bytes, "text/plain")},
    )
    assert response.status_code == 202
    job_info = response.json()
    job_id = job_info["job_id"]
    assert job_info["input_type"] == "blog"

    # Poll status
    status_res = client.get(f"/api/jobs/{job_id}")
    assert status_res.status_code == 200
    job_status = status_res.json()
    assert job_status["status"] == "completed"
    assert "result" in job_status
    result = job_status["result"]
    assert result["input_type"] == "blog"
    assert len(result["moments"]) >= 10


def test_blog_upload_md_success(client: TestClient):
    """Verifies that uploading a Markdown document generates >= 10 suggestions."""
    md_content = (
        "# High-Velocity Creator Operations\n\n"
        "## The Problem with Manual Workflows\n\n"
        "Disconnected tools create redundant manual handoffs, scattered files, and erratic rhythms. "
        "Content engineering teams require centralized ingestion and automated repurposing.\n\n"
        "## Tactical Solutions\n\n"
        "1. Hook formulation for fast retention\n"
        "2. Multi-slide visual carousel cards for LinkedIn and Instagram\n"
        "3. Step-by-step numbered threads for X."
    )
    file_bytes = md_content.encode("utf-8")

    response = client.post(
        "/api/jobs",
        data={"input_type": "blog"},
        files={"file": ("creator_ops.md", file_bytes, "text/markdown")},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    status_res = client.get(f"/api/jobs/{job_id}")
    job_status = status_res.json()
    assert job_status["status"] == "completed"
    result = job_status["result"]
    assert result["source_document_title"] == "High-Velocity Creator Operations"
    assert len(result["moments"]) >= 10


def test_blog_upload_docx_success(client: TestClient, tmp_path: Path):
    """Verifies that uploading a DOCX file generates >= 10 suggestions."""
    import docx
    doc_path = tmp_path / "test_article.docx"
    doc_obj = docx.Document()
    doc_obj.add_heading("Operational Framework for Content Engines", level=1)
    doc_obj.add_paragraph(
        "Creating high-impact short videos requires identifying core pedagogical moments. "
        "When long-form recordings are transcribed, algorithmic extraction isolates the most engaging soundbites."
    )
    doc_obj.add_heading("Targeting Social Platforms", level=2)
    doc_obj.add_paragraph(
        "Publishing across LinkedIn, Instagram, YouTube Shorts, and Twitter ensures broad organic reach. "
        "Each channel demands tailored formatting, hooks, and low-friction calls to action."
    )
    doc_obj.save(str(doc_path))

    with open(doc_path, "rb") as f:
        file_bytes = f.read()

    response = client.post(
        "/api/jobs",
        data={"input_type": "blog"},
        files={"file": ("test_article.docx", file_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    status_res = client.get(f"/api/jobs/{job_id}")
    assert status_res.status_code == 200
    job_status = status_res.json()
    assert job_status["status"] == "completed"
    assert len(job_status["result"]["moments"]) >= 10


def test_blog_upload_pdf_success(client: TestClient):
    """Verifies that uploading a PDF file with selectable text generates >= 10 suggestions."""
    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        b"5 0 obj << /Length 210 >> stream\n"
        b"BT\n/F1 14 Tf\n50 700 Td\n(Social Media Content Engine Whitepaper) Tj\n"
        b"0 -30 Td\n(Content repurposing transforms long webinars into bite-sized clips for LinkedIn and YouTube.) Tj\n"
        b"0 -20 Td\n(Consistent publishing systems prevent creator burnout and guarantee regular audience growth.) Tj\n"
        b"ET\nendstream\nendobj\nxref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000224 00000 n \n"
        b"0000000293 00000 n \n"
        b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n555\n%%EOF"
    )

    response = client.post(
        "/api/jobs",
        data={"input_type": "blog"},
        files={"file": ("whitepaper.pdf", pdf_content, "application/pdf")},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    status_res = client.get(f"/api/jobs/{job_id}")
    job_status = status_res.json()
    assert job_status["status"] == "completed"
    assert len(job_status["result"]["moments"]) >= 10


def test_blog_upload_unsupported_extension_rejected(client: TestClient):
    """Verifies that uploading an unsupported extension for blog returns HTTP 400."""
    response = client.post(
        "/api/jobs",
        data={"input_type": "blog"},
        files={"file": ("archive.zip", b"some zip data", "application/zip")},
    )
    assert response.status_code == 400
    assert "Unsupported document format '.zip'" in response.json()["detail"]


def test_blog_upload_empty_file_rejected(client: TestClient):
    """Verifies that an empty 0-byte document returns HTTP 400."""
    response = client.post(
        "/api/jobs",
        data={"input_type": "blog"},
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 400
    assert "empty (0 bytes)" in response.json()["detail"]


def test_blog_upload_oversized_file_rejected(client: TestClient):
    """Verifies that a document exceeding 10 MB returns HTTP 413."""
    oversized = b"x" * (11 * 1024 * 1024)  # 11 MB
    response = client.post(
        "/api/jobs",
        data={"input_type": "blog"},
        files={"file": ("huge.txt", oversized, "text/plain")},
    )
    assert response.status_code == 413
    assert "exceeds maximum allowed limit" in response.json()["detail"]


def test_video_upload_still_rejects_txt(client: TestClient):
    """Verifies that video upload still strictly requires .mp4."""
    response = client.post(
        "/api/jobs",
        data={"input_type": "video"},
        files={"file": ("not_a_video.txt", b"some text", "text/plain")},
    )
    assert response.status_code == 400
    assert "Only .mp4 video files are accepted" in response.json()["detail"]

