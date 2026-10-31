"""Unit and integration tests for Phase 3.7: Brand Compliance, Rights Safety, and Platform Readiness."""

import csv
import json
from pathlib import Path
import pytest

from app.models.asset import (
    SourceSegment,
    DraftCandidate,
    PlatformEnum,
    AssetFormatEnum,
    ClaimCategoryEnum,
    PillarEnum
)
from app.models.compliance import (
    ComplianceStatusEnum,
    DestinationUrlStatusEnum,
    RightsStatusEnum,
    ApprovedClaim,
    BrandComplianceProfile,
    MediaRightsRecord,
    BrandComplianceResult
)
from app.core.brand_compliance import (
    get_default_brand_profile,
    evaluate_destination_url,
    evaluate_media_rights,
    evaluate_brand_voice_and_claims,
    evaluate_platform_readiness,
    evaluate_brand_compliance,
    generate_compliance_report
)
from app.core.review_workflow import ReviewWorkflowManager, ReviewStatusEnum
from app.core.pipeline import run_content_pipeline


@pytest.fixture
def clean_draft() -> DraftCandidate:
    """Fixture providing a clean, source-attributed draft candidate."""
    return DraftCandidate(
        draft_id="draft_compliance_test_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Creating multi-channel content without a structured system often causes severe creative fatigue.",
        source_derived_text="Creating multi-channel content without a structured system often causes severe creative fatigue.",
        platform=PlatformEnum.LINKEDIN,
        content_format=AssetFormatEnum.TEXT_POST,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Content strategists and solo creators",
        draft_hook="Operational perspective on content production: Systems prevent fatigue.",
        draft_caption=(
            "Creating multi-channel content without a structured system often causes severe creative fatigue. "
            "A repeatable framework turns long recordings into structured platform drafts. "
            "Focus on predictable cadence over sporadic bursts."
        ),
        suggested_hashtags=["#ContentStrategy", "#CreatorOperations"],
        call_to_action="Explore the repurposing framework.",
        generated_suggestions={
            "draft_hook": "Operational perspective on content production: Systems prevent fatigue.",
            "call_to_action": "Explore the repurposing framework."
        },
        is_source_attributed=True,
        is_factually_verified=False,
        claim_category=ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
    )


# 1. Brand profile loading and attributes
def test_default_brand_profile_loading_and_attributes():
    profile = get_default_brand_profile()
    assert profile.brand_name == "IncuBrix"
    assert len(profile.approved_product_descriptions) >= 2
    assert len(profile.approved_messaging_themes) == 5
    assert len(profile.prohibited_phrases) >= 15
    assert len(profile.approved_claims) >= 5
    assert len(profile.approved_destination_urls) >= 5
    # Verify unapproved URL is NOT present
    assert "https://app.incubrix.com/explore" not in profile.approved_destination_urls


# 2. Approved destination URL on allowlist
def test_destination_url_approved_when_on_allowlist():
    profile = get_default_brand_profile()
    status, findings = evaluate_destination_url("https://app.incubrix.com/", profile)
    assert status == DestinationUrlStatusEnum.APPROVED
    assert any("verified on the approved" in f for f in findings)

    status_pricing, _ = evaluate_destination_url("https://www.incubrix.com/pricing.html", profile)
    assert status_pricing == DestinationUrlStatusEnum.APPROVED


# 3. Unapproved destination URL not on allowlist
def test_destination_url_unapproved_when_not_on_allowlist():
    profile = get_default_brand_profile()
    # Unapproved test destination identified in earlier audit
    status, findings = evaluate_destination_url("https://app.incubrix.com/explore", profile)
    assert status == DestinationUrlStatusEnum.UNAPPROVED
    assert any("NOT on the approved-destinations allowlist" in f for f in findings)


# 4. Empty allowlist policy rejects all destination URLs
def test_destination_url_empty_allowlist_rejects_all_urls():
    profile = get_default_brand_profile(approved_destination_urls=[], allow_empty_destinations=True)
    assert len(profile.approved_destination_urls) == 0

    status, findings = evaluate_destination_url("https://app.incubrix.com/", profile)
    assert status == DestinationUrlStatusEnum.UNAPPROVED
    assert any("contains zero approved destinations" in f for f in findings)


