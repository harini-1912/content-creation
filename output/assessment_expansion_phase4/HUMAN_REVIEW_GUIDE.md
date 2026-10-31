# IncuBrix Human Review & Editorial Governance Guide (Phase 4.1)

**Active Workspace:** `C:\Users\Harini V\OneDrive\Desktop\incu`  
**Target Portfolio:** 40 Assessment-Ready Repurposed Content Assets  
**Governance Standard:** Human-in-the-Loop Content Verification & Editorial Integrity  

---

## 1. Purpose of Human Review

The IncuBrix content pipeline automates semantic segment ingestion, platform-specific drafting, quality gate scoring, cryptographic media rendering, and UTM attribution tracking. 

However, **automated checks do not equal publication authorization or factual verification**.

Automated quality gates verify syntax, length constraints, schema rules, and absence of prohibited buzzwords. Only a human editorial reviewer can evaluate:
1. **Audience Resonance:** Does the hook genuinely stop a creator or marketing engineer in their feed?
2. **Technical Accuracy:** Does the explanation faithfully represent sound content engineering principles?
3. **Tone & Nuance:** Does the voice remain disciplined, technical, and anti-hype?
4. **Factual Integrity:** Are empirical assertions verified by real-world data or clearly presented as hypotheses?

---

## 2. Review Workflow States & Authorized Decisions

Every asset begins in **`PENDING_REVIEW`** with `requires_human_review=True` and `is_ready_to_publish=False`.

As a reviewer, you must record one of three auditable decisions in the review register:

### Decision 1: `APPROVED`
- **When to Apply:** 
  - The asset satisfies all platform formatting constraints.
  - The copy is clear, compelling, and aligned with IncuBrix engineer-first brand voice.
  - The CTA is appropriate and does not overpromise.
  - The destination URL is verified on the approved allowlist (`https://app.incubrix.com/`).
  - Rendered preview media (MP4 or slide deck) matches the editable text.
  - All factual claims have either been verified against `research/evidence_register.csv` or explicitly confirmed as acceptable source-attributed hypotheses.
- **Mandatory Requirements for Approval:**
  - `reviewer_name` (e.g. `Editorial_Reviewer_Lead`)
  - `claims_reviewed_confirmed` set to `True`
  - `approval_timestamp` (ISO 8601 UTC timestamp)
  - `reviewer_notes` documenting review rationale.
- **Critical Policy:** Marking an asset `APPROVED` indicates editorial readiness for scheduling consideration. It **does NOT publish or schedule the post automatically**.

### Decision 2: `REVISION_REQUESTED`
- **When to Apply:**
  - The core premise is strong, but the hook is truncated, copy needs tightening, hashtags need refinement, or a pending landing page link must be assigned.
  - A proposed revision in `proposed_revisions.md` is selected for application.
- **Mandatory Requirements:**
  - `reviewer_name`
  - `reviewer_notes` specifying exactly what adjustments are required (e.g. "Apply Proposed Revision 04 to hook metadata").

### Decision 3: `REJECTED`
- **When to Apply:**
  - The asset contains unfixable factual errors, off-brand messaging, irrelevant topics, or violates editorial standards.
- **Mandatory Requirements:**
  - `reviewer_name`
  - `reviewer_notes` providing an explicit rejection reason (rejections cannot be blank).

---

## 3. Step-by-Step Review Instructions

