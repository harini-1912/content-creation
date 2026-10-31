"""Command-line entry point for IncuBrix End-to-End Content Pipeline (Phase 3.6).

Usage:
    python run_pipeline.py <source_file> [options]

Examples:
    python run_pipeline.py sample_inputs/repurposing_operations_guide.md
    python run_pipeline.py sample_inputs/repurposing_operations_guide.md --destination-url https://app.incubrix.com/explore
    python run_pipeline.py sample_inputs/repurposing_operations_guide.md --platforms linkedin youtube_shorts --target-count 8
"""

import argparse
from pathlib import Path
import sys

from app.core.pipeline import run_content_pipeline
from app.core.utm import DEFAULT_CAMPAIGN


def parse_args():
    parser = argparse.ArgumentParser(
        description="IncuBrix Content Engine: End-to-end multi-platform content generation pipeline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "source",
        type=str,
        help="Path to source document (.txt or .md) to ingest and repurpose."
    )
    parser.add_argument(
        "--platforms",
        nargs="+",
        choices=["linkedin", "youtube_shorts", "twitter", "instagram"],
        default=None,
        help="Filter generation to specific platforms (default: all supported platforms)."
    )
    parser.add_argument(
        "--destination-url",
        type=str,
        default=None,
        help="Target landing destination URL for UTM tracking links."
    )
    parser.add_argument(
        "--campaign",
        type=str,
        default=DEFAULT_CAMPAIGN,
        help="Campaign name for UTM tracking parameters."
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/pipeline_runs",
        help="Base directory for pipeline run outputs."
    )
    parser.add_argument(
        "--target-count",
        type=int,
        default=None,
        help="Target number of unique candidates to generate (honest shortfall reported if unmet)."
    )
    parser.add_argument(
        "--skip-media",
        action="store_true",
        default=False,
        help="Skip rendering local media previews (runs copy and calendar generation only)."
    )

    return parser.parse_args()


def main():
    args = parse_args()
    source_path = Path(args.source)

    print("=" * 80)
    print("INCUBRIX CONTENT PIPELINE: END-TO-END REPURPOSING EXECUTION")
    print("=" * 80)
    print(f"Source file:      {source_path}")
    print(f"Platforms:        {args.platforms or 'ALL (linkedin, youtube_shorts, twitter, instagram)'}")
    print(f"Destination URL:  {args.destination_url or 'NONE (Tracking links will remain blank)'}")
    print(f"Render Media:     {not args.skip_media}")
    print(f"Base Output Dir:  {args.output_dir}")
    print("-" * 80)

    try:
        result = run_content_pipeline(
            source_path=source_path,
            platforms=args.platforms,
            destination_url=args.destination_url,
            output_dir=args.output_dir,
            campaign=args.campaign,
            render_media=not args.skip_media,
            target_count=args.target_count
        )
    except Exception as e:
        print(f"\n[PIPELINE FAILED] Execution error: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n--- PIPELINE EXECUTION COMPLETED ---")
    print(f"Run ID:                  {result.run_id}")
    print(f"Execution Duration:      {result.execution_duration_seconds:.2f}s")
    print(f"Source Segments Ingested:{result.total_segments}")
    print(f"Candidates Generated:    {result.total_candidates}")
    print("Platform Breakdown:")
    for plat, cnt in result.platform_counts.items():
        print(f"  - {plat}: {cnt}")

    print("\nQuality Gate Status:")
    for qstat, cnt in result.quality_counts.items():
        print(f"  - {qstat}: {cnt}")

    print("\nMedia Previews:")
    print(f"  - Rendered: {result.media_rendered_count}")
    print(f"  - Skipped:  {result.media_skipped_count}")
    print(f"  - Failed:   {result.media_failed_count}")

    print("\nHuman Review Registration:")
    for rstat, cnt in result.review_status_counts.items():
        print(f"  - {rstat}: {cnt}")

    print("\nExported Artifacts:")
    print(f"  - Complete Draft Calendar: {result.run_dir / 'calendars' / 'complete_draft_calendar.csv'}")
    print(f"  - Approved Calendar:        {result.run_dir / 'calendars' / 'approved_calendar.csv'} (Count: {result.approved_export_count})")
    print(f"  - Unapproved Calendar:      {result.run_dir / 'calendars' / 'unapproved_calendar.csv'} (Count: {result.unapproved_export_count})")
    print(f"  - Quality Audit Report:     {result.run_dir / 'quality' / 'quality_report.json'}")
    print(f"  - Consolidated Summary:     {result.run_dir / 'summaries' / 'pipeline_summary.json'}")
    print(f"  - Review Store:             {result.run_dir / 'summaries' / 'review_store.json'}")
    print(f"  - Media Previews Directory: {result.run_dir / 'media'}")

    if result.warnings:
        print("\nWarnings:")
        for w in result.warnings:
            print(f"  [!] {w}")

    print("=" * 80)
    print("PIPELINE RUN READY FOR HUMAN REVIEW (Zero automated approvals applied)")
    print("=" * 80)


if __name__ == "__main__":
    main()

