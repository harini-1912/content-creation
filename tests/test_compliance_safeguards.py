"""Targeted regression tests for Phase 3.7A: Compliance and Approval Safeguards.

Covers all 15 required verification cases:
1. Approval rejected when compliance_result is None.
2. Approved export excludes assets with missing compliance.
3. Legacy approved record with missing compliance cannot be loaded as valid APPROVED.
4. A substantive caption edit invalidates and reruns compliance.
5. A prohibited claim introduced during refinement causes compliance FAIL.
6. A destination URL edit triggers fresh destination evaluation.
7. Media replacement invalidates old rights evaluation.
8. Unknown media provenance does not receive NOT_APPLICABLE.
9. Missing third-party permission evidence remains PENDING_VERIFICATION.
10. PENDING_VERIFICATION blocks approval even if warning confirmation is supplied.
11. Explicitly renderer-generated media can receive NOT_APPLICABLE with provenance.
12. Restricted media continues to block approval.
13. Existing review audit history survives re-evaluation and reload.
14. Existing pipeline output counts and CSV exports remain consistent.
15. Existing UTM and quality-gate behaviour remains unchanged.
"""

import csv
import dataclasses
import json
from pathlib import Path
import pytest
from pydantic import ValidationError

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
from app.models.review import (
    ReviewStatusEnum,
    ReviewActionEnum,
    ReviewActionRecord,
    ReviewableAsset
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
from app.core.review_workflow import ReviewWorkflowManager
from app.core.pipeline import run_content_pipeline
from app.core.quality_gate import evaluate_asset_quality, QualityGateStatusEnum
from app.core.utm import generate_utm_tracking_url, UTMStatusEnum
from app.core.media_renderer import compute_file_sha256


@pytest.fixture
def clean_draft() -> DraftCandidate:
    """Fixture providing a clean source-attributed text draft candidate."""
    return DraftCandidate(
        draft_id="draft_safe_test_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Creating multi-channel content without a structured system causes fatigue.",
        source_derived_text="Creating multi-channel content without a structured system causes fatigue.",
        platform=PlatformEnum.LINKEDIN,
        content_format=AssetFormatEnum.TEXT_POST,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Solo creators and marketing engineers",
        draft_hook="Operational perspective: Repeatable systems prevent burnout.",
        draft_caption=(
            "Creating multi-channel content without a structured system causes fatigue. "
            "A repeatable framework turns long recordings into structured platform drafts. "
            "Focus on predictable cadence over sporadic bursts."
        ),
        suggested_hashtags=["#ContentStrategy", "#CreatorOperations"],
        call_to_action="Explore the repurposing framework.",
        generated_suggestions={
            "draft_hook": "Operational perspective: Repeatable systems prevent burnout.",
            "call_to_action": "Explore the repurposing framework."
        },
        is_source_attributed=True,
        is_factually_verified=False,
        claim_category=ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED
    )


# 1. Approval rejected when compliance_result is None
def test_approval_rejected_when_compliance_result_is_none(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    qr = evaluate_asset_quality(clean_draft)
    asset = mgr.register_draft(clean_draft, quality_result=qr, compliance_result=None, auto_evaluate=False)
    assert asset.compliance_result is None

    with pytest.raises(ValueError, match="Missing brand compliance evaluation"):
        mgr.approve_asset(
            asset_id=clean_draft.draft_id,
            reviewer_id="Reviewer_01",
            confirm_claims_reviewed=True
        )


# 2. Approved export excludes assets with missing compliance
def test_approved_export_excludes_assets_with_missing_compliance(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    asset = mgr.register_draft(clean_draft, auto_evaluate=False)
    assert asset.compliance_result is None

    # Even if somehow flagged approved, is_eligible_for_approved_export must be False
    assert mgr.is_eligible_for_approved_export(asset) is False

    export_path = tmp_path / "approved.csv"
    mgr.export_approved_assets_calendar_csv(output_path=export_path)
    with open(export_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 0


# 3. Legacy approved record with missing compliance cannot be loaded as valid APPROVED
def test_legacy_approved_record_with_missing_compliance_cannot_be_loaded_as_valid_approved(clean_draft: DraftCandidate, tmp_path: Path):
    # Case A: Direct Pydantic model validation rejects APPROVED with compliance_result=None
    legacy_dict = {
        "asset_id": "draft_legacy_approved_01",
        "draft": clean_draft.model_dump(),
        "original_draft": clean_draft.model_dump(),
        "review_status": "APPROVED",
        "reviewer_id": "Reviewer_Legacy",
        "approval_timestamp": "2026-10-29T12:00:00Z",
        "claims_reviewed_confirmed": True,
        "warnings_reviewed_confirmed": True,
        "quality_result": dataclasses.asdict(evaluate_asset_quality(clean_draft)),
        "compliance_result": None,
        "review_history": [],
        "created_at": "2026-10-29T10:00:00Z",
        "updated_at": "2026-10-29T12:00:00Z"
    }

    with pytest.raises(ValidationError) as exc_info:
        ReviewableAsset.model_validate(legacy_dict)
    assert "Approved asset must have an evaluated compliance_result" in str(exc_info.value)

    # Case B: ReviewWorkflowManager.load() invalidates legacy approval, reverting to PENDING_REVIEW
    store_file = tmp_path / "legacy_review_store.json"
    raw_store = {
        "schema_version": "1.0",
        "updated_at": "2026-10-29T12:00:00Z",
        "total_assets": 1,
        "assets": {
            "draft_legacy_approved_01": legacy_dict
        }
    }
    store_file.write_text(json.dumps(raw_store, indent=2), encoding="utf-8")

    mgr = ReviewWorkflowManager(storage_path=store_file)
    loaded_asset = mgr.get_asset("draft_legacy_approved_01")
    assert loaded_asset.review_status == ReviewStatusEnum.PENDING_REVIEW
    assert loaded_asset.approval_timestamp is None
    assert mgr.is_eligible_for_approved_export(loaded_asset) is False
    assert any("Legacy approval invalidated on load" in h.comments for h in loaded_asset.review_history)


# 4. A substantive caption edit invalidates and reruns compliance
def test_substantive_caption_edit_invalidates_and_reruns_compliance(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    asset = mgr.register_draft(clean_draft, auto_evaluate=True)
    assert asset.compliance_result is not None
    assert asset.compliance_result.brand_compliance_status == ComplianceStatusEnum.PASS

    # Apply substantive edit
    refined = mgr.apply_refinements(
        asset_id=clean_draft.draft_id,
        reviewer_id="Reviewer_Editor",
        caption="Refined caption: Standardizing content operations across platforms with rigor and clarity."
    )

    assert refined.compliance_result is not None
    assert refined.compliance_result.brand_compliance_status == ComplianceStatusEnum.PASS
    assert any(h.metadata.get("is_substantive") is True for h in refined.review_history)


# 5. A prohibited claim introduced during refinement causes compliance FAIL
def test_prohibited_claim_introduced_during_refinement_causes_compliance_fail(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)

    # Introduce severe prohibited claim in caption
    refined = mgr.apply_refinements(
        asset_id=clean_draft.draft_id,
        reviewer_id="Reviewer_Editor",
        caption="Sign up now! 100% money back guarantee with no credit card required!"
    )

    assert refined.compliance_result is not None
    assert refined.compliance_result.brand_compliance_status == ComplianceStatusEnum.FAIL
    assert any("Prohibited Deceptive Phrase" in f for f in refined.compliance_result.unsupported_claim_findings)

    # Attempting approval must fail
    with pytest.raises(ValueError, match="Brand compliance status is FAIL"):
        mgr.approve_asset(
            asset_id=clean_draft.draft_id,
            reviewer_id="Reviewer_01",
            confirm_claims_reviewed=True,
            confirm_warnings_reviewed=True
        )


# 6. A destination URL edit triggers fresh destination evaluation
def test_destination_url_edit_triggers_fresh_destination_evaluation(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)
    mgr.reevaluate_compliance(clean_draft.draft_id, destination_url="https://app.incubrix.com/")
    assert mgr.get_asset(clean_draft.draft_id).compliance_result.destination_url_status == DestinationUrlStatusEnum.APPROVED

    # Refine destination URL to unapproved endpoint
    refined = mgr.apply_refinements(
        asset_id=clean_draft.draft_id,
        reviewer_id="Reviewer_Editor",
        destination_url="https://app.incubrix.com/explore"
    )

    assert refined.compliance_result.destination_url_status == DestinationUrlStatusEnum.UNAPPROVED
    assert refined.compliance_result.brand_compliance_status == ComplianceStatusEnum.FAIL

    with pytest.raises(ValueError, match="Destination URL is UNAPPROVED"):
        mgr.approve_asset(
            asset_id=clean_draft.draft_id,
            reviewer_id="Reviewer_01",
            confirm_claims_reviewed=True,
            confirm_warnings_reviewed=True
        )


# 7. Media replacement invalidates old rights evaluation
def test_media_replacement_invalidates_old_rights_evaluation(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)
    assert mgr.get_asset(clean_draft.draft_id).compliance_result.rights_status == RightsStatusEnum.NOT_APPLICABLE

    # Replace media with third-party pending verification
    third_party_rec = MediaRightsRecord(
        media_asset_id="stock_media_01",
        media_type="VIDEO_BROLL",
        source_or_provider="STOCK_VIDEO_PROVIDER",
        license_description="Editorial Web License",
        rights_status=RightsStatusEnum.PENDING_VERIFICATION
    )
    refined = mgr.apply_refinements(
        asset_id=clean_draft.draft_id,
        reviewer_id="Reviewer_Editor",
        media_rights=[third_party_rec]
    )

    assert refined.compliance_result.rights_status == RightsStatusEnum.PENDING_VERIFICATION
    with pytest.raises(ValueError, match="Media rights are PENDING_VERIFICATION"):
        mgr.approve_asset(
            asset_id=clean_draft.draft_id,
            reviewer_id="Reviewer_01",
            confirm_claims_reviewed=True,
            confirm_warnings_reviewed=True
        )


# 8. Unknown media provenance does not receive NOT_APPLICABLE
def test_unknown_media_provenance_does_not_receive_not_applicable():
    video_draft = DraftCandidate(
        draft_id="draft_video_unprovenanced",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text for video.",
        source_derived_text="Source text for video.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Hook for video.",
        draft_caption="Video script body here.",
        call_to_action="Watch now."
    )

    # Calling without render_dir or media_rights must NOT default to NOT_APPLICABLE
    status, findings = evaluate_media_rights(video_draft, render_dir=None)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert status != RightsStatusEnum.NOT_APPLICABLE
    assert any("Cannot infer local provenance from content format alone" in f for f in findings)


# 9. Missing third-party permission evidence remains PENDING_VERIFICATION
def test_missing_third_party_permission_evidence_remains_pending_verification(clean_draft: DraftCandidate):
    rec = MediaRightsRecord(
        media_asset_id="ext_photo_01",
        media_type="IMAGE",
        source_or_provider="EXTERNAL_STOCK_AGENCY",
        license_description="Commercial Usage Tier 1",
        permission_evidence_reference=None,
        rights_status=RightsStatusEnum.PENDING_VERIFICATION
    )
    status, findings = evaluate_media_rights(clean_draft, media_rights=[rec])
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("requires documented permission evidence" in f for f in findings)


# 10. PENDING_VERIFICATION blocks approval even if warning confirmation is supplied
def test_pending_verification_blocks_approval_even_if_warning_confirmation_supplied(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)

    rec = MediaRightsRecord(
        media_asset_id="ext_photo_01",
        media_type="IMAGE",
        source_or_provider="EXTERNAL_STOCK_AGENCY",
        license_description="Commercial",
        rights_status=RightsStatusEnum.PENDING_VERIFICATION
    )
    mgr.reevaluate_compliance(clean_draft.draft_id, media_rights=[rec])
    asset = mgr.get_asset(clean_draft.draft_id)
    assert asset.compliance_result.rights_status == RightsStatusEnum.PENDING_VERIFICATION

    # confirm_warnings_reviewed=True must NOT allow approval of pending rights
    with pytest.raises(ValueError, match="Media rights are PENDING_VERIFICATION.*cannot be overridden by human warning confirmation"):
        mgr.approve_asset(
            asset_id=clean_draft.draft_id,
            reviewer_id="Reviewer_01",
            confirm_claims_reviewed=True,
            confirm_warnings_reviewed=True
        )


# 11. Explicitly renderer-generated media can receive NOT_APPLICABLE with provenance
def test_explicitly_renderer_generated_media_can_receive_not_applicable_with_provenance(tmp_path: Path):
    render_dir = tmp_path / "render_draft_shorts_01"
    render_dir.mkdir(parents=True, exist_ok=True)
    dummy_video = render_dir / "preview.mp4"
    dummy_video.write_bytes(b"dummy_rendered_video_preview_stream_bytes")
    video_hash = compute_file_sha256(dummy_video)

    manifest = {
        "asset_id": "draft_shorts_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4"],
        "file_hashes": {
            "preview.mp4": video_hash
        },
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    video_draft = DraftCandidate(
        draft_id="draft_shorts_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Excerpt",
        source_derived_text="Derived text",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Hook text",
        draft_caption="Caption text",
        call_to_action="CTA"
    )

    status, findings = evaluate_media_rights(video_draft, render_dir=render_dir)
    assert status == RightsStatusEnum.NOT_APPLICABLE
    assert any("Media Provenance and File Integrity Verified" in f for f in findings)


# 12. Restricted media continues to block approval
def test_restricted_media_continues_to_block_approval(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)

    rec = MediaRightsRecord(
        media_asset_id="restricted_footage_01",
        media_type="VIDEO",
        source_or_provider="RESTRICTED_ARCHIVE",
        license_description="Strictly non-commercial personal use",
        rights_status=RightsStatusEnum.RESTRICTED
    )
    mgr.reevaluate_compliance(clean_draft.draft_id, media_rights=[rec])

    with pytest.raises(ValueError, match="Media rights are RESTRICTED"):
        mgr.approve_asset(
            asset_id=clean_draft.draft_id,
            reviewer_id="Reviewer_01",
            confirm_claims_reviewed=True,
            confirm_warnings_reviewed=True
        )


# 13. Existing review audit history survives re-evaluation and reload
def test_existing_review_audit_history_survives_reevaluation_and_reload(clean_draft: DraftCandidate, tmp_path: Path):
    store_file = tmp_path / "reviews" / "review_store.json"
    mgr1 = ReviewWorkflowManager(storage_path=store_file)
    mgr1.register_draft(clean_draft, auto_evaluate=True)

    mgr1.record_feedback(clean_draft.draft_id, reviewer_id="Reviewer_Alpha", feedback="Initial review notes.")
    mgr1.apply_refinements(clean_draft.draft_id, reviewer_id="Reviewer_Alpha", hook="New Hook Refinement.")
    mgr1.reevaluate_compliance(clean_draft.draft_id, destination_url="https://app.incubrix.com/")

    # Reload from disk in a fresh manager instance
    mgr2 = ReviewWorkflowManager(storage_path=store_file)
    loaded_asset = mgr2.get_asset(clean_draft.draft_id)

    assert len(loaded_asset.review_history) == 3
    assert loaded_asset.review_history[0].action == ReviewActionEnum.RECORD_FEEDBACK
    assert loaded_asset.review_history[1].action == ReviewActionEnum.APPLY_REFINEMENTS
    assert loaded_asset.compliance_result.destination_url_status == DestinationUrlStatusEnum.APPROVED


# 14. Existing pipeline output counts and CSV exports remain consistent
def test_existing_pipeline_output_counts_and_csv_exports_remain_consistent(tmp_path: Path):
    fixture_path = Path("sample_inputs/repurposing_operations_guide.md")
    result = run_content_pipeline(
        source_path=fixture_path,
        destination_url="https://app.incubrix.com/",
        campaign="qa_2026",
        output_dir=tmp_path / "pipeline_runs",
        render_media=False,
        target_count=4
    )

    assert result.total_candidates == 12
    assert len(result.compliance_results) == 12
    assert result.approved_export_count == 0
    assert result.unapproved_export_count == 12

    # Check candidate calendar column count (28 columns)
    complete_cal = result.run_dir / "calendars" / "complete_draft_calendar.csv"
    with open(complete_cal, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        assert len(reader.fieldnames) == 28
        rows = list(reader)
        assert len(rows) == 12


# 15. Existing UTM and quality-gate behaviour remains unchanged
def test_existing_utm_and_quality_gate_behaviour_remains_unchanged(clean_draft: DraftCandidate):
    utm_res = generate_utm_tracking_url(
        destination_url="https://app.incubrix.com/?ref=partner#pricing",
        platform=PlatformEnum.LINKEDIN,
        content_format=AssetFormatEnum.TEXT_POST,
        campaign="test_camp",
        content_id="test_id"
    )
    assert utm_res.status == UTMStatusEnum.GENERATED
    assert "utm_source=linkedin" in utm_res.tracking_url
    assert "ref=partner" in utm_res.tracking_url
    assert "#pricing" in utm_res.tracking_url

    q_res = evaluate_asset_quality(clean_draft)
    assert q_res.overall_status == QualityGateStatusEnum.PASS
    assert q_res.requires_human_review is True
    assert q_res.is_ready_to_publish is False


# ==============================================================================
# PHASE 3.8: Media Integrity & Refinement Hardening Regression Tests
# ==============================================================================

# 16. Valid video manifest and matching hash
def test_valid_video_manifest_and_matching_hash(tmp_path: Path):
    render_dir = tmp_path / "valid_video"
    render_dir.mkdir(parents=True, exist_ok=True)
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"actual_valid_mp4_encoded_stream_bytes")
    expected_hash = compute_file_sha256(video_file)

    manifest = {
        "asset_id": "draft_video_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4"],
        "file_hashes": {"preview.mp4": expected_hash},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_video_01",
        source_document="doc.md",
        source_segment_id="seg_01",
        source_excerpt="Source text for video.",
        source_derived_text="Source text for video.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Audience",
        draft_hook="Hook for video",
        draft_caption="Caption for video",
        call_to_action="CTA"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.NOT_APPLICABLE
    assert any("All 1 media file(s) matched manifest SHA-256 digests" in f for f in findings)


# 17. Valid carousel manifest with all matching hashes
def test_valid_carousel_manifest_with_all_matching_hashes(tmp_path: Path):
    render_dir = tmp_path / "valid_carousel"
    render_dir.mkdir(parents=True, exist_ok=True)

    file_hashes = {}
    for i in range(1, 6):
        fn = f"slide_{i:02d}.png"
        fpath = render_dir / fn
        fpath.write_bytes(f"png_slide_image_content_{i}".encode("utf-8"))
        file_hashes[fn] = compute_file_sha256(fpath)

    sheet_path = render_dir / "carousel_contact_sheet.png"
    sheet_path.write_bytes(b"contact_sheet_image_content")
    file_hashes["carousel_contact_sheet.png"] = compute_file_sha256(sheet_path)

    manifest = {
        "asset_id": "draft_carousel_01",
        "platform": "instagram",
        "content_format": "carousel",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": list(file_hashes.keys()),
        "file_hashes": file_hashes,
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_carousel_01",
        source_document="doc.md",
        source_segment_id="seg_01",
        source_excerpt="Source text for carousel.",
        source_derived_text="Source text for carousel.",
        platform=PlatformEnum.INSTAGRAM,
        content_format=AssetFormatEnum.CAROUSEL,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Audience",
        draft_hook="Hook for carousel",
        draft_caption="Caption for carousel",
        call_to_action="CTA"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.NOT_APPLICABLE
    assert any("All 6 media file(s) matched manifest SHA-256 digests" in f for f in findings)


# 18. Modified MP4 after rendering fails integrity
def test_modified_mp4_after_rendering_fails_integrity(tmp_path: Path):
    render_dir = tmp_path / "modified_video"
    render_dir.mkdir(parents=True, exist_ok=True)
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"original_rendered_bytes")
    original_hash = compute_file_sha256(video_file)

    manifest = {
        "asset_id": "draft_video_mod_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4"],
        "file_hashes": {"preview.mp4": original_hash},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Post-render modification (e.g. video file replaced with external copyrighted content)
    video_file.write_bytes(b"external_replaced_tampered_video_content")

    draft = DraftCandidate(
        draft_id="draft_video_mod_01",
        source_document="doc.md",
        source_segment_id="seg_01",
        source_excerpt="Source text for video.",
        source_derived_text="Source text for video.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Audience",
        draft_hook="Operational Hook for video testing",
        draft_caption="Operational caption text for video testing.",
        call_to_action="CTA"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("Cryptographic hash mismatch for 'preview.mp4'" in f for f in findings)


# 19. Modified carousel slide after rendering fails integrity
def test_modified_carousel_slide_after_rendering_fails_integrity(tmp_path: Path):
    render_dir = tmp_path / "modified_carousel"
    render_dir.mkdir(parents=True, exist_ok=True)

    file_hashes = {}
    for i in range(1, 6):
        fn = f"slide_{i:02d}.png"
        fpath = render_dir / fn
        fpath.write_bytes(f"slide_{i}_original".encode("utf-8"))
        file_hashes[fn] = compute_file_sha256(fpath)

    manifest = {
        "asset_id": "draft_car_mod_01",
        "platform": "instagram",
        "content_format": "carousel",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": list(file_hashes.keys()),
        "file_hashes": file_hashes,
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Tamper with slide 3
    (render_dir / "slide_03.png").write_bytes(b"tampered_slide_3_replacement")

    draft = DraftCandidate(
        draft_id="draft_car_mod_01",
        source_document="doc.md",
        source_segment_id="seg_01",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.INSTAGRAM,
        content_format=AssetFormatEnum.CAROUSEL,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Audience",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("Cryptographic hash mismatch for 'slide_03.png'" in f for f in findings)


# 20. Missing media file fails integrity
def test_missing_media_file_fails_integrity(tmp_path: Path):
    render_dir = tmp_path / "missing_file"
    render_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "asset_id": "draft_missing_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4"],
        "file_hashes": {"preview.mp4": "a" * 64},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Do not create preview.mp4 on disk
    draft = DraftCandidate(
        draft_id="draft_missing_01",
        source_document="doc.md",
        source_segment_id="seg_01",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Audience",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("Expected media artifact 'preview.mp4' not found on disk" in f for f in findings)


# 21. Missing hash in an old manifest fails integrity
def test_missing_hash_in_old_manifest_fails_integrity(tmp_path: Path):
    render_dir = tmp_path / "old_manifest"
    render_dir.mkdir(parents=True, exist_ok=True)
    (render_dir / "preview.mp4").write_bytes(b"some_mp4_bytes")

    # Legacy manifest from Phase 3.7 without file_hashes mapping
    legacy_manifest = {
        "asset_id": "draft_old_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4"]
        # Notice: file_hashes is missing
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(legacy_manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_old_01",
        source_document="doc.md",
        source_segment_id="seg_01",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Audience",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("lacks cryptographic 'file_hashes' mapping" in f for f in findings)


# 22. Wrong asset ID in manifest fails integrity
def test_wrong_asset_id_in_manifest_fails_integrity(tmp_path: Path):
    render_dir = tmp_path / "wrong_aid"
    render_dir.mkdir(parents=True, exist_ok=True)
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"video_bytes")
    v_hash = compute_file_sha256(video_file)

    manifest = {
        "asset_id": "draft_DIFFERENT_id",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "file_hashes": {"preview.mp4": v_hash}
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_actual_01",
        source_document="doc.md",
        source_segment_id="seg_01",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Audience",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("Manifest asset ID 'draft_DIFFERENT_id' does not match draft ID 'draft_actual_01'" in f for f in findings)


# 23. Stale manifest after media replacement fails integrity
def test_stale_manifest_after_media_replacement(tmp_path: Path):
    render_dir = tmp_path / "stale_manifest"
    render_dir.mkdir(parents=True, exist_ok=True)
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"initial_video_v1")
    hash_v1 = compute_file_sha256(video_file)

    manifest = {
        "asset_id": "draft_stale_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "file_hashes": {"preview.mp4": hash_v1}
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Replace media file with v2 without regenerating manifest
    video_file.write_bytes(b"replacement_video_v2")

    draft = DraftCandidate(
        draft_id="draft_stale_01",
        source_document="doc.md",
        source_segment_id="seg_01",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Audience",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("Media Integrity Tampering Detected" in f for f in findings)


# 24. Render directory change invalidates approval
def test_render_dir_change_invalidates_approval(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)

    # First approve the asset
    mgr.approve_asset(
        asset_id=clean_draft.draft_id,
        reviewer_id="Reviewer_01",
        confirm_claims_reviewed=True
    )
    assert mgr.get_asset(clean_draft.draft_id).review_status == ReviewStatusEnum.APPROVED

    # Now change render_dir in refinement
    new_render_dir = tmp_path / "new_media_dir"
    new_render_dir.mkdir(parents=True, exist_ok=True)
    refined = mgr.apply_refinements(
        asset_id=clean_draft.draft_id,
        reviewer_id="Reviewer_01",
        render_dir=new_render_dir
    )

    # Approval must be invalidated
    assert refined.review_status == ReviewStatusEnum.IN_REVIEW
    assert refined.approval_timestamp is None
    assert refined.claims_reviewed_confirmed is False
    assert refined.warnings_reviewed_confirmed is False
    assert refined.draft.render_directory == str(new_render_dir)
    assert any(h.metadata.get("approval_invalidated") is True for h in refined.review_history)


# 25. Render directory change recalculates media provenance
def test_render_dir_change_recalculates_media_provenance(tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")

    video_draft = DraftCandidate(
        draft_id="draft_video_dir_change_01",
        source_document="doc.md",
        source_segment_id="seg_01",
        source_excerpt="Source text for video.",
        source_derived_text="Source text for video.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Audience",
        draft_hook="Hook text",
        draft_caption="Caption text",
        call_to_action="CTA"
    )

    # Registered without render dir -> PENDING_VERIFICATION
    asset = mgr.register_draft(video_draft, auto_evaluate=True)
    assert asset.compliance_result.rights_status == RightsStatusEnum.PENDING_VERIFICATION

    # Create valid render directory with manifest and video
    render_dir = tmp_path / "rendered_video"
    render_dir.mkdir(parents=True, exist_ok=True)
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"valid_video_bytes")
    v_hash = compute_file_sha256(video_file)

    manifest = {
        "asset_id": "draft_video_dir_change_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4"],
        "file_hashes": {"preview.mp4": v_hash},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Apply refinement supplying the valid render dir
    refined = mgr.apply_refinements(
        asset_id=video_draft.draft_id,
        reviewer_id="Reviewer_Editor",
        render_dir=render_dir
    )

    assert refined.compliance_result.rights_status == RightsStatusEnum.NOT_APPLICABLE
    assert refined.draft.render_directory == str(render_dir)


# 26. Replacement media with invalid hash becomes pending verification and blocks approval
def test_replacement_media_with_invalid_hash_becomes_pending_verification(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.core.quality_gate.probe_media_duration", lambda p: 15.0)
    monkeypatch.setattr("app.core.quality_gate.probe_media_dimensions", lambda p: (1080, 1920))

    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")

    # Start with valid video
    render_dir1 = tmp_path / "valid_render"
    render_dir1.mkdir(parents=True, exist_ok=True)
    v1 = render_dir1 / "preview.mp4"
    v1.write_bytes(b"initial_clean_bytes")
    h1 = compute_file_sha256(v1)

    manifest1 = {
        "asset_id": "draft_vid_replace_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "source_segment_id": "seg_01",
        "review_status": "DRAFT_PREVIEW_REQUIRES_HUMAN_REVIEW",
        "output_files": ["preview.mp4"],
        "file_hashes": {"preview.mp4": h1},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir1 / "render_manifest.json").write_text(json.dumps(manifest1), encoding="utf-8")

    video_draft = DraftCandidate(
        draft_id="draft_vid_replace_01",
        source_document="doc.md",
        source_segment_id="seg_01",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Audience",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA"
    )

    asset = mgr.register_draft(video_draft, render_dir=render_dir1, auto_evaluate=True)
    assert asset.compliance_result.rights_status == RightsStatusEnum.NOT_APPLICABLE

    # Approve initial asset
    mgr.approve_asset(
        asset_id=video_draft.draft_id,
        reviewer_id="Reviewer_01",
        confirm_claims_reviewed=True,
        confirm_warnings_reviewed=True
    )
    assert mgr.get_asset(video_draft.draft_id).review_status == ReviewStatusEnum.APPROVED

    # Now replace with directory containing corrupted/tampered hash
    render_dir2 = tmp_path / "corrupted_render"
    render_dir2.mkdir(parents=True, exist_ok=True)
    v2 = render_dir2 / "preview.mp4"
    v2.write_bytes(b"actual_tampered_bytes")
    manifest2 = {
        "asset_id": "draft_vid_replace_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "source_segment_id": "seg_01",
        "review_status": "DRAFT_PREVIEW_REQUIRES_HUMAN_REVIEW",
        "output_files": ["preview.mp4"],
        "file_hashes": {"preview.mp4": "0" * 64},  # Mismatched hash
        "integrity_algorithm": "SHA-256"
    }
    (render_dir2 / "render_manifest.json").write_text(json.dumps(manifest2), encoding="utf-8")

    refined = mgr.apply_refinements(
        asset_id=video_draft.draft_id,
        reviewer_id="Reviewer_01",
        render_dir=render_dir2
    )

    assert refined.review_status == ReviewStatusEnum.IN_REVIEW
    assert refined.compliance_result.rights_status == RightsStatusEnum.PENDING_VERIFICATION

    # Attempt to approve must fail
    with pytest.raises(ValueError, match="Media rights are PENDING_VERIFICATION"):
        mgr.approve_asset(
            asset_id=video_draft.draft_id,
            reviewer_id="Reviewer_01",
            confirm_claims_reviewed=True,
            confirm_warnings_reviewed=True
        )


# 27. Hook edit recalculates compliance
def test_hook_edit_recalculates_compliance(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)
    assert mgr.get_asset(clean_draft.draft_id).compliance_result.brand_compliance_status == ComplianceStatusEnum.PASS

    # Edit hook with severe prohibited phrase
    refined = mgr.apply_refinements(
        asset_id=clean_draft.draft_id,
        reviewer_id="Reviewer_Editor",
        hook="Guaranteed return on all creator workflows!"
    )

    assert refined.compliance_result.brand_compliance_status == ComplianceStatusEnum.FAIL
    assert any("Prohibited Deceptive Phrase" in f for f in refined.compliance_result.unsupported_claim_findings)


# 28. Hashtag edit recalculates compliance
def test_hashtag_edit_recalculates_compliance(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)

    refined = mgr.apply_refinements(
        asset_id=clean_draft.draft_id,
        reviewer_id="Reviewer_Editor",
        hashtags=["#OperationsEngine", "#ContentSystems2026"]
    )

    assert refined.draft.suggested_hashtags == ["#OperationsEngine", "#ContentSystems2026"]
    assert refined.compliance_result is not None
    assert any("suggested_hashtags" in h.metadata.get("edited_fields", []) for h in refined.review_history)


# 29. CTA edit recalculates compliance
def test_cta_edit_recalculates_compliance(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)

    refined = mgr.apply_refinements(
        asset_id=clean_draft.draft_id,
        reviewer_id="Reviewer_Editor",
        call_to_action="Register for the certified repurposing masterclass today."
    )

    assert refined.draft.call_to_action == "Register for the certified repurposing masterclass today."
    assert refined.compliance_result is not None
    assert any("call_to_action" in h.metadata.get("edited_fields", []) for h in refined.review_history)


# 30. Content-format edit recalculates compliance
def test_content_format_edit_recalculates_compliance(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)
    # clean_draft is TEXT_POST -> rights NOT_APPLICABLE
    assert mgr.get_asset(clean_draft.draft_id).compliance_result.rights_status == RightsStatusEnum.NOT_APPLICABLE

    # Change format to SHORT_VIDEO without media render_dir
    refined = mgr.apply_refinements(
        asset_id=clean_draft.draft_id,
        reviewer_id="Reviewer_Editor",
        content_format=AssetFormatEnum.SHORT_VIDEO
    )

    # Now requires media rights verification
    assert refined.compliance_result.rights_status == RightsStatusEnum.PENDING_VERIFICATION


# 31. Unsupported platform change explicitly rejected
def test_unsupported_platform_change_explicitly_rejected(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)

    with pytest.raises(ValueError, match="Modifying platform from 'linkedin' to 'twitter' is not supported"):
        mgr.apply_refinements(
            asset_id=clean_draft.draft_id,
            reviewer_id="Reviewer_Editor",
            platform=PlatformEnum.TWITTER
        )


# 32. Unsupported source segment change explicitly rejected
def test_unsupported_source_segment_change_explicitly_rejected(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)

    with pytest.raises(ValueError, match="Modifying source_segment_id from .* is not supported"):
        mgr.apply_refinements(
            asset_id=clean_draft.draft_id,
            reviewer_id="Reviewer_Editor",
            source_segment_id="seg_different_1234"
        )


# 33. Reevaluate compliance invalidates approval on compliance failure
def test_reevaluate_compliance_invalidates_approval_on_compliance_failure(clean_draft: DraftCandidate, tmp_path: Path):
    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")
    mgr.register_draft(clean_draft, auto_evaluate=True)

    mgr.approve_asset(
        asset_id=clean_draft.draft_id,
        reviewer_id="Reviewer_01",
        confirm_claims_reviewed=True
    )
    assert mgr.get_asset(clean_draft.draft_id).review_status == ReviewStatusEnum.APPROVED

    # Re-evaluate compliance introducing unapproved destination URL
    re_evaluated = mgr.reevaluate_compliance(
        asset_id=clean_draft.draft_id,
        destination_url="https://app.incubrix.com/explore"
    )

    # Must be invalidated to PENDING_REVIEW
    assert re_evaluated.review_status == ReviewStatusEnum.PENDING_REVIEW
    assert re_evaluated.approval_timestamp is None
    assert re_evaluated.compliance_result.destination_url_status == DestinationUrlStatusEnum.UNAPPROVED
    assert mgr.is_eligible_for_approved_export(re_evaluated) is False


# ==============================================================================
# Phase 3.9 Security Hardening Regression Tests (Tests 34-47)
# ==============================================================================

# 34. Path traversal: parent directory traversal ('../') is rejected
def test_manifest_rejects_parent_directory_traversal(tmp_path: Path):
    render_dir = tmp_path / "traversal_parent"
    render_dir.mkdir(parents=True, exist_ok=True)
    
    manifest = {
        "asset_id": "draft_trav_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["../escaped_video.mp4"],
        "file_hashes": {"../escaped_video.mp4": "a" * 64},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_trav_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text for traversal test.",
        source_derived_text="Source text for traversal test.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("parent directory traversal" in f or "Media Path Traversal Rejected" in f for f in findings)


# 35. Path traversal: nested traversal ('nested/../../') is rejected
def test_manifest_rejects_nested_directory_traversal(tmp_path: Path):
    render_dir = tmp_path / "traversal_nested"
    render_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "asset_id": "draft_trav_02",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["nested/../../outside.mp4"],
        "file_hashes": {"nested/../../outside.mp4": "b" * 64},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_trav_02",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text for traversal test.",
        source_derived_text="Source text for traversal test.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("parent directory traversal" in f or "Media Path Traversal Rejected" in f for f in findings)


# 36. Path traversal: absolute Windows paths are rejected
def test_manifest_rejects_absolute_windows_path(tmp_path: Path):
    render_dir = tmp_path / "traversal_win_abs"
    render_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "asset_id": "draft_trav_03",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["C:/windows/secret.mp4"],
        "file_hashes": {"C:/windows/secret.mp4": "c" * 64},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_trav_03",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text for traversal test.",
        source_derived_text="Source text for traversal test.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("drive specification" in f or "absolute path" in f or "Media Path Traversal Rejected" in f for f in findings)


# 37. Path traversal: absolute POSIX paths are rejected
def test_manifest_rejects_absolute_posix_path(tmp_path: Path):
    render_dir = tmp_path / "traversal_posix_abs"
    render_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "asset_id": "draft_trav_04",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["/etc/passwd"],
        "file_hashes": {"/etc/passwd": "d" * 64},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_trav_04",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text for traversal test.",
        source_derived_text="Source text for traversal test.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("directory separator or root slash" in f or "absolute path" in f or "Media Path Traversal Rejected" in f for f in findings)


# 38. Path traversal: symbolic links escaping render directory are rejected
def test_manifest_rejects_symlink_escaping_render_directory(tmp_path: Path, monkeypatch):
    render_dir = tmp_path / "traversal_symlink"
    render_dir.mkdir(parents=True, exist_ok=True)

    # External file outside render_dir
    outside_dir = tmp_path / "outside_store"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_video = outside_dir / "target_video.mp4"
    outside_video.write_bytes(b"outside_escaped_bytes")
    video_hash = compute_file_sha256(outside_video)

    link_file = render_dir / "escaped_link.mp4"

    # Attempt to create OS symlink; if OS requires elevated privilege, mock symlink behavior
    try:
        import os
        os.symlink(outside_video, link_file)
    except OSError:
        # On Windows non-admin accounts, create a dummy file and monkeypatch is_symlink & resolve
        link_file.write_bytes(b"outside_escaped_bytes")
        original_resolve = Path.resolve
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda self: self.name == "escaped_link.mp4"
        )
        monkeypatch.setattr(
            Path,
            "resolve",
            lambda self, strict=False: outside_video.resolve() if self.name == "escaped_link.mp4" else original_resolve(self)
        )

    manifest = {
        "asset_id": "draft_trav_sym_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["escaped_link.mp4"],
        "file_hashes": {"escaped_link.mp4": video_hash},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_trav_sym_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text for traversal test.",
        source_derived_text="Source text for traversal test.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("Symlink" in f and "resolves outside render directory" in f for f in findings)


# 39. Path traversal: valid files inside render directory pass path safety
def test_manifest_accepts_valid_files_strictly_inside_render_directory(tmp_path: Path):
    render_dir = tmp_path / "valid_safe_dir"
    render_dir.mkdir(parents=True, exist_ok=True)
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"clean_local_preview_bytes")
    v_hash = compute_file_sha256(video_file)

    manifest = {
        "asset_id": "draft_valid_path_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4"],
        "file_hashes": {"preview.mp4": v_hash},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_valid_path_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.NOT_APPLICABLE
    assert any("Media Provenance and File Integrity Verified" in f for f in findings)


# 40. Unexpected files: extra PNG file in render directory causes PENDING_VERIFICATION
def test_unexpected_extra_png_in_render_dir_evaluates_to_pending_verification(tmp_path: Path):
    render_dir = tmp_path / "extra_png_dir"
    render_dir.mkdir(parents=True, exist_ok=True)
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"valid_video_bytes")
    v_hash = compute_file_sha256(video_file)

    manifest = {
        "asset_id": "draft_extra_png_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4"],
        "file_hashes": {"preview.mp4": v_hash},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Drop unauthorized extra PNG into render directory
    extra_png = render_dir / "unauthorized_overlay.png"
    extra_png.write_bytes(b"extra_png_content")

    draft = DraftCandidate(
        draft_id="draft_extra_png_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("Unexpected File Detected" in f and "unauthorized_overlay.png" in f for f in findings)


# 41. Unexpected files: extra MP4 file in render directory causes PENDING_VERIFICATION
def test_unexpected_extra_mp4_in_render_dir_evaluates_to_pending_verification(tmp_path: Path):
    render_dir = tmp_path / "extra_mp4_dir"
    render_dir.mkdir(parents=True, exist_ok=True)
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"valid_video_bytes")
    v_hash = compute_file_sha256(video_file)

    manifest = {
        "asset_id": "draft_extra_mp4_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4"],
        "file_hashes": {"preview.mp4": v_hash},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Drop unauthorized extra MP4 clip into render directory
    extra_mp4 = render_dir / "bonus_broll_clip.mp4"
    extra_mp4.write_bytes(b"unauthorized_broll_bytes")

    draft = DraftCandidate(
        draft_id="draft_extra_mp4_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("Unexpected File Detected" in f and "bonus_broll_clip.mp4" in f for f in findings)


# 42. Unexpected files: unexpected subdirectory in render directory causes PENDING_VERIFICATION
def test_unexpected_subdirectory_in_render_dir_evaluates_to_pending_verification(tmp_path: Path):
    render_dir = tmp_path / "extra_subdir_dir"
    render_dir.mkdir(parents=True, exist_ok=True)
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"valid_video_bytes")
    v_hash = compute_file_sha256(video_file)

    manifest = {
        "asset_id": "draft_extra_sub_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4"],
        "file_hashes": {"preview.mp4": v_hash},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Create unexpected subfolder
    subfolder = render_dir / "raw_assets"
    subfolder.mkdir(parents=True, exist_ok=True)

    draft = DraftCandidate(
        draft_id="draft_extra_sub_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("Unexpected Directory Detected" in f and "raw_assets" in f for f in findings)


# 43. Unexpected files: missing declared output file causes PENDING_VERIFICATION
def test_missing_declared_output_file_evaluates_to_pending_verification(tmp_path: Path):
    render_dir = tmp_path / "missing_declared"
    render_dir.mkdir(parents=True, exist_ok=True)

    # Manifest declares preview.mp4 and slide_01.png, but slide_01.png is missing from disk
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"valid_video_bytes")
    v_hash = compute_file_sha256(video_file)

    manifest = {
        "asset_id": "draft_missing_decl_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4", "slide_01.png"],
        "file_hashes": {
            "preview.mp4": v_hash,
            "slide_01.png": "e" * 64
        },
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_missing_decl_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("Media File Missing" in f and "slide_01.png" in f for f in findings)


# 44. Inconsistent manifest: declared output file without a hash causes PENDING_VERIFICATION
def test_declared_output_file_without_hash_evaluates_to_pending_verification(tmp_path: Path):
    render_dir = tmp_path / "unhashed_output"
    render_dir.mkdir(parents=True, exist_ok=True)
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"valid_video_bytes")
    v_hash = compute_file_sha256(video_file)

    # Manifest declares output_files with slide_01.png, but file_hashes lacks slide_01.png
    manifest = {
        "asset_id": "draft_unhashed_decl_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4", "slide_01.png"],
        "file_hashes": {
            "preview.mp4": v_hash
        },
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_unhashed_decl_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("lack SHA-256 hashes in 'file_hashes'" in f for f in findings)


# 45. Inconsistent manifest: hash entry without corresponding declared output causes PENDING_VERIFICATION
def test_hash_entry_without_declared_output_evaluates_to_pending_verification(tmp_path: Path):
    render_dir = tmp_path / "undeclared_hash"
    render_dir.mkdir(parents=True, exist_ok=True)
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"valid_video_bytes")
    v_hash = compute_file_sha256(video_file)

    # file_hashes has unlisted.mp4, but output_files only declares preview.mp4
    manifest = {
        "asset_id": "draft_undecl_hash_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": ["preview.mp4"],
        "file_hashes": {
            "preview.mp4": v_hash,
            "unlisted.mp4": "f" * 64
        },
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_undecl_hash_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.PENDING_VERIFICATION
    assert any("present in 'file_hashes' but not declared in 'output_files'" in f for f in findings)


# 46. Valid render directory with only expected files and permitted metadata passes
def test_valid_render_dir_with_only_expected_files_and_permitted_metadata_passes(tmp_path: Path):
    render_dir = tmp_path / "valid_complete_carousel"
    render_dir.mkdir(parents=True, exist_ok=True)

    file_hashes = {}
    for i in range(1, 6):
        fn = f"slide_{i:02d}.png"
        fp = render_dir / fn
        fp.write_bytes(f"slide_pixel_data_{i}".encode("utf-8"))
        file_hashes[fn] = compute_file_sha256(fp)

    cs_path = render_dir / "carousel_contact_sheet.png"
    cs_path.write_bytes(b"contact_sheet_data")
    file_hashes["carousel_contact_sheet.png"] = compute_file_sha256(cs_path)

    manifest = {
        "asset_id": "draft_clean_car_01",
        "platform": "instagram",
        "content_format": "carousel",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow)",
        "media_rights_status": "NOT_APPLICABLE",
        "output_files": list(file_hashes.keys()),
        "file_hashes": file_hashes,
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = DraftCandidate(
        draft_id="draft_clean_car_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01_a1b2c3d4",
        source_excerpt="Source text for carousel.",
        source_derived_text="Source text for carousel.",
        platform=PlatformEnum.INSTAGRAM,
        content_format=AssetFormatEnum.CAROUSEL,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    status, findings = evaluate_media_rights(draft, render_dir=render_dir)
    assert status == RightsStatusEnum.NOT_APPLICABLE
    assert any("strict directory isolation and verified internal kinetic typography provenance" in f for f in findings)


# 47. Security failures (traversal or unexpected files) strictly block reviewer approval
def test_path_traversal_or_unexpected_file_strictly_blocks_approval(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.core.quality_gate.probe_media_duration", lambda p: 15.0)
    monkeypatch.setattr("app.core.quality_gate.probe_media_dimensions", lambda p: (1080, 1920))

    render_dir = tmp_path / "security_block_dir"
    render_dir.mkdir(parents=True, exist_ok=True)
    video_file = render_dir / "preview.mp4"
    video_file.write_bytes(b"valid_video_bytes")
    v_hash = compute_file_sha256(video_file)

    manifest = {
        "asset_id": "draft_sec_block_01",
        "platform": "youtube_shorts",
        "content_format": "short_video",
        "media_provenance": "LOCALLY_GENERATED_KINETIC_TEXT",
        "renderer_engine": "IncuBrix Media Renderer v1.0 (Pillow + FFmpeg)",
        "media_rights_status": "NOT_APPLICABLE",
        "source_segment_id": "seg_01",
        "review_status": "DRAFT_PREVIEW_REQUIRES_HUMAN_REVIEW",
        "output_files": ["preview.mp4"],
        "file_hashes": {"preview.mp4": v_hash},
        "integrity_algorithm": "SHA-256"
    }
    (render_dir / "render_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Add unexpected file into render directory
    (render_dir / "malicious_extra.mp4").write_bytes(b"malicious_clip")

    mgr = ReviewWorkflowManager(storage_path=tmp_path / "review_store.json")

    draft = DraftCandidate(
        draft_id="draft_sec_block_01",
        source_document="operations_mastery.md",
        source_segment_id="seg_01",
        source_excerpt="Source text.",
        source_derived_text="Source text.",
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        pillar=PillarEnum.WORKFLOW_EDUCATION,
        intended_audience="Creators",
        draft_hook="Operational Hook for testing",
        draft_caption="Operational caption text for testing purposes.",
        call_to_action="CTA explore"
    )

    asset = mgr.register_draft(draft, render_dir=render_dir, auto_evaluate=True)
    assert asset.compliance_result.rights_status == RightsStatusEnum.PENDING_VERIFICATION

    # Attempt approval with human warning confirmations; must be strictly blocked
    with pytest.raises(ValueError, match="Media rights are PENDING_VERIFICATION"):
        mgr.approve_asset(
            asset_id=draft.draft_id,
            reviewer_id="Reviewer_01",
            confirm_claims_reviewed=True,
            confirm_warnings_reviewed=True
        )

    # Asset must remain in review and ineligible for approved calendar export
    current_asset = mgr.get_asset(draft.draft_id)
    assert current_asset.review_status != ReviewStatusEnum.APPROVED
    assert mgr.is_eligible_for_approved_export(current_asset) is False
