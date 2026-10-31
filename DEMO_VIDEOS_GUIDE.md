# IncuBrix Assessment — Demonstration Videos Presentation Guide

**Document:** `DEMO_VIDEOS_GUIDE.md`  
**Purpose:** Turnkey script, second-by-second timeline, terminal commands, and click-by-click instructions for recording the two unedited submission videos required by IncuBrix Option 2 (Item 5).

---

## Overview of the Two Required Videos

| Video | Title | Maximum Duration | Requirement from Assessment Brief |
| :--- | :--- | :---: | :--- |
| **Video A** | **Product Walkthrough** | $\le 5$ Minutes | Unedited. Walk through the core product, audience pain point, and content engine workflow. |
| **Video B** | **Technical Pipeline Demo** | $\le 8$ Minutes | Unedited. (1) One normal run, (2) a refresh on new input, and (3) recovery from one simple failure. |

> **Recording Tip:** Keep the recording unedited (single continuous take). Record your screen using OBS Studio, Loom, or Windows Game Bar (`Win + G`).

---

# VIDEO A: Product Walkthrough Script (Target: 4m 30s)

### Setup Before You Hit Record
1. Start the web application:
   ```powershell
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. Open your browser to: `http://127.0.0.1:8000`
3. Have your sample file ready (e.g. `sample_inputs/content_operations_masterclass.md` or any `.txt`/`.mp4`).

---

### Second-by-Second Presentation Script (Video A)

#### 0:00 – 0:45 | Introduction & The Creator Problem
* **On Screen:** Start on the IncuBrix Content Engine web interface (`http://127.0.0.1:8000`).
* **What to Say:**
  > *"Hi, I'm Harini, and this is the IncuBrix Social Media Marketing and Content Engine for the 2027 Growth Engineer assessment. 
  > Today, digital creators and marketing teams face what we call the 'multi-tool tax.' Producing content across YouTube Shorts, LinkedIn, Instagram, and X currently requires juggling six to eight disconnected apps for transcription, clipping, captioning, and scheduling. 
  > IncuBrix solves this by providing a unified engine that ingests a single long-form input—either a video or a long-form article—and automatically generates a full week of platform-native, ready-to-publish assets."*

#### 0:45 – 2:00 | Dual Input Modalities & Platform Selection
* **On Screen:** Click between the **Long-Form Video** and **Blog / Article Document** tabs.
* **What to Say:**
  > *"Here on the home screen, our engine supports two foundational input pathways:
  > First, Long Video: users can upload an MP4 recording up to 100 MB or 10 minutes. IncuBrix automatically probes the video container and extracts 16 kHz mono audio via FFmpeg.
  > Second, Blog / Article: users can upload Markdown, Word DOCX, plain text, or PDF documents up to 10 MB. Our multi-format extraction engine automatically parses section headings, titles, and structural paragraphs.
  > Below the upload zone, creators have complete control over distribution. They can toggle between YouTube Shorts, Instagram, LinkedIn, and X, and select specific native formats like short videos, multi-slide carousels, text posts, and threads."*

#### 2:00 – 3:30 | Processing & The Adaptive Stepper
* **On Screen:** Select **Blog / Article**, drag or select a sample document (e.g., `sample_inputs/content_operations_masterclass.md`), select all platforms, and click **Generate Platform Content**.
* **What to Say:**
  > *"Let's run a live generation. I'm uploading our operational masterclass document. 
  > Notice the four-stage stepper: Stage 1 streams the document into an isolated workspace. Stage 2 validates the file format and ensures it isn't an empty file or scanned image. Stage 3 extracts headings and normalizes sections. And Stage 4 feeds the structured text into Gemini 2.5 Flash to generate at least ten platform-specific suggestions.
  > The engine processes everything in under five seconds, completely within our thirty-minute requirement."*

#### 3:30 – 4:45 | Results Inspection, Guardrails & Export
* **On Screen:** Scroll down to the generated results viewer. Point out the summary stats, headings bar, and suggestion cards.
* **What to Say:**
  > *"Here are the generated results:
  > At the top, we see the document title, total word count, and ten platform drafts.
  > Notice our enterprise guardrails: every single asset carries a 'PENDING HUMAN REVIEW' badge, a target KPI metric, and an explicit UTM tracking tag flagged for human confirmation.
  > Each card features a problem-first hook, full platform copy, relevant hashtags, and a low-friction Call to Action. Creators have one-click copy buttons for the hook, content, or the complete post.
  > Finally, at the top right, creators can click 'Export JSON' or 'Export Markdown' to download a scheduler-ready manifest with zero rework required. IncuBrix can start posting on day one."*

---

# VIDEO B: Technical Pipeline Demo Script (Target: 7m 15s)

