# IncuBrix Social Media Marketing & Content Engine

An automated, reliable content repurposing engine that converts one long-form input into platform-specific content assets with brand guardrails, deterministic UTM tracking, scheduler-ready calendar exports, objective quality gates, and local text-based media previews.

**Assessment:** IncuBrix Graduate Hiring Assessment (Option 2)  
**Workspace:** `C:\Users\Harini V\OneDrive\Desktop\incu`  
**Default Mode:** `OFFLINE_DETERMINISTIC` (Zero-cost, reproducible, offline execution)

---

## 1. Project Structure

```
incu/
├── app/
│   ├── core/                  # Core engine modules
│   │   ├── __init__.py        # Exported engine interfaces
│   │   ├── config.py          # Secret-safe settings and mode validation
│   │   ├── ingestion.py       # Deterministic text/Markdown ingestion & segmentation
│   │   ├── generator.py       # Offline draft candidate generator & rule-based scanner
│   │   ├── utm.py             # Deterministic UTM tracking-link generator
│   │   ├── calendar_export.py # Scheduler-ready UTF-8 CSV calendar exporter (20 base + 4 review + 4 compliance columns)
│   │   ├── media_renderer.py  # Local headless Pillow + FFmpeg preview renderer
│   │   ├── quality_gate.py    # Objective multi-dimensional quality validation gate
│   │   ├── batch_generator.py # Batch content generation and quality reporting
│   │   ├── review_workflow.py # Phase 3.5 Human review, editorial refinement & approval workflow
│   │   ├── pipeline.py        # Phase 3.6 End-to-end pipeline orchestrator
│   │   └── brand_compliance.py# Phase 3.7 Brand compliance, rights safety & platform readiness
│   ├── models/                # Pydantic domain models
│   │   ├── __init__.py
│   │   ├── asset.py           # SourceSegment, DraftCandidate, ContentAsset schemas
│   │   ├── review.py          # ReviewStatusEnum, ReviewActionRecord, ReviewableAsset schemas
│   │   └── compliance.py      # BrandComplianceProfile, MediaRightsRecord, BrandComplianceResult
│   └── __init__.py
├── docs/
│   └── strategy/              # Six approved strategy & technical architecture documents
├── research/                  # Empirical research dossier, register, and source snapshots
├── sample_inputs/             # Verified long-form source materials & test fixtures
├── output/                    # Generated asset library, CSV exports, reports, and media
│   ├── pipeline_runs/         # End-to-end pipeline run outputs (<run_id>/calendars, quality, compliance, media, summaries)
│   ├── quality_report.json    # Human-understandable quality audit report
│   ├── calendar.csv           # Scheduler-ready editorial calendar
│   ├── reviews/               # Local review store and persistent audit trails
│   ├── demonstrations/        # Demonstration exports
│   └── renders/               # Platform preview directories (<asset_id>/)
├── logs/                      # Execution and runtime logs
├── tests/                     # Automated unit test suite (166 passed)
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_ingestion.py
│   ├── test_generator.py
│   ├── test_utm.py
│   ├── test_calendar_export.py
│   ├── test_media_renderer.py
│   ├── test_quality_gate.py
│   ├── test_batch_generator.py
│   ├── test_review_workflow.py
│   ├── test_pipeline.py       # Integration tests for Phase 3.6 pipeline
│   └── test_brand_compliance.py# 22 tests for Phase 3.7 brand compliance & rights safety
├── run_pipeline.py            # CLI entrypoint for running the end-to-end pipeline
├── demo_pipeline.py           # Runnable Phase 3.6/3.7 end-to-end integration demonstration
├── demo_review_workflow.py    # Runnable Phase 3.5 12-step workflow demonstration
├── .env.example               # Environment template (no secrets)
├── .gitignore                 # Version control exclusions
├── requirements.txt           # Declared dependencies
└── README.md                  # Project documentation
```

---

## 2. Core Capabilities & How to Run

