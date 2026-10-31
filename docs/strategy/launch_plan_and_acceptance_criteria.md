# IncuBrix Launch Plan, Audience Testing, and Acceptance Criteria
**Document:** `docs/strategy/launch_plan_and_acceptance_criteria.md`  
**Phase:** Phase 2 — Content Strategy and Technical Design (Integrity Corrected)  
**Date:** October 29, 2026  
**Status:** DESIGN & STRATEGY ONLY (Pre-implementation)

---

## 1. 30-Day Launch Campaign Blueprint

The 30-day launch plan outlines a structured, reproducible social distribution campaign designed to establish consistent organic reach, test audience resonance, and drive qualified traffic to `app.incubrix.com`.

### 1.1. 30-Asset Distribution Matrix Across 4 Platforms

The engine generates a publishing library of **30 production-ready content assets**, exceeding the assessment requirement ($\ge 30$ finished assets, $\ge 10$ short videos, $\ge 5$ carousels, across $\ge 3$ platforms).

```
┌────────────────────────────────────────────────────────────────────────┐
│                        30-ASSET PUBLISHING MATRIX                      │
├─────────────────┬───────────┬──────────────┬─────────────┬─────────────┤
│ Platform        │ Content Format           │ Asset Count │ Video Count │
├─────────────────┼──────────────────────────┼─────────────┼─────────────┤
│ YouTube Shorts  │ 9:16 Vertical MP4 Video  │ 6 Assets    │ 6 Videos    │
│ TikTok / Reels  │ 9:16 Vertical MP4 Video  │ 6 Assets    │ 6 Videos    │
│ LinkedIn        │ 4:5 Multi-Slide Carousels│ 6 Assets    │ 0 Videos    │
│ LinkedIn        │ Long-Form Thought Posts  │ 6 Assets    │ 0 Videos    │
│ X (Twitter)     │ 5-Tweet Discussion Thread│ 6 Assets    │ 0 Videos    │
├─────────────────┴──────────────────────────┼─────────────┼─────────────┤
│ TOTAL FINISHED ASSETS                      │ 30 Assets   │ 12 Videos   │
│ TOTAL FINISHED CAROUSELS / GRAPHICS        │ 6 Decks     │ (36 Slides) │
│ DISTINCT PLATFORMS COVERED                 │ 4 Platforms │             │
└────────────────────────────────────────────┴─────────────┴─────────────┘
```

*Fulfillment Verification:*
* Total finished assets: **30 assets** (Assessment requirement: $\ge 30$).
* Total short-form videos: **12 completed MP4 videos** (Assessment requirement: $\ge 10$).
* Total visual carousels: **6 completed multi-slide decks** (Assessment requirement: $\ge 5$).
* Multi-platform breadth: **4 distinct platforms** (Assessment requirement: $\ge 3$).

### 1.2. 30-Day Publishing Cadence & Schedule

* **Weekly Cadence (7 assets per week, Monday through Sunday):**
  * *Monday:* LinkedIn Thought Leadership Post (Pillar 1: Workflow Education) + X Thread.
  * *Tuesday:* YouTube Shorts #1 (Pillar 2: Hook Writing Tutorial, $\le 45$s MP4).
  * *Wednesday:* LinkedIn Carousel #1 (Pillar 3: 1-to-10 Repurposing Teardown, 6 slides).
  * *Thursday:* TikTok / Reels #1 (Pillar 2: Faceless Video Demo, $\le 45$s MP4).
  * *Friday:* LinkedIn Post #2 (Pillar 5: Attribution Breakdown) + X Thread #2.
  * *Saturday:* YouTube Shorts #2 (Pillar 4: Consistency & CreatorOps, $\le 45$s MP4).
  * *Sunday:* TikTok / Reels #2 (Pillar 1: Workflow Simplification, $\le 45$s MP4).

---

## 2. Operating Procedures, RACI Matrix, and Cost Estimates

