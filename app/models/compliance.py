"""Data models for Phase 3.7 & Phase 3.9 Brand Compliance, Rights Safety, and Platform Readiness.

Defines schemas for:
1. Configurable Brand Compliance Profiles (voice, approved claims, allowlists).
2. Structured Media Rights Metadata (licenses, evidence references, statuses).
3. Brand Compliance Evaluation Results (voice, claims, destination URLs, rights, readiness).

Crucial Safeguards & Trust Boundaries:
- Automated compliance evaluation never approves content or sets is_ready_to_publish=True.
- Syntactically valid URLs are not automatically approved.
- Unapproved or missing destinations are explicitly tracked.
- Missing media permissions default to PENDING_VERIFICATION.
- Restricted media explicitly fails compliance.
- All assets strictly maintain requires_human_review=True.
- Phase 3.9 Security Trust Boundary:
  SHA-256 verifies that files match the manifest hashes when the manifest itself is trusted.
  Unsigned JSON manifests do not provide cryptographic origin authentication or non-repudiation.
  Renderer provenance strings are descriptive assertions, not cryptographically verified identities.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class ComplianceStatusEnum(str, Enum):
    """Evaluation status for brand compliance and platform readiness."""
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"
    NOT_ASSESSED = "NOT_ASSESSED"


class DestinationUrlStatusEnum(str, Enum):
    """Verification status for campaign destination URLs against the approved allowlist."""
    APPROVED = "APPROVED"
    UNAPPROVED = "UNAPPROVED"
    PENDING_DESTINATION_URL = "PENDING_DESTINATION_URL"
    INVALID = "INVALID"


class RightsStatusEnum(str, Enum):
    """Media rights verification and licensing status."""
    VERIFIED = "VERIFIED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    RESTRICTED = "RESTRICTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ApprovedClaim(BaseModel):
    """Factual claim backed by an explicit evidence reference."""
    claim_id: str = Field(..., description="Unique claim identifier, e.g. CLAIM_PRICING_TIERS")
    claim_text: str = Field(..., description="Approved statement wording or core assertion")
    evidence_reference: str = Field(..., description="Traceable evidence citation e.g. EV-001, EV-003")
    allowed_framing: Optional[str] = Field(
        default=None,
        description="Required framing when applicable e.g. 'As advertised on public website'"
    )
    keywords: List[str] = Field(
        default_factory=list,
        description="Key terms associated with this claim for matching"
    )


class BrandComplianceProfile(BaseModel):
    """Configurable brand compliance configuration profile."""
    brand_name: str = Field(default="IncuBrix", description="Brand or product name")
    approved_product_descriptions: List[str] = Field(
        default_factory=list,
        description="Official approved descriptions of product capabilities"
    )
    approved_messaging_themes: List[str] = Field(
        default_factory=list,
        description="Approved strategic messaging pillars and themes"
    )
    brand_voice_principles: List[str] = Field(
        default_factory=list,
        description="Core stylistic principles (direct, practitioner-oriented, evidence-grounded)"
    )
    prohibited_phrases: List[str] = Field(
        default_factory=list,
        description="Banned marketing buzzwords, superlative claims, or misleading phrases"
    )
    approved_claims: List[ApprovedClaim] = Field(
        default_factory=list,
        description="Claims backed by explicit evidence references"
    )
    approved_destination_urls: List[str] = Field(
        default_factory=list,
        description="Strict allowlist of verified live destination URLs (empty list = no approved URLs)"
    )
    required_disclosures: Dict[str, str] = Field(
        default_factory=dict,
        description="Mandatory disclosures when specific formats or claim categories are used"
    )


class MediaRightsRecord(BaseModel):
    """Structured copyright and media rights metadata for a visual or audio asset."""
    media_asset_id: str = Field(..., description="Identifier matching asset or slide, e.g. draft_shorts_01")
    media_type: str = Field(..., description="Media format type: VIDEO_PREVIEW, CAROUSEL_SLIDE, etc.")
    source_or_provider: str = Field(..., description="Source or provider e.g. LOCALLY_GENERATED_KINETIC_TEXT, THIRD_PARTY")
    original_source_url: Optional[str] = Field(default=None, description="Original source link if third-party asset")
    license_description: str = Field(..., description="License terms or description")
    attribution_requirement: bool = Field(default=False, description="Whether attribution is legally required")
    attribution_text: Optional[str] = Field(default=None, description="Exact attribution text to display if required")
    permission_evidence_reference: Optional[str] = Field(default=None, description="Reference to documented permission or contract")
    rights_status: RightsStatusEnum = Field(default=RightsStatusEnum.NOT_APPLICABLE)
    notes: Optional[str] = Field(default=None, description="Additional legal or operational notes")

    @model_validator(mode="after")
    def validate_rights_consistency(self) -> "MediaRightsRecord":
        """Ensures third-party media is not claimed verified without explicit permission evidence,
        and cannot be marked NOT_APPLICABLE without verified local provenance."""
        if self.source_or_provider.upper() != "LOCALLY_GENERATED_KINETIC_TEXT":
            if self.rights_status == RightsStatusEnum.VERIFIED and not self.permission_evidence_reference:
                raise ValueError(
                    "Third-party media cannot be marked VERIFIED without an explicit permission_evidence_reference."
                )
            if self.rights_status == RightsStatusEnum.NOT_APPLICABLE:
                raise ValueError(
                    "Third-party or external media cannot be marked NOT_APPLICABLE. "
                    "NOT_APPLICABLE is strictly reserved for internally generated media with verified provenance."
                )
        return self


class BrandComplianceResult(BaseModel):
    """Structured evaluation output for an asset through the brand compliance layer."""
    asset_id: str = Field(..., description="Unique draft identifier")
    brand_compliance_status: ComplianceStatusEnum = Field(..., description="Overall compliance status")
    brand_compliance_findings: List[str] = Field(default_factory=list, description="Findings related to brand voice/style")
    unsupported_claim_findings: List[str] = Field(default_factory=list, description="Findings related to claims/evidence")
    destination_url_status: DestinationUrlStatusEnum = Field(..., description="Destination URL allowlist status")
    destination_url: Optional[str] = Field(default=None, description="Evaluated destination URL")
    rights_status: RightsStatusEnum = Field(..., description="Media rights verification status")
    rights_findings: List[str] = Field(default_factory=list, description="Findings related to media rights and licensing")
    platform_readiness_status: ComplianceStatusEnum = Field(..., description="Structural platform readiness status")
    platform_readiness_findings: List[str] = Field(default_factory=list, description="Findings related to platform formatting")
    requires_human_review: bool = Field(default=True, description="Strict invariant: all assets require human review")
    is_ready_to_publish: bool = Field(default=False, description="Strict invariant: automated compliance never approves")
    evaluated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Dict[str, Any] = Field(default_factory=dict, description="Diagnostic metadata")

    @field_validator("is_ready_to_publish")
    @classmethod
    def validate_never_ready_to_publish(cls, v: bool) -> bool:
        if v is True:
            raise ValueError(
                "BrandComplianceResult cannot set is_ready_to_publish=True. Human review is mandatory."
            )
        return False

    @field_validator("requires_human_review")
    @classmethod
    def validate_always_requires_human_review(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError(
                "BrandComplianceResult must maintain requires_human_review=True."
            )
        return True