# 5. Missing destination URL evaluates to PENDING_DESTINATION_URL
def test_destination_url_missing_evaluates_to_pending():
    profile = get_default_brand_profile()
    status_none, findings_none = evaluate_destination_url(None, profile)
    assert status_none == DestinationUrlStatusEnum.PENDING_DESTINATION_URL
    assert any("tracking link is pending" in f for f in findings_none)

    status_empty, _ = evaluate_destination_url("   ", profile)
    assert status_empty == DestinationUrlStatusEnum.PENDING_DESTINATION_URL


# 6. Syntactically invalid destination URL evaluates to INVALID
def test_destination_url_invalid_syntax_evaluates_to_invalid():
    profile = get_default_brand_profile()
    status, findings = evaluate_destination_url("not_a_valid_url", profile)
    assert status == DestinationUrlStatusEnum.INVALID
    assert any("syntactically invalid" in f for f in findings)


# 7. Locally generated media has NOT_APPLICABLE rights status
def test_media_rights_locally_generated_is_not_applicable(clean_draft: DraftCandidate):
    status, findings = evaluate_media_rights(clean_draft)
    assert status == RightsStatusEnum.NOT_APPLICABLE
    assert any("media rights not applicable" in f.lower() for f in findings)


# 8. Third-party media rights with valid evidence reference
def test_media_rights_verified_third_party_with_evidence(clean_draft: DraftCandidate):
    rec = MediaRightsRecord(
        media_asset_id="media_img_01",
        media_type="INFOGRAPHIC_IMAGE",
        source_or_provider="THIRD_PARTY_PARTNER",
        original_source_url="https://partner.com/asset_123",
        license_description="Partner Educational License v1",
        permission_evidence_reference="EV-001",
        rights_status=RightsStatusEnum.VERIFIED
    )
    status, findings = evaluate_media_rights(clean_draft, media_rights=[rec])
    assert status == RightsStatusEnum.VERIFIED
    assert any("verified under evidence reference 'EV-001'" in f for f in findings)


# 9. Third-party media rights pending verification when evidence missing
def test_media_rights_pending_verification_when_evidence_missing(clean_draft: DraftCandidate):
    rec = MediaRightsRecord(
        media_asset_id="media_img_unverified",
        media_type="STOCK_PHOTO",
        source_or_provider="EXTERNAL_STOCK_PROVIDER",
        license_description="Pending License Receipt",
        rights_status=RightsStatusEnum.PENDING_VERIFICATION
    )
    status, findings = evaluate_media_rights(clean_draft, media_rights=[rec])
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("rights pending verification" in f for f in findings)


# 10. Restricted media rights fails compliance
def test_media_rights_restricted_fails_compliance(clean_draft: DraftCandidate):
    rec = MediaRightsRecord(
        media_asset_id="media_restricted_01",
        media_type="VIDEO_CLIP",
        source_or_provider="THIRD_PARTY_LICENSOR",
        license_description="Restricted: Editorial Personal Use Only",
        rights_status=RightsStatusEnum.RESTRICTED,
        notes="Commercial distribution prohibited"
    )
    res = evaluate_brand_compliance(clean_draft, media_rights=[rec])
    assert res.rights_status == RightsStatusEnum.RESTRICTED
    assert res.brand_compliance_status == ComplianceStatusEnum.FAIL
    assert any("RESTRICTED" in f for f in res.rights_findings)


# 11. Severe prohibited deceptive phrases trigger FAIL
def test_prohibited_severe_misleading_phrases_cause_fail(clean_draft: DraftCandidate):
    clean_draft.draft_caption += " Sign up today with no credit card required!"
    res = evaluate_brand_compliance(clean_draft)
    assert res.brand_compliance_status == ComplianceStatusEnum.FAIL
    assert any("Prohibited Deceptive Phrase Detected" in f for f in res.unsupported_claim_findings)


# 12. Discouraged buzzwords produce PASS_WITH_WARNINGS
def test_prohibited_buzzwords_produce_pass_with_warnings(clean_draft: DraftCandidate):
    clean_draft.draft_caption += " This system is a true game-changer for solo creators."
    res = evaluate_brand_compliance(clean_draft)
    assert res.brand_compliance_status == ComplianceStatusEnum.PASS_WITH_WARNINGS
    assert any("discouraged buzzword 'game-changer'" in f for f in res.brand_compliance_findings)