```
┌────────────────────────────────────────────────────────────────────────┐
│                        LAUNCH TEAM RACI MATRIX                         │
├────────────────────────────┬─────────┬─────────┬───────────┬───────────┤
│ Operational Task           │ Growth Eng│ Lead Editor│ Content Lead│ CMO/Founder│
├────────────────────────────┼─────────┼─────────┼───────────┼───────────┤
│ Source Document Ingestion  │    R    │    C    │     A     │     I     │
│ Pipeline Run & Validation  │    R    │    C    │     A     │     I     │
│ 20-Asset Quality Audit     │    A    │    R    │     R     │     I     │
│ Scheduler CSV Import       │    C    │    R    │     A     │     I     │
│ Daily Community Engagement │    I    │    R    │     A     │     I     │
│ UTM Analytics Review       │    R    │    I    │     A     │     C     │
└────────────────────────────┴─────────┴─────────┴───────────┴───────────┘
Legend: R = Responsible (Does work), A = Accountable (Final approval), 
        C = Consulted (Provides input), I = Informed (Kept updated).
```

### 2.1. Tooling & Cost Estimation Policy
* **Core Generation & Rendering Stack:** **\$0.00 (Zero Cost).** All asset creation, text-to-speech audio, and video/graphic compositing execute locally using pre-installed open-source libraries (`pillow`, `imageio-ffmpeg`, `gTTS`).
* **AI Generation API:** Optional. In offline deterministic mode, cost is **\$0.00**. In live Gemini 2.5 Flash mode, estimated API token cost is $< \$0.50$ per full 30-asset batch.
* **Third-Party Schedulers:** The engine outputs standard, scheduler-ready CSV files (`calendar.csv`). Importing into a paid scheduler (e.g. Buffer Essentials at ~\$24/mo) is an optional user convenience, NOT a technical requirement. The engine does NOT commit the user to any paid subscription.

---

## 3. Real-Audience Preference Test Design

In strict compliance with assessment integrity standards, **we do not fabricate respondents, manufacture survey metrics, or claim ungrounded statistical significance**. The evaluation is structured as an honest, neutral testing procedure that the user can distribute to real target audience practitioners.

```
┌────────────────────────────────────────────────────────────────────────┐
│                   REAL-AUDIENCE TESTING METHODOLOGY                    │
├───────────────────┬────────────────────────────────────────────────────┤
│ Target Sample Size│ $N \ge 20$ Real Participants                       │
│ Target Cohorts    │ Active Creators, Video Editors, Content Marketers  │
│ Testing Instrument│ Neutral Online Survey (Google Forms)               │
│ Evaluation Format │ Blind A/B Creative Preference Evaluation (4 Tests) │
│ Data Protection   │ Anonymized Participant IDs, Zero PII Collected     │
└───────────────────┴────────────────────────────────────────────────────┘
```

### 3.1. Recruitment, Eligibility & Informed Consent
* **Eligibility Criteria:** Participants must actively produce, edit, or market digital content (videos, podcasts, blogs, or social posts).
* **Recruitment Method:** Direct outreach to professional peers, tech community groups, and LinkedIn connections.
* **Informed Consent:** Participants are informed that the survey is an academic/placement evaluation of creative preferences, responses are completely anonymous, and no personal identifiable information (PII) is collected or stored.

### 3.2. Neutral Survey Structure (4 Blind A/B Creative Pairings)

All stimuli are presented neutrally without brand logos or leading descriptions:

#### Test 1: Video Opening Hook (YouTube Shorts / Reels)
* **Variant A (Traditional Conversational Opening):**  
  *"Hey everyone, in today's video I want to talk about a few different ways you can improve your content repurposing workflow..."*
* **Variant B (Direct Kinetic Hook):**  
  *[High-contrast text card: 'CREATOR WORKFLOWS'] "If you need 5 different tools open just to publish one video, your workflow has an operational bottleneck."*
* **Question:** *"Which video opening would make you more likely to keep watching?"* (Choices: Variant A / Variant B / No preference).

#### Test 2: Informational Structure (LinkedIn Carousel / Document)
* **Variant A (Broad Overview):**  
  A broad summary describing why multi-platform publishing is important for modern brands.
* **Variant B (Structured Workflow Comparison):**  
  A step-by-step visual teardown comparing a disconnected 5-tool process against a unified single-interface repurposing pipeline.
* **Question:** *"Which post format provides more practical value to your team?"* (Choices: Variant A / Variant B / No preference).

#### Test 3: Educational Thread Approach (X / Twitter)
* **Variant A (Generic Tips):**  
  A list of 5 general productivity suggestions for online writers and creators.
* **Variant B (Operational Framework):**  
  A 4-step framework outlining how to systematically extract short clips from a long-form recording.
* **Question:** *"Which thread would you be more likely to bookmark or share?"* (Choices: Variant A / Variant B / No preference).

