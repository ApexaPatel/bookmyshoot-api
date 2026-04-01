from datetime import date, datetime, time
from typing import List, Optional

from bson import ObjectId
from pydantic import BaseModel, Field, validator


class PortfolioGalleryImage(BaseModel):
    url: str = Field(..., min_length=1)
    is_thumbnail: bool = False

    @validator("url")
    def validate_url(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Gallery image URL is required")
        return value


class PortfolioBase(BaseModel):
    event_name: str = Field(..., min_length=1, max_length=120)
    shoot_date: date
    city: str = Field(..., min_length=1, max_length=120)
    destinations: List[str] = Field(default_factory=list)
    days: int = Field(1, ge=1, le=365)
    props: List[str] = Field(default_factory=list)
    thumbnail_url: Optional[str] = Field(None, min_length=1)
    gallery: List[PortfolioGalleryImage] = Field(..., min_items=3, max_items=10)

    @validator("event_name", "city", pre=True)
    def strip_required_strings(cls, value):
        if value is None:
            raise ValueError("Field is required")
        value = str(value).strip()
        if not value:
            raise ValueError("Field is required")
        return value

    @validator("thumbnail_url", pre=True, always=True)
    def normalize_thumbnail_url(cls, value):
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @validator("destinations", "props", pre=True)
    def normalize_string_lists(cls, value):
        if value is None:
            return []
        cleaned = []
        seen = set()
        for item in value:
            normalized = str(item).strip()
            lowered = normalized.lower()
            if normalized and lowered not in seen:
                cleaned.append(normalized)
                seen.add(lowered)
        return cleaned

    @validator("gallery")
    def validate_gallery(cls, value):
        if not (3 <= len(value) <= 10):
            raise ValueError("Gallery must contain between 3 and 10 images")
        return value


class PortfolioCreate(PortfolioBase):
    pass


class PortfolioUpdate(PortfolioBase):
    pass


class PortfolioResponse(BaseModel):
    id: str
    user_id: str
    event_name: str
    shoot_date: date
    city: str
    destinations: List[str]
    days: int
    props: List[str]
    thumbnail_url: str
    gallery: List[PortfolioGalleryImage]
    created_at: datetime
    updated_at: datetime


def serialize_portfolio(doc: dict) -> PortfolioResponse:
    return PortfolioResponse(
        id=str(doc["_id"]),
        user_id=str(doc["user_id"]),
        event_name=doc["event_name"],
        shoot_date=doc["shoot_date"],
        city=doc["city"],
        destinations=doc.get("destinations", []),
        days=doc.get("days", 1),
        props=doc.get("props", []),
        thumbnail_url=doc["thumbnail_url"],
        gallery=doc.get("gallery", []),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def prepare_portfolio_payload(payload: PortfolioBase, user_id: str) -> dict:
    gallery = [image.dict() for image in payload.gallery]
    thumbnail_url = payload.thumbnail_url

    if thumbnail_url:
        matched_thumbnail = False
        for image in gallery:
            is_match = image["url"] == thumbnail_url
            image["is_thumbnail"] = is_match
            matched_thumbnail = matched_thumbnail or is_match
        if not matched_thumbnail and gallery:
            gallery[0]["is_thumbnail"] = True
            thumbnail_url = gallery[0]["url"]
    elif gallery:
        gallery[0]["is_thumbnail"] = True
        thumbnail_url = gallery[0]["url"]

    now = datetime.utcnow()
    return {
        "user_id": ObjectId(user_id),
        "event_name": payload.event_name,
        "shoot_date": datetime.combine(payload.shoot_date, time.min),
        "city": payload.city,
        "destinations": payload.destinations,
        "days": payload.days,
        "props": payload.props,
        "thumbnail_url": thumbnail_url,
        "gallery": gallery,
        "updated_at": now,
    }
