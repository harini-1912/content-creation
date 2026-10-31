"""Content calendar CSV export module.

Exports draft candidates to a standard UTF-8 CSV suitable for import into
social media schedulers (Buffer, Hootsuite) or spreadsheet review in Excel.
Preserves complete source traceability, enforces DRAFT_PENDING_REVIEW status,
integrates objective quality gate statuses, and avoids fabricating performance
metrics or publication claims.
"""

import csv
import io
from pathlib import Path
from typing import List, Dict, Optional, Union, Any

from app.models.asset import DraftCandidate, PlatformEnum, AssetFormatEnum
from app.core.utm import generate_utm_tracking_url, DEFAULT_CAMPAIGN

# Stable column headers for scheduler/Excel calendar export
CALENDAR_CSV_COLUMNS = [
    "asset_id",
    "platform",
    "content_format",
    "content_pillar",
    "hook",
    "caption_or_script",
    "hashtags",
    "call_to_action",
    "destination_url",
    "tracking_url",
    "scheduled_date",
    "scheduled_time",
    "target_metric",
    "source_document",
    "source_segment_id",
    "claim_category",
    "requires_human_review",
    "publication_status",
    "warnings",
    "quality_gate_status"
]

# Extended review metadata columns appended without modifying or reordering base 20 columns
REVIEW_METADATA_COLUMNS = [
    "human_review_status",
    "reviewer_id",
    "approval_timestamp",
    "reviewer_notes"
]

CALENDAR_WITH_REVIEW_COLUMNS = CALENDAR_CSV_COLUMNS + REVIEW_METADATA_COLUMNS

# Extended compliance metadata columns appended without modifying or reordering earlier columns
COMPLIANCE_COLUMNS = [
    "brand_compliance_status",
    "destination_url_status",
    "rights_status",
    "platform_readiness_status"
]

CALENDAR_WITH_COMPLIANCE_COLUMNS = CALENDAR_WITH_REVIEW_COLUMNS + COMPLIANCE_COLUMNS

# Standard target metric hypotheses based on Strategy Doc 3
TARGET_METRIC_MAP: Dict[AssetFormatEnum, str] = {
    AssetFormatEnum.SHORT_VIDEO: "3s Retention Rate Hypothesis",
    AssetFormatEnum.CAROUSEL: "Post Saves / Bookmarks Hypothesis",
    AssetFormatEnum.TEXT_POST: "Discussion Comments / Reposts Hypothesis",
    AssetFormatEnum.THREAD: "Thread Expansion / Bookmark Hypothesis"
}


def convert_draft_to_calendar_row(
    draft: DraftCandidate,
    destination_url: Optional[str] = None,
    campaign: str = DEFAULT_CAMPAIGN,
    scheduled_date: str = "",
    scheduled_time: str = "",
    quality_status: Optional[str] = None,
    human_review_status: Optional[str] = None,
    reviewer_id: Optional[str] = None,
    approval_timestamp: Optional[str] = None,
    reviewer_notes: Optional[str] = None,
    include_review_columns: bool = False,
    brand_compliance_status: Optional[str] = None,
    destination_url_status: Optional[str] = None,
    rights_status: Optional[str] = None,
    platform_readiness_status: Optional[str] = None,
    include_compliance_columns: bool = False
) -> Dict[str, str]:
    """Converts a DraftCandidate into a standardized CSV dictionary row."""
    # Resolve UTM tracking link if destination_url is provided
    tracking_url = ""
    clean_dest_url = ""
    if destination_url and destination_url.strip():
        if destination_url.strip() == "PENDING_DESTINATION_URL":
            clean_dest_url = "PENDING_DESTINATION_URL"
            tracking_url = "PENDING_DESTINATION_URL"
        else:
            utm_res = generate_utm_tracking_url(
                destination_url=destination_url.strip(),
                platform=draft.platform,
                content_format=draft.content_format,
                campaign=campaign,
                content_id=draft.draft_id
            )
            if utm_res.is_generated and utm_res.tracking_url:
                clean_dest_url = utm_res.original_url or ""
                tracking_url = utm_res.tracking_url

    hashtags_str = " ".join(draft.suggested_hashtags) if draft.suggested_hashtags else ""
    target_metric = TARGET_METRIC_MAP.get(draft.content_format, "Engagement Rate Hypothesis")
    warnings_str = "; ".join(draft.warnings) if draft.warnings else ""
    q_status = quality_status.strip() if quality_status and quality_status.strip() else "NOT_EVALUATED"

    # Human review publication status mapping
    rev_status = human_review_status.strip().upper() if human_review_status and human_review_status.strip() else "PENDING_REVIEW"
    if rev_status == "APPROVED":
        pub_status = "APPROVED_FOR_SCHEDULING"
    elif rev_status == "REJECTED":
        pub_status = "REJECTED"
    elif rev_status == "REVISION_REQUESTED":
        pub_status = "REVISION_REQUIRED"
    else:
        pub_status = "DRAFT_PENDING_REVIEW"

    row = {
        "asset_id": draft.draft_id,
        "platform": draft.platform.value,
        "content_format": draft.content_format.value,
        "content_pillar": draft.pillar.value,
        "hook": draft.draft_hook,
        "caption_or_script": draft.draft_caption,
        "hashtags": hashtags_str,
        "call_to_action": draft.call_to_action,
        "destination_url": clean_dest_url,
        "tracking_url": tracking_url,
        "scheduled_date": scheduled_date.strip(),
        "scheduled_time": scheduled_time.strip(),
        "target_metric": target_metric,
        "source_document": draft.source_document,
        "source_segment_id": draft.source_segment_id,
        "claim_category": draft.claim_category.value,
        "requires_human_review": "TRUE",
        "publication_status": pub_status,
        "warnings": warnings_str,
        "quality_gate_status": q_status
    }

    if include_review_columns:
        row["human_review_status"] = rev_status
        row["reviewer_id"] = (reviewer_id or "").strip()
        row["approval_timestamp"] = (approval_timestamp or "").strip()
        row["reviewer_notes"] = (reviewer_notes or "").strip()

    if include_compliance_columns:
        row["brand_compliance_status"] = (brand_compliance_status or "NOT_ASSESSED").strip()
        row["destination_url_status"] = (destination_url_status or "PENDING_DESTINATION_URL").strip()
        row["rights_status"] = (rights_status or "NOT_APPLICABLE").strip()
        row["platform_readiness_status"] = (platform_readiness_status or "NOT_ASSESSED").strip()

    return row


