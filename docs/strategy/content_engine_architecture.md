# IncuBrix Content Engine Technical Architecture
**Document:** `docs/strategy/content_engine_architecture.md`  
**Phase:** Phase 2 — Content Strategy and Technical Design (Integrity Corrected)  
**Date:** October 29, 2026  
**Status:** DESIGN & STRATEGY ONLY (Pre-implementation)

---

## 1. System Overview & Technical Environment

The IncuBrix Social Media Marketing and Content Engine is a modular Python pipeline designed to run on the host Windows workstation (`Python 3.14.4`, `Node.js v22.19.0`). Its primary objective is to **convert one long-form source input (webinar transcript, case study, or podcast recording) into at least 10 platform-specific content assets in under 30 minutes**, with brand guardrails, deterministic UTM tracking links, and scheduler-ready exports.

### Host Runtime & Pre-Installed Library Mapping
* **Core Language & Runtime:** Python 3.14.4 (Standard Library: `asyncio`, `hashlib`, `re`, `logging`, `pathlib`, `json`, `csv`, `time`).
* **Data Schemas & Validation:** `pydantic 2.13.4` (Strict type enforcement, runtime validation).
* **Spreadsheets & Data Processing:** `pandas 3.0.2`, `openpyxl 3.1.5` (Cell formatting and formula preservation).
* **Headless Visual & Video Rendering:**
  * `pillow 12.2.0` (Programmatic multi-slide 1080x1350 PNG carousel generation).
  * `imageio-ffmpeg 0.6.0` (Bundled FFmpeg v7.1 binary at `Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe` for stitching 9:16 vertical MP4 video clips).
  * `gTTS 2.5.4` (Text-to-speech voiceover generation).
* **Web UI & API Interface:** `fastapi 0.138.0`, `uvicorn 0.49.0` (Lightweight local dashboard).
* **Automated Testing:** `pytest 9.1.1`, `pytest-asyncio 1.4.0` (Automated quality gate verification).
* **Execution Modes (Strictly Delineated):**
  * *Online LLM Mode:* Uses Google Gemini 2.5 Flash via `google-genai 2.34.0` when a valid key is provided in a local `.env` file.
  * *Offline Deterministic Mode:* Generates structured drafts using supplied source material and predefined algorithmic templates.
  * *Strict Policy:* Missing credentials produce an explicit status (`MODE: OFFLINE_DETERMINISTIC`). The pipeline must never silently claim an LLM was used when running offline, and offline output is never represented as equivalent to live LLM generation. API keys are never requested or exposed in chat or reports.

---

## 2. High-Level Pipeline Architecture

