"""Unit tests for Phase 3.5 Human Review, Content Refinement, and Approval Workflow."""

import csv
import io
import json
from pathlib import Path
import pytest

from app.core.review_workflow import (
    ReviewWorkflowManager,
    ReviewStatusEnum,
    ReviewActionEnum,
    ReviewableAsset
)
from app.core.generator import generate_draft_candidates
from app.core.quality_gate import (
    evaluate_asset_quality,
    QualityGateStatusEnum,
    QualityCheckResult
)
from app.core.calendar_export import CALENDAR_CSV_COLUMNS, CALENDAR_WITH_REVIEW_COLUMNS
from app.models.asset import (
    SourceSegment,
    DraftCandidate,
    PlatformEnum,
    AssetFormatEnum,
    ClaimCategoryEnum
)


@pytest.fixture
def sample_drafts() -> list[DraftCandidate]:
    seg = SourceSegment(
        segment_id="seg_01_a1b2c3d4",
        source_document="operations_mastery.md",
        segment_index=1,
        source_location="Paragraph 1, Line 1",
        heading="Content Distribution Framework",
        text=(
            "Creating multi-channel content without a structured system often causes severe creative fatigue. "
            "A repeatable repurpose engine turns one core long-form recording into ten platform-specific assets. "
            "Teams can maintain regular distribution schedules without having to record net-new footage daily."
        ),
        word_count=37,
        char_count=264,
        sentences=[
            "Creating multi-channel content without a structured system often causes severe creative fatigue.",
            "A repeatable repurpose engine turns one core long-form recording into ten platform-specific assets.",
            "Teams can maintain regular distribution schedules without having to record net-new footage daily."
        ]
    )
    return generate_draft_candidates([seg])


@pytest.fixture
def workflow_mgr(tmp_path: Path) -> ReviewWorkflowManager:
    store_file = tmp_path / "reviews" / "review_store.json"
    return ReviewWorkflowManager(storage_path=store_file)


# 1. New asset begins in PENDING_REVIEW
def test_new_asset_begins_in_pending_review(workflow_mgr, sample_drafts):
    draft = sample_drafts[0]
    asset = workflow_mgr.register_draft(draft)

    assert asset.asset_id == draft.draft_id
    assert asset.review_status == ReviewStatusEnum.PENDING_REVIEW
    assert asset.reviewer_id is None
    assert asset.approval_timestamp is None
    assert asset.claims_reviewed_confirmed is False
    assert asset.warnings_reviewed_confirmed is False


# 2. PASS does not automatically approve
def test_pass_does_not_automatically_approve(workflow_mgr, sample_drafts):
    draft = sample_drafts[0]
    qr = evaluate_asset_quality(draft)
    assert qr.overall_status == QualityGateStatusEnum.PASS

    asset = workflow_mgr.register_draft(draft, quality_result=qr)
    # Automated quality evaluation must never approve an asset
    assert asset.quality_result.overall_status == QualityGateStatusEnum.PASS
    assert asset.review_status == ReviewStatusEnum.PENDING_REVIEW
    assert asset.review_status != ReviewStatusEnum.APPROVED
    assert asset.approval_timestamp is None


# 3. PASS_WITH_WARNINGS requires explicit human review of warnings
def test_pass_with_warnings_requires_explicit_human_review(workflow_mgr, sample_drafts):
    draft = sample_drafts[0].model_copy(update={"suggested_hashtags": []})
    qr = evaluate_asset_quality(draft)
    assert qr.overall_status == QualityGateStatusEnum.PASS_WITH_WARNINGS

    asset = workflow_mgr.register_draft(draft, quality_result=qr)

    # Attempt approval without confirming warnings reviewed -> Must raise ValueError
    with pytest.raises(ValueError, match="Asset has quality warnings.*confirm_warnings_reviewed=True"):
        workflow_mgr.approve_asset(
            asset_id=asset.asset_id,
            reviewer_id="Reviewer_Alex",
            confirm_claims_reviewed=True,
            confirm_warnings_reviewed=False
        )

    # Now approve with confirm_warnings_reviewed=True -> Succeeds
    approved = workflow_mgr.approve_asset(
        asset_id=asset.asset_id,
        reviewer_id="Reviewer_Alex",
        confirm_claims_reviewed=True,
        confirm_warnings_reviewed=True
    )
    assert approved.review_status == ReviewStatusEnum.APPROVED
    assert approved.warnings_reviewed_confirmed is True


