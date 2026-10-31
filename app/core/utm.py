"""UTM tracking-link generation and parameter management module.

Constructs deterministic UTM tracking parameters for social distribution assets,
preserves existing query strings and URL fragments, and ensures zero fabrication
of destination endpoints.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Union
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from app.models.asset import PlatformEnum, AssetFormatEnum

# Standard mapping of platforms to utm_source values
PLATFORM_SOURCE_MAP: Dict[str, str] = {
    "linkedin": "linkedin",
    "youtube_shorts": "youtube",
    "youtube": "youtube",
    "instagram": "instagram",
    "twitter": "x",
    "x": "x",
}

# Standard mapping of content formats to utm_medium values
FORMAT_MEDIUM_MAP: Dict[str, str] = {
    "short_video": "short_video",
    "carousel": "carousel",
    "text_post": "text_post",
    "thread": "thread",
}

DEFAULT_CAMPAIGN = "creator_repurpose_2026"
SUPPORTED_SCHEMES = {"http", "https"}


class UTMStatusEnum(str, Enum):
    """Status of UTM link generation."""
    GENERATED = "GENERATED"
    PENDING_DESTINATION_URL = "PENDING_DESTINATION_URL"
    INVALID_URL = "INVALID_URL"


@dataclass(frozen=True)
class UTMTrackingResult:
    """Encapsulates the result of UTM tracking-link generation."""
    status: UTMStatusEnum
    original_url: Optional[str]
    tracking_url: Optional[str]
    parameters: Optional[Dict[str, str]]
    error_message: Optional[str] = None

    @property
    def is_generated(self) -> bool:
        return self.status == UTMStatusEnum.GENERATED


def normalize_platform_source(platform: Union[PlatformEnum, str]) -> str:
    """Normalizes platform to standard utm_source string."""
    raw = platform.value if isinstance(platform, PlatformEnum) else str(platform)
    cleaned = raw.strip().lower()
    return PLATFORM_SOURCE_MAP.get(cleaned, cleaned)


def normalize_format_medium(content_format: Union[AssetFormatEnum, str]) -> str:
    """Normalizes format to standard utm_medium string."""
    raw = content_format.value if isinstance(content_format, AssetFormatEnum) else str(content_format)
    cleaned = raw.strip().lower()
    return FORMAT_MEDIUM_MAP.get(cleaned, cleaned)


def validate_destination_url(url: str) -> str:
    """Validates that destination URL is well-formed with supported scheme and valid host.

    Raises ValueError on malformed or unsupported URLs.
    Never accepts javascript:, ftp:, mailto:, or schemes other than http/https.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError("Destination URL must not be empty.")

    cleaned = url.strip()
    try:
        parsed = urlsplit(cleaned)
    except Exception as e:
        raise ValueError(f"Malformed URL: {e}")

    if parsed.scheme.lower() not in SUPPORTED_SCHEMES:
        raise ValueError(
            f"Unsupported URL scheme '{parsed.scheme}'. Only http:// and https:// URLs are supported."
        )

    if not parsed.netloc or not parsed.netloc.strip():
        raise ValueError(f"URL is missing a valid domain/host: '{cleaned}'")

    return cleaned


def build_utm_parameters(
    platform: Union[PlatformEnum, str],
    content_format: Union[AssetFormatEnum, str],
    campaign: str = DEFAULT_CAMPAIGN,
    content_id: str = ""
) -> Dict[str, str]:
    """Generates standard UTM query parameters dictionary deterministically."""
    source = normalize_platform_source(platform)
    medium = normalize_format_medium(content_format)
    clean_campaign = campaign.strip() if campaign and campaign.strip() else DEFAULT_CAMPAIGN
    clean_content = content_id.strip() if content_id and content_id.strip() else "asset_generic"

    return {
        "utm_source": source,
        "utm_medium": medium,
        "utm_campaign": clean_campaign,
        "utm_content": clean_content
    }


def generate_utm_tracking_url(
    destination_url: Optional[str],
    platform: Union[PlatformEnum, str],
    content_format: Union[AssetFormatEnum, str],
    campaign: str = DEFAULT_CAMPAIGN,
    content_id: str = ""
) -> UTMTrackingResult:
    """Builds a deterministic UTM tracking URL from a destination URL and asset metadata.

    Preserves existing query parameters and fragments.
    If no destination URL is provided, returns PENDING_DESTINATION_URL without fabricating a link.
    """
    params = build_utm_parameters(
        platform=platform,
        content_format=content_format,
        campaign=campaign,
        content_id=content_id
    )

    if destination_url is None or not destination_url.strip():
        return UTMTrackingResult(
            status=UTMStatusEnum.PENDING_DESTINATION_URL,
            original_url=None,
            tracking_url=None,
            parameters=params,
            error_message="Tracking link pending: destination URL was not supplied."
        )

    try:
        valid_url = validate_destination_url(destination_url)
    except ValueError as e:
        return UTMTrackingResult(
            status=UTMStatusEnum.INVALID_URL,
            original_url=destination_url,
            tracking_url=None,
            parameters=params,
            error_message=str(e)
        )

    parsed = urlsplit(valid_url)
    existing_queries = parse_qsl(parsed.query, keep_blank_values=True)
    query_dict = dict(existing_queries)
    # Merge UTM parameters (standard UTMs will take precedence over conflicting duplicate params)
    query_dict.update(params)

    new_query = urlencode(query_dict)
    tracking_url = urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        new_query,
        parsed.fragment
    ))

    return UTMTrackingResult(
        status=UTMStatusEnum.GENERATED,
        original_url=valid_url,
        tracking_url=tracking_url,
        parameters=params,
        error_message=None
    )

