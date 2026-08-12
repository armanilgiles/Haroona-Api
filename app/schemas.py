from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, HttpUrl, Field, field_validator, model_validator

from app.media.audio import (
    MAX_VOICE_RECORDING_DURATION_SECONDS,
    MAX_VOICE_RECORDING_FILE_SIZE_BYTES,
    normalize_audio_mime_type,
)


class UserMeOut(BaseModel):
    id: str
    email: str
    name: str | None = None
    avatar: HttpUrl | None = None
    welcome_seen: bool

    class Config:
        from_attributes = True


class CountryOut(BaseModel):
    id: int
    code: str
    name: str

    class Config:
        from_attributes = True


class BrandCountry(BaseModel):
    code: str
    name: str

    class Config:
        from_attributes = True


class BrandOut(BaseModel):
    id: int
    name: str
    country: BrandCountry
    logo_url: str | None = Field(default=None, alias="logoUrl")

    class Config:
        from_attributes = True
        allow_population_by_field_name = True


class BrandMini(BaseModel):
    id: int
    name: str
    logo_url: str | None = Field(default=None, alias="logoUrl")

    class Config:
        from_attributes = True
        allow_population_by_field_name = True


class BrandLogoIn(BaseModel):
    logo_url: str | None = Field(default=None, alias="logoUrl")

    class Config:
        allow_population_by_field_name = True


class ImageAssetOut(BaseModel):
    url: str
    alt: str
    width: int | None = None
    height: int | None = None


class ProductCityScoreComponentOut(BaseModel):
    key: str
    label: str
    score: float
    maxScore: float
    reasons: list[str] = Field(default_factory=list)


class ProductCardOut(BaseModel):
    productId: str
    productName: str
    advertiserId: str | None = None
    brandName: str | None = None
    price: str | None = None
    currency: str | None = None
    affiliateUrl: str
    merchantUrl: str | None = None
    isAffiliate: bool | None = None
    productImage: ImageAssetOut | None = None
    originalProductImage: ImageAssetOut | None = None
    logoImage: ImageAssetOut | None = None


    id: int | None = None
    name: str | None = None
    brand: BrandMini | None = None
    imageUrl: str | None = None
    imageAlt: str | None = None


class ProductCityAnalysisOut(BaseModel):
    citySlug: str
    cityName: str
    score: int | None = None
    confidence: int | None = None
    matchLabel: str
    matchType: str | None = None
    rank: int
    explanation: str | None = None
    scoreComponents: list[ProductCityScoreComponentOut] = Field(default_factory=list)


class ProductDetailOut(BaseModel):
    productId: str
    dbProductId: int
    productName: str
    brandName: str | None = None
    price: str | None = None
    originalPrice: str | None = None
    currency: str
    shippingText: str | None = None
    productImage: ImageAssetOut | None = None
    originalProductImage: ImageAssetOut | None = None
    additionalImages: list[ImageAssetOut] = Field(default_factory=list)
    logoImage: ImageAssetOut | None = None
    description: str | None = None
    details: list[str] = Field(default_factory=list)
    category: str | None = None
    style: str | None = None
    vibe: str | None = None
    styleTags: list[str] = Field(default_factory=list)
    discoveryLabel: str | None = None
    cityConnectionType: str | None = None
    cityConnectionLocation: str | None = None
    cityConnectionNote: str | None = None
    citySlug: str | None = None
    cityName: str | None = None
    cityAnalysis: list[ProductCityAnalysisOut] = Field(default_factory=list)
    whyItFits: str | None = None
    affiliateUrl: str | None = None
    merchantUrl: str | None = None
    isAffiliate: bool | None = None
    merchantDestinationAvailable: bool = False
    availabilityStatus: str
    isAvailable: bool
    isSaved: bool | None = None


class ProductOut(BaseModel):
    id: int
    name: str
    price: Decimal | None
    currency: str
    affiliate_url: HttpUrl
    source: str
    brand: BrandMini

    class Config:
        from_attributes = True