# 4. FAIL cannot be approved
def test_fail_cannot_be_approved(workflow_mgr, sample_drafts):
    # Missing hook triggers quality FAIL
    bad_draft = sample_drafts[0].model_copy(update={"draft_hook": "   "})
    qr = evaluate_asset_quality(bad_draft)
    assert qr.overall_status == QualityGateStatusEnum.FAIL

    asset = workflow_mgr.register_draft(bad_draft, quality_result=qr)

    with pytest.raises(ValueError, match="Quality gate status is FAIL"):
        workflow_mgr.approve_asset(
            asset_id=asset.asset_id,
            reviewer_id="Reviewer_Alex",
            confirm_claims_reviewed=True,
            confirm_warnings_reviewed=True
        )


# 5. Missing reviewer identity prevents approval
def test_missing_reviewer_identity_prevents_approval(workflow_mgr, sample_drafts):
    draft = sample_drafts[0]
    asset = workflow_mgr.register_draft(draft)

    # Empty string
    with pytest.raises(ValueError, match="Reviewer identity is required"):
        workflow_mgr.approve_asset(
            asset_id=asset.asset_id,
            reviewer_id="",
            confirm_claims_reviewed=True
        )

    # Whitespace only
    with pytest.raises(ValueError, match="Reviewer identity is required"):
        workflow_mgr.approve_asset(
            asset_id=asset.asset_id,
            reviewer_id="   ",
            confirm_claims_reviewed=True
        )


# 6. Missing claim-review confirmation prevents approval
def test_missing_claim_review_confirmation_prevents_approval(workflow_mgr, sample_drafts):
    draft = sample_drafts[0]
    asset = workflow_mgr.register_draft(draft)

    with pytest.raises(ValueError, match="Reviewer must explicitly confirm that claims.*confirm_claims_reviewed=True"):
        workflow_mgr.approve_asset(
            asset_id=asset.asset_id,
            reviewer_id="Reviewer_Alex",
            confirm_claims_reviewed=False
        )


# 7. Explicit valid human approval succeeds
def test_explicit_valid_human_approval_succeeds(workflow_mgr, sample_drafts):
    draft = sample_drafts[0]
    asset = workflow_mgr.register_draft(draft)

    approved = workflow_mgr.approve_asset(
        asset_id=asset.asset_id,
        reviewer_id="Reviewer_Jordan",
        comments="Checked against source document. Approved for editorial calendar.",
        confirm_claims_reviewed=True
    )

    assert approved.review_status == ReviewStatusEnum.APPROVED
    assert approved.reviewer_id == "Reviewer_Jordan"
    assert approved.approval_timestamp is not None
    assert approved.claims_reviewed_confirmed is True
    assert len(approved.review_history) == 1
    assert approved.review_history[0].action == ReviewActionEnum.APPROVE
    assert approved.review_history[0].reviewer_id == "Reviewer_Jordan"


# 8. Rejection requires a reason
def test_rejection_requires_reason(workflow_mgr, sample_drafts):
    draft = sample_drafts[0]
    asset = workflow_mgr.register_draft(draft)

    with pytest.raises(ValueError, match="Rejection reason is required"):
        workflow_mgr.reject_asset(
            asset_id=asset.asset_id,
            reviewer_id="Reviewer_Jordan",
            reason=""
        )

    rejected = workflow_mgr.reject_asset(
        asset_id=asset.asset_id,
        reviewer_id="Reviewer_Jordan",
        reason="Does not align with current quarter editorial focus on podcast workflows."
    )
    assert rejected.review_status == ReviewStatusEnum.REJECTED
    assert rejected.rejection_reason == "Does not align with current quarter editorial focus on podcast workflows."


# 9. Revision requests are recorded
def test_revision_requests_are_recorded(workflow_mgr, sample_drafts):
    draft = sample_drafts[0]
    asset = workflow_mgr.register_draft(draft)

    with pytest.raises(ValueError, match="Revision notes are required"):
        workflow_mgr.request_revision(
            asset_id=asset.asset_id,
            reviewer_id="Reviewer_Jordan",
            revision_notes=""
        )

    rev_asset = workflow_mgr.request_revision(
        asset_id=asset.asset_id,
        reviewer_id="Reviewer_Jordan",
        revision_notes="Please tighten the opening hook and shorten line 2."
    )
    assert rev_asset.review_status == ReviewStatusEnum.REVISION_REQUESTED
    assert rev_asset.revision_notes == "Please tighten the opening hook and shorten line 2."
    assert any(a.action == ReviewActionEnum.REQUEST_REVISION for a in rev_asset.review_history)


