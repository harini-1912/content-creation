"""Batch content generation and quality-auditing module.

Ingests long-form source documents, deterministically derives platform-specific
draft candidate assets, executes the objective quality gate across all candidates,
and outputs non-developer-readable summary reports.

Preserves full source traceability without duplicate padding, artificial approval,
or mock data substitution.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from app.models.asset import SourceSegment, DraftCandidate
from app.core.ingestion import ingest_source_document
from app.core.generator import generate_draft_candidates
from app.core.quality_gate import (
    evaluate_asset_quality,
    QualityCheckResult,
    QualityGateStatusEnum
)


@dataclass
class BatchGenerationResult:
    """Summary and payload resulting from batch content generation."""
    source_document: str
    target_count: Optional[int]
    total_segments_ingested: int
    total_assets_generated: int
    target_met: bool
    shortfall: int
    drafts: List[DraftCandidate] = field(default_factory=list)
    quality_results: List[QualityCheckResult] = field(default_factory=list)
    summary_counts: Dict[str, int] = field(default_factory=dict)
    platform_counts: Dict[str, int] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_report_dict(self) -> Dict[str, Any]:
        """Produces a non-developer friendly structured summary dictionary."""
        return {
            "title": "IncuBrix Content Engine — Batch Generation & Quality Gate Report",
            "generated_at": self.generated_at,
            "source_provenance": {
                "source_document": self.source_document,
                "total_source_segments_extracted": self.total_segments_ingested
            },
            "generation_metrics": {
                "target_assets_requested": self.target_count,
                "total_unique_assets_generated": self.total_assets_generated,
                "target_goal_satisfied": self.target_met,
                "shortfall": self.shortfall,
                "duplicate_padding_applied": False,
                "shortfall_notice": (
                    f"Shortfall of {self.shortfall} assets: The source text yielded {self.total_segments_ingested} "
                    f"distinct segments ({self.total_assets_generated} unique multi-platform drafts). "
                    "The engine reports this shortfall honestly rather than duplicating copy."
                    if self.shortfall > 0 else "Target quantity satisfied with distinct, source-derived content."
                )
            },
            "quality_gate_summary": {
                "total_assets_evaluated": len(self.quality_results),
                "passed_cleanly": self.summary_counts.get("pass", 0),
                "passed_with_warnings": self.summary_counts.get("pass_with_warnings", 0),
                "failed_quality_gate": self.summary_counts.get("fail", 0),
                "requiring_human_review": self.summary_counts.get("requires_human_review", 0),
                "factually_verified": self.summary_counts.get("factually_verified", 0),
                "ready_to_publish": self.summary_counts.get("ready_to_publish", 0),
                "governance_rule": (
                    "Automated validation assesses technical and structural formatting only. "
                    "All generated drafts remain DRAFT_PENDING_REVIEW and require human editorial sign-off. "
                    "Zero assets are marked ready to publish automatically."
                )
            },
            "platform_distribution": self.platform_counts,
            "asset_evaluations": [
                {
                    "asset_id": q.asset_id,
                    "platform": q.platform,
                    "format": q.content_format,
                    "status": q.overall_status.value,
                    "claim_classification": q.claim_category,
                    "source_segment_id": q.source_segment_id,
                    "requires_human_review": q.requires_human_review,
                    "ready_to_publish": q.is_ready_to_publish,
                    "failed_checks": q.failed_checks,
                    "warnings": q.warnings,
                    "passed_checks_count": len(q.passed_checks)
                }
                for q in self.quality_results
            ]
        }


def run_batch_generation(
    source_input: Union[str, Path, List[SourceSegment]],
    target_count: Optional[int] = 10,
    render_dir_map: Optional[Dict[str, Union[str, Path]]] = None
) -> BatchGenerationResult:
    """Executes end-to-end batch content generation and quality gating.

    1. Ingests source document or takes pre-extracted segments.
    2. Derives unique platform drafts deterministically.
    3. Runs the quality gate against each candidate draft.
    4. Compiles results, reporting any shortfall honestly without duplication.
    """
    if isinstance(source_input, (str, Path)):
        source_path = Path(source_input)
        segments = ingest_source_document(source_path)
        source_doc_name = source_path.name
    elif isinstance(source_input, list):
        segments = source_input
        source_doc_name = segments[0].source_document if segments else "unknown_document"
    else:
        raise ValueError(f"Unsupported source_input type: {type(source_input)}")

    if not segments:
        raise ValueError("Cannot run batch generation: no source segments provided.")

    # Generate multi-platform draft candidates
    drafts = generate_draft_candidates(segments)
    total_generated = len(drafts)

    # Calculate target fulfillment honestly (never invent duplicates)
    target_met = True
    shortfall = 0
    if target_count is not None and target_count > 0:
        if total_generated < target_count:
            target_met = False
            shortfall = target_count - total_generated

    # Evaluate each draft through the quality gate
    quality_results: List[QualityCheckResult] = []
    render_map = render_dir_map or {}

    pass_count = 0
    warning_count = 0
    fail_count = 0
    platform_counts: Dict[str, int] = {}

    for draft in drafts:
        p_name = draft.platform.value
        platform_counts[p_name] = platform_counts.get(p_name, 0) + 1

        render_dir = render_map.get(draft.draft_id)
        q_res = evaluate_asset_quality(draft, render_dir=render_dir)
        quality_results.append(q_res)

        if q_res.overall_status == QualityGateStatusEnum.PASS:
            pass_count += 1
        elif q_res.overall_status == QualityGateStatusEnum.PASS_WITH_WARNINGS:
            warning_count += 1
        elif q_res.overall_status == QualityGateStatusEnum.FAIL:
            fail_count += 1

    summary_counts = {
        "total_generated": total_generated,
        "pass": pass_count,
        "pass_with_warnings": warning_count,
        "fail": fail_count,
        "requires_human_review": total_generated,  # 100% of drafts require review
        "factually_verified": 0,                   # 0% automatically verified
        "ready_to_publish": 0                      # 0% ready to publish
    }

    return BatchGenerationResult(
        source_document=source_doc_name,
        target_count=target_count,
        total_segments_ingested=len(segments),
        total_assets_generated=total_generated,
        target_met=target_met,
        shortfall=shortfall,
        drafts=drafts,
        quality_results=quality_results,
        summary_counts=summary_counts,
        platform_counts=platform_counts
    )


def export_quality_report_json(
    batch_result: BatchGenerationResult,
    output_path: Union[str, Path]
) -> Path:
    """Writes a human-understandable quality audit report in JSON format."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    report_data = batch_result.to_report_dict()
    path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    return path