class CityOut(BaseModel):
    id: int
    slug: str
    name: str
    countryCode: str
    countryName: str
    latitude: float
    longitude: float
    markerColor: str | None = None
    imageUrl: str | None = None
    followers: int


class FeedProductOut(BaseModel):
    productId: str
    productName: str
    advertiserId: str | None = None
    brandName: str | None = None
    price: str | None = None
    currency: str | None = None
    affiliateUrl: str | None = None
    merchantUrl: str | None = None
    isAffiliate: bool | None = None
    productImage: ImageAssetOut | None = None
    originalProductImage: ImageAssetOut | None = None
    logoImage: ImageAssetOut | None = None

    videoUrl: str | None = None

    cityConnectionType: str | None = None
    cityConnectionLocation: str | None = None
    cityConnectionNote: str | None = None

    citySlug: str | None = None
    cityName: str | None = None
    category: str | None = None
    style: str | None = None
    vibe: str | None = None
    isBestSeller: bool | None = None

class FeedResponse(BaseModel):
    items: list[FeedProductOut]
    total: int
    selectedCity: str | None = None
    selectedCities: list[str] = Field(default_factory=list)
    selectedCategories: list[str] = Field(default_factory=list)
    mode: str
    limit: int
    offset: int
    nextOffset: int | None = None
    hasMore: bool = False


class FeedCategoryGroupOut(BaseModel):
    key: str
    label: str
    values: list[str] = Field(default_factory=list)
    count: int = 0
    isAvailable: bool = False


class FeedFiltersOut(BaseModel):
    categories: list[str]
    categoryGroups: list[FeedCategoryGroupOut] = Field(default_factory=list)
    styles: list[str]
    vibes: list[str]
    cityConnectionTypes: list[str] = Field(default_factory=list)


class SearchCityOut(BaseModel):
    id: int
    slug: str
    name: str
    countryCode: str
    countryName: str


class SearchBrandOut(BaseModel):
    id: int
    name: str
    logoUrl: str | None = None


class SearchFacetOut(BaseModel):
    value: str
    label: str
    kind: str


class SearchProductOut(BaseModel):
    productId: str
    dbProductId: int
    productName: str
    brandName: str
    category: str | None = None
    style: str | None = None
    vibe: str | None = None
    citySlug: str
    cityName: str


class SearchHasMoreOut(BaseModel):
    cities: bool = False
    categories: bool = False
    brands: bool = False
    styles: bool = False
    products: bool = False


class SearchResponse(BaseModel):
    query: str
    minimumQueryLength: int
    cities: list[SearchCityOut] = Field(default_factory=list)
    categories: list[SearchFacetOut] = Field(default_factory=list)
    brands: list[SearchBrandOut] = Field(default_factory=list)
    styles: list[SearchFacetOut] = Field(default_factory=list)
    products: list[SearchProductOut] = Field(default_factory=list)
    hasMore: SearchHasMoreOut = Field(default_factory=SearchHasMoreOut)


class AnalyticsEventCreate(BaseModel):
    eventName: str = Field(..., min_length=1, max_length=80)

    anonymousId: str | None = Field(default=None, max_length=120)
    sessionId: str | None = Field(default=None, max_length=120)

    productId: str | None = Field(default=None, max_length=200)
    dbProductId: int | None = None
    citySlug: str | None = Field(default=None, max_length=80)
    cityName: str | None = Field(default=None, max_length=120)

    path: str | None = Field(default=None, max_length=1000)
    referrer: str | None = Field(default=None, max_length=1000)
    properties: dict[str, Any] = Field(default_factory=dict)


class AnalyticsEventOut(BaseModel):
    ok: bool = True
    id: int


VoiceReactionExperienceType = Literal["first_impression", "wore_it"]
VoiceReactionComplimentResponse = Literal["yes", "no", "not_sure"]
VoiceReactionTag = Literal[
    "general",
    "would_compliment",
    "would_wear",
    "great_fit",
    "great_city_fit",
    "got_compliments",
    "loved_fit",
    "would_wear_again",
]


