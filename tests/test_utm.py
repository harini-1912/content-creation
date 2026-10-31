"""Unit tests for UTM tracking-link generation module."""

import pytest

from app.core.utm import (
    generate_utm_tracking_url,
    validate_destination_url,
    build_utm_parameters,
    normalize_platform_source,
    normalize_format_medium,
    UTMStatusEnum,
    DEFAULT_CAMPAIGN
)
from app.models.asset import PlatformEnum, AssetFormatEnum


def test_normalize_platform_source():
    assert normalize_platform_source(PlatformEnum.LINKEDIN) == "linkedin"
    assert normalize_platform_source(PlatformEnum.YOUTUBE_SHORTS) == "youtube"
    assert normalize_platform_source("youtube") == "youtube"
    assert normalize_platform_source(PlatformEnum.INSTAGRAM) == "instagram"
    assert normalize_platform_source(PlatformEnum.TWITTER) == "x"
    assert normalize_platform_source("x") == "x"


def test_normalize_format_medium():
    assert normalize_format_medium(AssetFormatEnum.SHORT_VIDEO) == "short_video"
    assert normalize_format_medium(AssetFormatEnum.CAROUSEL) == "carousel"
    assert normalize_format_medium(AssetFormatEnum.TEXT_POST) == "text_post"
    assert normalize_format_medium(AssetFormatEnum.THREAD) == "thread"


def test_validate_destination_url_valid():
    url1 = "https://app.incubrix.com/"
    assert validate_destination_url(url1) == url1

    url2 = "http://localhost:3000/dashboard"
    assert validate_destination_url(url2) == url2


def test_validate_destination_url_invalid_schemes():
    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        validate_destination_url("ftp://files.example.com/doc")

    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        validate_destination_url("mailto:support@incubrix.com")

    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        validate_destination_url("javascript:alert(1)")


def test_validate_destination_url_missing_host():
    with pytest.raises(ValueError, match="missing a valid domain/host"):
        validate_destination_url("https:///only/path")

    with pytest.raises(ValueError, match="Destination URL must not be empty"):
        validate_destination_url("")


def test_generate_utm_valid():
    dest = "https://app.incubrix.com/signup"
    res = generate_utm_tracking_url(
        destination_url=dest,
        platform=PlatformEnum.LINKEDIN,
        content_format=AssetFormatEnum.TEXT_POST,
        campaign="creator_repurpose_2026",
        content_id="draft_linkedin_01"
    )

    assert res.status == UTMStatusEnum.GENERATED
    assert res.is_generated is True
    assert res.original_url == dest
    assert "utm_source=linkedin" in res.tracking_url
    assert "utm_medium=text_post" in res.tracking_url
    assert "utm_campaign=creator_repurpose_2026" in res.tracking_url
    assert "utm_content=draft_linkedin_01" in res.tracking_url
    assert res.parameters["utm_source"] == "linkedin"


def test_generate_utm_preserves_existing_query_params():
    dest = "https://app.incubrix.com/pricing.html?ref=partner&tier=free"
    res = generate_utm_tracking_url(
        destination_url=dest,
        platform=PlatformEnum.INSTAGRAM,
        content_format=AssetFormatEnum.CAROUSEL,
        content_id="draft_ig_01"
    )

    assert res.status == UTMStatusEnum.GENERATED
    assert "ref=partner" in res.tracking_url
    assert "tier=free" in res.tracking_url
    assert "utm_source=instagram" in res.tracking_url
    assert "utm_medium=carousel" in res.tracking_url


def test_generate_utm_preserves_url_fragment():
    dest = "https://app.incubrix.com/docs#frequently-asked-questions"
    res = generate_utm_tracking_url(
        destination_url=dest,
        platform=PlatformEnum.YOUTUBE_SHORTS,
        content_format=AssetFormatEnum.SHORT_VIDEO,
        content_id="draft_shorts_01"
    )

    assert res.status == UTMStatusEnum.GENERATED
    assert res.tracking_url.endswith("#frequently-asked-questions")
    assert "?utm_source=youtube" in res.tracking_url


def test_generate_utm_spaces_and_special_characters():
    dest = "https://app.incubrix.com/landing"
    res = generate_utm_tracking_url(
        destination_url=dest,
        platform="X",
        content_format="thread",
        campaign="creator launch 2026 & growth",
        content_id="asset/part+1 [v2]"
    )

    assert res.status == UTMStatusEnum.GENERATED
    assert "creator+launch+2026+%26+growth" in res.tracking_url
    assert "utm_source=x" in res.tracking_url


def test_generate_utm_missing_destination_url():
    # If destination_url is None or empty, return pending status without fake link
    res_none = generate_utm_tracking_url(
        destination_url=None,
        platform=PlatformEnum.LINKEDIN,
        content_format=AssetFormatEnum.TEXT_POST,
        content_id="draft_01"
    )
    assert res_none.status == UTMStatusEnum.PENDING_DESTINATION_URL
    assert res_none.is_generated is False
    assert res_none.original_url is None
    assert res_none.tracking_url is None
    assert res_none.parameters["utm_source"] == "linkedin"

    res_empty = generate_utm_tracking_url(
        destination_url="   ",
        platform=PlatformEnum.LINKEDIN,
        content_format=AssetFormatEnum.TEXT_POST,
        content_id="draft_01"
    )
    assert res_empty.status == UTMStatusEnum.PENDING_DESTINATION_URL
    assert res_empty.tracking_url is None


def test_generate_utm_invalid_url():
    res = generate_utm_tracking_url(
        destination_url="not_a_valid_url",
        platform=PlatformEnum.LINKEDIN,
        content_format=AssetFormatEnum.TEXT_POST,
        content_id="draft_01"
    )
    assert res.status == UTMStatusEnum.INVALID_URL
    assert res.tracking_url is None
    assert "Unsupported URL scheme" in res.error_message


def test_generate_utm_deterministic():
    dest = "https://app.incubrix.com/"
    res1 = generate_utm_tracking_url(dest, PlatformEnum.LINKEDIN, AssetFormatEnum.TEXT_POST, content_id="draft_01")
    res2 = generate_utm_tracking_url(dest, PlatformEnum.LINKEDIN, AssetFormatEnum.TEXT_POST, content_id="draft_01")
    assert res1.tracking_url == res2.tracking_url