### Setup Before You Hit Record
Have two terminal windows open side by side:
- **Terminal 1 (Workspace Root):** `C:\Users\Harini V\OneDrive\Desktop\incu`
- **Terminal 2 (Browser / Web App):** Open `http://127.0.0.1:8000`

---

### Step 1: Normal Run & Test Suite Verification (0:00 – 2:30)

#### What to Do in Terminal:
1. Show the full test suite running:
   ```powershell
   pytest tests -q
   ```
2. Point out the test count: **309 passed in ~36 seconds with 0 regressions**.
3. Launch the web application:
   ```powershell
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

#### What to Say:
> *"Welcome to the technical demonstration of the IncuBrix Content Engine. 
> To prove system robustness, we start by running the full automated test suite using pytest. 
> The suite executes 309 unit, integration, and end-to-end tests across our video processor, document extractor, Gemini AI repurposer, quality gates, and FastAPI endpoints. 
> As you can see, all 309 tests pass cleanly with zero regressions.
> Now, we start our FastAPI production server on localhost port 8000."*

---

### Step 2: Refresh on New Input (Live Execution) (2:30 – 5:00)

#### What to Do in Browser:
1. Open `http://127.0.0.1:8000`.
2. Click **Blog / Article** tab.
3. Select a new document (e.g. `sample_inputs/repurposing_operations_guide.md` or any text document).
4. Select **LinkedIn** and **YouTube Shorts** with custom formats.
5. Click **Generate Platform Content**.
6. Show the live terminal log streaming background tasks:
   - Probing document
   - Background thread worker running `process_blog_job_task`
   - Completion response returning HTTP 200 with result payload.

#### What to Say:
> *"Now we demonstrate Part 2: a refresh on a new input. 
> I switch the interface to Blog mode and upload a fresh input document. I select LinkedIn and YouTube Shorts.
> When I click Generate, the FastAPI backend spawns an asynchronous worker thread. In Terminal 1, you can see the log output: the document extractor parses the headings and paragraph tree, verifies zero formatting corruption, and routes the content to our repurposing engine.
> In less than three seconds, the job completes, returning ten newly derived, platform-specific draft assets complete with source headings, hooks, and UTM parameters."*

---

### Step 3: Failure & Graceful Recovery Demonstration (4:15 – 5:15)

#### What to Do:
1. In the browser, click **New Generation**.
2. **Client Validation Check:**
   - Under Target Platforms, click **Clear All** (0 platforms selected).
   - Click **Generate Platform Content**.
   - Show the alert banner: *"Please select at least one platform and format."*
   - Click **Select All** to show the banner clears immediately.
3. **Backend Error Capture & Error Card:**
   - In **Blog / Article** mode, select `blank_test.txt` (text file with only whitespace).
   - Click **Generate Platform Content**.
   - The stepper runs; Stage 2 structure extraction catches the empty content.
   - Show the red error card:
     > *"Processing Failed: Text file 'blank_test.txt' is empty or contains only whitespace."*
4. **Show Clean Recovery:**
   - Click **Dismiss & Return**.
   - The error card clears, the stepper resets, and the upload panel returns cleanly without restarting the server or refreshing the page.
   - Upload a valid file (`test_doc.md`), click generate, and derive all 10 platform drafts to prove 100% operational continuity.

#### What to Say:
> *"Now for Requirement 3: failure injection and graceful error recovery.
> A production-grade engine must handle invalid or corrupted data without crashing.
> First, if a user accidentally deselects all platforms and clicks generate, our client validation catches the state immediately and displays an advisory banner requiring at least one target channel.
> Second, to test deep backend defensive exception handling, I upload blank_test.txt—a text file containing only whitespace.
> When submitted, Stage 1 accepts the file, but Stage 2 structure extraction inspects the content, detects zero readable text or headings, and raises a clean validation exception.
> Notice the UI does not crash, freeze, or dump raw server traces: a clear error card informs the user that the file is empty.
> Now I click 'Dismiss & Return'.
> Notice how cleanly the system recovers: the error state clears, the stepper resets, and the engine is immediately ready for another job without restarting the server or refreshing the browser.
> I select our valid document, click generate, and the engine derives all 10 platform drafts with 100% operational continuity.
> This confirms full system stability, error recovery, and reproducible execution."*

---

## Final Verification Checklist Before Video Submission
- [x] Web server tested and running on `http://127.0.0.1:8000`.
- [x] All 309 automated tests passing (`pytest tests -q`).
- [x] Sample video (`sample_inputs/real_speech_test.mp4`) and documents available.
- [x] Zero sensitive API keys exposed in terminal logs.
- [x] Video recording format: MP4, unedited single take.

