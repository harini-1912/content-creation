"""Data models for Phase 3.5 human review, content refinement, and approval workflow.

Maintains strict separation between:
1. Automated quality gate evaluations (PASS, PASS_WITH_WARNINGS, FAIL).
2. Human editorial review lifecycle (PENDING_REVIEW, IN_REVIEW, REVISION_REQUESTED, REJECTED, APPROVED).

Enforces human-in-the-loop safeguards:
- Automated processes never approve assets.
- Reviewer identity and approval timestamps are mandatory.
- Substantive edits invalidate prior approvals.
- Full audit history of all reviewer interactions is retained.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.asset import DraftCandidate, ClaimCategoryEnum, AssetFormatEnum, PlatformEnum
from app.models.compliance import (
    BrandComplianceResult,
    ComplianceStatusEnum,
    DestinationUrlStatusEnum,
    RightsStatusEnum
)


class ReviewStatusEnum(str, Enum):
    """Human editorial review states."""
    PENDING_REVIEW = "PENDING_REVIEW"
    IN_REVIEW = "IN_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"


class ReviewActionEnum(str, Enum):
    """Auditable review actions performed by human operators."""
    START_REVIEW = "START_REVIEW"
    RECORD_FEEDBACK = "RECORD_FEEDBACK"
    APPLY_REFINEMENTS = "APPLY_REFINEMENTS"
    REQUEST_REVISION = "REQUEST_REVISION"
    REJECT = "REJECT"
    APPROVE = "APPROVE"


class ReviewActionRecord(BaseModel):
    """Immutable audit trail entry for a single human review action."""
    action_id: str = Field(..., description="Unique action identifier")
    asset_id: str = Field(..., description="Target asset identifier")
    action: ReviewActionEnum = Field(..., description="Action performed")
    reviewer_id: str = Field(..., min_length=1, description="Authenticated reviewer identifier or display name")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp of action")
    comments: str = Field(default="", description="Reviewer feedback or rationale")
    previous_status: ReviewStatusEnum = Field(..., description="Review status before action")
    new_status: ReviewStatusEnum = Field(..., description="Review status after action")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Action-specific metadata (edited fields, confirmations)")

    @field_validator("reviewer_id")
    @classmethod
    def validate_reviewer_id(cls, v: str) -> str:
        v_clean = v.strip()
        if not v_clean:
            raise ValueError("Reviewer identity must not be blank.")
        return v_clean


class ReviewableAsset(BaseModel):
    """Container tracking a draft candidate, its quality result, and its human review lifecycle."""
    asset_id: str = Field(..., description="Asset identifier matching draft.draft_id")
    draft: DraftCandidate = Field(..., description="Current active draft copy with refinements")
    original_draft: DraftCandidate = Field(..., description="Untouched initial draft copy from generation")
    review_status: ReviewStatusEnum = Field(default=ReviewStatusEnum.PENDING_REVIEW)
    quality_result: Optional[Any] = Field(default=None, description="Current quality check result")
    compliance_result: Optional[BrandComplianceResult] = Field(default=None, description="Current brand compliance evaluation result")
    render_dir: Optional[str] = Field(default=None, description="Local directory path containing rendered preview media and manifest")
    review_history: List[ReviewActionRecord] = Field(default_factory=list, description="Chronological audit history")

    reviewer_id: Optional[str] = Field(default=None, description="Reviewer who approved or performed latest action")
    approval_timestamp: Optional[str] = Field(default=None, description="ISO 8601 timestamp of explicit human approval")
    claims_reviewed_confirmed: bool = Field(default=False, description="Explicit human confirmation that claims were audited")
    warnings_reviewed_confirmed: bool = Field(default=False, description="Explicit human confirmation that warnings were evaluated")
    revision_notes: Optional[str] = Field(default=None, description="Latest revision request instructions")
    rejection_reason: Optional[str] = Field(default=None, description="Reason recorded when asset is rejected")

    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, v: str) -> str:
        v_clean = v.strip()
        if not v_clean or " " in v_clean:
            raise ValueError("asset_id must not be empty or contain spaces.")
        return v_clean

    @model_validator(mode="after")
    def validate_approval_integrity(self) -> "ReviewableAsset":
        """Enforces that APPROVED assets strictly meet all human approval and compliance criteria."""
        if self.review_status == ReviewStatusEnum.APPROVED:
            if not self.reviewer_id or not self.reviewer_id.strip():
                raise ValueError("Approved asset must have an assigned reviewer_id.")
            if not self.approval_timestamp or not self.approval_timestamp.strip():
                raise ValueError("Approved asset must have an explicit approval_timestamp.")
            if not self.claims_reviewed_confirmed:
                raise ValueError("Approved asset must have claims_reviewed_confirmed=True.")
            if self.quality_result:
                q_status = getattr(self.quality_result, "overall_status", None)
                if hasattr(q_status, "value"):
                    q_status = q_status.value
                elif isinstance(self.quality_result, dict):
                    q_status = self.quality_result.get("overall_status")
                if str(q_status) == "FAIL":
                    raise ValueError("Cannot approve an asset with quality status FAIL.")
            if self.draft.claim_category == ClaimCategoryEnum.CAT_4_UNSUPPORTED:
                raise ValueError("Cannot approve an asset flagged with CAT_4_UNSUPPORTED claim.")
            
            # Strict compliance validation for APPROVED assets
            if self.compliance_result is None:
                raise ValueError(
                    "Approved asset must have an evaluated compliance_result. "
                    "Assets with missing compliance results cannot be marked APPROVED."
                )
            if self.compliance_result.brand_compliance_status == ComplianceStatusEnum.FAIL:
                raise ValueError("Cannot approve an asset with brand compliance status FAIL.")
            if self.compliance_result.destination_url_status == DestinationUrlStatusEnum.UNAPPROVED:
                raise ValueError("Cannot approve an asset with UNAPPROVED destination URL.")
            if self.compliance_result.destination_url_status == DestinationUrlStatusEnum.INVALID:
                raise ValueError("Cannot approve an asset with INVALID destination URL.")
            if self.compliance_result.rights_status == RightsStatusEnum.RESTRICTED:
                raise ValueError("Cannot approve an asset with RESTRICTED media rights.")
            if self.compliance_result.rights_status == RightsStatusEnum.PENDING_VERIFICATION:
                raise ValueError(
                    "Cannot approve an asset with PENDING_VERIFICATION media rights. "
                    "Documented permission evidence or verified internal provenance is mandatory."
                )
        return self

