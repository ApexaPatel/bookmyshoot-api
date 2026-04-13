from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field, validator, HttpUrl, Extra
from enum import Enum
from bson import ObjectId

# Import only the enums to avoid circular imports
from .event import EventType

class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    STAFF = "staff"
    CUSTOMER = "customer"
    PHOTOGRAPHER = "photographer"


class PhotographerPlan(str, Enum):
    FREE = "free"
    PRO = "pro"
    PREMIUM = "premium"

class OrganizationInline(BaseModel):
    """Inline organization for signup when is_part_of_organization is True."""
    name: str = Field(..., min_length=1, max_length=200)
    location: Optional[str] = Field(None, max_length=200)
    contact_number: Optional[str] = Field(None, max_length=20)


class UserBase(BaseModel):
    email: EmailStr = Field(..., description="User's email address, must be unique")
    full_name: str = Field(..., min_length=2, max_length=100, description="User's full name")
    phone: str = Field(..., min_length=10, max_length=15, 
                      regex=r'^\+?[1-9]\d{1,14}$', 
                      description="User's phone number in E.164 format")
    bio: Optional[str] = Field(None, max_length=500, description="Short photographer bio")
    profile_picture: Optional[HttpUrl] = Field(None, description="URL to user's profile picture (avatar)")
    cover_image: Optional[HttpUrl] = Field(None, description="URL to photographer's cover/banner image")
    is_active: bool = Field(True, description="Whether the user account is active")
    is_verified: bool = Field(False, description="Whether the user's email is verified")
    role: UserRole = Field(UserRole.CUSTOMER, description="User's role in the system")
    photographer_plan: PhotographerPlan = Field(PhotographerPlan.FREE, description="Photographer subscription plan")
    plan_started_at: Optional[datetime] = Field(None, description="Start date for paid photographer plans")
    plan_expires_at: Optional[datetime] = Field(None, description="Expiry date for paid photographer plans")
    is_member: bool = Field(False, description="Whether user has active marketplace membership")
    membership_start: Optional[datetime] = Field(None, description="Membership start date")
    membership_expiry: Optional[datetime] = Field(None, description="Membership expiry date")
    is_part_of_organization: bool = Field(False, description="True if photographer belongs to an organization")
    organization_id: Optional[str] = Field(None, description="Reference to Organization _id")
    preferences: Dict[str, Any] = Field(default_factory=dict, 
                                      description="User preferences and settings")
    last_login: Optional[datetime] = Field(None, description="Last login timestamp")
    created_at: datetime = Field(default_factory=datetime.utcnow, 
                               description="Account creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, 
                               description="Last update timestamp")

class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=100, 
                         description="Password must be at least 8 characters long")
    organization: Optional[OrganizationInline] = Field(
        None, description="Organization details when is_part_of_organization is True (photographers only)"
    )

    @validator('password')
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one number')
        return v

    @validator('organization')
    def validate_organization(cls, v, values):
        if values.get('is_part_of_organization') is True:
            if values.get('role') != UserRole.PHOTOGRAPHER:
                raise ValueError('Only photographers can be part of an organization')
            if not v:
                raise ValueError('Organization details are required when is_part_of_organization is True')
            if not (v.name and v.name.strip()):
                raise ValueError('Organization name is required')
        elif v:
            return None
        return v

class ProfileImageUpdate(BaseModel):
    """Body for updating only the profile image URL (e.g. from Cloudinary)."""
    profile_picture: str = Field(..., min_length=1, description="Public URL of the profile image (e.g. Cloudinary secure URL)")

    class Config:
        schema_extra = {
            "example": {"profile_picture": "https://res.cloudinary.com/demo/image/upload/sample.jpg"}
        }


class CoverImageUpdate(BaseModel):
    """Body for updating only the cover image URL (e.g. from Cloudinary). Photographers only."""
    cover_image: str = Field(..., min_length=1, description="Public URL of the cover image (e.g. Cloudinary secure URL)")

    class Config:
        schema_extra = {
            "example": {"cover_image": "https://res.cloudinary.com/demo/image/upload/cover.jpg"}
        }