def export_calendar_csv_string(
    drafts: List[DraftCandidate],
    destination_url: Optional[str] = None,
    campaign: str = DEFAULT_CAMPAIGN,
    quality_results: Optional[List[Any]] = None,
    include_review_columns: bool = False,
    review_metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
    include_compliance_columns: bool = False,
    compliance_results: Optional[Union[List[Any], Dict[str, Any]]] = None
) -> str:
    """Exports a list of DraftCandidate instances to a CSV-formatted string.

    Uses RFC 4180 standard escaping for newlines, quotes, and commas.
    """
    quality_map: Dict[str, str] = {}
    if quality_results:
        for qr in quality_results:
            aid = getattr(qr, "asset_id", None) or (qr.get("asset_id") if isinstance(qr, dict) else None)
            stat = getattr(qr, "overall_status", None) or (qr.get("overall_status") if isinstance(qr, dict) else None)
            if aid and stat:
                val = stat.value if hasattr(stat, "value") else str(stat)
                quality_map[aid] = val

    compliance_map: Dict[str, Any] = {}
    if compliance_results:
        if isinstance(compliance_results, dict):
            compliance_map = compliance_results
        else:
            for cr in compliance_results:
                aid = getattr(cr, "asset_id", None) or (cr.get("asset_id") if isinstance(cr, dict) else None)
                if aid:
                    compliance_map[aid] = cr

    rev_map = review_metadata_map or {}
    
    if include_compliance_columns:
        fieldnames = CALENDAR_WITH_COMPLIANCE_COLUMNS if include_review_columns else (CALENDAR_CSV_COLUMNS + COMPLIANCE_COLUMNS)
    else:
        fieldnames = CALENDAR_WITH_REVIEW_COLUMNS if include_review_columns else CALENDAR_CSV_COLUMNS

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
        extrasaction="ignore"
    )
    writer.writeheader()

    for draft in drafts:
        q_stat = quality_map.get(draft.draft_id)
        r_meta = rev_map.get(draft.draft_id, {})
        cr = compliance_map.get(draft.draft_id)

        bc_stat = None
        dest_stat = None
        r_stat = None
        pr_stat = None

        if cr:
            bc_stat = getattr(cr, "brand_compliance_status", None)
            bc_stat = bc_stat.value if hasattr(bc_stat, "value") else str(bc_stat or "")
            dest_stat = getattr(cr, "destination_url_status", None)
            dest_stat = dest_stat.value if hasattr(dest_stat, "value") else str(dest_stat or "")
            r_stat = getattr(cr, "rights_status", None)
            r_stat = r_stat.value if hasattr(r_stat, "value") else str(r_stat or "")
            pr_stat = getattr(cr, "platform_readiness_status", None)
            pr_stat = pr_stat.value if hasattr(pr_stat, "value") else str(pr_stat or "")

        dest_url = r_meta.get("destination_url", destination_url)
        sched_date = r_meta.get("scheduled_date", "")
        sched_time = r_meta.get("scheduled_time", "")

        row = convert_draft_to_calendar_row(
            draft,
            destination_url=dest_url,
            campaign=campaign,
            scheduled_date=sched_date,
            scheduled_time=sched_time,
            quality_status=q_stat,
            human_review_status=r_meta.get("human_review_status"),
            reviewer_id=r_meta.get("reviewer_id"),
            approval_timestamp=r_meta.get("approval_timestamp"),
            reviewer_notes=r_meta.get("reviewer_notes"),
            include_review_columns=include_review_columns,
            brand_compliance_status=bc_stat,
            destination_url_status=dest_stat,
            rights_status=r_stat,
            platform_readiness_status=pr_stat,
            include_compliance_columns=include_compliance_columns
        )
        writer.writerow(row)

    return output.getvalue()


def export_calendar_csv_file(
    drafts: List[DraftCandidate],
    output_path: Union[str, Path],
    destination_url: Optional[str] = None,
    campaign: str = DEFAULT_CAMPAIGN,
    quality_results: Optional[List[Any]] = None,
    include_review_columns: bool = False,
    review_metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
    include_compliance_columns: bool = False,
    compliance_results: Optional[Union[List[Any], Dict[str, Any]]] = None
) -> Path:
    """Exports drafts to a CSV file on disk using UTF-8 with BOM (utf-8-sig) for Excel compatibility.

    Ensures parent directories exist before writing. Never overwrites unrelated files.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    csv_content = export_calendar_csv_string(
        drafts=drafts,
        destination_url=destination_url,
        campaign=campaign,
        quality_results=quality_results,
        include_review_columns=include_review_columns,
        review_metadata_map=review_metadata_map,
        include_compliance_columns=include_compliance_columns,
        compliance_results=compliance_results
    )

    path.write_text(csv_content, encoding="utf-8-sig")
    return path