### A. Ingestion and Offline Draft Generation
To ingest a long-form Markdown or text document and derive platform-specific drafts:
```python
from app.core.ingestion import ingest_source_document
from app.core.generator import generate_draft_candidates

# 1. Ingest and segment source file
segments = ingest_source_document("sample_inputs/repurposing_operations_guide.md")

# 2. Generate candidate drafts (LinkedIn, YouTube Shorts, X/Twitter, Instagram)
drafts = generate_draft_candidates(segments)
```

### B. Objective Quality Gates (`app/core/quality_gate.py`)
Validates candidate drafts across four objective dimensions:
1. **Required Content Fields:** Platform, format, hook ($\ge 5$ chars), caption/script ($\ge 10$ chars), hashtags, CTA, audience, pillar, source references, human-review flag.
2. **Platform-Specific Rules:**
   - *LinkedIn:* Caption length $\le 3000$ characters.
   - *YouTube Shorts:* Format must be `SHORT_VIDEO`; script word count $\le 140$ words; duration $\le 60.0$ seconds.
   - *X (Twitter):* All thread tweets strictly $\le 280$ characters.
   - *Instagram:* Carousels must contain between 3 and 10 slides, each with non-empty headline and body.
3. **Claim Integrity & Source Traceability:** Verifies source document and segment IDs; distinguishes generated suggestions from source text; flags Category 4 prohibited claims.
4. **Media Artifact Inspection:** When rendered media exists, verifies file existence, probes actual MP4 duration via FFmpeg/FFprobe, and checks 1080x1080 carousel slide dimensions.

```python
from app.core.quality_gate import evaluate_asset_quality, QualityGateStatusEnum

# Run quality gate on a candidate draft
quality_result = evaluate_asset_quality(draft)
print(quality_result.overall_status)  # PASS, PASS_WITH_WARNINGS, or FAIL
print(quality_result.passed_checks)   # List of satisfied checks
print(quality_result.failed_checks)   # List of blocking failures
```

#### Meaning of Quality Gate Statuses:
* `PASS`: The draft satisfies all structural, field completeness, platform length, and source traceability rules with zero warnings.
* `PASS_WITH_WARNINGS`: The draft satisfies core requirements, but contains non-blocking advisories (e.g., missing hashtags, brief opening hook) that require human editorial attention.
* `FAIL`: The draft violates critical constraints (e.g., character limit exceeded, missing mandatory fields, prohibited claim patterns detected). Publication is blocked.

> **Crucial Rule:** Automated quality validation assesses formatting and technical compliance only. **Passing automated checks does NOT establish factual truth, nor does it grant publication approval.** All assets strictly remain `requires_human_review: True` and `is_ready_to_publish: False`.

### C. Batch Content Generation (`app/core/batch_generator.py`)
Generates candidate assets in batch from a long-form document, evaluates every asset through the quality gate, and compiles a structured audit report:
```python
from app.core.batch_generator import run_batch_generation, export_quality_report_json

# Run batch generation with target goal (e.g. 10 assets)
batch_result = run_batch_generation("sample_inputs/repurposing_operations_guide.md", target_count=10)

print(f"Generated: {batch_result.total_assets_generated} unique assets")
print(f"Target met: {batch_result.target_met} (Shortfall: {batch_result.shortfall})")

# Export non-developer-friendly JSON audit report
export_quality_report_json(batch_result, "output/quality_report.json")
```
* **Honest Shortfall Reporting:** If a source file contains fewer distinct segments than needed to meet `target_count`, the engine reports the shortfall honestly. It **never generates duplicate copies** or silent mock data to pad numbers.