#### Test 4: Call-to-Action Relevance
* **Variant A (General Promotional CTA):**  
  *"Sign up now for our platform to transform your social media growth!"*
* **Variant B (Specific Educational CTA):**  
  *"Explore how Creator Studio consolidates transcription and scheduling on the free exploration tier."*
* **Question:** *"Which call-to-action feels more transparent and relevant?"* (Choices: Variant A / Variant B / No preference).

### 3.3. Response Quality Control & Data Integrity
1. **Attention Check:** One verification question (*"To confirm you are reading each option, please select 'No preference' for this question"*) is embedded to filter low-effort bots or spam.
2. **Completion Time Filter:** Submissions completed in under 45 seconds are flagged and excluded from final tally.
3. **Data Minimization:** No email addresses, phone numbers, or company names are recorded. Participants are referenced solely as `RESP_01`, `RESP_02`, etc.
4. **Honest Reporting Standard:** Results will report actual submission counts ($N$), raw percentage splits, and an explicit statement of sample size limitations. If $N < 20$ at the submission deadline, results will be clearly reported as preliminary exploratory data rather than claiming definitive statistical significance.

---

## 4. Master Acceptance Criteria Checklist

To ensure complete alignment with assessment criteria, every item is tracked across five distinct lifecycle statuses: `DESIGNED`, `IMPLEMENTED`, `GENERATED`, `TESTED`, and `VERIFIED`.

```
┌────────────────────────────────────────────────────────────────────────┐
│                   OPTION 2 MASTER ACCEPTANCE CHECKLIST                 │
├───────────────────────────────────────────────────┬─────────┬──────────┤
│ Assessment Requirement                            │ Target  │ Status   │
├───────────────────────────────────────────────────┼─────────┼──────────┤
│ Total Ready-to-Publish Assets                     │ $\ge 30$│ DESIGNED │
│ Completed Short-Form Videos (<=60s MP4)           │ $\ge 10$│ DESIGNED │
│ Completed Carousels / Graphics (PNG decks)        │ $\ge 5$ │ DESIGNED │
│ Distinct Platforms Covered                        │ $\ge 3$ │ DESIGNED │
│ Pipeline Runtime (<10 assets from 1 input)        │ < 30m   │ DESIGNED │
│ Programmatic Tracking Links (Unique UTMs)         │ 100%    │ DESIGNED │
│ Scheduler-Ready Export (calendar.csv)             │ Valid   │ DESIGNED │
│ Contingency Submission Workbook (workbook.xlsx)   │ Valid   │ DESIGNED │
│ 20-Asset Randomized Quality Audit Pass Rate       │ $\ge 85$│ DESIGNED │
│ Stretch Audit Quality Target                      │ $\ge 90$│ DESIGNED │
│ Real-Audience Test Plan ($N \ge 20$ participants) │ Valid   │ DESIGNED │
│ Monday Morning Launch Kit Document                │ Valid   │ DESIGNED │
│ Demonstration Video 1 (Product Walkthrough <5m)   │ Scripted│ DESIGNED │
│ Demonstration Video 2 (Technical Pipeline Demo <8m)│ Scripted│ DESIGNED │
└───────────────────────────────────────────────────┴─────────┴──────────┘
```

---

## 5. Contingency Workbook Architecture

As established in Phase 0 (Section C), the **official Option 2 Excel submission workbook is MISSING** (only Option 1's workbook was found in Downloads).

To maintain absolute transparency and avoid misrepresenting an unofficial file as a company-issued template:
* The engine will generate a 6-tab `workbook.xlsx` using `openpyxl`.
* Every sheet will carry an explicit disclaimer:  
  > **"CONTINGENCY REPLACEMENT WORKBOOK (Option 2: Social Media Marketing & Content Engine) — Programmatically generated adhering to Assessment Rubric Standards. Pending confirmation from IncuBrix hiring team."**
* Formula cells (green) and user input cells (yellow) will preserve native Excel formulas (`COUNTA`, `SUM`, `AVERAGE`).

---

## 6. Demonstration Video Outlines

1. **Video 1: Product & Content Strategy Walkthrough ($< 5$ minutes):** Explaining the target audience pain points, the 5 content pillars, the multi-platform distribution strategy, and the 30-day launch roadmap.
2. **Video 2: Technical Engine Demo ($< 8$ minutes):** Showing the live CLI pipeline run, generating 30 assets and physical media in seconds, testing a new input file, and demonstrating automated error recovery when invalid constraints are injected.