class BioUpdate(BaseModel):
    """Body for updating only the user bio. Photographers only."""
    bio: str = Field(..., max_length=500, description="Short photographer bio (max 500 characters)")

    @validator("bio")
    def validate_bio(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Bio cannot be empty")
        if len(value) > 500:
            raise ValueError("Bio must be 500 characters or fewer")
        return value

    class Config:
        schema_extra = {
            "example": {"bio": "Wedding and destination photographer with a cinematic, story-first style."}
        }


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = Field(None, description="New email address")
    full_name: Optional[str] = Field(None, min_length=2, max_length=100, 
                                   description="Updated full name")
    phone: Optional[str] = Field(None, min_length=10, max_length=15,
                                regex=r'^\+?[1-9]\d{1,14}$',
                                description="Updated phone number")
    bio: Optional[str] = Field(None, max_length=500, description="Updated bio")
    profile_picture: Optional[HttpUrl] = Field(None, description="URL to updated profile picture")
    cover_image: Optional[HttpUrl] = Field(None, description="URL to updated cover image")
    is_active: Optional[bool] = Field(None, description="Account active status")
    preferences: Optional[Dict[str, Any]] = Field(None, description="Updated preferences")
    password: Optional[str] = Field(None, min_length=8, max_length=100,
                                  description="New password (if changing)")
    
    class Config:
        schema_extra = {
            "example": {
                "full_name": "Updated Name",
                "phone": "+1234567890",
                "profile_picture": "https://example.com/profile.jpg",
                "is_active": True
            }
        }

class UserInDB(UserBase):
    id: str = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    hashed_password: str = Field(..., exclude=True)
    
    class Config:
        allow_population_by_field_name = True
        extra = Extra.ignore
        json_encoders = {ObjectId: str}
        schema_extra = {
            "example": {
                "email": "user@example.com",
                "full_name": "John Doe",
                "phone": "+1234567890",
                "role": "customer",
                "is_active": True,
                "is_verified": False
            }
        }

class UserResponse(UserBase):
    """User model for API responses (excludes sensitive data)"""
    id: str = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    
    class Config:
        allow_population_by_field_name = True
        json_encoders = {ObjectId: str}
        orm_mode = True
        schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439011",
                "email": "user@example.com",
                "full_name": "John Doe",
                "phone": "+1234567890",
                "profile_picture": "https://example.com/profile.jpg",
                "cover_image": "https://example.com/cover.jpg",
                "role": "customer",
                "is_active": True,
                "is_verified": False,
                "preferences": {},
                "last_login": "2023-01-01T12:00:00",
                "created_at": "2023-01-01T00:00:00",
                "updated_at": "2023-01-01T00:00:00"
            }
        }

class User(UserBase):
    """User model with all fields including sensitive data"""
    id: str = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    
    class Config:
        json_encoders = {ObjectId: str}
        allow_population_by_field_name = True
        schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439011",
                "email": "user@example.com",
                "full_name": "John Doe",
                "phone": "+1234567890",
                "role": "customer",
                "is_active": True,
                "is_verified": True,
                "created_at": "2023-01-01T00:00:00",
                "updated_at": "2023-01-01T00:00:00"
            }
        }

class Token(BaseModel):
    """Token response model"""
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field("bearer", description="Token type")
    expires_in: int = Field(3600, description="Token expiration time in seconds")
    refresh_token: Optional[str] = Field(None, description="Refresh token for getting new access tokens")
    user: Optional[UserResponse] = Field(None, description="User information")
    
    class Config:
        schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 3600,
                "refresh_token": "def50200e5c8d3b8f1e2a3b4c5d6e7f8..."
            }
        }

class TokenData(BaseModel):
    sub: Optional[str] = Field(None, description="Subject (user id)")
    email: Optional[str] = Field(None, description="User's email")
    role: Optional[UserRole] = Field(None, description="User's role")
    exp: Optional[int] = Field(None, description="Expiration timestamp")
    
    class Config:
        schema_extra = {
            "example": {
                "sub": "507f1f77bcf86cd799439011",
                "email": "user@example.com",
                "role": "customer",
                "exp": 1672444800
            }
        }

class EmailVerification(BaseModel):
    token: str = Field(..., description="Verification token")
    user_id: str = Field(..., description="ID of the user to verify")
    
    @validator('user_id')
    def validate_user_id(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId format for user_id")
        return v
    expires_at: datetime = Field(..., description="Expiration timestamp")
    
    class Config:
        json_encoders = {ObjectId: str}
        schema_extra = {
            "example": {
                "token": "a1b2c3d4e5f6g7h8i9j0",
                "user_id": "507f1f77bcf86cd799439011",
                "expires_at": "2023-12-31T23:59:59"
            }
        }