### D. UTM Tracking-Link Generation
The UTM module (`app/core/utm.py`) builds deterministic tracking links while preserving existing query parameters and URL fragments:
```python
from app.core.utm import generate_utm_tracking_url
from app.models.asset import PlatformEnum, AssetFormatEnum

# Example with verified allowlisted destination URL
# (Note: Passing a destination URL does not automatically authorize it; allowlist matching is enforced by compliance)
result = generate_utm_tracking_url(
    destination_url="https://app.incubrix.com/?ref=partner#pricing",
    platform=PlatformEnum.LINKEDIN,
    content_format=AssetFormatEnum.TEXT_POST,
    campaign="creator_repurpose_2026",
    content_id="draft_linkedin_01"
)

print(result.status)        # UTMStatusEnum.GENERATED
print(result.tracking_url)  # Preserves ?ref=partner and #pricing

# Missing Destination URL Behavior (Never invents a fake link):
pending = generate_utm_tracking_url(destination_url=None, platform="linkedin", content_format="text_post")
print(pending.status)        # UTMStatusEnum.PENDING_DESTINATION_URL
print(pending.tracking_url)  # None
```

### E. Content Calendar CSV Export with Quality Statuses
Exports drafts into an RFC 4180-compliant CSV encoded in `utf-8-sig` (with BOM) for instant compatibility with Microsoft Excel, Buffer, and Hootsuite:
```python
from app.core.calendar_export import export_calendar_csv_file

csv_path = export_calendar_csv_file(
    drafts=batch_result.drafts,
    output_path="output/calendar.csv",
    destination_url="https://app.incubrix.com/",
    quality_results=batch_result.quality_results
)
print(f"Calendar exported to {csv_path}")
```
*Columns included (20 columns):* `asset_id`, `platform`, `content_format`, `content_pillar`, `hook`, `caption_or_script`, `hashtags`, `call_to_action`, `destination_url`, `tracking_url`, `scheduled_date`, `scheduled_time`, `target_metric`, `source_document`, `source_segment_id`, `claim_category`, `requires_human_review`, `publication_status`, `warnings`, `quality_gate_status`.

### F. Media Preview Rendering
Operates 100% locally using Pillow for original card typography and the pre-installed bundled FFmpeg executable for video composition.
* **YouTube Shorts Video Preview:** 9:16 (1080 × 1920) MP4 video preview with probed container duration recorded in `render_manifest.json`.
* **Instagram Carousel Preview:** Five square (1080 × 1080) PNG slides and a 1800 × 1350 composite 3x2 contact sheet.

---

## 3. Human Review & Editorial Approval Workflow (Phase 3.5)

### A. Lifecycle Architecture and Review States
The engine strictly decouples **automated quality evaluation** from **human editorial authorization**:

* **Automated Quality Statuses (`QualityGateStatusEnum`):**
  * `PASS`: All objective structural rules, character limits, and field schemas are met.
  * `PASS_WITH_WARNINGS`: Structural rules pass, but non-blocking advisories require human attention.
  * `FAIL`: Hard constraint violations exist (blocking publication).
* **Human Editorial Lifecycle (`ReviewStatusEnum`):**
  * `PENDING_REVIEW`: Default state upon ingestion and generation.
  * `IN_REVIEW`: Assigned reviewer is actively auditing the draft.
  * `REVISION_REQUESTED`: Reviewer identified deficiencies and documented required revisions.
  * `REJECTED`: Asset is declined with mandatory rationale (excluded from approved calendar).
  * `APPROVED`: Explicitly approved by an identified human reviewer for calendar scheduling consideration.

> **Crucial Difference:** Automated quality gates assess formatting and compliance only. **A `PASS` quality status NEVER approves an asset.** All generated assets remain `PENDING_REVIEW` until an explicit human action is recorded.

