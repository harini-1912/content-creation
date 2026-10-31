"""Human review, content refinement, and approval workflow module.

Implements an auditable, human-controlled editorial process for IncuBrix content assets.

Core Principles:
1. Automated quality gates (PASS, PASS_WITH_WARNINGS, FAIL) are distinct from human review states
   (PENDING_REVIEW, IN_REVIEW, REVISION_REQUESTED, REJECTED, APPROVED).
2. Automated generation or evaluation NEVER automatically approves an asset.
3. Reviewer identity, approval timestamp, and explicit claim-review confirmations are mandatory for approval.
4. Substantive content edits invalidate previous approvals and return the asset to review.
5. Original generated content and source traceability are preserved across all revisions.
6. Approval represents editorial clearance for scheduling consideration; it never triggers social-media publishing.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from app.models.asset import (
    DraftCandidate,
    PlatformEnum,
    AssetFormatEnum,
    ClaimCategoryEnum
)
from app.models.review import (
    ReviewStatusEnum,
    ReviewActionEnum,
    ReviewActionRecord,
    ReviewableAsset
)
from app.models.compliance import (
    BrandComplianceResult,
    BrandComplianceProfile,
    MediaRightsRecord,
    ComplianceStatusEnum,
    DestinationUrlStatusEnum,
    RightsStatusEnum
)
from app.core.brand_compliance import evaluate_brand_compliance
from app.core.quality_gate import (
    evaluate_asset_quality,
    QualityCheckResult,
    QualityGateStatusEnum,
    DEFAULT_LIMITS
)
from app.core.generator import detect_claim_warnings
from app.core.calendar_export import (
    export_calendar_csv_string,
    export_calendar_csv_file,
    CALENDAR_CSV_COLUMNS,
    CALENDAR_WITH_REVIEW_COLUMNS
)
from app.core.utm import DEFAULT_CAMPAIGN


def _extract_quality_status(qr: Any) -> Optional[str]:
    """Helper to safely extract the quality status string from a QualityCheckResult object or dict."""
    if qr is None:
        return None
    val = qr.get("overall_status") if isinstance(qr, dict) else getattr(qr, "overall_status", None)
    if hasattr(val, "value"):
        return val.value
    return str(val) if val is not None else None


def _extract_quality_failures(qr: Any) -> List[str]:
    """Helper to safely extract failed checks from QualityCheckResult or dict."""
    if qr is None:
        return ["Quality gate not evaluated"]
    if isinstance(qr, dict):
        return qr.get("failed_checks", [])
    return getattr(qr, "failed_checks", []) or []


def _extract_quality_warnings(qr: Any) -> List[str]:
    """Helper to safely extract warnings from QualityCheckResult or dict."""
    if qr is None:
        return []
    if isinstance(qr, dict):
        return qr.get("warnings", [])
    return getattr(qr, "warnings", []) or []


class ReviewWorkflowManager:
    """Manages the lifecycle, refinements, audits, and persistence of human reviews."""

    def __init__(self, storage_path: Optional[Union[str, Path]] = None):
        """Initializes review workflow manager with optional local JSON persistence path."""
        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            self.storage_path = Path("output/reviews/review_store.json")

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.assets: Dict[str, ReviewableAsset] = {}

        if self.storage_path.exists():
            self.load()

    def save(self) -> Path:
        """Atomically persists all review assets and audit trails to disk with Windows lock resilience."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": "1.0",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total_assets": len(self.assets),
            "assets": {aid: asset.model_dump(mode="json") for aid, asset in self.assets.items()}
        }
        json_content = json.dumps(data, indent=2)
        temp_file = self.storage_path.with_suffix(f".tmp_{uuid.uuid4().hex[:8]}")
        temp_file.write_text(json_content, encoding="utf-8")

        # Retry atomic replace against brief OS/antivirus file locks
        for attempt in range(5):
            try:
                os.replace(temp_file, self.storage_path)
                return self.storage_path
            except PermissionError:
                import time
                time.sleep(0.05)

        # Fallback to direct write if replace is held
        self.storage_path.write_text(json_content, encoding="utf-8")
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass
        return self.storage_path

    def load(self) -> None:
        """Loads and strictly validates persisted review assets from disk.

        Safeguards for legacy records:
        - If a legacy record is marked APPROVED but lacks compliance_result, its approval
          is invalidated (reverting to PENDING_REVIEW) and an audit action is recorded.
          This preserves full history while preventing unverified legacy approvals.
        """
        if not self.storage_path.exists():
            return
        text = self.storage_path.read_text(encoding="utf-8")
        data = json.loads(text)
        assets_data = data.get("assets", {})
        self.assets = {}
        for aid, a_dict in assets_data.items():
            # Invalidate legacy approved assets that lack compliance results
            if (
                a_dict.get("review_status") == ReviewStatusEnum.APPROVED.value
                and a_dict.get("compliance_result") is None
            ):
                a_dict["review_status"] = ReviewStatusEnum.PENDING_REVIEW.value
                a_dict["approval_timestamp"] = None
                a_dict["claims_reviewed_confirmed"] = False
                a_dict["warnings_reviewed_confirmed"] = False
                action_rec = {
                    "action_id": f"act_legacy_rev_{uuid.uuid4().hex[:8]}",
                    "asset_id": aid,
                    "action": ReviewActionEnum.RECORD_FEEDBACK.value,
                    "reviewer_id": "System_Compliance_Gate",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "comments": (
                        "Legacy approval invalidated on load: Missing brand compliance evaluation. "
                        "Re-evaluation required prior to approval."
                    ),
                    "previous_status": ReviewStatusEnum.APPROVED.value,
                    "new_status": ReviewStatusEnum.PENDING_REVIEW.value,
                    "metadata": {"legacy_migration": True, "reason": "missing_compliance_result"}
                }
                hist = a_dict.get("review_history", [])
                hist.append(action_rec)
                a_dict["review_history"] = hist

            self.assets[aid] = ReviewableAsset.model_validate(a_dict)

    def register_draft(
        self,
        draft: DraftCandidate,
        quality_result: Optional[QualityCheckResult] = None,
        compliance_result: Optional[BrandComplianceResult] = None,
        render_dir: Optional[Union[str, Path]] = None,
        auto_evaluate: bool = True,
        auto_save: bool = True
    ) -> ReviewableAsset:
        """Registers a newly generated draft candidate into the human review workflow.

        Begins in PENDING_REVIEW state. Preserves original draft content immutably.
        """
        asset_id = draft.draft_id
        if asset_id in self.assets:
            if compliance_result is not None and self.assets[asset_id].compliance_result is None:
                self.assets[asset_id].compliance_result = compliance_result
                if auto_save:
                    self.save()
            return self.assets[asset_id]

        # Ensure render directory is recorded on draft and asset
        r_dir_str = str(render_dir) if render_dir is not None else draft.render_directory
        if r_dir_str and draft.render_directory != r_dir_str:
            draft = draft.model_copy(update={"render_directory": r_dir_str})

        # Evaluate quality gate if not supplied
        q_res = quality_result
        if q_res is None and auto_evaluate:
            q_res = evaluate_asset_quality(draft, render_dir=r_dir_str)

        # Evaluate brand compliance if not supplied
        c_res = compliance_result
        if c_res is None and auto_evaluate:
            c_res = evaluate_brand_compliance(draft, render_dir=r_dir_str)

        # Deep copy original draft to ensure it can never be mutated by edits
        original_copy = draft.model_copy(deep=True)
        now_iso = datetime.now(timezone.utc).isoformat()

        asset = ReviewableAsset(
            asset_id=asset_id,
            draft=draft.model_copy(deep=True),
            original_draft=original_copy,
            review_status=ReviewStatusEnum.PENDING_REVIEW,
            quality_result=q_res,
            compliance_result=c_res,
            render_dir=r_dir_str,
            review_history=[],
            created_at=now_iso,
            updated_at=now_iso
        )

        self.assets[asset_id] = asset
        if auto_save:
            self.save()
        return asset

    def register_batch(
        self,
        drafts: List[DraftCandidate],
        quality_results: Optional[List[QualityCheckResult]] = None,
        compliance_results: Optional[List[BrandComplianceResult]] = None,
        render_map: Optional[Dict[str, Union[str, Path]]] = None
    ) -> List[ReviewableAsset]:
        """Registers a collection of drafts from batch generation into the review workflow."""
        q_map: Dict[str, QualityCheckResult] = {}
        if quality_results:
            for qr in quality_results:
                q_map[qr.asset_id] = qr

        c_map: Dict[str, BrandComplianceResult] = {}
        if compliance_results:
            for cr in compliance_results:
                c_map[cr.asset_id] = cr

        r_map = render_map or {}
        registered: List[ReviewableAsset] = []
        for draft in drafts:
            qr = q_map.get(draft.draft_id)
            cr = c_map.get(draft.draft_id)
            r_dir = r_map.get(draft.draft_id)
            rev_asset = self.register_draft(
                draft=draft,
                quality_result=qr,
                compliance_result=cr,
                render_dir=r_dir,
                auto_evaluate=True,
                auto_save=False
            )
            registered.append(rev_asset)

        self.save()
        return registered

    def get_asset(self, asset_id: str) -> ReviewableAsset:
        """Retrieves an asset by identifier; raises KeyError if not found."""
        if asset_id not in self.assets:
            raise KeyError(f"Asset '{asset_id}' not found in review registry.")
        return self.assets[asset_id]

    def list_assets(self, status_filter: Optional[ReviewStatusEnum] = None) -> List[ReviewableAsset]:
        """Lists all registered review assets, optionally filtered by review status."""
        all_assets = list(self.assets.values())
        if status_filter is None:
            return all_assets
        return [a for a in all_assets if a.review_status == status_filter]

    def start_review(
        self,
        asset_id: str,
        reviewer_id: str,
        comments: str = ""
    ) -> ReviewableAsset:
        """Transitions an asset from PENDING_REVIEW or REVISION_REQUESTED into IN_REVIEW."""
        clean_reviewer = reviewer_id.strip() if reviewer_id else ""
        if not clean_reviewer:
            raise ValueError("Reviewer identity is required to start review.")

        asset = self.get_asset(asset_id)
        if asset.review_status == ReviewStatusEnum.REJECTED:
            raise ValueError(f"Cannot start review on rejected asset '{asset_id}'.")

        prev_status = asset.review_status
        now_iso = datetime.now(timezone.utc).isoformat()

        asset.review_status = ReviewStatusEnum.IN_REVIEW
        asset.reviewer_id = clean_reviewer
        asset.updated_at = now_iso

        action_rec = ReviewActionRecord(
            action_id=f"act_{uuid.uuid4().hex[:12]}",
            asset_id=asset_id,
            action=ReviewActionEnum.START_REVIEW,
            reviewer_id=clean_reviewer,
            timestamp=now_iso,
            comments=comments.strip() or "Reviewer opened asset for evaluation.",
            previous_status=prev_status,
            new_status=ReviewStatusEnum.IN_REVIEW
        )
        asset.review_history.append(action_rec)
        self.save()
        return asset

    def record_feedback(
        self,
        asset_id: str,
        reviewer_id: str,
        feedback: str
    ) -> ReviewableAsset:
        """Records reviewer feedback notes without changing current lifecycle state."""
        clean_reviewer = reviewer_id.strip() if reviewer_id else ""
        if not clean_reviewer:
            raise ValueError("Reviewer identity is required to record feedback.")
        clean_feedback = feedback.strip() if feedback else ""
        if not clean_feedback:
            raise ValueError("Feedback text is required.")

        asset = self.get_asset(asset_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        asset.updated_at = now_iso

        action_rec = ReviewActionRecord(
            action_id=f"act_{uuid.uuid4().hex[:12]}",
            asset_id=asset_id,
            action=ReviewActionEnum.RECORD_FEEDBACK,
            reviewer_id=clean_reviewer,
            timestamp=now_iso,
            comments=clean_feedback,
            previous_status=asset.review_status,
            new_status=asset.review_status
        )
        asset.review_history.append(action_rec)
        self.save()
        return asset

    def apply_refinements(
        self,
        asset_id: str,
        reviewer_id: str,
        hook: Optional[str] = None,
        caption: Optional[str] = None,
        hashtags: Optional[List[str]] = None,
        call_to_action: Optional[str] = None,
        content_format: Optional[AssetFormatEnum] = None,
        destination_url: Optional[str] = None,
        media_rights: Optional[List[MediaRightsRecord]] = None,
        brand_profile: Optional[BrandComplianceProfile] = None,
        reviewer_notes: Optional[str] = None,
        render_dir: Optional[Union[str, Path]] = None,
        platform: Optional[PlatformEnum] = None,
        source_segment_id: Optional[str] = None,
        source_document: Optional[str] = None
    ) -> ReviewableAsset:
        """Applies human editorial refinements to an asset.

        Preserves original generated content untouched.
        Re-evaluates the asset through the quality gate.
        Re-evaluates brand compliance and invalidates any previous compliance PASS.
        Substantive edits invalidate any prior approval and reset to IN_REVIEW.
        Explicitly rejects unsupported mutations (platform, source attribution).
        """
        clean_reviewer = reviewer_id.strip() if reviewer_id else ""
        if not clean_reviewer:
            raise ValueError("Reviewer identity is required to apply refinements.")

        asset = self.get_asset(asset_id)
        current_draft = asset.draft

        # Explicitly reject unsupported structural mutations
        if platform is not None and platform != current_draft.platform:
            raise ValueError(
                f"Modifying platform from '{current_draft.platform.value}' to '{platform.value}' "
                "is not supported on existing drafts. Platform transformation requires re-running "
                "generator candidate creation to ensure platform-native length, layout, and compliance."
            )
        if source_segment_id is not None and source_segment_id != current_draft.source_segment_id:
            raise ValueError(
                f"Modifying source_segment_id from '{current_draft.source_segment_id}' to '{source_segment_id}' "
                "is not supported on existing drafts. Source attribution and excerpt traceability are immutable; "
                "re-generating from the target source segment is required."
            )
        if source_document is not None and source_document != current_draft.source_document:
            raise ValueError(
                f"Modifying source_document from '{current_draft.source_document}' to '{source_document}' "
                "is not supported on existing drafts. Source attribution is immutable."
            )

        is_substantive = False
        updates: Dict[str, Any] = {}

        if hook is not None and hook.strip() != current_draft.draft_hook:
            updates["draft_hook"] = hook.strip()
            is_substantive = True

        if caption is not None and caption.strip() != current_draft.draft_caption:
            updates["draft_caption"] = caption.strip()
            is_substantive = True

        if hashtags is not None and hashtags != current_draft.suggested_hashtags:
            updates["suggested_hashtags"] = hashtags
            is_substantive = True

        if call_to_action is not None and call_to_action.strip() != current_draft.call_to_action:
            updates["call_to_action"] = call_to_action.strip()
            is_substantive = True

        if content_format is not None and content_format != current_draft.content_format:
            updates["content_format"] = content_format
            is_substantive = True

        if destination_url is not None:
            curr_dest = asset.compliance_result.destination_url if asset.compliance_result else None
            if destination_url.strip() != (curr_dest or ""):
                is_substantive = True

        if media_rights is not None:
            is_substantive = True

        if render_dir is not None:
            clean_r_dir = str(render_dir)
            updates["render_directory"] = clean_r_dir
            is_substantive = True

        if not updates and destination_url is None and media_rights is None and render_dir is None and not reviewer_notes:
            raise ValueError("At least one field or note must be provided to refine asset.")

        prev_status = asset.review_status
        now_iso = datetime.now(timezone.utc).isoformat()

        # Invalidate previous approval if substantive changes are made
        approval_invalidated = False
        if is_substantive and asset.review_status == ReviewStatusEnum.APPROVED:
            asset.review_status = ReviewStatusEnum.IN_REVIEW
            asset.approval_timestamp = None
            asset.claims_reviewed_confirmed = False
            asset.warnings_reviewed_confirmed = False
            approval_invalidated = True

        # Scan edited text for any newly introduced heuristic claim warnings
        new_hook = updates.get("draft_hook", current_draft.draft_hook)
        new_caption = updates.get("draft_caption", current_draft.draft_caption)
        combined_text = f"{new_hook} {new_caption}"
        scanned_warnings = detect_claim_warnings(combined_text)

        # Merge with existing non-redundant warnings
        all_warnings = list(current_draft.warnings)
        for w in scanned_warnings:
            if w not in all_warnings:
                all_warnings.append(w)
        updates["warnings"] = all_warnings

        # Create updated draft copy preserving traceability
        updated_draft = current_draft.model_copy(update=updates)

        # Determine effective render directory for quality and compliance evaluation
        effective_render_dir = render_dir if render_dir is not None else (updated_draft.render_directory or asset.render_dir)

        # Re-run automated quality gate on refined draft
        new_q_res = evaluate_asset_quality(updated_draft, render_dir=effective_render_dir)

        # Re-evaluate brand compliance and invalidate old evaluation
        eval_dest = destination_url if destination_url is not None else (asset.compliance_result.destination_url if asset.compliance_result else None)
        eval_rights = media_rights if media_rights is not None else None

        try:
            new_comp_res = evaluate_brand_compliance(
                draft=updated_draft,
                destination_url=eval_dest,
                media_rights=eval_rights,
                render_dir=effective_render_dir,
                profile=brand_profile
            )
        except Exception:
            new_comp_res = None

        asset.draft = updated_draft
        asset.quality_result = new_q_res
        asset.compliance_result = new_comp_res
        asset.render_dir = str(effective_render_dir) if effective_render_dir is not None else None
        asset.reviewer_id = clean_reviewer
        asset.updated_at = now_iso

        action_rec = ReviewActionRecord(
            action_id=f"act_{uuid.uuid4().hex[:12]}",
            asset_id=asset_id,
            action=ReviewActionEnum.APPLY_REFINEMENTS,
            reviewer_id=clean_reviewer,
            timestamp=now_iso,
            comments=reviewer_notes or "Editorial refinements applied by reviewer.",
            previous_status=prev_status,
            new_status=asset.review_status,
            metadata={
                "edited_fields": list(updates.keys()) + (["destination_url"] if destination_url is not None else []) + (["media_rights"] if media_rights is not None else []) + (["render_dir"] if render_dir is not None else []),
                "is_substantive": is_substantive,
                "approval_invalidated": approval_invalidated,
                "quality_status_after_edit": new_q_res.overall_status.value,
                "compliance_status_after_edit": new_comp_res.brand_compliance_status.value if new_comp_res else "NOT_ASSESSED"
            }
        )
        asset.review_history.append(action_rec)
        self.save()
        return asset

    def reevaluate_compliance(
        self,
        asset_id: str,
        destination_url: Optional[str] = None,
        media_rights: Optional[List[MediaRightsRecord]] = None,
        render_dir: Optional[Union[str, Path]] = None,
        profile: Optional[BrandComplianceProfile] = None
    ) -> ReviewableAsset:
        """Evaluates or refreshes brand compliance for an existing registered asset.

        Provides a safe migration and refresh path for legacy assets or assets
        requiring updated compliance checks. Automatically invalidates prior approval
        if refreshed compliance produces blocking issues.
        """
        asset = self.get_asset(asset_id)
        effective_r_dir = render_dir if render_dir is not None else (asset.draft.render_directory or asset.render_dir)
        comp_res = evaluate_brand_compliance(
            draft=asset.draft,
            destination_url=destination_url,
            media_rights=media_rights,
            render_dir=effective_r_dir,
            profile=profile
        )
        asset.compliance_result = comp_res
        if effective_r_dir:
            asset.render_dir = str(effective_r_dir)
            if asset.draft.render_directory != str(effective_r_dir):
                asset.draft = asset.draft.model_copy(update={"render_directory": str(effective_r_dir)})

        prev_status = asset.review_status
        new_status = asset.review_status
        # Invalidate approval if refreshed compliance reveals blocking issues
        if asset.review_status == ReviewStatusEnum.APPROVED:
            has_blocking_issue = (
                comp_res.brand_compliance_status == ComplianceStatusEnum.FAIL
                or comp_res.destination_url_status in (DestinationUrlStatusEnum.UNAPPROVED, DestinationUrlStatusEnum.INVALID)
                or comp_res.rights_status in (RightsStatusEnum.RESTRICTED, RightsStatusEnum.PENDING_VERIFICATION)
            )
            if has_blocking_issue:
                new_status = ReviewStatusEnum.PENDING_REVIEW
                asset.review_status = ReviewStatusEnum.PENDING_REVIEW
                asset.approval_timestamp = None
                asset.claims_reviewed_confirmed = False
                asset.warnings_reviewed_confirmed = False

        now_iso = datetime.now(timezone.utc).isoformat()
        asset.updated_at = now_iso

        action_rec = ReviewActionRecord(
            action_id=f"act_{uuid.uuid4().hex[:12]}",
            asset_id=asset_id,
            action=ReviewActionEnum.RECORD_FEEDBACK,
            reviewer_id="System_Compliance_Gate",
            timestamp=now_iso,
            comments=f"Brand compliance re-evaluated: status is {comp_res.brand_compliance_status.value}.",
            previous_status=prev_status,
            new_status=new_status,
            metadata={"compliance_status": comp_res.brand_compliance_status.value}
        )
        asset.review_history.append(action_rec)
        self.save()
        return asset
        self.save()
        return asset

    def request_revision(
        self,
        asset_id: str,
        reviewer_id: str,
        revision_notes: str
    ) -> ReviewableAsset:
        """Requests revisions on an asset, moving it to REVISION_REQUESTED state.

        Invalidates prior approval if present.
        """
        clean_reviewer = reviewer_id.strip() if reviewer_id else ""
        if not clean_reviewer:
            raise ValueError("Reviewer identity is required to request revisions.")
        clean_notes = revision_notes.strip() if revision_notes else ""
        if not clean_notes:
            raise ValueError("Revision notes are required when requesting revisions.")

        asset = self.get_asset(asset_id)
        prev_status = asset.review_status
        now_iso = datetime.now(timezone.utc).isoformat()

        # Invalidate approval if previously approved
        if asset.review_status == ReviewStatusEnum.APPROVED:
            asset.approval_timestamp = None
            asset.claims_reviewed_confirmed = False
            asset.warnings_reviewed_confirmed = False

        asset.review_status = ReviewStatusEnum.REVISION_REQUESTED
        asset.reviewer_id = clean_reviewer
        asset.revision_notes = clean_notes
        asset.updated_at = now_iso

        action_rec = ReviewActionRecord(
            action_id=f"act_{uuid.uuid4().hex[:12]}",
            asset_id=asset_id,
            action=ReviewActionEnum.REQUEST_REVISION,
            reviewer_id=clean_reviewer,
            timestamp=now_iso,
            comments=clean_notes,
            previous_status=prev_status,
            new_status=ReviewStatusEnum.REVISION_REQUESTED
        )
        asset.review_history.append(action_rec)
        self.save()
        return asset

    def reject_asset(
        self,
        asset_id: str,
        reviewer_id: str,
        reason: str
    ) -> ReviewableAsset:
        """Explicitly rejects an asset with a mandatory recorded reason."""
        clean_reviewer = reviewer_id.strip() if reviewer_id else ""
        if not clean_reviewer:
            raise ValueError("Reviewer identity is required to reject an asset.")
        clean_reason = reason.strip() if reason else ""
        if not clean_reason:
            raise ValueError("Rejection reason is required when rejecting an asset.")

        asset = self.get_asset(asset_id)
        prev_status = asset.review_status
        now_iso = datetime.now(timezone.utc).isoformat()

        if asset.review_status == ReviewStatusEnum.APPROVED:
            asset.approval_timestamp = None
            asset.claims_reviewed_confirmed = False
            asset.warnings_reviewed_confirmed = False

        asset.review_status = ReviewStatusEnum.REJECTED
        asset.reviewer_id = clean_reviewer
        asset.rejection_reason = clean_reason
        asset.updated_at = now_iso

        action_rec = ReviewActionRecord(
            action_id=f"act_{uuid.uuid4().hex[:12]}",
            asset_id=asset_id,
            action=ReviewActionEnum.REJECT,
            reviewer_id=clean_reviewer,
            timestamp=now_iso,
            comments=clean_reason,
            previous_status=prev_status,
            new_status=ReviewStatusEnum.REJECTED
        )
        asset.review_history.append(action_rec)
        self.save()
        return asset

    def approve_asset(
        self,
        asset_id: str,
        reviewer_id: str,
        comments: str = "",
        confirm_claims_reviewed: bool = False,
        confirm_warnings_reviewed: bool = False
    ) -> ReviewableAsset:
        """Explicitly approves an asset for publication scheduling consideration.

        Safeguards:
        - Reviewer identity is mandatory.
        - Cannot approve asset with quality status FAIL.
        - Cannot approve asset flagged with CAT_4_UNSUPPORTED claim.
        - Cannot approve asset with warnings without confirm_warnings_reviewed=True.
        - Reviewer must explicitly confirm claim and source verification (confirm_claims_reviewed=True).
        - Approval never triggers automatic publishing or external API calls.
        """
        clean_reviewer = reviewer_id.strip() if reviewer_id else ""
        if not clean_reviewer:
            raise ValueError("Reviewer identity is required for approval. Cannot approve without reviewer ID.")

        asset = self.get_asset(asset_id)

        # 1. Block approval of rejected assets without reopening
        if asset.review_status == ReviewStatusEnum.REJECTED:
            raise ValueError(
                f"Cannot approve rejected asset '{asset_id}'. "
                "Asset must be re-opened into review before approval can be granted."
            )

        # 2. Block approval if quality status is FAIL
        q_status = _extract_quality_status(asset.quality_result)
        if q_status is None or q_status == QualityGateStatusEnum.FAIL.value:
            failures = _extract_quality_failures(asset.quality_result)
            raise ValueError(
                f"Cannot approve asset '{asset_id}': Quality gate status is FAIL. "
                f"Blocking failures must be resolved before approval. Failures: {failures}"
            )

        # 3. Block approval if claim is categorized as CAT_4_UNSUPPORTED
        if asset.draft.claim_category == ClaimCategoryEnum.CAT_4_UNSUPPORTED:
            raise ValueError(
                f"Cannot approve asset '{asset_id}': Asset is categorized as CAT_4_UNSUPPORTED. "
                "Unsupported or prohibited claims cannot be approved."
            )

        # 4. Enforce warning confirmation if quality status is PASS_WITH_WARNINGS or warnings present
        q_warnings = _extract_quality_warnings(asset.quality_result)
        has_warnings = (
            q_status == QualityGateStatusEnum.PASS_WITH_WARNINGS.value
            or len(asset.draft.warnings) > 0
            or len(q_warnings) > 0
        )
        if has_warnings and not confirm_warnings_reviewed:
            raise ValueError(
                f"Cannot approve asset '{asset_id}': Asset has quality warnings. "
                "Approval requires explicit human review confirmation (confirm_warnings_reviewed=True)."
            )

        # 5. Enforce explicit claim and source attribution confirmation
        if not confirm_claims_reviewed:
            raise ValueError(
                f"Cannot approve asset '{asset_id}': Reviewer must explicitly confirm that "
                "claims and source attribution have been verified (confirm_claims_reviewed=True)."
            )

        # 6. Compliance safeguards - compliance evaluation is MANDATORY
        if asset.compliance_result is None:
            raise ValueError(
                f"Cannot approve asset '{asset_id}': Missing brand compliance evaluation. "
                "All assets must undergo brand compliance evaluation prior to approval."
            )
        if asset.compliance_result.rights_status == RightsStatusEnum.RESTRICTED:
            raise ValueError(
                f"Cannot approve asset '{asset_id}': Media rights are RESTRICTED. "
                "Assets with restricted copyright licensing cannot be approved for scheduling."
            )
        if asset.compliance_result.rights_status == RightsStatusEnum.PENDING_VERIFICATION:
            raise ValueError(
                f"Cannot approve asset '{asset_id}': Media rights are PENDING_VERIFICATION. "
                "Missing permission evidence or verified internal provenance cannot be overridden by human warning confirmation."
            )
        if asset.compliance_result.destination_url_status == DestinationUrlStatusEnum.UNAPPROVED:
            raise ValueError(
                f"Cannot approve asset '{asset_id}': Destination URL is UNAPPROVED. "
                "Campaign destination must be on the approved allowlist before approval can be granted."
            )
        if asset.compliance_result.destination_url_status == DestinationUrlStatusEnum.INVALID:
            raise ValueError(
                f"Cannot approve asset '{asset_id}': Destination URL is INVALID."
            )
        if asset.compliance_result.brand_compliance_status == ComplianceStatusEnum.FAIL:
            findings = asset.compliance_result.brand_compliance_findings + asset.compliance_result.unsupported_claim_findings
            raise ValueError(
                f"Cannot approve asset '{asset_id}': Brand compliance status is FAIL. "
                f"Blocking violations must be resolved before approval. Findings: {findings}"
            )
        if asset.compliance_result.brand_compliance_status == ComplianceStatusEnum.PASS_WITH_WARNINGS and not confirm_warnings_reviewed:
            raise ValueError(
                f"Cannot approve asset '{asset_id}': Asset has brand compliance warnings. "
                "Approval requires explicit human review confirmation (confirm_warnings_reviewed=True)."
            )

        prev_status = asset.review_status
        now_iso = datetime.now(timezone.utc).isoformat()

        asset.review_status = ReviewStatusEnum.APPROVED
        asset.reviewer_id = clean_reviewer
        asset.approval_timestamp = now_iso
        asset.claims_reviewed_confirmed = True
        asset.warnings_reviewed_confirmed = True
        asset.updated_at = now_iso

        action_rec = ReviewActionRecord(
            action_id=f"act_{uuid.uuid4().hex[:12]}",
            asset_id=asset_id,
            action=ReviewActionEnum.APPROVE,
            reviewer_id=clean_reviewer,
            timestamp=now_iso,
            comments=comments.strip() or "Asset approved by human reviewer for scheduling consideration.",
            previous_status=prev_status,
            new_status=ReviewStatusEnum.APPROVED,
            metadata={
                "quality_status": q_status or "NOT_EVALUATED",
                "claims_reviewed_confirmed": True,
                "warnings_reviewed_confirmed": True,
                "warnings_count": len(asset.draft.warnings)
            }
        )
        asset.review_history.append(action_rec)
        self.save()
        return asset

    def get_review_history(self, asset_id: str) -> List[ReviewActionRecord]:
        """Retrieves chronological audit history for an asset."""
        return self.get_asset(asset_id).review_history

    def is_eligible_for_approved_export(self, asset: ReviewableAsset) -> bool:
        """Determines if an asset satisfies all criteria for the approved export stream."""
        q_status = _extract_quality_status(asset.quality_result)
        return (
            asset.review_status == ReviewStatusEnum.APPROVED
            and bool(asset.reviewer_id and asset.reviewer_id.strip())
            and bool(asset.approval_timestamp and asset.approval_timestamp.strip())
            and asset.claims_reviewed_confirmed is True
            and asset.quality_result is not None
            and q_status in (QualityGateStatusEnum.PASS.value, QualityGateStatusEnum.PASS_WITH_WARNINGS.value)
            and bool(asset.draft.source_document and asset.draft.source_segment_id)
            and asset.draft.claim_category != ClaimCategoryEnum.CAT_4_UNSUPPORTED
            and asset.compliance_result is not None
            and asset.compliance_result.brand_compliance_status != ComplianceStatusEnum.FAIL
            and asset.compliance_result.destination_url_status not in (DestinationUrlStatusEnum.UNAPPROVED, DestinationUrlStatusEnum.INVALID)
            and asset.compliance_result.rights_status not in (RightsStatusEnum.RESTRICTED, RightsStatusEnum.PENDING_VERIFICATION)
        )

    def export_approved_assets_calendar_csv(
        self,
        output_path: Optional[Union[str, Path]] = None,
        destination_url: Optional[str] = None,
        campaign: str = DEFAULT_CAMPAIGN,
        include_compliance_columns: bool = False,
        schedule_map: Optional[Dict[str, Tuple[str, str]]] = None
    ) -> str:
        """Exports ONLY eligible approved assets to calendar CSV with 24 or 28 columns."""
        approved_assets = [a for a in self.assets.values() if self.is_eligible_for_approved_export(a)]
        drafts = [a.draft for a in approved_assets]
        q_results = [a.quality_result for a in approved_assets if a.quality_result]
        c_map = {a.asset_id: a.compliance_result for a in approved_assets if a.compliance_result}

        rev_map = {
            a.asset_id: {
                "human_review_status": "APPROVED",
                "reviewer_id": a.reviewer_id or "",
                "approval_timestamp": a.approval_timestamp or "",
                "reviewer_notes": "Approved for scheduling consideration",
                "destination_url": a.compliance_result.destination_url if a.compliance_result and a.compliance_result.destination_url else destination_url,
                "scheduled_date": schedule_map[a.asset_id][0] if schedule_map and a.asset_id in schedule_map else "",
                "scheduled_time": schedule_map[a.asset_id][1] if schedule_map and a.asset_id in schedule_map else ""
            }
            for a in approved_assets
        }

        csv_str = export_calendar_csv_string(
            drafts=drafts,
            destination_url=destination_url,
            campaign=campaign,
            quality_results=q_results,
            include_review_columns=True,
            review_metadata_map=rev_map,
            include_compliance_columns=include_compliance_columns,
            compliance_results=c_map
        )

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(csv_str, encoding="utf-8-sig")

        return csv_str

    def export_unapproved_assets_calendar_csv(
        self,
        output_path: Optional[Union[str, Path]] = None,
        destination_url: Optional[str] = None,
        campaign: str = DEFAULT_CAMPAIGN,
        include_compliance_columns: bool = False,
        schedule_map: Optional[Dict[str, Tuple[str, str]]] = None
    ) -> str:
        """Exports all unapproved assets (PENDING_REVIEW, IN_REVIEW, REVISION_REQUESTED, REJECTED)."""
        unapproved = [a for a in self.assets.values() if not self.is_eligible_for_approved_export(a)]
        drafts = [a.draft for a in unapproved]
        q_results = [a.quality_result for a in unapproved if a.quality_result]
        c_map = {a.asset_id: a.compliance_result for a in unapproved if a.compliance_result}

        rev_map = {
            a.asset_id: {
                "human_review_status": a.review_status.value,
                "reviewer_id": a.reviewer_id or "",
                "approval_timestamp": a.approval_timestamp or "",
                "reviewer_notes": a.rejection_reason or a.revision_notes or "",
                "destination_url": a.compliance_result.destination_url if a.compliance_result and a.compliance_result.destination_url else destination_url,
                "scheduled_date": schedule_map[a.asset_id][0] if schedule_map and a.asset_id in schedule_map else "",
                "scheduled_time": schedule_map[a.asset_id][1] if schedule_map and a.asset_id in schedule_map else ""
            }
            for a in unapproved
        }

        csv_str = export_calendar_csv_string(
            drafts=drafts,
            destination_url=destination_url,
            campaign=campaign,
            quality_results=q_results,
            include_review_columns=True,
            review_metadata_map=rev_map,
            include_compliance_columns=include_compliance_columns,
            compliance_results=c_map
        )

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(csv_str, encoding="utf-8-sig")

        return csv_str

    def export_assets_by_status_calendar_csv(
        self,
        status: ReviewStatusEnum,
        output_path: Optional[Union[str, Path]] = None,
        destination_url: Optional[str] = None,
        campaign: str = DEFAULT_CAMPAIGN,
        include_compliance_columns: bool = False
    ) -> str:
        """Exports assets of a specific review status to calendar CSV."""
        filtered = [a for a in self.assets.values() if a.review_status == status]
        drafts = [a.draft for a in filtered]
        q_results = [a.quality_result for a in filtered if a.quality_result]
        c_map = {a.asset_id: a.compliance_result for a in filtered if a.compliance_result}

        rev_map = {
            a.asset_id: {
                "human_review_status": a.review_status.value,
                "reviewer_id": a.reviewer_id or "",
                "approval_timestamp": a.approval_timestamp or "",
                "reviewer_notes": a.rejection_reason or a.revision_notes or ""
            }
            for a in filtered
        }

        csv_str = export_calendar_csv_string(
            drafts=drafts,
            destination_url=destination_url,
            campaign=campaign,
            quality_results=q_results,
            include_review_columns=True,
            review_metadata_map=rev_map,
            include_compliance_columns=include_compliance_columns,
            compliance_results=c_map
        )

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(csv_str, encoding="utf-8-sig")

        return csv_str

    def export_all_candidates_calendar_csv(
        self,
        output_path: Optional[Union[str, Path]] = None,
        destination_url: Optional[str] = None,
        campaign: str = DEFAULT_CAMPAIGN,
        include_review_columns: bool = True,
        include_compliance_columns: bool = False,
        schedule_map: Optional[Dict[str, Tuple[str, str]]] = None
    ) -> str:
        """Exports all registered candidate assets regardless of review status."""
        all_assets = list(self.assets.values())
        drafts = [a.draft for a in all_assets]
        q_results = [a.quality_result for a in all_assets if a.quality_result]
        c_map = {a.asset_id: a.compliance_result for a in all_assets if a.compliance_result}

        rev_map = {
            a.asset_id: {
                "human_review_status": a.review_status.value,
                "reviewer_id": a.reviewer_id or "",
                "approval_timestamp": a.approval_timestamp or "",
                "reviewer_notes": a.rejection_reason or a.revision_notes or "",
                "destination_url": a.compliance_result.destination_url if a.compliance_result and a.compliance_result.destination_url else destination_url,
                "scheduled_date": schedule_map[a.asset_id][0] if schedule_map and a.asset_id in schedule_map else "",
                "scheduled_time": schedule_map[a.asset_id][1] if schedule_map and a.asset_id in schedule_map else ""
            }
            for a in all_assets
        }

        csv_str = export_calendar_csv_string(
            drafts=drafts,
            destination_url=destination_url,
            campaign=campaign,
            quality_results=q_results,
            include_review_columns=include_review_columns,
            review_metadata_map=rev_map,
            include_compliance_columns=include_compliance_columns,
            compliance_results=c_map
        )

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(csv_str, encoding="utf-8-sig")

        return csv_str

    def export_review_summary_json(
        self,
        output_path: Optional[Union[str, Path]] = None
    ) -> Dict[str, Any]:
        """Generates an auditable summary report of all assets and their review statuses."""
        status_counts = {s.value: 0 for s in ReviewStatusEnum}
        quality_counts = {"PASS": 0, "PASS_WITH_WARNINGS": 0, "FAIL": 0, "NOT_EVALUATED": 0}

        for a in self.assets.values():
            status_counts[a.review_status.value] = status_counts.get(a.review_status.value, 0) + 1
            if a.quality_result:
                q_val = _extract_quality_status(a.quality_result) or "NOT_EVALUATED"
                quality_counts[q_val] = quality_counts.get(q_val, 0) + 1
            else:
                quality_counts["NOT_EVALUATED"] += 1

        summary = {
            "schema_version": "1.0",
            "report_timestamp": datetime.now(timezone.utc).isoformat(),
            "total_registered_assets": len(self.assets),
            "review_status_summary": status_counts,
            "quality_status_summary": quality_counts,
            "approved_assets_count": status_counts.get("APPROVED", 0),
            "unapproved_assets_count": len(self.assets) - status_counts.get("APPROVED", 0),
            "publishing_safety": {
                "social_publishing_triggered": False,
                "is_ready_to_publish_enforced_false": True,
                "factual_truth_guaranteed_by_engine": False
            },
            "assets": [
                {
                    "asset_id": a.asset_id,
                    "platform": a.draft.platform.value,
                    "content_format": a.draft.content_format.value,
                    "review_status": a.review_status.value,
                    "reviewer_id": a.reviewer_id,
                    "approval_timestamp": a.approval_timestamp,
                    "quality_gate_status": _extract_quality_status(a.quality_result) or "NOT_EVALUATED",
                    "source_document": a.draft.source_document,
                    "source_segment_id": a.draft.source_segment_id,
                    "audit_actions_count": len(a.review_history)
                }
                for a in self.assets.values()
            ]
        }

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        return summary

