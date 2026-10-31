"""Brand Compliance, Rights Safety, and Platform Readiness Module for IncuBrix.

Implements Phase 3.7 & Phase 3.9 compliance and security checks:
1. Brand voice and messaging consistency (pillars, approved terminology, buzzword checks).
2. Unsupported or unverified brand claims (backed by explicit evidence references).
3. Destination URL safeguards (strict allowlist validation; syntactically valid != approved).
4. Copyright and media-rights documentation (locally generated kinetic text vs third-party media).
5. Platform-specific content-format readiness (structural rules vs external platform policies).
6. Missing publishing/scheduler metadata checks.
7. Phase 3.9 Manifest Security Hardening:
   - Canonical absolute directory resolution.
   - Strict path traversal protection (rejection of '..', drive letters, absolute Windows/POSIX paths, symlink escapes).
   - Strict directory content comparison (unexpected media files and directories result in PENDING_VERIFICATION).
   - Manifest trust-boundary clarification (SHA-256 confirms file integrity against a trusted manifest, but
     an unsigned manifest does not provide cryptographic origin authentication or non-repudiation).

Crucial Safeguards:
- Automated compliance evaluation NEVER approves an asset.
- Passing compliance NEVER sets is_ready_to_publish=True.
- CAT_4_UNSUPPORTED claims strictly FAIL compliance.
- Unapproved destination URLs strictly FAIL compliance.
- Missing destination URLs receive PENDING_DESTINATION_URL (advisory warning).
- Third-party media without documented permission evidence is PENDING_VERIFICATION.
- Restricted media strictly FAILS compliance.
- Manifest path traversal or unexpected files strictly evaluate to PENDING_VERIFICATION.
- All assets strictly maintain requires_human_review=True.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlsplit

from app.models.asset import (
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
from app.core.utm import validate_destination_url
from app.core.quality_gate import evaluate_asset_quality, QualityGateStatusEnum
from app.core.media_renderer import compute_file_sha256


# ==============================================================================
# 1. Default Brand Compliance Profile Factory
# ==============================================================================

# Default verified live destination endpoints from Strategy Doc 5 (EV-001, EV-003, EV-004)
# Note: https://app.incubrix.com/explore is EXCLUDED as it is not on the verified allowlist.
DEFAULT_APPROVED_DESTINATION_URLS: List[str] = [
    "https://app.incubrix.com/",
    "https://app.incubrix.com",
    "https://www.incubrix.com/",
    "https://www.incubrix.com",
    "https://www.incubrix.com/pricing.html",
    "https://www.incubrix.com/how-it-works.html",
    "https://calendly.com/contact-incubrix/30min?hide_gdpr_banner=1&background_color=0a0e27&text_color=e2e8f0&primary_color=1e6bff"
]

# Prohibited buzzwords and hyperbolic marketing phrases from Strategy Doc 4 Section 2.1
DEFAULT_PROHIBITED_PHRASES: List[str] = [
    # Banned hyperbolic buzzwords
    "game-changer",
    "game changer",
    "revolutionary",
    "skyrocket",
    "unlock your potential",
    "magic",
    "secret sauce",
    "supercharge",
    "unleash",
    "secret hack",
    "miracle",
    "make you viral",
    "guaranteed viral",
    "10x your growth",
    "explode your reach",
    # Deceptive or unverified commercial promises
    "no credit card required",
    "100% money back",
    "100% automated without human",
    "guaranteed return",
    "proven to 10x",
    "upload 1 video, get 10 clips free",
    "act now or get left behind"
]

# Severe misleading commercial claims that trigger immediate FAIL rather than advisory warning
SEVERE_PROHIBITED_PHRASES: Set[str] = {
    "no credit card required",
    "100% money back",
    "100% automated without human",
    "guaranteed return",
    "guaranteed viral",
    "make you viral",
    "upload 1 video, get 10 clips free"
}

# Approved factual brand claims backed by explicit evidence citations (Strategy Doc 4 Section 3.1)
DEFAULT_APPROVED_CLAIMS: List[ApprovedClaim] = [
    ApprovedClaim(
        claim_id="CLAIM_DOMAINS",
        claim_text="IncuBrix operates at incubrix.com, incubrix.ai, and app.incubrix.com.",
        evidence_reference="EV-001, EV-004",
        keywords=["incubrix.com", "incubrix.ai", "app.incubrix.com"]
    ),
    ApprovedClaim(
        claim_id="CLAIM_PRICING_TIERS",
        claim_text="IncuBrix lists 6 public pricing tiers: Free ($0), Starter ($10/mo), Essential ($20/mo), Growth ($50/mo), Scale ($100/mo), and Pro ($250/mo).",
        evidence_reference="EV-003",
        keywords=["starter ($10", "essential ($20", "growth ($50", "scale ($100", "pro ($250"]
    ),
    ApprovedClaim(
        claim_id="CLAIM_FREE_PLAN",
        claim_text="IncuBrix states that it offers a Free plan for exploring the platform, with no free trials for paid plans.",
        evidence_reference="EV-003",
        keywords=["free plan", "exploring the platform", "no free trials"]
    ),
    ApprovedClaim(
        claim_id="CLAIM_CORE_MISSION",
        claim_text="IncuBrix's stated core mission is turning one content into clips, captions, voiceovers, and posts for every platform.",
        evidence_reference="EV-001",
        keywords=["turning one content into clips", "clips, captions, voiceovers"]
    ),
    ApprovedClaim(
        claim_id="CLAIM_LINKEDIN_FOLLOWERS",
        claim_text="IncuBrix has 1,235 followers on LinkedIn as of October 29, 2026.",
        evidence_reference="EV-005",
        keywords=["1,235 followers", "1235 followers"]
    )
]

DEFAULT_APPROVED_MESSAGING_THEMES: List[str] = [
    "Creator Workflow Education / Reducing Multi-Tool Fragmentation",
    "Hook Writing & Short-Video Retention (First-3-Second Attention)",
    "1-to-Many Transformation (Extending Content Lifespans)",
    "Creator Operations & Consistent Publishing (Systems Over Hustle)",
    "Measurement, Attribution & Growth Experiments"
]

DEFAULT_BRAND_VOICE_PRINCIPLES: List[str] = [
    "Direct, practitioner-oriented, evidence-grounded, and professional.",
    "Explain repurposing workflows and operating systems with clear mechanics.",
    "Target average sentence length of 12 to 18 words.",
    "Use active voice and short paragraphs (2-3 sentences max) for mobile feed readability.",
    "Distinguish clearly between tested capabilities, advertised features, and hypotheses."
]

DEFAULT_REQUIRED_DISCLOSURES: Dict[str, str] = {
    "category_2_advertised": "Capabilities advertised on marketing pages but untested in production must use transparent framing (e.g. 'As advertised on IncuBrix public website...').",
    "category_3_hypothesis": "Metric targets and performance estimates must be explicitly framed as hypotheses or targets.",
    "offline_media_preview": "Offline video and carousel renders are text-based preview drafts for editorial review."
}


def get_default_brand_profile(
    approved_destination_urls: Optional[List[str]] = None,
    allow_empty_destinations: bool = False
) -> BrandComplianceProfile:
    """Creates a default BrandComplianceProfile grounded in verified strategy documents.
    
    If approved_destination_urls is explicitly passed as an empty list (allow_empty_destinations=True),
    the profile will contain NO approved destinations, enforcing that any supplied URL is UNAPPROVED.
    """
    if approved_destination_urls is not None:
        dest_urls = list(approved_destination_urls)
    elif allow_empty_destinations:
        dest_urls = []
    else:
        dest_urls = list(DEFAULT_APPROVED_DESTINATION_URLS)

    return BrandComplianceProfile(
        brand_name="IncuBrix",
        approved_product_descriptions=[
            "IncuBrix is a creator operations and content repurposing platform that turns one long-form video or text into platform-native clips, captions, carousels, and scheduler-ready posts across social channels.",
            "IncuBrix provides text transcript-driven editing, vertical short-form video generation, multi-slide carousel creation, and programmatic UTM tracking."
        ],
        approved_messaging_themes=list(DEFAULT_APPROVED_MESSAGING_THEMES),
        brand_voice_principles=list(DEFAULT_BRAND_VOICE_PRINCIPLES),
        prohibited_phrases=list(DEFAULT_PROHIBITED_PHRASES),
        approved_claims=list(DEFAULT_APPROVED_CLAIMS),
        approved_destination_urls=dest_urls,
        required_disclosures=dict(DEFAULT_REQUIRED_DISCLOSURES)
    )


# ==============================================================================
# 2. Destination URL Safeguards & Allowlist Checking
# ==============================================================================

def normalize_destination_url(url: str) -> str:
    """Normalizes a URL for comparison against the allowlist."""
    clean = url.strip()
    if not clean:
        return ""
    parsed = urlsplit(clean)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    # Normalize path: strip trailing slash except for root '/'
    path = parsed.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{scheme}://{netloc}{path}{query}"


def evaluate_destination_url(
    destination_url: Optional[str],
    profile: BrandComplianceProfile
) -> Tuple[DestinationUrlStatusEnum, List[str]]:
    """Evaluates a destination URL against the strict approved-destination allowlist.
    
    Rules:
    - Missing destination URL -> PENDING_DESTINATION_URL (non-blocking advisory).
    - Syntactically invalid URL -> INVALID (blocking error).
    - Empty allowlist -> UNAPPROVED (no URLs permitted).
    - URL in allowlist -> APPROVED.
    - URL not in allowlist -> UNAPPROVED (blocking error).
    """
    findings: List[str] = []
    
    if destination_url is None or not destination_url.strip() or destination_url.strip() == "PENDING_DESTINATION_URL":
        findings.append("No destination URL supplied; tracking link is pending campaign assignment.")
        return DestinationUrlStatusEnum.PENDING_DESTINATION_URL, findings

    clean_url = destination_url.strip()
    
    # 1. Validate URL syntax
    try:
        valid_url = validate_destination_url(clean_url)
    except ValueError as e:
        findings.append(f"Destination URL '{clean_url}' is syntactically invalid: {e}")
        return DestinationUrlStatusEnum.INVALID, findings

    # 2. Check if allowlist is empty (empty allowlist means NO destination is approved)
    if not profile.approved_destination_urls:
        findings.append(
            f"Destination URL '{valid_url}' cannot be approved: The active brand compliance profile "
            "contains zero approved destinations (empty allowlist policy)."
        )
        return DestinationUrlStatusEnum.UNAPPROVED, findings

    # 3. Check against normalized allowlist entries
    norm_target = normalize_destination_url(valid_url)
    normalized_allowlist = {normalize_destination_url(u) for u in profile.approved_destination_urls if u.strip()}

    if norm_target in normalized_allowlist:
        findings.append(f"Destination URL '{valid_url}' is verified on the approved campaign allowlist.")
        return DestinationUrlStatusEnum.APPROVED, findings
    
    # Also check base URL without query parameters if allowlist entry is base URL
    target_base = f"{urlsplit(norm_target).scheme}://{urlsplit(norm_target).netloc}{urlsplit(norm_target).path}"
    if target_base in normalized_allowlist or f"{target_base}/" in normalized_allowlist:
        findings.append(f"Destination URL base '{target_base}' is verified on the approved campaign allowlist.")
        return DestinationUrlStatusEnum.APPROVED, findings

    findings.append(
        f"Destination URL '{valid_url}' is NOT on the approved-destinations allowlist. "
        "Publishing to unverified endpoints is blocked."
    )
    return DestinationUrlStatusEnum.UNAPPROVED, findings


# ==============================================================================
# 3. Media Rights, Path Traversal Protection, and Integrity Safeguards
# ==============================================================================

# Permitted non-media metadata files within a render directory.
# These files are exempt from media-file hashing requirements.
# All other files in a render directory must be explicitly declared in output_files.
PERMITTED_RENDER_METADATA_FILES: Set[str] = {
    "render_manifest.json"
}


def validate_manifest_filename(filename: Any, dir_path: Path) -> Optional[str]:
    """Validates that a manifest filename is a clean relative name strictly within dir_path.
    
    Security Checks (Phase 3.9):
    - Rejects empty, whitespace, or non-string filenames.
    - Rejects absolute paths (Windows drive letters, UNC paths, and POSIX root slashes).
    - Rejects parent directory traversal ('..' components, '../', '..\\').
    - Rejects paths that resolve outside dir_path or resolve to dir_path itself.
    - Inspects symlink destinations to prevent symlink-based directory escapes.
    - Rejects suspicious filenames rather than silently normalizing them.
    
    Returns an error message string if invalid/unsafe, or None if safe.
    """
    if not isinstance(filename, str) or not filename.strip():
        return f"Filename '{filename}' is empty or not a string."

    clean_fn = filename.strip()

    # 1. Reject absolute paths (Windows drive letters, POSIX leading slashes, UNC paths)
    if os.path.isabs(clean_fn) or Path(clean_fn).is_absolute():
        return f"Filename '{clean_fn}' is an absolute path."
    if clean_fn.startswith(("/", "\\")):
        return f"Filename '{clean_fn}' starts with a directory separator or root slash."
    if bool(re.match(r'^[a-zA-Z]:', clean_fn)):
        return f"Filename '{clean_fn}' contains a drive specification."

    # 2. Reject parent directory traversal patterns
    p = Path(clean_fn)
    if ".." in p.parts or "../" in clean_fn or "..\\" in clean_fn or clean_fn.startswith(".."):
        return f"Filename '{clean_fn}' contains parent directory traversal ('..')."

    # 3. Canonical resolution and containment enforcement
    try:
        resolved_dir = dir_path.resolve()
        target = dir_path / clean_fn
        resolved_target = target.resolve()

        # Target must not resolve to the directory itself
        if resolved_target == resolved_dir:
            return f"Filename '{clean_fn}' resolves to the render directory itself."

        # Target must be strictly inside the render directory
        if not resolved_target.is_relative_to(resolved_dir):
            return f"Filename '{clean_fn}' resolves outside render directory to '{resolved_target}'."

        # If target already exists on disk as a symlink, verify its destination
        if target.is_symlink():
            symlink_dest = target.resolve()
            if not symlink_dest.is_relative_to(resolved_dir) or symlink_dest == resolved_dir:
                return f"Symlink '{clean_fn}' resolves outside render directory to '{symlink_dest}'."

    except Exception as e:
        return f"Failed to validate path for filename '{clean_fn}': {e}"

    return None


def evaluate_media_rights(
    draft: DraftCandidate,
    media_rights: Optional[List[MediaRightsRecord]] = None,
    render_dir: Optional[Union[str, Path]] = None
) -> Tuple[RightsStatusEnum, List[str]]:
    """Evaluates copyright, path security, and media-rights documentation for an asset.
    
    Rules:
    - If media_rights records are supplied, evaluates each record:
      - Any RESTRICTED status -> RESTRICTED (blocking failure).
      - Any third-party asset missing permission evidence -> PENDING_VERIFICATION (blocking approval).
      - NOT_APPLICABLE is permitted ONLY for verified local renderer provenance (LOCALLY_GENERATED_KINETIC_TEXT).
      - Third-party or unknown media cannot receive NOT_APPLICABLE.
      - If verified with permission evidence -> VERIFIED.
    - If no external media_rights records are provided:
      - Text-only posts and Twitter threads -> NOT_APPLICABLE (no media attached).
      - Visual/video formats (SHORT_VIDEO, CAROUSEL):
        - Local provenance is verified IF render_dir contains a valid render_manifest.json
          with media_provenance="LOCALLY_GENERATED_KINETIC_TEXT" matching the asset.
        - Without verified internal render manifest provenance, media rights MUST NOT
          default to NOT_APPLICABLE. They evaluate to PENDING_VERIFICATION.
        - Strict Path Traversal Protection: Reject absolute paths, parent directory traversal,
          and symbolic links escaping the render directory.
        - Strict File Consistency: Declared output_files must match file_hashes exactly.
          Any missing declared file, unhashed file, undeclared hash, or unexpected file
          on disk results in PENDING_VERIFICATION.
    
    TRUST BOUNDARY & ARCHITECTURAL LIMITATION (Phase 3.9):
    - SHA-256 verification confirms that files on disk match the hashes recorded in render_manifest.json.
    - This provides file integrity verification against post-render tampering when the manifest is trusted.
    - An unsigned JSON manifest can be replaced or fabricated by an actor with local filesystem write access.
    - Matching file hashes do not provide cryptographic non-repudiation or prove that IncuBrix generated the media.
    - Renderer engine identity and provenance strings are descriptive consistency checks, not cryptographic identity.
    - Secure asymmetric signing with key management infrastructure is documented as future work.
    """
    findings: List[str] = []

    if media_rights:
        has_restricted = False
        has_pending = False
        has_verified = False

        for rec in media_rights:
            if rec.rights_status == RightsStatusEnum.RESTRICTED:
                has_restricted = True
                findings.append(
                    f"Media asset '{rec.media_asset_id}' is RESTRICTED: {rec.notes or 'Usage license restricts publication.'}"
                )
            elif rec.rights_status == RightsStatusEnum.PENDING_VERIFICATION:
                has_pending = True
                findings.append(
                    f"Media asset '{rec.media_asset_id}' rights pending verification: Provider '{rec.source_or_provider}' "
                    "requires documented permission evidence prior to publishing."
                )
            elif rec.rights_status == RightsStatusEnum.VERIFIED:
                if not rec.permission_evidence_reference:
                    has_pending = True
                    findings.append(
                        f"Media asset '{rec.media_asset_id}' claims VERIFIED but lacks permission_evidence_reference. "
                        "Held in PENDING_VERIFICATION."
                    )
                else:
                    has_verified = True
                    findings.append(
                        f"Media asset '{rec.media_asset_id}' verified under evidence reference '{rec.permission_evidence_reference}'."
                    )
            elif rec.rights_status == RightsStatusEnum.NOT_APPLICABLE:
                if rec.source_or_provider.upper() == "LOCALLY_GENERATED_KINETIC_TEXT":
                    findings.append(
                        f"Media asset '{rec.media_asset_id}' verified local programmatic provenance ({rec.license_description})."
                    )
                else:
                    has_pending = True
                    findings.append(
                        f"Media asset '{rec.media_asset_id}' from provider '{rec.source_or_provider}' cannot receive NOT_APPLICABLE: "
                        "NOT_APPLICABLE is strictly reserved for verified internal renderer assets."
                    )

        if has_restricted:
            return RightsStatusEnum.RESTRICTED, findings
        if has_pending:
            return RightsStatusEnum.PENDING_VERIFICATION, findings
        if has_verified:
            return RightsStatusEnum.VERIFIED, findings
        return RightsStatusEnum.NOT_APPLICABLE, findings

    # If format is text-based (no media files involved)
    if draft.content_format in (AssetFormatEnum.TEXT_POST, AssetFormatEnum.THREAD):
        findings.append(f"Content format '{draft.content_format.value}' is text-based; media rights not applicable.")
        return RightsStatusEnum.NOT_APPLICABLE, findings

    # Visual/video formats (SHORT_VIDEO, CAROUSEL): check for explicit render manifest provenance, path safety, and file integrity
    effective_dir = render_dir or getattr(draft, "render_directory", None)
    if effective_dir:
        dir_path = Path(effective_dir).resolve()
        if not dir_path.exists() or not dir_path.is_dir():
            findings.append(
                f"Media Render Directory Missing: Directory '{dir_path}' does not exist on disk. "
                "Rights status is PENDING_VERIFICATION."
            )
            return RightsStatusEnum.PENDING_VERIFICATION, findings

        manifest_path = dir_path / "render_manifest.json"
        if manifest_path.exists():
            try:
                m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest_aid = m_data.get("asset_id")
                provenance = m_data.get("media_provenance")
                renderer_engine = str(m_data.get("renderer_engine", ""))
                file_hashes = m_data.get("file_hashes")
                output_files = m_data.get("output_files")

                # 1. Manifest asset ID must match draft ID
                if manifest_aid != draft.draft_id:
                    findings.append(
                        f"Media Rights Mismatch: Manifest asset ID '{manifest_aid}' does not match draft ID '{draft.draft_id}'. "
                        "Stale or mismatched manifest cannot establish local provenance. Rights status is PENDING_VERIFICATION."
                    )
                    return RightsStatusEnum.PENDING_VERIFICATION, findings

                # 2. Provenance must identify approved local renderer (descriptive provenance check)
                # NOTE: String-based check only. Does not cryptographically authenticate origin.
                if provenance != "LOCALLY_GENERATED_KINETIC_TEXT" or not renderer_engine.startswith("IncuBrix Media Renderer"):
                    findings.append(
                        f"Media Rights Unverified: Manifest provenance '{provenance}' / engine '{renderer_engine}' "
                        "is not recognized as approved internal kinetic typography renderer. Rights status is PENDING_VERIFICATION."
                    )
                    return RightsStatusEnum.PENDING_VERIFICATION, findings

                # 3. Cryptographic file hashes must be present and non-empty (legacy manifests without hashes are rejected)
                if not file_hashes or not isinstance(file_hashes, dict):
                    findings.append(
                        "Media Integrity Unverified: Manifest lacks cryptographic 'file_hashes' mapping. "
                        "Legacy or incomplete manifests without SHA-256 digests cannot establish local provenance. "
                        "Fresh media rendering or explicit media rights verification is required. Rights status is PENDING_VERIFICATION."
                    )
                    return RightsStatusEnum.PENDING_VERIFICATION, findings

                # 4. Output files list and strict declared outputs vs hashed entries consistency
                has_integrity_failure = False
                declared_set: Set[str] = set()
                if output_files is None or not isinstance(output_files, list) or len(output_files) == 0:
                    has_integrity_failure = True
                    findings.append(
                        "Media Integrity Incomplete: Manifest lacks valid 'output_files' declaration. "
                        "Rights status is PENDING_VERIFICATION."
                    )
                    # Fallback to file_hashes keys so subsequent disk and hash checks can still be evaluated
                    declared_set = set(file_hashes.keys())
                else:
                    for item in output_files:
                        if not isinstance(item, str) or not item.strip():
                            has_integrity_failure = True
                            findings.append(
                                f"Media Integrity Incomplete: Output file entry '{item}' is empty or invalid. "
                                "Rights status is PENDING_VERIFICATION."
                            )
                        else:
                            declared_set.add(item.strip())

                hashed_set: Set[str] = set()
                for k in file_hashes.keys():
                    if not isinstance(k, str) or not k.strip():
                        has_integrity_failure = True
                        findings.append(
                            f"Media Integrity Incomplete: Hash mapping entry '{k}' is empty or invalid. "
                            "Rights status is PENDING_VERIFICATION."
                        )
                    else:
                        hashed_set.add(k.strip())

                if output_files is not None and declared_set != hashed_set:
                    has_integrity_failure = True
                    unhashed = declared_set - hashed_set
                    if unhashed:
                        findings.append(
                            f"Media Integrity Incomplete: Manifest output files {sorted(unhashed)} lack SHA-256 hashes in 'file_hashes'. "
                            "Rights status is PENDING_VERIFICATION."
                        )
                    undeclared = hashed_set - declared_set
                    if undeclared:
                        findings.append(
                            f"Media Integrity Inconsistent: Hash entries {sorted(undeclared)} are present in 'file_hashes' but not declared in 'output_files'. "
                            "Rights status is PENDING_VERIFICATION."
                        )

                # 5. Path Traversal & Suspicious Path Validation
                for filename in declared_set.union(hashed_set):
                    err = validate_manifest_filename(filename, dir_path)
                    if err:
                        has_integrity_failure = True
                        findings.append(
                            f"Media Path Traversal Rejected: {err} "
                            "Rights status is PENDING_VERIFICATION."
                        )

                # 6. Unexpected Media-File and Directory Detection
                for disk_entry in dir_path.iterdir():
                    if disk_entry.is_dir():
                        has_integrity_failure = True
                        findings.append(
                            f"Unexpected Directory Detected: Directory '{disk_entry.name}' is present in render directory. "
                            "Render directory must contain only flat declared media artifacts and permitted metadata. "
                            "Rights status is PENDING_VERIFICATION."
                        )
                    elif disk_entry.name not in declared_set and disk_entry.name not in PERMITTED_RENDER_METADATA_FILES:
                        has_integrity_failure = True
                        findings.append(
                            f"Unexpected File Detected: File '{disk_entry.name}' is present in render directory but not declared "
                            "in manifest 'output_files'. Unexpected or unhashed files are prohibited. "
                            "Rights status is PENDING_VERIFICATION."
                        )

                # 7. Verify existence, symlink containment, and SHA-256 cryptographic match for every declared file
                for filename, expected_hash in file_hashes.items():
                    target_file = dir_path / filename
                    if not target_file.exists() or not target_file.is_file():
                        has_integrity_failure = True
                        findings.append(
                            f"Media File Missing: Expected media artifact '{filename}' not found on disk at '{target_file}'. "
                            "Rights status is PENDING_VERIFICATION."
                        )
                        continue

                    # Validate symlink target safety on files present
                    if target_file.is_symlink():
                        try:
                            resolved_symlink = target_file.resolve()
                            if not resolved_symlink.is_relative_to(dir_path) or resolved_symlink == dir_path:
                                has_integrity_failure = True
                                findings.append(
                                    f"Media Symlink Traversal Detected: Symlink '{filename}' resolves outside render directory to '{resolved_symlink}'. "
                                    "Rights status is PENDING_VERIFICATION."
                                )
                                continue
                        except Exception as e:
                            has_integrity_failure = True
                            findings.append(
                                f"Media Symlink Error: Failed to resolve symlink '{filename}': {e}. "
                                "Rights status is PENDING_VERIFICATION."
                            )
                            continue

                    try:
                        actual_hash = compute_file_sha256(target_file)
                        if actual_hash.lower() != str(expected_hash).strip().lower():
                            has_integrity_failure = True
                            findings.append(
                                f"Media Integrity Tampering Detected: Cryptographic hash mismatch for '{filename}'. "
                                f"Expected SHA-256: {str(expected_hash)[:16]}..., actual: {actual_hash[:16]}... "
                                "File has been modified or replaced post-render. Rights status is PENDING_VERIFICATION."
                            )
                    except Exception as e:
                        has_integrity_failure = True
                        findings.append(
                            f"Media Hash Error: Failed to compute SHA-256 for '{filename}': {e}. "
                            "Rights status is PENDING_VERIFICATION."
                        )

                if has_integrity_failure:
                    return RightsStatusEnum.PENDING_VERIFICATION, findings

                # All integrity, path traversal, unexpected file, and provenance checks passed
                findings.append(
                    f"Media Provenance and File Integrity Verified: All {len(file_hashes)} media file(s) matched manifest "
                    "SHA-256 digests with strict directory isolation and verified internal kinetic typography provenance."
                )
                return RightsStatusEnum.NOT_APPLICABLE, findings

            except Exception as e:
                findings.append(
                    f"Media Rights Verification Error: Failed to validate manifest in '{effective_dir}': {e}. "
                    "Rights status is PENDING_VERIFICATION."
                )
                return RightsStatusEnum.PENDING_VERIFICATION, findings

    findings.append(
        f"Media Rights Unverified: Asset format '{draft.content_format.value}' involves visual/video media, "
        "but no trusted internal render manifest or explicit MediaRightsRecord was found. "
        "Cannot infer local provenance from content format alone. Rights status is PENDING_VERIFICATION."
    )
    return RightsStatusEnum.PENDING_VERIFICATION, findings


# ==============================================================================
# 4. Brand Voice and Claim Integrity Evaluation
# ==============================================================================

def evaluate_brand_voice_and_claims(
    draft: DraftCandidate,
    profile: BrandComplianceProfile
) -> Tuple[ComplianceStatusEnum, List[str], List[str]]:
    """Evaluates brand voice, messaging alignment, prohibited phrasing, and factual claims.
    
    Returns:
    - status: ComplianceStatusEnum (PASS, PASS_WITH_WARNINGS, FAIL)
    - voice_findings: List of style and tone findings
    - claim_findings: List of claim and evidence findings
    """
    voice_findings: List[str] = []
    claim_findings: List[str] = []
    has_blocking_failure = False
    has_warning = False

    combined_text = f"{draft.draft_hook} {draft.draft_caption}".lower()

    # 1. Prohibited phrases scan
    for phrase in profile.prohibited_phrases:
        p_lower = phrase.lower().strip()
        if not p_lower:
            continue
        # Use word boundary check where appropriate or substring
        pattern = r"\b" + re.escape(p_lower) + r"\b"
        if re.search(pattern, combined_text, flags=re.IGNORECASE):
            if p_lower in SEVERE_PROHIBITED_PHRASES:
                has_blocking_failure = True
                claim_findings.append(
                    f"Prohibited Deceptive Phrase Detected: Asset contains forbidden wording '{phrase}'. "
                    "Misleading or unverified commercial promises are strictly blocked."
                )
            else:
                has_warning = True
                voice_findings.append(
                    f"Brand Voice Advisory: Asset contains discouraged buzzword '{phrase}'. "
                    "Recommend replacing with direct, practitioner-oriented vocabulary."
                )

    # 2. Readability and sentence structure analysis
    # Split body into sentences and check average length
    sentences = [s.strip() for s in re.split(r"[.!?]+", draft.draft_caption) if len(s.strip()) > 3]
    if sentences:
        total_words = sum(len(s.split()) for s in sentences)
        avg_sentence_len = total_words / len(sentences)
        if avg_sentence_len > 25.0:
            has_warning = True
            voice_findings.append(
                f"Readability Advisory: Average sentence length is {avg_sentence_len:.1f} words "
                "(exceeds recommended target of 12-18 words)."
            )
        else:
            voice_findings.append(
                f"Readability Compliant: Average sentence length is {avg_sentence_len:.1f} words (target: 12-18 words)."
            )

    # 3. Content pillar alignment
    pillar_val = draft.pillar.value if isinstance(draft.pillar, PillarEnum) else str(draft.pillar)
    voice_findings.append(f"Strategic Pillar: Aligned to '{pillar_val}'.")

    # 4. Claim Category Safeguards
    if draft.claim_category == ClaimCategoryEnum.CAT_4_UNSUPPORTED:
        has_blocking_failure = True
        claim_findings.append(
            "Claim Integrity Violation: Draft is classified as CAT_4_UNSUPPORTED. "
            f"Prohibited or unsupported claims cannot be approved. Flags: {'; '.join(draft.warnings) if draft.warnings else 'None'}"
        )
    elif draft.claim_category == ClaimCategoryEnum.SOURCE_ATTRIBUTED_UNVERIFIED:
        claim_findings.append(
            f"Source Provenance: Draft content is attributed to source segment '{draft.source_segment_id}' "
            f"in '{draft.source_document}' (unverified independent factual truth)."
        )
    elif draft.claim_category == ClaimCategoryEnum.CAT_2_ADVERTISED:
        # Check transparent framing requirement
        framing_indicators = ["advertised", "according to", "specifications", "public website"]
        if not any(ind in combined_text for ind in framing_indicators):
            has_warning = True
            claim_findings.append(
                "Claim Framing Advisory: Asset references Category 2 advertised capabilities without "
                "transparent framing (e.g. 'As advertised on IncuBrix public website...')."
            )
        else:
            claim_findings.append("Claim Framing: Category 2 advertised capability uses transparent framing.")

    # 5. Check if draft asserts specific brand facts and match with approved evidence
    for app_claim in profile.approved_claims:
        if any(kw.lower() in combined_text for kw in app_claim.keywords):
            claim_findings.append(
                f"Evidence Citation: Statement aligns with verified fact '{app_claim.claim_id}' "
                f"supported by evidence reference '{app_claim.evidence_reference}'."
            )

    # 6. Preserve draft-level scanner warnings as advisories
    if draft.warnings:
        for w in draft.warnings:
            has_warning = True
            claim_findings.append(f"Scanner Warning Flag: {w}")

    # Determine status
    if has_blocking_failure:
        status = ComplianceStatusEnum.FAIL
    elif has_warning:
        status = ComplianceStatusEnum.PASS_WITH_WARNINGS
    else:
        status = ComplianceStatusEnum.PASS

    return status, voice_findings, claim_findings


# ==============================================================================
# 5. Platform Structural Readiness Evaluation
# ==============================================================================

def evaluate_platform_readiness(
    draft: DraftCandidate,
    render_dir: Optional[Union[str, Path]] = None
) -> Tuple[ComplianceStatusEnum, List[str]]:
    """Evaluates structural platform-specific content readiness.
    
    Distinguishes internal technical schema validation from official platform policy compliance.
    """
    findings: List[str] = [
        "Platform Readiness Notice: Evaluates structural and technical formatting against internal "
        "delivery specifications. This does NOT represent official platform policy clearance or algorithmic ranking guarantees."
    ]
    
    # Leverage existing multi-dimensional quality gate for objective validation
    q_res = evaluate_asset_quality(draft, render_dir=render_dir)

    for chk in q_res.passed_checks:
        findings.append(f"Format Check Passed: {chk}")
    for fail in q_res.failed_checks:
        findings.append(f"Format Failure: {fail}")
    for warn in q_res.warnings:
        findings.append(f"Format Advisory: {warn}")

    # Additional missing publishing/scheduler metadata checks
    if not draft.intended_audience or not draft.intended_audience.strip():
        findings.append("Missing Scheduler Metadata: Intended audience is blank.")
        return ComplianceStatusEnum.FAIL, findings

    if not draft.call_to_action or not draft.call_to_action.strip():
        findings.append("Missing Scheduler Metadata: Call to action is blank.")
        return ComplianceStatusEnum.FAIL, findings

    if q_res.overall_status == QualityGateStatusEnum.FAIL:
        return ComplianceStatusEnum.FAIL, findings
    elif q_res.overall_status == QualityGateStatusEnum.PASS_WITH_WARNINGS:
        return ComplianceStatusEnum.PASS_WITH_WARNINGS, findings
    return ComplianceStatusEnum.PASS, findings


# ==============================================================================
# 6. Unified Brand Compliance Engine
# ==============================================================================

def evaluate_brand_compliance(
    draft: DraftCandidate,
    destination_url: Optional[str] = None,
    media_rights: Optional[List[MediaRightsRecord]] = None,
    render_dir: Optional[Union[str, Path]] = None,
    profile: Optional[BrandComplianceProfile] = None
) -> BrandComplianceResult:
    """Executes full brand compliance, rights safety, and platform readiness evaluation for a draft.
    
    Guarantees:
    - requires_human_review is always True.
    - is_ready_to_publish is always False.
    - Automated checks never approve assets.
    """
    active_profile = profile or get_default_brand_profile()

    # 1. Destination URL check
    dest_status, dest_findings = evaluate_destination_url(destination_url, active_profile)

    # 2. Media Rights check
    rights_status, rights_findings = evaluate_media_rights(draft, media_rights=media_rights, render_dir=render_dir)

    # 3. Brand Voice and Claim checks
    voice_status, voice_findings, claim_findings = evaluate_brand_voice_and_claims(draft, active_profile)

    # 4. Platform Readiness check
    readiness_status, readiness_findings = evaluate_platform_readiness(draft, render_dir=render_dir)

    # Synthesize overall brand compliance status
    # FAIL triggers:
    # - Prohibited claim (CAT_4) or severe misleading phrasing
    # - Unapproved destination URL when a URL is supplied
    # - Invalid destination URL
    # - Restricted media rights
    # - Platform structural failure
    overall_status = ComplianceStatusEnum.PASS

    if (
        voice_status == ComplianceStatusEnum.FAIL
        or dest_status in (DestinationUrlStatusEnum.UNAPPROVED, DestinationUrlStatusEnum.INVALID)
        or rights_status == RightsStatusEnum.RESTRICTED
        or readiness_status == ComplianceStatusEnum.FAIL
    ):
        overall_status = ComplianceStatusEnum.FAIL
    elif (
        voice_status == ComplianceStatusEnum.PASS_WITH_WARNINGS
        or rights_status == RightsStatusEnum.PENDING_VERIFICATION
        or readiness_status == ComplianceStatusEnum.PASS_WITH_WARNINGS
    ):
        overall_status = ComplianceStatusEnum.PASS_WITH_WARNINGS

    return BrandComplianceResult(
        asset_id=draft.draft_id,
        brand_compliance_status=overall_status,
        brand_compliance_findings=voice_findings,
        unsupported_claim_findings=claim_findings,
        destination_url_status=dest_status,
        destination_url=destination_url,
        rights_status=rights_status,
        rights_findings=rights_findings,
        platform_readiness_status=readiness_status,
        platform_readiness_findings=readiness_findings,
        requires_human_review=True,
        is_ready_to_publish=False,
        details={
            "brand_name": active_profile.brand_name,
            "destination_url_findings": dest_findings,
            "sub_statuses": {
                "voice_and_claims": voice_status.value,
                "destination_url": dest_status.value,
                "media_rights": rights_status.value,
                "platform_readiness": readiness_status.value
            }
        }
    )


# ==============================================================================
# 7. Compliance Reporting
# ==============================================================================

def generate_compliance_report(
    results: List[BrandComplianceResult],
    run_id: str = "default_run",
    output_path: Optional[Union[str, Path]] = None
) -> Dict[str, Any]:
    """Compiles a non-developer-friendly, auditable JSON compliance report."""
    total = len(results)
    
    status_counts = {"PASS": 0, "PASS_WITH_WARNINGS": 0, "FAIL": 0, "NOT_ASSESSED": 0}
    dest_counts = {"APPROVED": 0, "UNAPPROVED": 0, "PENDING_DESTINATION_URL": 0, "INVALID": 0}
    rights_counts = {"VERIFIED": 0, "PENDING_VERIFICATION": 0, "RESTRICTED": 0, "NOT_APPLICABLE": 0}
    readiness_counts = {"PASS": 0, "PASS_WITH_WARNINGS": 0, "FAIL": 0}

    unsupported_claim_count = 0
    failure_reasons: List[Dict[str, Any]] = []
    warning_reasons: List[Dict[str, Any]] = []

    for r in results:
        status_counts[r.brand_compliance_status.value] = status_counts.get(r.brand_compliance_status.value, 0) + 1
        dest_counts[r.destination_url_status.value] = dest_counts.get(r.destination_url_status.value, 0) + 1
        rights_counts[r.rights_status.value] = rights_counts.get(r.rights_status.value, 0) + 1
        readiness_counts[r.platform_readiness_status.value] = readiness_counts.get(r.platform_readiness_status.value, 0) + 1

        # Check for claim violations
        has_claim_violation = any("Violation" in f or "CAT_4" in f for f in r.unsupported_claim_findings)
        if has_claim_violation:
            unsupported_claim_count += 1

        if r.brand_compliance_status == ComplianceStatusEnum.FAIL:
            failure_reasons.append({
                "asset_id": r.asset_id,
                "destination_status": r.destination_url_status.value,
                "rights_status": r.rights_status.value,
                "findings": r.brand_compliance_findings + r.unsupported_claim_findings + r.rights_findings + r.platform_readiness_findings
            })
        elif r.brand_compliance_status == ComplianceStatusEnum.PASS_WITH_WARNINGS:
            warning_reasons.append({
                "asset_id": r.asset_id,
                "destination_status": r.destination_url_status.value,
                "rights_status": r.rights_status.value,
                "findings": r.brand_compliance_findings + r.unsupported_claim_findings + r.rights_findings + r.platform_readiness_findings
            })

    report_data: Dict[str, Any] = {
        "report_title": "IncuBrix Brand Compliance, Rights Safety, and Platform Readiness Report",
        "schema_version": "1.0",
        "run_id": run_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "total_assets_evaluated": total,
        "brand_compliance_status_counts": status_counts,
        "destination_url_status_counts": dest_counts,
        "media_rights_status_counts": rights_counts,
        "platform_readiness_status_counts": readiness_counts,
        "unsupported_claim_count": unsupported_claim_count,
        "human_review_required_count": total,
        "ready_to_publish_count": 0,
        "publishing_safety_enforced": True,
        "disclaimer": (
            "Automated compliance evaluation assesses brand voice heuristics, claim categories, "
            "destination allowlists, media rights records, and structural platform formatting. "
            "A PASS evaluation does NOT constitute legal clearance, fact verification, or platform approval. "
            "All assets strictly require human editorial review prior to publication."
        ),
        "failure_reasons": failure_reasons,
        "warning_reasons": warning_reasons,
        "asset_evaluations": [r.model_dump(mode="json") for r in results]
    }

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    return report_data