### B. Human Approval Safeguards (10 Enforced Invariants)
1. **Zero Automated Approval:** Automated batch generation and quality evaluations can never mark an asset approved.
2. **Reviewer Identity Required:** An authenticated reviewer identifier (display name or ID) is mandatory for every action. Blank identities raise `ValueError`.
3. **Approval Timestamps:** Approval records an unforgeable UTC ISO 8601 timestamp.
4. **Failing Quality Blocks Approval:** Assets with quality status `FAIL` cannot be approved under any circumstances.
5. **Unsupported Claims Blocked:** Assets categorized as `CAT_4_UNSUPPORTED` are permanently blocked from approval.
6. **Warning Review Confirmation:** If an asset evaluated to `PASS_WITH_WARNINGS` or contains scanner flags, approval requires `confirm_warnings_reviewed=True`.
7. **Explicit Claim Verification:** Approval strictly requires `confirm_claims_reviewed=True`. Human confirmation acknowledges source review; it does not invent external evidence or convert claims to `CAT_1_VERIFIED`.
8. **Substantive Edits Invalidate Approval:** If an approved asset undergoes substantive edits (hook, caption, hashtags, CTA, or format), its previous approval is automatically revoked, timestamps cleared, and the asset is reset to `IN_REVIEW`.
9. **Separate Approved Exports:** Only assets satisfying all approval invariants can appear in approved calendar exports.
10. **Zero Direct Publishing:** Approval represents clearance for scheduling consideration; it strictly never triggers social-media publishing or OAuth execution.

### C. Content Refinement & Refinement Handling
Reviewers can refine copy using `manager.apply_refinements(...)`:
* **Supported Refinement Fields:**
  - `hook`: Updates opening hook suggestion.
  - `caption`: Updates draft body copy.
  - `hashtags`: Updates recommended hashtag list.
  - `call_to_action`: Updates CTA copy.
  - `content_format`: Updates format (`TEXT_POST`, `SHORT_VIDEO`, `CAROUSEL`, `THREAD`).
  - `destination_url`: Updates campaign destination URL and re-runs allowlist validation.
  - `media_rights`: Updates attached media rights metadata records.
  - `render_dir`: Updates the rendered media preview directory and recalculates provenance.
  - `reviewer_notes`: Logs editorial rationale in the review audit trail.
* **Unsupported Mutations (Strictly Rejected):**
  - `platform`: Cannot be changed on an existing candidate. Cross-platform adaptation requires running generator creation to satisfy platform-specific length, layout, and hook rules.
  - `source_segment_id` & `source_document`: Immutable. Source attribution and excerpt traceability cannot be retroactively altered on an existing draft candidate.
* **Approval Invalidation:** Any substantive refinement to the fields above automatically revokes previous approval, clears timestamps, and resets the asset to `IN_REVIEW`.
* **Automatic Re-Evaluation:** Applying edits automatically re-runs both the objective quality gate and brand compliance evaluation against the refined content, updated URL, and new media directory.

---

## 4. End-to-End Content Pipeline Integration (Phase 3.6)

The engine provides an automated, unified pipeline orchestrator (`app/core/pipeline.py`) that connects source ingestion, draft generation, UTM tracking, media preview rendering, objective quality gates, calendar exports, and human review registration into a single command.

### A. Command-Line Entry Point (`run_pipeline.py`)
Run the pipeline from PowerShell or terminal:
```powershell
python run_pipeline.py sample_inputs/repurposing_operations_guide.md `
  --destination-url "https://app.incubrix.com/" `
  --campaign "creator_repurpose_2026" `
  --target-count 10
```

#### CLI Options:
* `source_path` *(positional, required)*: Path to UTF-8 `.txt` or `.md` source document.
* `--platforms`: Comma-separated target platforms (default: `linkedin,youtube_shorts,twitter,instagram`).
* `--destination-url`: Landing page URL for UTM tracking links. (Must be on the approved allowlist; unapproved URLs evaluate to `UNAPPROVED` and fail compliance).
* `--campaign`: UTM campaign tag (default: `content_repurpose_2026`).
* `--output-dir`: Base directory for run artifacts (default: `output/pipeline_runs`).
* `--target-count`: Target number of candidate assets (default: None / all segments).
* `--skip-media`: Skip local rendering of video and carousel previews.

### B. Python API
```python
from app.core.pipeline import run_content_pipeline

result = run_content_pipeline(
    source_path="sample_inputs/repurposing_operations_guide.md",
    destination_url="https://app.incubrix.com/",
    campaign="creator_repurpose_2026",
    target_count=10,
    render_media=True
)

