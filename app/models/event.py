from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, EmailStr, validator, HttpUrl
from bson import ObjectId
from .objectid import PyObjectId

class EventType(str, Enum):
    WEDDING = "wedding"
    PRE_WEDDING = "pre_wedding"
    BIRTHDAY = "birthday"
    CORPORATE = "corporate"
    INAUGURATION = "inauguration"
    PROMOTION = "promotion"
    INFLUENCER = "influencer"
    OTHER = "other"

class ComboType(str, Enum):
    PHOTO_ONLY = "photo_only"
    VIDEO_ONLY = "video_only"
    PHOTO_PLUS_VIDEO = "photo_plus_video"
    PHOTO_PLUS_DRONE = "photo_plus_drone"
    ALL_SERVICES = "all_services"

class Location(BaseModel):
    city: str
    sub_location: str
    coordinates: Optional[tuple[float, float]] = None  # [longitude, latitude] for GeoJSON

class PricingTier(BaseModel):
    event_type: EventType
    combo_type: ComboType
    price_per_hour: float
    min_hours: int = 1
    max_hours: Optional[int] = None
    description: Optional[str] = None

class AvailabilitySlot(BaseModel):
    start_time: datetime
    end_time: datetime
    is_available: bool = True
    booking_id: Optional[str] = None
    
    @validator('booking_id')
    def validate_booking_id(cls, v):
        if v is not None and not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId format for booking_id")
        return v

class PortfolioImage(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    url: str
    caption: Optional[str] = None
    event_type: EventType
    is_featured: bool = False
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {ObjectId: str}
        allow_population_by_field_name = True

class ReviewBase(BaseModel):
    photographer_id: str
    customer_id: str
    booking_id: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    media_urls: List[HttpUrl] = []

    @validator('photographer_id', 'customer_id', 'booking_id')
    def validate_object_ids(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError(f"Invalid ObjectId: {v}")
        return v

class ReviewCreate(ReviewBase):
    pass

class ReviewUpdate(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5)
    comment: Optional[str] = None
    media_urls: Optional[List[HttpUrl]] = None

class Review(ReviewBase):
    id: str = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {ObjectId: str}
        allow_population_by_field_name = True
        json_schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439011",
                "photographer_id": "507f1f77bcf86cd799439012",
                "customer_id": "507f1f77bcf86cd799439013",
                "booking_id": "507f1f77bcf86cd799439014",
                "rating": 5,
                "comment": "Great photographer!",
                "media_urls": [],
                "created_at": "2023-01-01T00:00:00",
                "updated_at": "2023-01-01T00:00:00"
            }
        }


class ReviewCreate(BaseModel):
    photographer_id: str
    booking_id: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    media_urls: List[str] = []

    @validator('photographer_id', 'booking_id')
    def validate_object_ids(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId format")
        return v


class ReviewUpdate(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5)
    comment: Optional[str] = None
    media_urls: Optional[List[str]] = None

class BookingStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

class BookingBase(BaseModel):
    event_type: EventType
    combo_type: ComboType
    location: Location
    start_time: datetime
    end_time: datetime
    total_hours: float
    total_amount: float
    special_requests: Optional[str] = None

class BookingCreate(BookingBase):
    pass

class BookingUpdate(BaseModel):
    status: Optional[BookingStatus] = None
    special_requests: Optional[str] = None
    cancellation_reason: Optional[str] = None

class Booking(BookingBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    customer_id: PyObjectId
    photographer_id: PyObjectId
    event_type: EventType
    combo_type: ComboType
    location: Location
    start_time: datetime
    end_time: datetime
    total_hours: float
    total_amount: float
    status: BookingStatus = BookingStatus.PENDING
    special_requests: Optional[str] = None
    cancellation_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('end_time')
    def validate_end_time(cls, v, values):
        if 'start_time' in values and v <= values['start_time']:
            raise ValueError('end_time must be after start_time')
        return v

    class Config:
        json_encoders = {ObjectId: str}
        populate_by_name = True

class PhotographerProfileBase(BaseModel):
    bio: Optional[str] = None
    experience_years: int = 0
    is_available: bool = True
    pricing_tiers: List[PricingTier] = []
    portfolio: List[PortfolioImage] = []
    availability: List[AvailabilitySlot] = []
    services_offered: List[EventType] = []
    equipment: List[str] = []
    social_links: dict = {}

class PhotographerProfileCreate(PhotographerProfileBase):
    pass

class PhotographerProfileUpdate(PhotographerProfileBase):
    pass

class PhotographerProfile(PhotographerProfileBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    user_id: PyObjectId
    bio: Optional[str] = None
    experience_years: int = 0
    is_verified: bool = False
    is_available: bool = True
    pricing_tiers: List[PricingTier] = []
    portfolio: List[PortfolioImage] = []
    availability: List[AvailabilitySlot] = []
    services_offered: List[EventType] = []
    equipment: List[str] = []
    social_links: dict = {}
    rating_avg: float = 0.0
    total_reviews: int = 0
    documents: List[dict] = []  # For PAN/Aadhaar/Work Certificates
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {ObjectId: str}
        populate_by_name = True
        schema_extra = {
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "bio": "Professional photographer with 5+ years of experience",
                "experience_years": 5,
                "is_verified": True,
                "is_available": True,
                "services_offered": ["wedding", "pre_wedding"],
                "equipment": ["Canon EOS R5", "DJI Mavic Air 2"],
                "rating_avg": 4.8,
                "total_reviews": 42
            }
        }

class CustomerProfile(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    user_id: PyObjectId
    address: Optional[dict] = None
    preferences: dict = {}
    favorite_photographers: List[PyObjectId] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {ObjectId: str}
        populate_by_name = True

class Notification(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    user_id: PyObjectId
    title: str
    message: str
    is_read: bool = False
    type: str  # booking_update, system, promotion, etc.
    related_entity_type: str  # booking, review, etc.
    related_entity_id: PyObjectId
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {ObjectId: str}
        populate_by_name = True
