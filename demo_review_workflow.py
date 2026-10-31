"""Demonstration script for Phase 3.5 Human Review and Approval Workflow.

Demonstrates the 12-step human editorial workflow using the synthetic fixture:
sample_inputs/repurposing_operations_guide.md

Notice:
All reviewer identities are synthetic demo personae (e.g. 'Reviewer_Ops_Lead_01').
No real customer material, real case studies, or social media publishing integrations are used.
"""

from pathlib import Path
import json

from app.core.ingestion import ingest_source_document
from app.core.generator import generate_draft_candidates
from app.core.quality_gate import evaluate_asset_quality, QualityGateStatusEnum
from app.core.review_workflow import ReviewWorkflowManager, ReviewStatusEnum
from app.models.asset import PlatformEnum


def run_demonstration():
    print("=" * 80)
    print("INCUBRIX PHASE 3.5: HUMAN REVIEW & APPROVAL WORKFLOW DEMONSTRATION")
    print("=" * 80)

    demo_dir = Path("output/demonstrations")
    demo_dir.mkdir(parents=True, exist_ok=True)
    store_path = demo_dir / "demo_review_store.json"
    if store_path.exists():
        store_path.unlink()

    manager = ReviewWorkflowManager(storage_path=store_path)

    # STEP 1: Ingest synthetic fixture and generate candidate assets
    print("\n--- STEP 1: INGESTING SOURCE & GENERATING CANDIDATES ---")
    source_file = Path("sample_inputs/repurposing_operations_guide.md")
    segments = ingest_source_document(source_file)
    print(f"Ingested {len(segments)} segments from '{source_file.name}'")

    drafts = generate_draft_candidates(segments)
    print(f"Generated {len(drafts)} multi-platform draft candidates")

    # STEP 2: Run automated quality checks & register into workflow
    print("\n--- STEP 2: RUNNING AUTOMATED QUALITY CHECKS & REGISTERING ASSETS ---")
    registered_assets = manager.register_batch(drafts)
    print(f"Registered {len(registered_assets)} assets in ReviewWorkflowManager")

    # STEP 3: Show a candidate awaiting human review
    print("\n--- STEP 3: CANDIDATE AWAITING HUMAN REVIEW ---")
    first_asset = registered_assets[0]
    print(f"Asset ID: {first_asset.asset_id}")
    print(f"Platform: {first_asset.draft.platform.value}")
    print(f"Quality Gate Status: {first_asset.quality_result.overall_status.value}")
    print(f"Human Review Status: {first_asset.review_status.value}")
    assert first_asset.review_status == ReviewStatusEnum.PENDING_REVIEW

    # STEP 4: Show its original content and source reference
    print("\n--- STEP 4: ORIGINAL CONTENT AND SOURCE TRACEABILITY ---")
    print(f"Source Document: {first_asset.draft.source_document}")
    print(f"Source Segment ID: {first_asset.draft.source_segment_id}")
    print(f"Source Excerpt: {first_asset.draft.source_excerpt[:100]}...")
    print(f"Original Hook: {first_asset.original_draft.draft_hook}")
    print(f"Original Caption (First 120 chars): {first_asset.original_draft.draft_caption[:120]}...")

    # STEP 5: Edit a caption or hook (Content Refinement)
    print("\n--- STEP 5: EDITING HOOK AND CAPTION (CONTENT REFINEMENT) ---")
    manager.start_review(first_asset.asset_id, reviewer_id="Reviewer_Ops_Lead_01", comments="Beginning editorial polish")
    refined_asset = manager.apply_refinements(
        asset_id=first_asset.asset_id,
        reviewer_id="Reviewer_Ops_Lead_01",
        hook="Stop rebuilding your distribution from scratch: 3 operational rules",
        caption="When scaling content distribution, operational systems dictate cadence.\n\n• Rule 1: Anchor on core master recording\n• Rule 2: Standardize repurposing pathways\n• Rule 3: Maintain strict UTM tracking hygiene",
        reviewer_notes="Polished hook for stronger pattern disruption and converted takeaways to bullet rules."
    )
    print(f"Refined Hook: {refined_asset.draft.draft_hook}")
    print(f"Original Hook Still Preserved: {refined_asset.original_draft.draft_hook}")

    # STEP 6: Re-run quality gate after edit
    print("\n--- STEP 6: QUALITY GATE STATUS AFTER REFINEMENT ---")
    print(f"Updated Quality Status: {refined_asset.quality_result.overall_status.value}")
    print(f"Passed Checks Count: {len(refined_asset.quality_result.passed_checks)}")
    print(f"Review Status: {refined_asset.review_status.value}")

    # STEP 7: Demonstrate a revision-requested asset
    print("\n--- STEP 7: DEMONSTRATING REVISION REQUEST ---")
    second_asset = registered_assets[1]
    manager.start_review(second_asset.asset_id, reviewer_id="Reviewer_Editorial_02")
    revised_asset = manager.request_revision(
        asset_id=second_asset.asset_id,
        reviewer_id="Reviewer_Editorial_02",
        revision_notes="The on-screen text duration needs to be tightened for vertical format pacing."
    )
    print(f"Asset ID: {revised_asset.asset_id}")
    print(f"Review Status: {revised_asset.review_status.value}")
    print(f"Revision Notes: {revised_asset.revision_notes}")

    # STEP 8: Demonstrate a rejected asset
    print("\n--- STEP 8: DEMONSTRATING REJECTED ASSET ---")
    third_asset = registered_assets[2]
    rejected_asset = manager.reject_asset(
        asset_id=third_asset.asset_id,
        reviewer_id="Reviewer_Editorial_02",
        reason="Redundant with prior weekly series; does not fit Q4 narrative focus."
    )
    print(f"Asset ID: {rejected_asset.asset_id}")
    print(f"Review Status: {rejected_asset.review_status.value}")
    print(f"Rejection Reason: {rejected_asset.rejection_reason}")

    # STEP 9: Demonstrate explicit human approval of an eligible asset
    print("\n--- STEP 9: EXPLICIT HUMAN APPROVAL OF ELIGIBLE ASSET ---")
    approved_asset = manager.approve_asset(
        asset_id=refined_asset.asset_id,
        reviewer_id="Reviewer_Ops_Lead_01",
        comments="Refined copy approved for calendar scheduling.",
        confirm_claims_reviewed=True,
        confirm_warnings_reviewed=True
    )
    print(f"Asset ID: {approved_asset.asset_id}")
    print(f"Review Status: {approved_asset.review_status.value}")
    print(f"Reviewer: {approved_asset.reviewer_id}")
    print(f"Approval Timestamp: {approved_asset.approval_timestamp}")
    print(f"Claims Reviewed Confirmed: {approved_asset.claims_reviewed_confirmed}")

    # STEP 10: Export approved and unapproved assets separately
    print("\n--- STEP 10: SEPARATE CALENDAR EXPORTS ---")
    approved_csv_path = demo_dir / "demo_approved_calendar.csv"
    unapproved_csv_path = demo_dir / "demo_unapproved_calendar.csv"
    summary_json_path = demo_dir / "demo_review_summary.json"

    manager.export_approved_assets_calendar_csv(output_path=approved_csv_path)
    manager.export_unapproved_assets_calendar_csv(output_path=unapproved_csv_path)
    summary_data = manager.export_review_summary_json(output_path=summary_json_path)

    print(f"Approved CSV written to: {approved_csv_path}")
    print(f"Approved Count: {summary_data['approved_assets_count']}")
    print(f"Unapproved CSV written to: {unapproved_csv_path}")
    print(f"Unapproved Count: {summary_data['unapproved_assets_count']}")
    print(f"Summary JSON written to: {summary_json_path}")

    # STEP 11: Show the review audit history
    print("\n--- STEP 11: REVIEW AUDIT TRAIL FOR APPROVED ASSET ---")
    history = manager.get_review_history(approved_asset.asset_id)
    print(f"Total Audit Actions: {len(history)}")
    for idx, act in enumerate(history, start=1):
        print(f"  {idx}. [{act.timestamp}] {act.action.value} by '{act.reviewer_id}': {act.comments}")

    # STEP 12: Confirm that no social media publishing occurs
    print("\n--- STEP 12: CONFIRMING PUBLISHING SAFETY INVARIANTS ---")
    print(f"Social Publishing Triggered: {summary_data['publishing_safety']['social_publishing_triggered']}")
    print(f"Draft is_ready_to_publish strictly False: {approved_asset.draft.is_ready_to_publish is False}")
    print(f"Approved Asset publication_status in Calendar: APPROVED_FOR_SCHEDULING (Editorial consideration only)")
    print("=" * 80)
    print("DEMONSTRATION COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    run_demonstration()