# 10. Reviewer edits trigger a fresh quality evaluation
def test_reviewer_edits_trigger_fresh_quality_evaluation(workflow_mgr, sample_drafts):
    draft = sample_drafts[0]
    asset = workflow_mgr.register_draft(draft)
    assert asset.quality_result.overall_status == QualityGateStatusEnum.PASS

    # Edit caption to exceed character limits (e.g. > 3000 chars for LinkedIn)
    long_caption = "A" * 3050
    refined = workflow_mgr.apply_refinements(
        asset_id=asset.asset_id,
        reviewer_id="Reviewer_Jordan",
        caption=long_caption
    )

    # Fresh quality evaluation must detect failure
    assert refined.quality_result.overall_status == QualityGateStatusEnum.FAIL
    assert any("exceeds maximum character limit" in f for f in refined.quality_result.failed_checks)


# 11. Substantive edits invalidate previous approval
def test_substantive_edits_invalidate_previous_approval(workflow_mgr, sample_drafts):
    draft = sample_drafts[0]
    asset = workflow_mgr.register_draft(draft)

    # First approve the asset
    approved = workflow_mgr.approve_asset(
        asset_id=asset.asset_id,
        reviewer_id="Reviewer_Lead",
        confirm_claims_reviewed=True
    )
    assert approved.review_status == ReviewStatusEnum.APPROVED
    assert approved.approval_timestamp is not None

    # Now make a substantive hook edit
    refined = workflow_mgr.apply_refinements(
        asset_id=asset.asset_id,
        reviewer_id="Reviewer_Lead",
        hook="New revised operational hook line for audience testing"
    )

    # Approval must be invalidated and returned to review
    assert refined.review_status == ReviewStatusEnum.IN_REVIEW
    assert refined.approval_timestamp is None
    assert refined.claims_reviewed_confirmed is False
    assert refined.warnings_reviewed_confirmed is False
    assert any(
        a.action == ReviewActionEnum.APPLY_REFINEMENTS and a.metadata.get("approval_invalidated") is True
        for a in refined.review_history
    )


# 12. Original generated content remains preserved
def test_original_generated_content_remains_preserved(workflow_mgr, sample_drafts):
    draft = sample_drafts[0]
    original_hook = draft.draft_hook
    original_caption = draft.draft_caption

    asset = workflow_mgr.register_draft(draft)

    # Refine draft with new content
    refined = workflow_mgr.apply_refinements(
        asset_id=asset.asset_id,
        reviewer_id="Reviewer_Editor",
        hook="Completely new refined hook line",
        caption="Completely new refined caption body copy with additional tactical details."
    )

    # Active draft reflects edits
    assert refined.draft.draft_hook == "Completely new refined hook line"
    assert refined.draft.draft_caption.startswith("Completely new refined caption")

    # Original draft remains completely intact
    assert refined.original_draft.draft_hook == original_hook
    assert refined.original_draft.draft_caption == original_caption


# 13. Source traceability survives editing
def test_source_traceability_survives_editing(workflow_mgr, sample_drafts):
    draft = sample_drafts[0]
    doc = draft.source_document
    seg_id = draft.source_segment_id
    excerpt = draft.source_excerpt

    asset = workflow_mgr.register_draft(draft)
    refined = workflow_mgr.apply_refinements(
        asset_id=asset.asset_id,
        reviewer_id="Reviewer_Editor",
        hook="Refined Hook Test",
        caption="Refined Caption Test"
    )

    assert refined.draft.source_document == doc
    assert refined.draft.source_segment_id == seg_id
    assert refined.draft.source_excerpt == excerpt


# 14. Review history persists across reloads
def test_review_history_persists_across_reloads(tmp_path: Path, sample_drafts):
    store_file = tmp_path / "persistent_reviews.json"
    mgr1 = ReviewWorkflowManager(storage_path=store_file)

    draft = sample_drafts[0]
    mgr1.register_draft(draft)
    mgr1.start_review(draft.draft_id, reviewer_id="Reviewer_A", comments="Initial check")
    mgr1.record_feedback(draft.draft_id, reviewer_id="Reviewer_A", feedback="Check tone")
    mgr1.approve_asset(draft.draft_id, reviewer_id="Reviewer_A", confirm_claims_reviewed=True)

    # Reload from disk into a completely new manager instance
    mgr2 = ReviewWorkflowManager(storage_path=store_file)
    reloaded_asset = mgr2.get_asset(draft.draft_id)

    assert reloaded_asset.review_status == ReviewStatusEnum.APPROVED
    assert reloaded_asset.reviewer_id == "Reviewer_A"
    assert len(reloaded_asset.review_history) == 3
    assert reloaded_asset.review_history[0].action == ReviewActionEnum.START_REVIEW
    assert reloaded_asset.review_history[1].action == ReviewActionEnum.RECORD_FEEDBACK
    assert reloaded_asset.review_history[2].action == ReviewActionEnum.APPROVE