class VoiceReactionCreatorOut(BaseModel):
    id: str
    name: str | None = None
    avatar: str | None = None


class VoiceReactionOut(BaseModel):
    id: int
    productId: int
    reactionTag: VoiceReactionTag
    experienceType: VoiceReactionExperienceType | None = None
    complimentResponse: VoiceReactionComplimentResponse | None = None
    cityId: int | None = None
    citySlug: str | None = None
    cityName: str | None = None
    creator: VoiceReactionCreatorOut | None = None
    mimeType: str
    fileSizeBytes: int
    durationMs: int
    createdAt: datetime


class VoiceReactionListOut(BaseModel):
    items: list[VoiceReactionOut]
    limit: int
    offset: int
    nextOffset: int | None = None
    hasMore: bool = False


class VoiceReactionCapabilitiesOut(BaseModel):
    allowedMimeTypes: list[str]
    maxDurationMs: int
    maxFileSizeBytes: int


class VoiceReactionUploadInitIn(BaseModel):
    experienceType: VoiceReactionExperienceType
    complimentResponse: VoiceReactionComplimentResponse | None = None
    experienceConfirmed: bool = False
    cityId: int | None = Field(default=None, gt=0)
    mimeType: str
    fileSizeBytes: int = Field(
        ...,
        gt=0,
        le=MAX_VOICE_RECORDING_FILE_SIZE_BYTES,
    )
    durationMs: int = Field(
        ...,
        gt=0,
        le=MAX_VOICE_RECORDING_DURATION_SECONDS * 1000,
    )

    @field_validator("mimeType")
    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        return normalize_audio_mime_type(value)

    @model_validator(mode="after")
    def validate_experience_details(self):
        if (
            self.experienceType == "wore_it"
            and self.complimentResponse == "not_sure"
        ):
            raise ValueError(
                "not_sure is only valid for a first-impression compliment response"
            )
        if self.experienceType == "wore_it" and not self.experienceConfirmed:
            raise ValueError(
                "worn-experience reactions require actual-experience confirmation"
            )
        return self


class SignedMediaUploadOut(BaseModel):
    url: str
    method: Literal["PUT"]
    headers: dict[str, str]
    expiresInSeconds: int


class VoiceReactionUploadInitOut(BaseModel):
    reactionId: int
    upload: SignedMediaUploadOut


class VoiceReactionUploadCompleteOut(BaseModel):
    reaction: VoiceReactionOut


class VoiceReactionPlaybackOut(BaseModel):
    url: str
    expiresInSeconds: int


VoiceReactionReportReason = Literal[
    "harassment",
    "hate",
    "sexual",
    "spam",
    "privacy",
    "off_topic",
    "other",
]


class VoiceReactionReportIn(BaseModel):
    reason: VoiceReactionReportReason
    details: str | None = Field(default=None, max_length=500)

    @field_validator("details")
    @classmethod
    def normalize_details(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None


class VoiceReactionReportOut(BaseModel):
    id: int
    reactionId: int
    reason: VoiceReactionReportReason
    status: Literal["open", "resolved", "dismissed"]
    createdAt: datetime


class VoiceReactionModerationReportOut(BaseModel):
    id: int
    reason: VoiceReactionReportReason
    details: str | None = None
    status: Literal["open", "resolved", "dismissed"]
    reporterName: str | None = None
    createdAt: datetime


class VoiceReactionModerationItemOut(BaseModel):
    reaction: VoiceReactionOut
    productName: str
    reactionStatus: Literal["pending", "published", "hidden", "deleted"]
    openReportCount: int
    reports: list[VoiceReactionModerationReportOut]


class VoiceReactionModerationListOut(BaseModel):
    items: list[VoiceReactionModerationItemOut]
    limit: int
    offset: int
    nextOffset: int | None = None
    hasMore: bool = False


class VoiceReactionModerationIn(BaseModel):
    action: Literal["hide", "restore", "dismiss_reports"]
