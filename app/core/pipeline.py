"""End-to-end content generation pipeline orchestrator for IncuBrix.

Connects source ingestion, multi-platform draft generation, automated quality gates,
local media preview rendering, UTM tracking, calendar CSV exports, human review
workflow registration, and structured run summaries into a single reproducible command.

Safeguards:
- 100% OFFLINE_DETERMINISTIC execution. Zero network calls, zero external APIs.
- Automated generation never approves assets. All assets start in PENDING_REVIEW.
- Quality PASS does not equal publication authorization or factual verification.
- Prohibited Category 4 claims are strictly blocked from approval.
- Preserves full source traceability (document name, segment IDs, excerpt) throughout.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

from app.models.asset import (
    SourceSegment,
    DraftCandidate,
    PlatformEnum,
    AssetFormatEnum,
    ClaimCategoryEnum
)
from app.models.review import (
    ReviewStatusEnum,
    ReviewableAsset
)
from app.core.ingestion import (
    validate_source_path,
    ingest_source_document
)
from app.core.generator import (
    generate_draft_candidates
)
from app.core.quality_gate import (
    evaluate_asset_quality,
    QualityCheckResult,
    QualityGateStatusEnum,
    DEFAULT_LIMITS
)
from app.core.media_renderer import (
    render_video_preview,
    render_carousel_preview
)
from app.core.utm import (
    generate_utm_tracking_url,
    validate_destination_url,
    DEFAULT_CAMPAIGN,
    UTMStatusEnum
)
from app.core.calendar_export import (
    export_calendar_csv_file,
    CALENDAR_CSV_COLUMNS,
    CALENDAR_WITH_REVIEW_COLUMNS
)
from app.core.review_workflow import (
    ReviewWorkflowManager
)
from app.models.compliance import (
    BrandComplianceProfile,
    BrandComplianceResult,
    ComplianceStatusEnum,
    DestinationUrlStatusEnum,
    RightsStatusEnum
)
from app.core.brand_compliance import (
    evaluate_brand_compliance,
    generate_compliance_report,
    get_default_brand_profile
)


SUPPORTED_PLATFORMS: Set[str] = {p.value for p in PlatformEnum}


@dataclass
class PipelineResult:
    """Consolidated result of an end-to-end pipeline run."""
    run_id: str
    run_dir: Path
    source_document: str
    source_path: Path
    total_segments: int
    total_candidates: int
    platform_counts: Dict[str, int]
    quality_counts: Dict[str, int]
    review_status_counts: Dict[str, int]
    approved_export_count: int
    unapproved_export_count: int
    media_rendered_count: int
    media_skipped_count: int
    media_failed_count: int
    has_destination_url: bool
    destination_url: Optional[str]
    target_count: Optional[int]
    target_met: bool
    shortfall: int
    execution_duration_seconds: float
    stage_statuses: Dict[str, str]
    warnings: List[str]
    errors: List[str]
    drafts: List[DraftCandidate]
    quality_results: List[QualityCheckResult]
    review_assets: List[ReviewableAsset]
    compliance_counts: Dict[str, int] = field(default_factory=dict)
    compliance_results: List[BrandComplianceResult] = field(default_factory=list)

    def to_summary_dict(self) -> Dict[str, Any]:
        """Returns JSON-serializable dictionary representation of the run summary."""
        return {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
            "execution_duration_seconds": round(self.execution_duration_seconds, 3),
            "source_provenance": {
                "source_document": self.source_document,
                "source_path": str(self.source_path),
                "total_segments_ingested": self.total_segments
            },
            "generation_metrics": {
                "total_candidates_generated": self.total_candidates,
                "platform_breakdown": self.platform_counts,
                "target_count": self.target_count,
                "target_met": self.target_met,
                "shortfall": self.shortfall,
                "duplicate_padding_applied": False
            },
            "quality_gate_summary": {
                "counts": self.quality_counts,
                "pass_rate_percent": round((self.quality_counts.get("PASS", 0) / max(1, self.total_candidates)) * 100, 1),
                "ready_to_publish_count": 0,
                "human_review_required_count": self.total_candidates
            },
            "compliance_summary": {
                "status_counts": self.compliance_counts,
                "destination_url_counts": {
                    s: sum(1 for c in self.compliance_results if c.destination_url_status.value == s)
                    for s in ["APPROVED", "UNAPPROVED", "PENDING_DESTINATION_URL", "INVALID"]
                } if self.compliance_results else {},
                "media_rights_counts": {
                    s: sum(1 for c in self.compliance_results if c.rights_status.value == s)
                    for s in ["VERIFIED", "PENDING_VERIFICATION", "RESTRICTED", "NOT_APPLICABLE"]
                } if self.compliance_results else {},
                "unsupported_claim_count": sum(
                    1 for c in self.compliance_results if any("Violation" in f or "CAT_4" in f for f in c.unsupported_claim_findings)
                ) if self.compliance_results else 0,
                "human_review_required": True,
                "ready_to_publish_count": 0
            },
            "media_rendering_summary": {
                "rendered_count": self.media_rendered_count,
                "skipped_count": self.media_skipped_count,
                "failed_count": self.media_failed_count
            },
            "review_workflow_summary": {
                "review_status_counts": self.review_status_counts,
                "approved_export_count": self.approved_export_count,
                "unapproved_export_count": self.unapproved_export_count,
                "automated_approvals_applied": False
            },
            "attribution_and_tracking": {
                "has_destination_url": self.has_destination_url,
                "destination_url": self.destination_url,
                "tracking_urls_generated": self.has_destination_url
            },
            "stages": self.stage_statuses,
            "warnings": self.warnings,
            "errors": self.errors,
            "output_paths": {
                "run_dir": str(self.run_dir),
                "complete_calendar": str(self.run_dir / "calendars" / "complete_draft_calendar.csv"),
                "approved_calendar": str(self.run_dir / "calendars" / "approved_calendar.csv"),
                "unapproved_calendar": str(self.run_dir / "calendars" / "unapproved_calendar.csv"),
                "quality_report": str(self.run_dir / "quality" / "quality_report.json"),
                "compliance_report": str(self.run_dir / "compliance" / "compliance_report.json"),
                "pipeline_summary": str(self.run_dir / "summaries" / "pipeline_summary.json"),
                "review_store": str(self.run_dir / "summaries" / "review_store.json"),
                "media_dir": str(self.run_dir / "media")
            }
        }


def run_content_pipeline(
    source_path: Union[str, Path],
    platforms: Optional[List[Union[PlatformEnum, str]]] = None,
    destination_url: Optional[str] = None,
    output_dir: Optional[Union[str, Path]] = None,
    campaign: str = DEFAULT_CAMPAIGN,
    render_media: bool = True,
    target_count: Optional[int] = None,
    run_id: Optional[str] = None,
    brand_profile: Optional[BrandComplianceProfile] = None,
    destination_url_map: Optional[Dict[str, Optional[str]]] = None,
    schedule_map: Optional[Dict[str, Tuple[str, str]]] = None
) -> PipelineResult:
    """Executes the complete, deterministic 10-stage IncuBrix content pipeline.

    Stages:
    1. Validate input source and parameters.
    2. Ingest source document into traceable segments.
    3. Generate multi-platform candidate drafts.
    4. Run initial automated quality checks.
    5. Render supported media previews (video/carousel) and probe streams.
    6. Re-evaluate quality gate with rendered media artifacts on disk.
    7. Brand compliance, rights safety, and platform readiness evaluation.
    8. Build UTM tracking links and register candidates into review workflow.
    9. Export complete draft calendar, approved calendar, and unapproved calendar.
    10. Write consolidated run summary, quality reports, and compliance reports.
    """
    start_time = time.perf_counter()
    warnings: List[str] = []
    errors: List[str] = []
    stage_statuses: Dict[str, str] = {}

    # Initialize Unique Run ID and Directory
    actual_run_id = run_id or f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    base_out = Path(output_dir) if output_dir else Path("output/pipeline_runs")
    run_dir = base_out / actual_run_id

    calendars_dir = run_dir / "calendars"
    quality_dir = run_dir / "quality"
    compliance_dir = run_dir / "compliance"
    media_dir = run_dir / "media"
    summaries_dir = run_dir / "summaries"

    for d in (calendars_dir, quality_dir, compliance_dir, media_dir, summaries_dir):
        d.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------------
    # STAGE 1: Input Validation
    # --------------------------------------------------------------------------
    stage_statuses["stage_1_input_validation"] = "RUNNING"
    try:
        resolved_source = validate_source_path(source_path)
        stage_statuses["stage_1_input_validation"] = "SUCCESS"
    except Exception as e:
        stage_statuses["stage_1_input_validation"] = "FAILED"
        errors.append(f"Input validation error: {e}")
        raise

    # Validate platform filter if provided
    platform_filter_set: Optional[Set[str]] = None
    if platforms:
        platform_filter_set = set()
        for p in platforms:
            p_val = p.value if isinstance(p, PlatformEnum) else str(p).strip().lower()
            if p_val not in SUPPORTED_PLATFORMS:
                raise ValueError(
                    f"Unsupported platform '{p_val}'. Supported platforms: {sorted(list(SUPPORTED_PLATFORMS))}"
                )
            platform_filter_set.add(p_val)

    # Validate destination URL if provided
    clean_destination_url: Optional[str] = None
    if destination_url and destination_url.strip():
        try:
            clean_destination_url = validate_destination_url(destination_url.strip())
        except ValueError as url_err:
            warnings.append(f"Destination URL validation warning: {url_err}")

    # --------------------------------------------------------------------------
    # STAGE 2: Source Ingestion
    # --------------------------------------------------------------------------
    stage_statuses["stage_2_source_ingestion"] = "RUNNING"
    try:
        segments = ingest_source_document(resolved_source)
        source_doc_name = resolved_source.name
        stage_statuses["stage_2_source_ingestion"] = "SUCCESS"
    except Exception as e:
        stage_statuses["stage_2_source_ingestion"] = "FAILED"
        errors.append(f"Source ingestion failed: {e}")
        raise

    # --------------------------------------------------------------------------
    # STAGE 3: Candidate Draft Generation
    # --------------------------------------------------------------------------
    stage_statuses["stage_3_candidate_generation"] = "RUNNING"
    try:
        all_drafts = generate_draft_candidates(segments)
        if platform_filter_set:
            drafts = [d for d in all_drafts if d.platform.value in platform_filter_set]
        else:
            drafts = all_drafts

        total_candidates = len(drafts)
        platform_counts: Dict[str, int] = {}
        for d in drafts:
            p_name = d.platform.value
            platform_counts[p_name] = platform_counts.get(p_name, 0) + 1

        stage_statuses["stage_3_candidate_generation"] = "SUCCESS"
    except Exception as e:
        stage_statuses["stage_3_candidate_generation"] = "FAILED"
        errors.append(f"Candidate generation failed: {e}")
        raise

    # Shortfall Calculation
    target_met = True
    shortfall = 0
    if target_count is not None and target_count > 0:
        if total_candidates < target_count:
            target_met = False
            shortfall = target_count - total_candidates
            warnings.append(
                f"Generation shortfall: Requested target of {target_count} assets, "
                f"but source material honestly yielded {total_candidates} assets without duplication."
            )

    # --------------------------------------------------------------------------
    # STAGE 4: Initial Quality Evaluation (Pre-Media)
    # --------------------------------------------------------------------------
    stage_statuses["stage_4_quality_evaluation"] = "RUNNING"
    quality_results_map: Dict[str, QualityCheckResult] = {}
    for d in drafts:
        qr = evaluate_asset_quality(d)
        quality_results_map[d.draft_id] = qr
    stage_statuses["stage_4_quality_evaluation"] = "SUCCESS"

    # --------------------------------------------------------------------------
    # STAGE 5 & 6: Media Preview Rendering & Re-Evaluation
    # --------------------------------------------------------------------------
    stage_statuses["stage_5_media_rendering"] = "RUNNING"
    media_rendered = 0
    media_skipped = 0
    media_failed = 0
    render_dir_map: Dict[str, Path] = {}

    if render_media:
        for d in drafts:
            asset_media_dir = media_dir / d.draft_id
            if d.content_format == AssetFormatEnum.SHORT_VIDEO:
                try:
                    render_video_preview(d, asset_media_dir)
                    media_rendered += 1
                    render_dir_map[d.draft_id] = asset_media_dir
                except Exception as e:
                    media_failed += 1
                    warnings.append(f"Failed to render video preview for '{d.draft_id}': {e}")
            elif d.content_format == AssetFormatEnum.CAROUSEL:
                try:
                    render_carousel_preview(d, asset_media_dir)
                    media_rendered += 1
                    render_dir_map[d.draft_id] = asset_media_dir
                except Exception as e:
                    media_failed += 1
                    warnings.append(f"Failed to render carousel preview for '{d.draft_id}': {e}")
            else:
                # Text post or Thread formats do not require video/carousel rendering
                media_skipped += 1

        stage_statuses["stage_5_media_rendering"] = "SUCCESS" if media_failed == 0 else "WARNING"
    else:
        media_skipped = len(drafts)
        stage_statuses["stage_5_media_rendering"] = "SKIPPED"

    # Re-evaluate quality gate for drafts that have rendered media directories
    for d in drafts:
        r_dir = render_dir_map.get(d.draft_id)
        if r_dir:
            quality_results_map[d.draft_id] = evaluate_asset_quality(d, render_dir=r_dir)

    quality_results = [quality_results_map[d.draft_id] for d in drafts]
    quality_counts = {"PASS": 0, "PASS_WITH_WARNINGS": 0, "FAIL": 0}
    for qr in quality_results:
        q_val = qr.overall_status.value
        quality_counts[q_val] = quality_counts.get(q_val, 0) + 1

    # --------------------------------------------------------------------------
    # STAGE 7: Brand Compliance, Rights Safety & Platform Readiness
    # --------------------------------------------------------------------------
    stage_statuses["stage_7_compliance_evaluation"] = "RUNNING"
    active_profile = brand_profile or get_default_brand_profile()
    compliance_results_map: Dict[str, BrandComplianceResult] = {}
    for d in drafts:
        r_dir = render_dir_map.get(d.draft_id)
        effective_dest = (
            destination_url_map.get(d.draft_id)
            if destination_url_map and d.draft_id in destination_url_map
            else clean_destination_url
        )
        cr = evaluate_brand_compliance(
            draft=d,
            destination_url=effective_dest,
            render_dir=r_dir,
            profile=active_profile
        )
        compliance_results_map[d.draft_id] = cr

    compliance_results = [compliance_results_map[d.draft_id] for d in drafts]
    compliance_counts = {"PASS": 0, "PASS_WITH_WARNINGS": 0, "FAIL": 0, "NOT_ASSESSED": 0}
    for cr in compliance_results:
        c_val = cr.brand_compliance_status.value
        compliance_counts[c_val] = compliance_counts.get(c_val, 0) + 1

    compliance_report_file = compliance_dir / "compliance_report.json"
    generate_compliance_report(
        results=compliance_results,
        run_id=actual_run_id,
        output_path=compliance_report_file
    )
    stage_statuses["stage_7_compliance_evaluation"] = "SUCCESS"

    # --------------------------------------------------------------------------
    # STAGE 8: Human Review Registration
    # --------------------------------------------------------------------------
    stage_statuses["stage_8_review_registration"] = "RUNNING"
    review_store_path = summaries_dir / "review_store.json"
    workflow_manager = ReviewWorkflowManager(storage_path=review_store_path)

    review_assets = workflow_manager.register_batch(
        drafts=drafts,
        quality_results=[quality_results_map[d.draft_id] for d in drafts],
        compliance_results=compliance_results,
        render_map=render_dir_map
    )

    review_status_counts = {"PENDING_REVIEW": 0, "IN_REVIEW": 0, "REVISION_REQUESTED": 0, "REJECTED": 0, "APPROVED": 0}
    for a in review_assets:
        s_val = a.review_status.value
        review_status_counts[s_val] = review_status_counts.get(s_val, 0) + 1

    stage_statuses["stage_8_review_registration"] = "SUCCESS"

    # --------------------------------------------------------------------------
    # STAGE 9: Calendar CSV Exports
    # --------------------------------------------------------------------------
    stage_statuses["stage_9_calendar_exports"] = "RUNNING"
    complete_cal_path = calendars_dir / "complete_draft_calendar.csv"
    approved_cal_path = calendars_dir / "approved_calendar.csv"
    unapproved_cal_path = calendars_dir / "unapproved_calendar.csv"

    # Export complete calendar (all registered candidates) with compliance columns
    workflow_manager.export_all_candidates_calendar_csv(
        output_path=complete_cal_path,
        destination_url=clean_destination_url,
        campaign=campaign,
        include_review_columns=True,
        include_compliance_columns=True,
        schedule_map=schedule_map
    )

    # Export approved calendar (only strictly approved assets - initially 0)
    workflow_manager.export_approved_assets_calendar_csv(
        output_path=approved_cal_path,
        destination_url=clean_destination_url,
        campaign=campaign,
        include_compliance_columns=True,
        schedule_map=schedule_map
    )

    # Export unapproved calendar (all pending/rejected/in-review assets)
    workflow_manager.export_unapproved_assets_calendar_csv(
        output_path=unapproved_cal_path,
        destination_url=clean_destination_url,
        campaign=campaign,
        include_compliance_columns=True,
        schedule_map=schedule_map
    )

    approved_count = review_status_counts.get("APPROVED", 0)
    unapproved_count = total_candidates - approved_count
    stage_statuses["stage_9_calendar_exports"] = "SUCCESS"

    # --------------------------------------------------------------------------
    # STAGE 10: Run Summary & Quality Reporting
    # --------------------------------------------------------------------------
    stage_statuses["stage_10_summary_reporting"] = "SUCCESS"
    execution_duration = time.perf_counter() - start_time

    # Write non-developer quality report
    quality_report_data = {
        "report_title": "IncuBrix Content Quality Gate Evaluation Report",
        "run_id": actual_run_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "total_assets_evaluated": total_candidates,
        "summary_counts": quality_counts,
        "human_review_required": True,
        "ready_to_publish": 0,
        "asset_evaluations": [
            {
                "asset_id": qr.asset_id,
                "overall_status": qr.overall_status.value,
                "platform": qr.platform,
                "content_format": qr.content_format,
                "passed_checks_count": len(qr.passed_checks),
                "failed_checks_count": len(qr.failed_checks),
                "warnings_count": len(qr.warnings),
                "failed_checks": qr.failed_checks,
                "warnings": qr.warnings,
                "requires_human_review": qr.requires_human_review,
                "is_ready_to_publish": qr.is_ready_to_publish
            }
            for qr in quality_results
        ]
    }
    quality_report_file = quality_dir / "quality_report.json"
    quality_report_file.write_text(json.dumps(quality_report_data, indent=2), encoding="utf-8")

    result = PipelineResult(
        run_id=actual_run_id,
        run_dir=run_dir,
        source_document=source_doc_name,
        source_path=resolved_source,
        total_segments=len(segments),
        total_candidates=total_candidates,
        platform_counts=platform_counts,
        quality_counts=quality_counts,
        review_status_counts=review_status_counts,
        approved_export_count=approved_count,
        unapproved_export_count=unapproved_count,
        media_rendered_count=media_rendered,
        media_skipped_count=media_skipped,
        media_failed_count=media_failed,
        has_destination_url=bool(clean_destination_url),
        destination_url=clean_destination_url,
        target_count=target_count,
        target_met=target_met,
        shortfall=shortfall,
        execution_duration_seconds=execution_duration,
        stage_statuses=stage_statuses,
        warnings=warnings,
        errors=errors,
        drafts=drafts,
        quality_results=quality_results,
        review_assets=review_assets,
        compliance_counts=compliance_counts,
        compliance_results=compliance_results
    )

    # Write consolidated pipeline summary JSON
    pipeline_summary_file = summaries_dir / "pipeline_summary.json"
    pipeline_summary_file.write_text(json.dumps(result.to_summary_dict(), indent=2), encoding="utf-8")

    return result