# 13. Unsupported CAT_4 claims trigger FAIL
def test_unsupported_cat_4_claim_fails_compliance(clean_draft: DraftCandidate):
    clean_draft.claim_category = ClaimCategoryEnum.CAT_4_UNSUPPORTED
    clean_draft.warnings = ["Fabricated statistics detected: beat benchmark by 10x"]
    res = evaluate_brand_compliance(clean_draft)
    assert res.brand_compliance_status == ComplianceStatusEnum.FAIL
    assert any("CAT_4_UNSUPPORTED" in f for f in res.unsupported_claim_findings)


# 14. Approved claims with explicit evidence citations are recognized
def test_approved_claim_with_evidence_reference_recognized(clean_draft: DraftCandidate):
    clean_draft.draft_caption += " IncuBrix operates at incubrix.com and app.incubrix.com."
    res = evaluate_brand_compliance(clean_draft)
    assert any("CLAIM_DOMAINS" in f and "EV-001" in f for f in res.unsupported_claim_findings)


# 15. Platform readiness distinguishes internal rules from external policies
def test_platform_readiness_distinguishes_internal_from_official_policy(clean_draft: DraftCandidate):
    status, findings = evaluate_platform_readiness(clean_draft)
    assert status == ComplianceStatusEnum.PASS
    assert any("does NOT represent official platform policy clearance" in f for f in findings)


# 16. Invariant: Compliance PASS never automatically approves or sets ready to publish
def test_compliance_pass_never_automatically_approves_or_sets_ready_to_publish(clean_draft: DraftCandidate):
    res = evaluate_brand_compliance(clean_draft, destination_url="https://app.incubrix.com/")
    assert res.brand_compliance_status == ComplianceStatusEnum.PASS
    assert res.requires_human_review is True
    assert res.is_ready_to_publish is False


# 17. Review workflow blocks approval of compliance FAIL assets
def test_review_workflow_blocks_approval_of_compliance_failures(clean_draft: DraftCandidate, tmp_path: Path):
    store_path = tmp_path / "review_store.json"
    mgr = ReviewWorkflowManager(storage_path=store_path)

    # Attach severe deceptive phrase
    clean_draft.draft_caption += " Guaranteed return on investment!"
    comp_res = evaluate_brand_compliance(clean_draft)
    assert comp_res.brand_compliance_status == ComplianceStatusEnum.FAIL

    mgr.register_draft(clean_draft, compliance_result=comp_res)

    with pytest.raises(ValueError, match="Brand compliance status is FAIL"):
        mgr.approve_asset(
            asset_id=clean_draft.draft_id,
            reviewer_id="Reviewer_01",
            confirm_claims_reviewed=True,
            confirm_warnings_reviewed=True
        )


# 18. Review workflow blocks approval of UNAPPROVED destination URLs
def test_review_workflow_blocks_approval_of_unapproved_destination_url(clean_draft: DraftCandidate, tmp_path: Path):
    store_path = tmp_path / "review_store.json"
    mgr = ReviewWorkflowManager(storage_path=store_path)

    # Supply unapproved destination URL
    comp_res = evaluate_brand_compliance(clean_draft, destination_url="https://app.incubrix.com/explore")
    assert comp_res.destination_url_status == DestinationUrlStatusEnum.UNAPPROVED

    mgr.register_draft(clean_draft, compliance_result=comp_res)

    with pytest.raises(ValueError, match="Destination URL is UNAPPROVED"):
        mgr.approve_asset(
            asset_id=clean_draft.draft_id,
            reviewer_id="Reviewer_01",
            confirm_claims_reviewed=True,
            confirm_warnings_reviewed=True
        )


# 19. Review workflow blocks approval of RESTRICTED media
def test_review_workflow_blocks_approval_of_restricted_rights(clean_draft: DraftCandidate, tmp_path: Path):
    store_path = tmp_path / "review_store.json"
    mgr = ReviewWorkflowManager(storage_path=store_path)

    rec = MediaRightsRecord(
        media_asset_id="restricted_media_01",
        media_type="VIDEO",
        source_or_provider="STOCK_RESTRICTED",
        license_description="Strict internal preview only",
        rights_status=RightsStatusEnum.RESTRICTED
    )
    comp_res = evaluate_brand_compliance(clean_draft, media_rights=[rec])
    assert comp_res.rights_status == RightsStatusEnum.RESTRICTED

    mgr.register_draft(clean_draft, compliance_result=comp_res)

    with pytest.raises(ValueError, match="Media rights are RESTRICTED"):
        mgr.approve_asset(
            asset_id=clean_draft.draft_id,
            reviewer_id="Reviewer_01",
            confirm_claims_reviewed=True,
            confirm_warnings_reviewed=True
        )


