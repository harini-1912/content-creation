# IncuBrix Conversion Funnel and Measurement Plan
**Document:** `docs/strategy/conversion_and_measurement.md`  
**Phase:** Phase 2 — Content Strategy and Technical Design (Integrity Corrected)  
**Date:** October 29, 2026  
**Status:** DESIGN & STRATEGY ONLY (Pre-implementation)

---

## 1. End-to-End Conversion Funnel Journey

The IncuBrix social growth engine does not publish content for vanity reach alone. Every asset is structured as an entry point into a multi-stage conversion journey, guiding target creators from discovery to verified platform touchpoints.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        THE 6-STAGE CONVERSION FUNNEL                   │
├─────────┬───────────────────┬──────────────────────────────────────────┤
│ Stage 1 │ Discovery         │ Native social feed exposure              │
│ Stage 2 │ High-Value Content│ Actionable hook, framework, or teardown  │
│ Stage 3 │ Relevant CTA      │ Contextual invitation or verified link   │
│ Stage 4 │ Verified Landings │ Direct to verified IncuBrix web resource │
│ Stage 5 │ Free Exploration  │ Account creation on advertised Free plan │
│ Stage 6 │ User Activation   │ Uploading content to test Studio features│
└─────────┴───────────────────┴──────────────────────────────────────────┘
```

### Detailed Stage Breakdown:
1. **Stage 1 (Discovery):** Audience encounters native content on LinkedIn, YouTube Shorts, Instagram, or X.
2. **Stage 2 (High-Value Content):** Post delivers standalone educational value (e.g., a hook structure, workflow comparison, or editing tip) without demanding an immediate conversion.
3. **Stage 3 (Relevant CTA):** Content concludes with a clear, honest call-to-action (e.g., "Explore IncuBrix Creator Studio", "Save this post for later", or a verified link).
4. **Stage 4 (Verified Landing Destination):** User arrives at a verified live IncuBrix web property.
5. **Stage 5 (Free Exploration):** User explores platform capabilities via the Free plan as advertised on the pricing page (`pricing.html`, EV-003).
6. **Stage 6 (User Activation):** User tests the platform by uploading source content to evaluate Creator Studio capabilities.

---

## 2. Destination URLs & Landing Page Registry

In strict adherence to evidence verification standards, **only exact, verified live URLs** are utilized as publishable tracking destinations. Hypothetical resources are labeled as recommendations requiring implementation, with clearly marked placeholders.

### 2.1. Verified Live Destination Endpoints (Active in Production)

| Destination Role | Verified Target URL | Evidence Reference | Notes & Context |
| :--- | :--- | :--- | :--- |
| **Primary App Portal** | `https://app.incubrix.com/` | EV-004 | Live Vite SPA; self-serve portal. Primary CTA for creator exploration. |
| **Marketing Homepage** | `https://www.incubrix.com/` | EV-001 | Comprehensive product overview & 4 Superpowers. |
| **Pricing Information** | `https://www.incubrix.com/pricing.html`| EV-003 | Public pricing details for Free, Starter (\$10), Essential (\$20), etc. |
| **Product Workflow** | `https://www.incubrix.com/how-it-works.html`| EV-001 | Visual walkthrough of the 4-step repurposing pipeline. |
| **B2B Demo Scheduler** | `https://calendly.com/contact-incubrix/30min?hide_gdpr_banner=1&background_color=0a0e27&text_color=e2e8f0&primary_color=1e6bff` | EV-001 | 30-min team demo scheduler (suitable for agency/B2B inquiries only). |
| **General Support** | `mailto:support@incubrix.com` | EV-001 | Official support contact email. |

### 2.2. Recommended Content Resources (Requiring Engineering Implementation)

To support future content-led conversion, the following web resources are recommended for development:
* *Recommendation R1:* **Interactive Workflow Savings Calculator** (A simple single-page web widget allowing creators to compare multi-tool costs).
* *Recommendation R2:* **Downloadable CreatorOps Calendar Template** (Public Notion/spreadsheet template).
* *Recommendation R3:* **Interactive 3-Second Hook Playground** (A friction-free demo widget on the homepage).

*Strict Publication Gate Policy:* Because recommendations R1–R3 are not currently implemented, **no tracking link may point to them**. Content referencing these concepts must use a clearly marked non-publishable placeholder in draft copy:  
`[CTA_PLACEHOLDER: Pending Live Resource Implementation]`  
Publishable tracking links must strictly route to `https://app.incubrix.com/`, `https://www.incubrix.com/pricing.html`, or `https://www.incubrix.com/how-it-works.html`.

---

## 3. Deterministic Programmatic UTM Architecture (DESIGNED)

*Current Status:* **DESIGNED** (Pending programmatic collision and duplicate checks during Phase 3 implementation).