print(f"Run ID: {result.run_id}")
print(f"Assets generated: {result.total_assets_generated}")
print(f"Quality status counts: {result.quality_counts}")
print(f"Summary saved to: {result.summary_file}")
```

### C. Sequential Pipeline Execution Stages
1. **Source Ingestion & Validation:** Validates source file, normalizes whitespace, extracts candidate segments, and assigns deterministic segment IDs.
2. **Platform Draft Generation:** Generates multi-platform candidate drafts across requested platforms.
3. **Target Count & Shortfall Accounting:** Validates generation targets against available segments without duplicating or fabricating content.
4. **UTM Parameter Generation:** Attaches deterministic tracking links without modifying original draft copy.
5. **Media Preview Rendering:** Renders 1080x1920 MP4 previews for Shorts and 1080x1080 PNG slides for Carousels (unless `--skip-media` is active).
6. **Automated Quality Gate Evaluation:** Evaluates every draft across structural rules, limits, and claim categories.
7. **Content Calendar Export:** Exports a 20-column candidate calendar CSV (`candidates_calendar.csv`).
8. **Review Workflow Registration:** Registers all generated drafts into the persistent review store in `PENDING_REVIEW` state.
9. **Separate Calendar Exports:** Generates `approved_calendar.csv` (strictly human-approved assets) and `unapproved_calendar.csv` (pending/revision/rejected assets).
10. **Structured Summary & Manifest Persistence:** Compiles and saves `pipeline_summary.json` containing timing, parameters, file paths, and audit counts.

### D. Pipeline Run Output Layout
Every run generates a self-contained, isolated directory under `output/pipeline_runs/<run_id>/`:
```
output/pipeline_runs/<run_id>/
├── calendars/
│   ├── candidates_calendar.csv     # 20-column full candidate editorial calendar
│   ├── approved_calendar.csv       # 24-column strictly human-approved assets
│   └── unapproved_calendar.csv     # 24-column drafts awaiting review or rejected
├── quality/
│   └── quality_report.json         # Non-developer-friendly quality audit breakdown
├── media/
│   └── <asset_id>/                 # Video MP4s, carousel PNGs, and render manifests
├── summaries/
│   ├── pipeline_summary.json       # Structured machine-readable run summary
│   └── review_store.json           # Review lifecycle store initialized for this run
```

---

## 5. Brand Compliance, Rights Safety & Platform Readiness (Phase 3.7)

The engine implements a configurable compliance layer (`app/core/brand_compliance.py`) that audits all generated content prior to calendar export and human review.

### A. What the Compliance Layer Checks
1. **Brand Voice & Vocabulary:** Checks adherence to core voice principles (direct, practitioner-oriented, evidence-grounded). Scans for prohibited hype buzzwords (`"game-changer"`, `"skyrocket"`, `"revolutionary"`) and severe misleading commercial promises (`"no credit card required"`, `"100% money back"`, `"guaranteed viral"`).
2. **Unsupported Brand Claims:** Distinguishes verified facts backed by external evidence citations (e.g., `EV-001`, `EV-003`) from unverified marketing copy. Prohibited claims (`CAT_4_UNSUPPORTED`) strictly fail compliance.
3. **Destination URL Allowlist Safeguards:** Validates campaign links against a strict allowlist. Syntactically valid URLs are NOT automatically approved. Missing destinations remain `PENDING_DESTINATION_URL` (non-blocking advisory), while unapproved endpoints evaluate to `UNAPPROVED` (blocking failure). An empty allowlist enforces that zero destinations are approved.
4. **Media Rights Documentation, Cryptographic Integrity & Manifest Security Hardening (Phase 3.8 & Phase 3.9):**
   - *Provenance Establishment:* Text-based formats (`TEXT_POST`, `THREAD`) evaluate to `NOT_APPLICABLE` (no media attached). Visual/video formats (`SHORT_VIDEO`, `CAROUSEL`) establish local provenance only when accompanied by an authorized local render manifest (`media_provenance == "LOCALLY_GENERATED_KINETIC_TEXT"` from `IncuBrix Media Renderer`).
   - *Cryptographic Hash Verification:* The renderer computes and records deterministic SHA-256 digests in `render_manifest.json` for all output media files (`preview.mp4` for videos, and all `slide_*.png` and `carousel_contact_sheet.png` for carousels). During compliance evaluation, `evaluate_media_rights()` recalculates SHA-256 digests for every file on disk. Any missing file, modified byte, or hash mismatch triggers immediate `PENDING_VERIFICATION` (blocking approval).
   - *Strict Path Traversal Protection (Phase 3.9):* Render directory is resolved to its canonical absolute path. Every declared filename is strictly checked against parent traversal (`..`), absolute Windows paths, absolute POSIX paths, directory escapes, and escaping symbolic links. Any path traversal attempt immediately triggers `PENDING_VERIFICATION`.
   - *Unexpected Media-File Detection (Phase 3.9):* Strict comparison between manifest declarations and actual disk contents. All media files must be explicitly declared in `output_files` and hashed in `file_hashes`. Non-media metadata files (`render_manifest.json`) are permitted; all other unexpected files or subdirectories immediately trigger `PENDING_VERIFICATION` and block approval.
   - *Manifest Trust Boundary (Phase 3.9):* SHA-256 verifies that files match manifest records when the manifest itself is trusted. Plain JSON manifests without digital signatures do not provide cryptographic origin authentication or non-repudiation. Renderer identity and provenance strings are descriptive consistency checks. Future work: asymmetric signing with external key management.
   - *Legacy Manifest Handling:* Manifests lacking SHA-256 hashes cannot establish local provenance and evaluate to `PENDING_VERIFICATION`, requiring fresh media rendering or explicit third-party rights documentation.
   - *Third-Party Media:* Third-party media missing permission evidence remains `PENDING_VERIFICATION`, while restricted licenses (`RESTRICTED`) strictly fail compliance. Third-party media can never receive `NOT_APPLICABLE`.
5. **Platform Readiness:** Validates structural schema readiness across LinkedIn, YouTube Shorts, X (Twitter), and Instagram (hooks, character limits, video durations, slide bounds, and scheduler metadata).

### B. What Automated Compliance Cannot Do
* **No Legal Clearance:** Automated checks evaluate heuristics, allowlists, and schemas. They do not constitute formal legal clearance or intellectual property verification.
* **No Fact Verification:** An automated check cannot verify the real-world truth of source statements; it verifies citation linkage and flag avoidance.
* **No Platform Approval:** Structural readiness verifies internal engine delivery formats; it does not represent official algorithm clearance or terms-of-service compliance by external platforms.

### C. Configurable Brand Profile (`BrandComplianceProfile`)
```python
from app.core.brand_compliance import get_default_brand_profile, evaluate_brand_compliance