# 20. Approved export stream excludes compliance failures
def test_review_workflow_approved_export_excludes_compliance_failures(clean_draft: DraftCandidate, tmp_path: Path):
    store_path = tmp_path / "review_store.json"
    mgr = ReviewWorkflowManager(storage_path=store_path)

    clean_draft.draft_caption += " Guaranteed viral growth!"
    comp_res = evaluate_brand_compliance(clean_draft)
    asset = mgr.register_draft(clean_draft, compliance_result=comp_res)

    # Force review_status to APPROVED artificially to test is_eligible_for_approved_export safeguard
    asset.review_status = ReviewStatusEnum.APPROVED
    asset.reviewer_id = "Reviewer_Bypass_Attempt"
    asset.approval_timestamp = "2026-10-30T12:00:00Z"
    asset.claims_reviewed_confirmed = True

    assert mgr.is_eligible_for_approved_export(asset) is False


# 21. Compliance report generation
def test_generate_compliance_report(clean_draft: DraftCandidate, tmp_path: Path):
    res = evaluate_brand_compliance(clean_draft, destination_url="https://app.incubrix.com/")
    report_file = tmp_path / "compliance_report.json"
    data = generate_compliance_report([res], run_id="test_run_01", output_path=report_file)

    assert report_file.exists()
    assert data["total_assets_evaluated"] == 1
    assert data["brand_compliance_status_counts"]["PASS"] == 1
    assert data["destination_url_status_counts"]["APPROVED"] == 1
    assert data["media_rights_status_counts"]["NOT_APPLICABLE"] == 1
    assert data["ready_to_publish_count"] == 0
    assert data["human_review_required_count"] == 1
    assert "legal clearance" in data["disclaimer"]


# 22. End-to-end pipeline compliance integration and calendar export
def test_pipeline_compliance_integration(tmp_path: Path):
    fixture_path = Path("sample_inputs/repurposing_operations_guide.md")
    result = run_content_pipeline(
        source_path=fixture_path,
        destination_url="https://app.incubrix.com/",
        campaign="brand_safety_2026",
        output_dir=tmp_path / "pipeline_runs",
        render_media=False,
        target_count=4
    )

    # Verify compliance results exist in PipelineResult
    assert len(result.compliance_results) == 12
    assert "PASS" in result.compliance_counts

    # Verify compliance report JSON file on disk
    compliance_file = result.run_dir / "compliance" / "compliance_report.json"
    assert compliance_file.exists()
    comp_json = json.loads(compliance_file.read_text(encoding="utf-8"))
    assert comp_json["total_assets_evaluated"] == 12
    assert comp_json["destination_url_status_counts"]["APPROVED"] == 12

    # Verify candidate calendar CSV contains compliance columns
    complete_cal = result.run_dir / "calendars" / "complete_draft_calendar.csv"
    with open(complete_cal, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        assert "brand_compliance_status" in fields
        assert "destination_url_status" in fields
        assert "rights_status" in fields
        assert "platform_readiness_status" in fields
        rows = list(reader)
        assert len(rows) == 12
        for r in rows:
            assert r["destination_url_status"] == "APPROVED"
            if r["content_format"] in ("text_post", "thread"):
                assert r["rights_status"] == "NOT_APPLICABLE"
            else:
                # Without media rendering (render_media=False), visual/video formats lack provenance manifests
                assert r["rights_status"] == "PENDING_VERIFICATION"

    # Verify summary JSON contains compliance_summary
    summary_file = result.run_dir / "summaries" / "pipeline_summary.json"
    summary_data = json.loads(summary_file.read_text(encoding="utf-8"))
    assert "compliance_summary" in summary_data
    assert summary_data["compliance_summary"]["human_review_required"] is True
    assert summary_data["compliance_summary"]["ready_to_publish_count"] == 0
