# IncuBrix Audience and Platform Strategy
**Document:** `docs/strategy/audience_and_platform_strategy.md`  
**Phase:** Phase 2 — Content Strategy and Technical Design (Integrity Corrected)  
**Date:** October 29, 2026  
**Status:** DESIGN & STRATEGY ONLY (Pre-implementation)

---

## 1. Executive Summary & Geographic Focus

This strategy establishes the audience segmentation and platform distribution architecture for the IncuBrix Social Media Marketing and Content Engine. It operationalizes findings from the Phase 1 Research Dossier ([`research/RESEARCH_DOSSIER.md`](file:///c:/Users/Harini%20V/OneDrive/Desktop/incu/research/RESEARCH_DOSSIER.md)) and Evidence Register ([`research/evidence_register.csv`](file:///c:/Users/Harini%20V/OneDrive/Desktop/incu/research/evidence_register.csv)).

### Geographic Scope
In accordance with assessment specifications, the engine targets creators and marketing practitioners in primary English-speaking technology and media hubs:
* **Primary Focus Markets:** United States, Canada, United Kingdom.
* **Secondary Focus Markets:** Australia, Singapore, Ireland, New Zealand.

All positioning, vocabulary, and scheduled publishing time windows are designed around these target timezones (Eastern Time `UTC-5` / `UTC-4`, GMT/BST `UTC+0` / `UTC+1`, and Singapore Time `UTC+8`).

---

## 2. Audience Segmentation & Problem Space

Based on the empirical audit of IncuBrix's public messaging (EV-001, EV-002, EV-005) and competitor observations (OpusClip EV-008, Descript EV-009, Buffer EV-010), the target audience is divided into two operational segments:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        INCUBRIX AUDIENCE MATRIX                        │
├──────────────────────────┬─────────────────────────────────────────────┤
│ Primary Segment (65%)    │ Solo Video Creators, Podcasters, Educators  │
├──────────────────────────┼─────────────────────────────────────────────┤
│ Secondary Segment (35%)  │ B2B SaaS Growth Marketers & Agency Leads    │
└──────────────────────────┴─────────────────────────────────────────────┘
```

### 2.1. Primary Segment: Solo Video Creators, Podcasters & Educators

* **Who They Are:** Independent YouTube creators, podcast hosts, technical newsletter authors expanding into video, and digital educators.
* **Concrete Content-Production Problem:** **The Repurposing Bottleneck.** Producing high-value long-form content requires significant preparation, recording, and editing time. However, manually extracting micro-hooks, formatting vertical clips for 9:16 feeds, adding subtitles, and crafting platform-specific text consumes excessive operational time. Consequently, long-form content often suffers a "one-post lifespan" (EV-006) before losing algorithmic discovery.
* **Current Workaround (Hypothetical Illustrative Model):** Creators typically combine multiple single-purpose tools (e.g., transcription software, clipping utilities, design editors, and scheduling apps) alongside manual copy-pasting.  
  *(Note on Cost/Time Estimates: Industry estimates of "$74+/mo" and "8–10 hours weekly" are conceptual illustrative models for discussion; they are unverified hypotheses and are not treated as empirical facts).*
* **What Useful Content They Seek:**
  1. Actionable video hook formulas designed to hold attention in the first 3 seconds.
  2. Concrete demonstrations of converting one source recording into multiple native formats.
  3. Video creation techniques that emphasize ideas, pacing, and kinetic text rather than requiring on-camera presence (EV-006).
* **Likely Objection to a New Platform:** Skepticism regarding automated tools producing generic, out-of-context clips or unnatural speech synthesis.
* **Desired Conversion Action:** Visit `https://app.incubrix.com/` (EV-004) to explore Creator Studio capabilities on the Free exploration tier (EV-003).
* **Assumptions Needing Validation:** Assumes independent creators prioritize end-to-end workflow speed over frame-by-frame timeline control (*Hypothesis to be evaluated in audience testing*).

### 2.2. Secondary Segment: B2B SaaS Growth Marketers & Content Operations Agencies

* **Who They Are:** Content leads at early/growth-stage software companies and boutique marketing agencies managing multi-channel presence.
* **Concrete Content-Production Problem:** **Attribution Gaps & Multi-Channel Overhead.** Demands for consistent multi-platform publishing are high, but teams struggle to isolate which specific social micro-hook or carousel generated pipeline inquiries or demo requests.
* **Current Workaround:** Delegating manual resizing, caption formatting, and link building across junior staff, external contractors, or spreadsheets.  
  *(Note: Comparative figures such as "$85/asset in-house vs $1.50 programmatic" are conceptual modeling assumptions, not verified historical baselines).*
* **What Useful Content They Seek:**
  1. Methodologies for programmatic UTM tracking to connect specific social hooks to landing page traffic.
  2. Standard operating procedures (SOPs) for maintaining multi-platform posting consistency.
  3. Structured content calendar schemas and multi-format distribution workflows.
* **Likely Objection to a New Platform:** Concerns over custom branding support, terminological accuracy, and compatibility with standard schedulers.
* **Desired Conversion Action:** Review the Content Calendar export schema or schedule an introductory demo via verified company contact channels (`https://www.incubrix.com/how-it-works.html` or `mailto:support@incubrix.com`).
* **Assumptions Needing Validation:** Assumes agency leads prefer standard scheduler-ready CSV exports over direct, unverified API publishing integrations (*Hypothesis*).

---

## 3. Platform Distribution Strategy

To ensure multi-platform coverage that satisfies the assessment's minimum requirement of $\ge 3$ platforms, the engine targets **four platforms**: LinkedIn, YouTube Shorts, Instagram, and X (Twitter).

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PLATFORM ECOSYSTEM MAP                          │
├───────────────┬──────────────┬──────────────────┬──────────────────────┤
│ Platform      │ Role         │ Core Format      │ Key Focus            │
├───────────────┼──────────────┼──────────────────┼──────────────────────┤
│ LinkedIn      │ B2B / Ops    │ Carousels & Text │ Frameworks & Saves   │
│ YouTube Shorts│ Discovery    │ 9:16 Video Clips │ Video Hook Retention │
│ Instagram     │ Visual Proof │ Reels & Carousels│ Visual Summaries     │
│ X (Twitter)   │ Discussion   │ Threads & Quotes │ Rapid Feedback       │
└───────────────┴──────────────┴──────────────────┴──────────────────────┤
```

### 3.1. Platform 1: LinkedIn (B2B Thought Leadership & CreatorOps)
* **Audience Fit & Role:** B2B practitioners, marketing directors, agency leads, and professional creators.
* **Native Technical Specifications:**
  * **Text Posts:** Recommended length 800–1,300 characters (max limit 3,000 characters). Short paragraphs with line breaks optimized for mobile reading.
  * **Document Carousels:** Multi-slide PDF/PNG format, 1080x1350 resolution (4:5 portrait aspect ratio), 5 to 7 slides per deck.
  * **Video (Feed):** 1080x1920 (9:16) or 1080x1080 (1:1), MP4 format, H.264 codec, $\le 60$ seconds, burned-in subtitles.
* **Recommended Posting Frequency:** 4 to 5 posts per week.
* **Best-Suited Content Types:** Workflow comparisons, operational frameworks, and content strategy teardowns.
* **CTA Style:** Conversational engagement or clear destination links to verified product information.
* **Target Success Metrics (Hypotheses):** Bookmark/Save Rate ($\ge 10\%$ target hypothesis), verified comment engagement (aiming to exceed the 0.793% empirical baseline from EV-006).
* **Scheduler Export Format:** Standard CSV schema (`Date`, `Time`, `Platform`, `Post_Text`, `Media_Path`, `UTM_Link`).
* **Risks & Restrictions:** Direct external links in post copy may receive algorithmic reach dampening; strategy specifies testing links in post footer vs. primary comment.

### 3.2. Platform 2: YouTube Shorts (Algorithmic Discovery)
* **Audience Fit & Role:** Broad creator audience seeking video production tutorials and software demonstrations.
* **Native Technical Specifications:**
  * **Dimensions:** Strictly 1080x1920 pixels (9:16 vertical aspect ratio).
  * **Duration:** Strictly $\le 60.0$ seconds (Engine sweet spot: 35–48 seconds; hard cut enforced at 58.0s).
  * **Frame Rate & Codec:** 30 fps, MP4 container, H.264 video codec, AAC audio codec (128 kbps).
  * **Pacing & Text:** High-contrast burned-in subtitles centered within safe zones (avoiding title bar and engagement icons). Spoken rate: 135–145 wpm.
* **Recommended Posting Frequency:** 5 to 7 videos per week.
* **Best-Suited Content Types:** 0–3s hook breakdowns, workflow contrast demonstrations, and quick editing tutorials.
* **CTA Style:** Concise closing audio and on-screen text CTA directing viewers to channel description links.
* **Target Success Metrics (Hypotheses):** 3-Second Retention Rate ($\ge 45\%$ target hypothesis) and Completion Rate ($\ge 35\%$ target hypothesis).
* **Scheduler Export Format:** Standard bulk CSV with `Title` ($\le 70$ chars + `#Shorts`), `Description`, `Tags`, and `Video_Path`.
* **Risks & Restrictions:** Any video exceeding 60.0 seconds forfeits vertical Shorts placement and renders as standard horizontal video.

### 3.3. Platform 3: Instagram (Reels & Carousels)
* **Audience Fit & Role:** Visual creators, agency operators, and digital media designers.
* **Native Technical Specifications:**
  * **Reels:** 1080x1920 (9:16), $\le 60$ seconds, MP4/H.264. Preserves 15% top and 20% bottom margins for interface elements.
  * **Feed Carousels:** 1080x1350 pixels (4:5 portrait) or 1080x1080 (1:1 square), PNG/JPEG format, 5–7 slides.
  * **Caption Limits:** Max 2,200 characters; optimal readability at 150–350 characters.
* **Recommended Posting Frequency:** 4 to 5 times per week.
* **Best-Suited Content Types:** Visual tips, before/after workflow comparisons, and quote cards.
* **CTA Style:** "Link in bio" or directional prompts for bookmarks.
* **Target Success Metrics (Hypotheses):** Post Saves and Shares.
* **Scheduler Export Format:** Standard multi-platform CSV.
* **Risks & Restrictions:** Post caption URLs are non-clickable; traffic conversion requires routing through bio links.

### 3.4. Platform 4: X / Twitter (High-Velocity Discussion)
* **Audience Fit & Role:** Founders, developers, growth engineers, and media commentators.
* **Native Technical Specifications:**
  * **Standalone Posts:** Strictly $\le 280$ characters for standard accounts.
  * **Threads:** 4 to 6 connected posts; opening tweet carries the primary hook, final tweet contains summary and link.
* **Recommended Posting Frequency:** 1 to 2 threads per week, plus 1 daily single-hook post.
* **Best-Suited Content Types:** Contrarian viewpoints, step-by-step numbered breakdowns, and concise quotes.
* **CTA Style:** Direct resource link in closing tweet.
* **Target Success Metrics (Hypotheses):** Retweets, Bookmarks, and Outbound Clicks.
* **Scheduler Export Format:** Standard thread-compatible CSV schema.
* **Risks & Restrictions:** High feed velocity requires strong conceptual clarity within the first 100 characters.

---

## 4. Technical Validation Status of Platform Specifications

| Platform & Specification | Standard Specification | Verification Status | Evidence Source & Limitation |
| :--- | :--- | :--- | :--- |
| **LinkedIn Text Limit** | 3,000 characters | **VERIFIED** | Official LinkedIn Publishing Help Docs. |
| **LinkedIn Carousel Ratio** | 4:5 (1080x1350) / 1:1 | **VERIFIED** | Official LinkedIn Document Ads & Post Spec. |
| **Shorts Duration Limit** | Strictly $\le 60.0$ seconds | **VERIFIED** | YouTube Creator Academy. Hard cut at 58.0s enforced. |
| **Shorts Aspect Ratio** | 9:16 (1080x1920) | **VERIFIED** | YouTube Shorts Technical Upload Guide. |
| **Instagram Reel Specs** | 1080x1920, $\le 90$s | **VERIFIED** | Meta Creator Guidelines. (Engine targets $\le 60$s). |
| **X Tweet Character Limit**| 280 characters | **VERIFIED** | X Developer Platform Documentation. |
| **Direct Publishing APIs**| Auto-publish endpoints | **NOT CONFIGURED** | Out of assessment scope. System exports scheduler-ready CSVs. |

---

## 5. Summary of Strategic Generation Rules

1. **Strict Duration Gate:** Spoken scripts must not exceed 140 words (approx. 56 seconds at 145 wpm). Scripts exceeding this limit fail the automated validation gate.
2. **Platform-Native Formatting:** No cross-posting of identical text. Content must adapt to native structural conventions (e.g. carousels for LinkedIn, vertical videos for Shorts/Reels, threads for X).
3. **Traceable Destination Links:** All tracking links must route to verified live endpoints (`app.incubrix.com`, `incubrix.com/pricing.html`, `incubrix.com/how-it-works.html`).