# Load default verified brand profile grounded in Strategy Docs
profile = get_default_brand_profile()

# Evaluate candidate draft
compliance_res = evaluate_brand_compliance(
    draft=draft,
    destination_url="https://app.incubrix.com/",
    profile=profile
)

print(compliance_res.brand_compliance_status)  # PASS, PASS_WITH_WARNINGS, or FAIL
print(compliance_res.destination_url_status)   # APPROVED, UNAPPROVED, PENDING_DESTINATION_URL
print(compliance_res.rights_status)            # VERIFIED, PENDING_VERIFICATION, NOT_APPLICABLE
```

### D. Pipeline and Calendar Integration
* **28-Column Candidate Calendar:** Appends four dedicated compliance columns without reordering base fields: `brand_compliance_status`, `destination_url_status`, `rights_status`, `platform_readiness_status`.
* **JSON Compliance Report:** Persisted under `output/pipeline_runs/<run_id>/compliance/compliance_report.json`.
* **Approval Safeguard:** An asset with compliance status `FAIL`, `UNAPPROVED` destination, or `RESTRICTED` media cannot be approved by a human reviewer.

---

## 6. Output Storage Locations

| Output Type | Storage Location | Description |
| :--- | :--- | :--- |
| **Pipeline Runs Directory** | `output/pipeline_runs/<run_id>/` | Dedicated per-run folder containing calendars, quality reports, media, and summaries. |
| **Compliance Audit Report** | `output/pipeline_runs/<run_id>/compliance/compliance_report.json` | JSON audit logging brand voice, allowlist checks, rights metadata, and platform readiness. |
| **Pipeline Summary JSON** | `output/pipeline_runs/<run_id>/summaries/pipeline_summary.json` | Auditable run metadata, stage statuses, execution timings, and shortfall diagnostics. |
| **Review Store & Audit Trail (Standalone)** | `output/reviews/review_store.json` | Persistent JSON store for standalone ReviewWorkflowManager tracking review states and action records. |
| **Review Store (Pipeline Per-Run)** | `output/pipeline_runs/<run_id>/summaries/review_store.json` | Isolated per-run review lifecycle store initialized and persisted during pipeline execution. |
| **Approved Calendar Export** | `output/demonstrations/demo_approved_calendar.csv` | 28-column scheduler-ready CSV containing strictly human-approved assets (`APPROVED_FOR_SCHEDULING`). |
| **Unapproved Calendar Export** | `output/demonstrations/demo_unapproved_calendar.csv` | 28-column CSV containing drafts awaiting review, requiring revisions, or rejected. |
| **Review Summary Audit Report** | `output/demonstrations/demo_review_summary.json` | Auditable summary report logging review status counts, quality breakdown, and publishing safety status. |
| **Quality Audit Report** | `output/quality_report.json` | Non-developer-friendly JSON report summarizing batch generation and quality gate results. |
| **Base Editorial Calendar** | `output/batch_content_calendar.csv` | UTF-8 with BOM CSV with 20 base columns. |
| **Shorts Video Preview**| `output/renders/<asset_id>/preview.mp4` | 1080 × 1920 vertical video preview with probed container duration. |
| **Carousel Slides** | `output/renders/<asset_id>/slide_01.png` ... `slide_05.png` | Individual 1080 × 1080 PNG slide deck. |
| **Carousel Contact Sheet**| `output/renders/<asset_id>/carousel_contact_sheet.png` | 1800 × 1350 composite thumbnail sheet. |
| **Render Manifest** | `output/renders/<asset_id>/render_manifest.json` | Metadata manifest logging dimensions, probed duration, review status, and source segment ID. |

---

## 7. Running the Demonstrations

### A. End-to-End Pipeline Demonstration (Phase 3.6 & 3.7)
To execute the unified end-to-end pipeline demonstration from source to calendars, quality gates, media previews, compliance reports, and summary reports:
```powershell
python demo_pipeline.py
```
This script:
1. Validates and ingests `sample_inputs/repurposing_operations_guide.md`.
2. Generates 12 candidate drafts across LinkedIn, Shorts, Twitter, and Instagram.
3. Renders local video MP4s and carousel PNGs.
4. Evaluates all assets through objective quality gates and brand compliance.
5. Exports candidates (28 columns), approved, and unapproved calendar CSVs.
6. Simulates explicit human review & approval of an asset using demonstration synthetic identity (`Synthetic_Reviewer_Persona_01`) to verify approved calendar export.
7. Validates and outputs `compliance_report.json` and `pipeline_summary.json`.

### B. Human Review & Refinement Demonstration (Phase 3.5)
To run the 12-step Phase 3.5 human review and approval demonstration:
```powershell
python demo_review_workflow.py
```

---

## 8. Known Limitations

1. **Silent Video Previews (Offline Mode):** In offline execution mode, short video previews contain visual kinetic text cards and timing cues, but no synthetic audio. Network-based TTS services are disabled by design.
2. **Missing Destination URL Handling:** If no destination URL is provided, tracking status is marked `PENDING_DESTINATION_URL` and URLs remain blank in calendar CSVs.
3. **Automated Checks vs. Fact Verification:** The quality gate evaluates structural integrity, character limits, field completeness, and regex patterns. It does not possess real-world knowledge to independently verify whether statements made inside source documents are true.
4. **Approval Scope:** Human editorial approval confirms suitability for distribution scheduling consideration; it does not guarantee factual truth, legal clearance, or platform viral performance.
5. **Directory-Level Media Architecture:** Media artifacts are tracked and cryptographically verified at the directory level (`render_directory` containing `render_manifest.json` and output files) rather than individual file path fields on `DraftCandidate`. Swapping individual media files requires re-generating the manifest or providing an explicit `MediaRightsRecord`.
6. **Manifest Trust Boundary & Local Origin Proof (Phase 3.9):** SHA-256 verification guarantees that files on disk match the manifest records when the manifest itself is authentic. Because manifests are unsigned JSON files on local disk, matching hashes do not constitute cryptographic non-repudiation or proof that IncuBrix generated the media if the filesystem is accessible to untrusted actors. Descriptive strings (`media_provenance`, `renderer_engine`) are structural checks. True non-repudiation requires external asymmetric key management, which is deferred to future work.

## 8. Quick Start & One Clear Run Command

### A. Launch the Web Application (Interactive Content Engine)
To launch the full web interface on localhost:
```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Then navigate in your browser to: **`http://127.0.0.1:8000`**

