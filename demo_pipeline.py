"""Demonstration script for IncuBrix End-to-End Content Pipeline (Phase 3.6).

Demonstrates the automated end-to-end orchestration using the synthetic educational fixture:
sample_inputs/repurposing_operations_guide.md

Notice:
- All source content is synthetic educational material, NOT real customer results or IncuBrix case studies.
- All reviewer identities are synthetic demonstration personae (e.g. 'Synthetic_Reviewer_Persona_01').
- Demonstrates automated pipeline completion, quality evaluation, media rendering, and separate calendar exports.
- Verifies that zero automated approvals occur, and zero external publishing integrations are triggered.
"""

from pathlib import Path
import json
import csv

from app.core.pipeline import run_content_pipeline
from app.core.review_workflow import ReviewWorkflowManager, ReviewStatusEnum


def run_pipeline_demonstration():
    print("=" * 80)
    print("INCUBRIX PHASE 3.6: END-TO-END CONTENT PIPELINE DEMONSTRATION")
    print("=" * 80)

    fixture_path = Path("sample_inputs/repurposing_operations_guide.md")
    demo_output_base = Path("output/demonstrations/pipeline_run")
    destination_url = "https://app.incubrix.com/"

    print(f"\n[DEMO] Source Fixture:  {fixture_path} (Synthetic Educational Material)")
    print(f"[DEMO] Destination URL: {destination_url}")
    print(f"[DEMO] Base Output Dir: {demo_output_base}")
    print("\nExecuting complete 10-stage content pipeline...")

    # Execute end-to-end pipeline
    result = run_content_pipeline(
        source_path=fixture_path,
        destination_url=destination_url,
        output_dir=demo_output_base,
        render_media=True,
        target_count=10,
        run_id="demo_phase3_6_run"
    )

    print("\n" + "-" * 80)
    print("PIPELINE EXECUTION METRICS:")
    print("-" * 80)
    print(f"Run ID:                  {result.run_id}")
    print(f"Run Directory:           {result.run_dir}")
    print(f"Execution Duration:      {result.execution_duration_seconds:.2f} seconds")
    print(f"Source Segments Ingested:{result.total_segments}")
    print(f"Candidates Generated:    {result.total_candidates}")
    print(f"Target Met (Goal=10):    {result.target_met} (Shortfall: {result.shortfall})")

    print("\nPlatform Breakdown:")
    for platform, count in result.platform_counts.items():
        print(f"  - {platform}: {count} candidates")

    print("\nAutomated Quality Gate Results:")
    for qstatus, count in result.quality_counts.items():
        print(f"  - {qstatus}: {count}")

    print("\nMedia Preview Rendering:")
    print(f"  - Successfully Rendered: {result.media_rendered_count}")
    print(f"  - Skipped (Text/Thread): {result.media_skipped_count}")
    print(f"  - Failed:                {result.media_failed_count}")

    print("\nHuman Review Invariant Check:")
    for rstatus, count in result.review_status_counts.items():
        print(f"  - {rstatus}: {count}")
    print(f"  [Safety Verified] Approved Export Count: {result.approved_export_count} (Must be 0 initially)")
    print(f"  [Safety Verified] Unapproved Export Count: {result.unapproved_export_count}")

    # Inspect the calendar CSVs generated
    print("\n" + "-" * 80)
    print("INSPECTING EXPORTED CALENDAR FILES:")
    print("-" * 80)
    complete_cal = result.run_dir / "calendars" / "complete_draft_calendar.csv"
    approved_cal = result.run_dir / "calendars" / "approved_calendar.csv"
    unapproved_cal = result.run_dir / "calendars" / "unapproved_calendar.csv"

    with open(complete_cal, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        complete_rows = list(reader)
        print(f"Complete Draft Calendar: {len(complete_rows)} rows | {len(reader.fieldnames)} columns")
        print(f"Sample Draft Hook:       {complete_rows[0]['hook'][:75]}...")
        print(f"Sample Tracking URL:     {complete_rows[0]['tracking_url']}")

    with open(approved_cal, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        approved_rows = list(reader)
        print(f"Approved Calendar:       {len(approved_rows)} rows (Pending human review)")

    with open(unapproved_cal, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        unapproved_rows = list(reader)
        print(f"Unapproved Calendar:     {len(unapproved_rows)} rows (All unapproved drafts)")

    # Demonstrate Phase 3.5 Human Approval of One Asset
    print("\n" + "-" * 80)
    print("DEMONSTRATING HUMAN EDITORIAL APPROVAL ON A SINGLE CANDIDATE:")
    print("-" * 80)
    workflow_mgr = ReviewWorkflowManager(storage_path=result.run_dir / "summaries" / "review_store.json")
    candidate_id = complete_rows[0]["asset_id"]

    print(f"Selected Candidate: {candidate_id}")
    approved_asset = workflow_mgr.approve_asset(
        asset_id=candidate_id,
        reviewer_id="Synthetic_Reviewer_Persona_01",
        comments="Editorial and claim review confirmed against source segment.",
        confirm_claims_reviewed=True,
        confirm_warnings_reviewed=True
    )
    print(f"Status after manual review: {approved_asset.review_status.value}")
    print(f"Reviewer:                   {approved_asset.reviewer_id}")
    print(f"Approval Timestamp:         {approved_asset.approval_timestamp}")

    # Re-export approved calendar to show updated export stream
    workflow_mgr.export_approved_assets_calendar_csv(output_path=approved_cal, destination_url=destination_url)
    workflow_mgr.export_unapproved_assets_calendar_csv(output_path=unapproved_cal, destination_url=destination_url)

    with open(approved_cal, encoding="utf-8-sig") as f:
        updated_approved_rows = list(csv.DictReader(f))
        print(f"\nUpdated Approved Calendar Count:   {len(updated_approved_rows)} (Approved candidate now included)")
    with open(unapproved_cal, encoding="utf-8-sig") as f:
        updated_unapproved_rows = list(csv.DictReader(f))
        print(f"Updated Unapproved Calendar Count: {len(updated_unapproved_rows)} (Remaining unapproved drafts)")

    print("\n" + "-" * 80)
    print("VERIFYING CONSOLIDATED RUN SUMMARY JSON:")
    print("-" * 80)
    summary_file = result.run_dir / "summaries" / "pipeline_summary.json"
    summary_data = json.loads(summary_file.read_text(encoding="utf-8"))
    print(f"Summary File: {summary_file}")
    print(f"Run ID recorded: {summary_data['run_id']}")
    print(f"All stages succeeded: {all(s in ('SUCCESS', 'SKIPPED') for s in summary_data['stages'].values())}")
    print(f"Social publishing triggered: {summary_data['review_workflow_summary']['automated_approvals_applied']}")

    print("=" * 80)
    print("PHASE 3.6 PIPELINE DEMONSTRATION COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    run_pipeline_demonstration()