```
[ Long-Form Input File (.md / .txt) ]
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Ingestion & Normalization Module                         │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Semantic Extraction & Segmenter (Hook Miner)             │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Generation Engine (Strictly Labeled Execution Modes)     │
│    ├── Mode A (Online): Gemini 2.5 Flash API (If key in env)│
│    └── Mode B (Offline): Deterministic Template Synthesizer │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Platform Adapter & Pydantic Formatter                    │
│    ├── LinkedIn Posts & 6-Slide Carousels                   │
│    ├── YouTube Shorts Scripts (<=60s)                       │
│    ├── Instagram Reels & Carousels                          │
│    └── X (Twitter) 5-Tweet Threads                          │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. Brand & Claim Guardrails Engine (Tier 1/2/3/4 Checks)    │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. Deterministic UTM & Asset ID Generator (DESIGNED)        │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. Headless Media Renderers (Local Zero-Cost)               │
│    ├── Pillow Renderer ───────► Multi-slide PNG Carousels   │
│    └── imageio-ffmpeg + gTTS ─► 9:16 Vertical MP4 Videos    │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 8. Export & Synchronization Hub                             │
│    ├── Scheduler CSV (Buffer / Hootsuite Compatible)        │
│    ├── Contingency Workbook (workbook.xlsx via openpyxl)    │
│    └── Asset Library (content/ Markdown + Media)            │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. The 13 Core Pipeline Components (Design Specifications)

### Component 1: Input Ingestion and Normalization
* **Status:** `DESIGNED` (To be implemented in Phase 3).
* **Responsibilities:** Ingests long-form text or transcripts (Markdown/TXT), normalizes UTF-8 characters, validates minimum length ($\ge 100$ words), and parses document metadata.
* **Inputs:** Local file path.
* **Outputs:** Cleaned text string and metadata dictionary (`word_count`, `headings`, `detected_type`).
* **Failure Modes & Recovery:** File missing or corrupt encoding $\rightarrow$ Graceful error logging with explicit path report.

### Component 2: Source-Content Extraction and Segmentation (Hook Miner)
* **Status:** `DESIGNED`.
* **Responsibilities:** Scans normalized text to identify key narrative sections: central thesis, supporting arguments, workflow steps, and quantitative points present in the source text.
* **Inputs:** Normalized text string.
* **Outputs:** List of `ContentSegment` objects.
* **Failure Modes & Recovery:** Text lacks clear headers $\rightarrow$ Falls back to sliding sentence-window chunking (~350 words per window).

### Component 3: Hook, Angle, and Draft Generation
* **Status:** `DESIGNED`.
* **Responsibilities:** Produces multiple platform-specific angles from extracted segments.
* **Execution Modes:**
  * *Online LLM Mode:* Activated only when a valid API key exists in local `.env`. Submits structured prompts to Gemini 2.5 Flash.
  * *Offline Deterministic Mode:* Uses predefined structural templates to format source sentences into standard hook archetypes. Does not invent external facts.
* **Auditing:** Every run output records `generation_mode: "ONLINE_LLM"` or `"OFFLINE_DETERMINISTIC"`. Missing API keys are explicitly reported as `LLM_CREDENTIAL_NOT_CONFIGURED`.

### Component 4: Platform-Specific Asset Generation
* **Status:** `DESIGNED`.
* **Responsibilities:** Formats drafts into native structural schemas:
  * *LinkedIn:* Structured posts with line breaks and 6-slide carousel outlines.
  * *YouTube Shorts / Reels:* Spoken voiceover scripts strictly $\le 140$ words ($\le 56$s), paired with visual cues and on-screen text.
  * *X (Twitter):* 5-tweet threads strictly $\le 280$ characters per tweet.
* **Inputs:** Raw angle drafts and segment text.
* **Outputs:** Typed Pydantic asset instances.

### Component 5: Structured Schemas and Validation Gate
* **Status:** `DESIGNED`.
* **Responsibilities:** Enforces programmatic quality checks before assets proceed to rendering:
  * LinkedIn character limit $\le 3,000$.
  * X character limit $\le 280$ per tweet.
  * Shorts/Reels script duration strictly $\le 60.0$ seconds.
  * Mandatory fields present (hook, caption, CTA, verified destination URL).
* **Failure Modes & Recovery:** Over-length copy $\rightarrow$ Automated trimming or regeneration; rejects asset if constraints cannot be met.

### Component 6: Brand and Product-Claim Guardrails Engine
* **Status:** `DESIGNED`.
* **Responsibilities:** Scans copy against the Claim-Verification Policy (Document 2):
  * Blocks Category 4 violations (unverified statistics, fake case studies, fabricated competitor comparisons, unverified offers).
  * Blocks banned AI buzzwords ("game-changer", "magic", "skyrocket").
  * Flags Category 2 claims (advertised but untested features) to ensure transparent framing.
* **Failure Modes & Recovery:** Detection of prohibited terms $\rightarrow$ Hard rejection or automated flag for manual review.

### Component 7: Deterministic UTM Generation and Unique Identifiers
* **Status:** `DESIGNED`.
* **Responsibilities:** Generates deterministic, collision-proof tracking links and asset IDs using SHA-256 hashing.
* **Verification Approach:** Phase 3 automated unit test will assert that 30 generated links produce 30 unique URLs in a collision check.

### Component 8: Headless Media Renderers (Local Zero-Cost)
* **Status:** `DESIGNED`.
* **Responsibilities:**
  * *Pillow Renderer:* Dynamically draws 1080x1350 PNG carousel slides (5–7 slides per deck) with dark-mode card styling, clear typography, and slide counters.
  * *Video Compositor:* Generates voiceover MP3 via `gTTS`, composites background cards and kinetic text overlays via the bundled `imageio-ffmpeg` binary, and outputs 1080x1920 MP4 video files ($\le 60$s).
* **Execution:** 100% local execution; requires zero paid API calls or cloud render farms.

### Component 9: Asset Library Manager
* **Status:** `DESIGNED`.
* **Responsibilities:** Saves output into an organized directory structure:
  * Markdown asset cards with complete copy and metadata under `content/`.
  * Media files (`.mp4`, `.png`) under `content/media/`.
  * Source definitions (`.json`) for audit reproducibility.

### Component 10: Calendar CSV and Contingency Workbook Exporters
* **Status:** `DESIGNED`.
* **Responsibilities:**
  * Compiles assets into a standard `calendar.csv` compatible with external schedulers (Buffer/Hootsuite).
  * Populates a 6-tab `workbook.xlsx` using `openpyxl`, clearly marked as a **Contingency Replacement Workbook** pending hiring team confirmation. Preserves green formula cells and formats yellow input cells.

### Component 11: Duplicate Prevention & Idempotency
* **Status:** `DESIGNED`.
* **Responsibilities:** Guarantees that running the pipeline multiple times on the same input file does not create duplicate rows, conflicting asset IDs, or corrupted files.

### Component 12: Runtime, Cost, and Error Logging
* **Status:** `DESIGNED`.
* **Responsibilities:**
  * Tracks wall-clock execution time via `time.perf_counter()`. (Target: under 30 minutes; offline runs targeted at $<60$ seconds).
  * Reports exact API token expenditure (\$0.00 in offline mode, or measured token costs in live LLM mode).
  * Writes execution logs to `run_report.json`.

### Component 13: Minimal User Interface (FastAPI + Vanilla JS)
* **Status:** `DESIGNED`.
* **Responsibilities:** Provides an optional, lightweight web interface allowing the user to submit an input file, select campaign parameters, monitor progress, preview rendered media, and download CSV/Excel exports. Runs locally via `uvicorn`.

---

## 4. Planned Testing & Quality Verification Approaches

| Dimension | Target Specification | Automated Testing Method in Phase 3 |
| :--- | :--- | :--- |
| **Pipeline Runtime** | $< 30.0$ minutes | Automated timer via `time.perf_counter()`; assert runtime $<1800.0$s. |
| **Video Duration** | Strictly $\le 60.0$s | Automated FFprobe duration check on generated `.mp4` files. |
| **Video Resolution** | 1080 x 1920 (9:16) | Automated FFprobe stream analysis checking width=1080, height=1920. |
| **Carousel Resolution**| 1080 x 1350 (4:5) | Automated `Pillow` image inspection checking `img.size == (1080, 1350)`. |
| **Schema Validity** | 100% compliant | Pydantic model validation on all 30 assets. |
| **UTM Uniqueness** | 0 collisions (30 unique)| Python `set` length test: `len(set(urls)) == len(urls)`. |
| **20-Asset Audit** | $\ge 85\%$ quality score | Automated scoring script running across 20 randomly sampled assets. |