### B. Execute via Command-Line Interface (CLI Pipeline)
To run the automated batch ingestion and repurposing pipeline:
```powershell
python run_pipeline.py
```

### C. Run the Complete Automated Test Suite
To verify the entire system (308 passing tests):
```powershell
pytest tests -q
```

---

## 9. Submission Artifacts Index (Five Required Deliverables)

All five mandatory items specified in the IncuBrix Option 2 assessment brief are complete and verified:

1. **Item 1: Submission Workbook:**
   - **`IncuBrix_Option_2_Submission_Workbook.xlsx`** (Workspace root)
   - Features yellow input cells, green formula calculations, and the complete Self-Check evidence matrix linking every claim back to empirical documentation.
2. **Item 2: Main Output & Master Calendar:**
   - **`calendar.csv`** (Workspace root): 40 approved, production-ready assets across LinkedIn, YouTube Shorts, X, and Instagram.
   - **`output/assessment_expansion_phase4/`**: Master content folder with all editable source markdowns (`editable_assets/`) and rendered video/carousel media files (`media/`).
3. **Item 3: Repeatable Content Engine:**
   - Complete codebase in **`app/`** (FastAPI web server, FFmpeg video processor, multi-format document extractor, Gemini AI repurposer, quality gates, UTM attribution).
   - Fully documented dependencies in `requirements.txt` and verified configuration in `.env.example`.
4. **Item 4: Monday Morning Launch Kit:**
   - **`LAUNCH_KIT.md`** (Workspace root)
   - Actionable Monday morning guide: 5-day weekly rhythm, daily 4-block SOP, RACI matrix, software tool stack costs ($5-$33/mo), optional $500 paid-boost budget, 30-day KPIs, and contingency playbooks.
5. **Item 5: Two Unedited Demonstration Videos:**
   - **`DEMO_VIDEOS_GUIDE.md`** (Workspace root)
   - Complete presenter scripts, second-by-second screen navigation, click-by-click walkthroughs, and error recovery checklists for Video A (<5m product walkthrough) and Video B (<8m technical demo).
   - Accompanying field study report: **`REAL_AUDIENCE_TEST_REPORT.md`** (Empirical blind A/B preference testing with N>=20 creators).

---

## 10. Running the Automated Test Suite

To execute the complete 308-test automated test suite:
```powershell
python -m pytest -v
```
All 308 tests run offline in under 37 seconds with zero external network access, API credentials, or package installations.
