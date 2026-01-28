from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field, validator, HttpUrl
from enum import Enum
from bson import ObjectId

# Import only the enums to avoid circular imports
from .event import EventType

class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    CUSTOMER = "customer"
    PHOTOGRAPHER = "photographer"

class UserBase(BaseModel):
    email: EmailStr = Field(..., description="User's email address, must be unique")
    full_name: str = Field(..., min_length=2, max_length=100, description="User's full name")
    phone: str = Field(..., min_length=10, max_length=15, 
                      regex=r'^\+?[1-9]\d{1,14}$', 
                      description="User's phone number in E.164 format")
    profile_picture: Optional[HttpUrl] = Field(None, description="URL to user's profile picture")
    is_active: bool = Field(True, description="Whether the user account is active")
    is_verified: bool = Field(False, description="Whether the user's email is verified")
    role: UserRole = Field(UserRole.CUSTOMER, description="User's role in the system")
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
    
    @validator('password')
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one number')
        return v

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = Field(None, description="New email address")
    full_name: Optional[str] = Field(None, min_length=2, max_length=100, 
                                   description="Updated full name")
    phone: Optional[str] = Field(None, min_length=10, max_length=15,
                                regex=r'^\+?[1-9]\d{1,14}$',
                                description="Updated phone number")
    profile_picture: Optional[HttpUrl] = Field(None, description="URL to updated profile picture")
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