# 15. Approved export contains only approved assets
def test_approved_export_contains_only_approved_assets(workflow_mgr, sample_drafts):
    # Register 4 drafts
    for d in sample_drafts:
        workflow_mgr.register_draft(d)

    # Approve only draft 0
    approved_draft = sample_drafts[0]
    workflow_mgr.approve_asset(
        asset_id=approved_draft.draft_id,
        reviewer_id="Reviewer_Lead",
        confirm_claims_reviewed=True
    )

    csv_str = workflow_mgr.export_approved_assets_calendar_csv()
    reader = csv.DictReader(io.StringIO(csv_str))
    rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["asset_id"] == approved_draft.draft_id
    assert rows[0]["human_review_status"] == "APPROVED"
    assert rows[0]["reviewer_id"] == "Reviewer_Lead"
    assert rows[0]["approval_timestamp"] != ""
    assert rows[0]["publication_status"] == "APPROVED_FOR_SCHEDULING"


# 16. Pending and rejected assets are excluded from approved export
def test_pending_and_rejected_assets_excluded_from_approved_export(workflow_mgr, sample_drafts):
    d0 = sample_drafts[0]
    d1 = sample_drafts[1]
    d2 = sample_drafts[2]

    workflow_mgr.register_draft(d0)  # PENDING_REVIEW
    workflow_mgr.register_draft(d1)  # Will be REJECTED
    workflow_mgr.register_draft(d2)  # Will be APPROVED

    workflow_mgr.reject_asset(d1.draft_id, reviewer_id="Reviewer_Ops", reason="Irrelevant format")
    workflow_mgr.approve_asset(d2.draft_id, reviewer_id="Reviewer_Ops", confirm_claims_reviewed=True)

    csv_str = workflow_mgr.export_approved_assets_calendar_csv()
    reader = csv.DictReader(io.StringIO(csv_str))
    rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["asset_id"] == d2.draft_id

    # Unapproved export includes d0 and d1
    unapproved_csv = workflow_mgr.export_unapproved_assets_calendar_csv()
    unapproved_reader = csv.DictReader(io.StringIO(unapproved_csv))
    unapproved_rows = list(unapproved_reader)
    unapproved_ids = {r["asset_id"] for r in unapproved_rows}

    assert d0.draft_id in unapproved_ids
    assert d1.draft_id in unapproved_ids
    assert d2.draft_id not in unapproved_ids


# 17. Calendar export preserves its original 20 columns
def test_calendar_export_preserves_original_20_columns(workflow_mgr, sample_drafts):
    workflow_mgr.register_draft(sample_drafts[0])
    workflow_mgr.approve_asset(sample_drafts[0].draft_id, reviewer_id="Reviewer_Lead", confirm_claims_reviewed=True)

    # 1. Base 20-column export
    base_csv = workflow_mgr.export_all_candidates_calendar_csv(include_review_columns=False)
    reader_base = csv.DictReader(io.StringIO(base_csv))
    assert reader_base.fieldnames == CALENDAR_CSV_COLUMNS
    assert len(reader_base.fieldnames) == 20

    # 2. Review-enriched 24-column export preserves the first 20 columns exactly
    enriched_csv = workflow_mgr.export_approved_assets_calendar_csv()
    reader_enriched = csv.DictReader(io.StringIO(enriched_csv))
    assert reader_enriched.fieldnames == CALENDAR_WITH_REVIEW_COLUMNS
    assert reader_enriched.fieldnames[:20] == CALENDAR_CSV_COLUMNS
    assert len(reader_enriched.fieldnames) == 24


# 18. Human approval never triggers publishing
def test_human_approval_never_triggers_publishing(workflow_mgr, sample_drafts):
    draft = sample_drafts[0]
    asset = workflow_mgr.register_draft(draft)

    approved = workflow_mgr.approve_asset(
        asset_id=asset.asset_id,
        reviewer_id="Reviewer_Lead",
        confirm_claims_reviewed=True
    )

    # Safety Invariant: draft.is_ready_to_publish remains False
    assert approved.draft.is_ready_to_publish is False
    assert approved.original_draft.is_ready_to_publish is False

    # Summary report confirms publishing safety
    summary = workflow_mgr.export_review_summary_json()
    assert summary["publishing_safety"]["social_publishing_triggered"] is False
    assert summary["publishing_safety"]["is_ready_to_publish_enforced_false"] is True