### Step 1: Open the Review Register
Open [`output/assessment_expansion_phase4/human_review_register.csv`](file:///C:/Users/Harini%20V/OneDrive/Desktop/incu/output/assessment_expansion_phase4/human_review_register.csv) in Excel, Google Sheets, or your preferred CSV editor.

Notice that columns 18–21 (`human_review_decision`, `reviewer_name`, `reviewer_notes`, `review_timestamp`) are **strictly blank**. These must be filled out by you during manual inspection.

### Step 2: Cross-Reference Findings and Revisions
1. Read the per-asset evaluations in [`output/assessment_expansion_phase4/content_quality_findings.md`](file:///C:/Users/Harini%20V/OneDrive/Desktop/incu/output/assessment_expansion_phase4/content_quality_findings.md).
2. Check if the asset is labeled `PASS`, `NEEDS_IMPROVEMENT`, or `NEEDS_FACTUAL_VERIFICATION`.
3. If an improvement is recommended, inspect the proposed replacement copy in [`output/assessment_expansion_phase4/proposed_revisions.md`](file:///C:/Users/Harini%20V/OneDrive/Desktop/incu/output/assessment_expansion_phase4/proposed_revisions.md).

### Step 3: Inspect Editable Files and Previews
- **For Video Scripts (10 Shorts):**
  - Open the markdown script in `editable_assets/scripts/{asset_id}_script.md`.
  - Open the rendered video preview in `media/{asset_id}/preview.mp4`.
  - Verify that visual kinetic text and spoken pacing align with the 60-second limit.
- **For Visual Carousels (10 Instagram Decks):**
  - Open the markdown outline in `editable_assets/carousels/{asset_id}_carousel.md`.
  - Open the rendered slide images in `media/{asset_id}/slide_01.png`–`slide_05.png` and `carousel_contact_sheet.png`.
  - Confirm readability on mobile screen dimensions (1080x1080).
- **For Text Posts & Threads (20 LinkedIn/Twitter Posts):**
  - Open the post markdown file in `editable_assets/posts/{asset_id}_*.md`.
  - Check readability, paragraph spacing, and character count limits.

### Step 4: Validate Destination URLs & Attribution
- Verify column `destination_url_status`:
  - If `APPROVED` (`https://app.incubrix.com/`), confirm that the UTM tracking parameters correctly identify platform and content ID.
  - If `PENDING_DESTINATION_URL`, decide whether to assign a specific landing page URL or retain as top-of-funnel educational discussion without a link.

### Step 5: Record Review Decisions
In `human_review_register.csv`, fill in:
- `human_review_decision`: Enter `APPROVED`, `REVISION_REQUESTED`, or `REJECTED`.
- `reviewer_name`: Enter your full name or reviewer ID (e.g. `Alex_Rivera_Lead_Editor`).
- `reviewer_notes`: Provide actionable comments, approval confirmation, or required edits.
- `review_timestamp`: Enter the current UTC timestamp (e.g. `2026-10-31T14:30:00Z`).

Save the completed register file.

---

## 4. Applying Refinements via CLI (Optional Automation)

If you wish to apply proposed revisions programmatically rather than manually editing files, you can use the built-in `ReviewWorkflowManager`:

```python
from app.core.review_workflow import ReviewWorkflowManager
from pathlib import Path

# Load existing review store
store_path = Path("output/assessment_expansion_phase4/review_store.json")
manager = ReviewWorkflowManager(storage_path=store_path)

# Apply refinement to hook or caption
manager.apply_refinements(
    asset_id="draft_shorts_seg_01_54bd0501_f5a9f73e",
    reviewer_id="Alex_Rivera_Lead_Editor",
    hook="[0-3s Kinetic Card] Stop overcomplicating your workflow: Fragmented tools drain creative energy.",
    reviewer_notes="Applied proposed revision 01 to restore complete hook sentence."
)
```

Applying refinements automatically:
1. Invalidates prior approvals.
2. Re-runs quality gates and brand compliance.
3. Appends an auditable record to `review_history`.

---

## 5. Compliance & Legal Summary

> [!IMPORTANT]
> **Approval Does Not Equal Factual Verification**  
> Approving an asset with claim category `SOURCE_ATTRIBUTED_UNVERIFIED` indicates that the copy faithfully represents the source document and meets editorial standards. It does not certify that external factual claims are empirically proven unless documented evidence in `research/evidence_register.csv` has been independently audited.

> [!CAUTION]
> **Zero Autonomous Publishing Guarantee**  
> Even after an asset is marked `APPROVED`, it enters the `APPROVED_FOR_SCHEDULING` calendar export. It will **never** be automatically published or pushed to social accounts without explicit export into an external social media management tool (Buffer, Hootsuite) by an authorized operator.