To ensure measurable link tracking across all generated assets, the engine includes a deterministic UTM generation specification.

### 3.1. UTM Parameter Schema

$$\text{Target URL} = \text{Base URL} + \text{?} + \text{utm\_source} + \text{\&} + \text{utm\_medium} + \text{\&} + \text{utm\_campaign} + \text{\&} + \text{utm\_content}$$

| Parameter | Syntax Rule | Example Value |
| :--- | :--- | :--- |
| `base_url` | Verified destination endpoint | `https://app.incubrix.com/` |
| `utm_source` | Platform name | `linkedin`, `youtube_shorts`, `instagram`, `twitter` |
| `utm_medium` | Asset format | `carousel`, `short_video`, `thread`, `text_post` |
| `utm_campaign` | Unified campaign identifier | `creator_repurpose_2026` |
| `utm_content` | Unique, deterministic asset identifier | `asset_01_linkedin_7a9f12c4` |

### 3.2. Deterministic Identifier & Anti-Collision Specification
To prevent duplicate tracking links across pipeline executions, the `utm_content` value is generated deterministically:

$$\text{Hash Salt} = \text{SHA256}(\text{Source Document} + \text{Pillar} + \text{Platform} + \text{Asset Index})[0:8]$$
$$\text{utm\_content} = \text{asset\_} + \text{Index (01..30)} + \text{\_} + \text{Platform} + \text{\_} + \text{Hash Salt}$$

*Verification Test Planned for Phase 3:* An automated test script will generate all 30 campaign URLs into a set and assert `len(unique_urls) == 30`. Until that test passes, this architecture is classified as `DESIGNED`.

---

## 4. Measurement Hierarchy & Metric Separation

To maintain analytical rigor, performance metrics are strictly partitioned into five independent evaluation layers. Vanity reach is never conflated with downstream user conversion.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        METRIC SEPARATION PYRAMID                       │
├─────────────────┬──────────────────────────────────────────────────────┤
│ 1. Reach        │ Impressions, Views, Discovery Volume                 │
│ 2. Engagement   │ Likes, Comments, Reposts, Watch Time, Carousel Dwell │
│ 3. Intent       │ Saves / Bookmarks, Profile Visits                    │
│ 4. Attribution  │ Unique Tracked Link Clicks (UTM visits)              │
│ 5. Conversion   │ Account Sign-ups, Content Uploads (Activation)       │
└─────────────────┴──────────────────────────────────────────────────────┘
```

### Layer Definitions:
1. **Layer 1: Reach & Impressions:** Raw visibility count in social feeds (indicates algorithmic distribution).
2. **Layer 2: Engagement:** Public reactions, comments, and shares (indicates hook relevance and audience agreement).  
   *(Note: Public reactions/comments are descriptive observations, not proof of causation. They must not be attributed to specific posting times or individual words without controlled A/B testing).*
3. **Layer 3: Save & Intent Actions:** Bookmarks and saves (indicates audience desire to retain practical information).
4. **Layer 4: Inbound Traffic (UTM Clicks):** Tracked link clicks arriving at verified IncuBrix endpoints.
5. **Layer 5: Conversion & Activation:**
   - *Exploration Sign-up:* User registration on the advertised Free exploration plan.
   - *Activation:* User uploading source media to test Creator Studio features.

---

## 5. Performance Hypotheses vs. Measured Baselines

All numerical targets are **hypotheses** for evaluation, NOT established facts.

| Metric Layer | Target Metric | Stated Hypothesis (Target) | Evaluation Method | Current Status |
| :--- | :--- | :--- | :--- | :--- |
| **Short-Form Video** | 3-Second Retention Rate | $\ge 45.0\%$ of viewers | YouTube Studio / Reels Analytics | **HYPOTHESIS** |
| **Short-Form Video** | Completion Rate ($<50$s) | $\ge 35.0\%$ of viewers | YouTube Studio / TikTok Analytics | **HYPOTHESIS** |
| **LinkedIn Carousels**| Save Rate (Bookmarks) | $\ge 10.0\%$ of engaged users | LinkedIn Post Analytics | **HYPOTHESIS** |
| **LinkedIn Posts** | Organic Engagement Rate | Aim to exceed baseline | Formula: $\frac{\text{Reactions+Comments}}{\text{Followers}}$ | **0.793% EMPIRICAL BASELINE** (EV-006) |
| **Outbound Clicks** | Click-Through Rate (CTR) | $\ge 1.0\%$ on bio/comment links | UTM sessions / Total post views | **HYPOTHESIS** |
| **Engine Runtime** | Generation Time (30 assets)| $< 30.0$ minutes | Automated pipeline timer | **TECHNICAL TARGET** (To be tested) |
