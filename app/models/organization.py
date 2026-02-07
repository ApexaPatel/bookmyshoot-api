from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from bson import ObjectId


class OrganizationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Organization name")
    location: Optional[str] = Field(None, max_length=200)
    contact_number: Optional[str] = Field(None, max_length=20)


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationInDB(OrganizationBase):
    id: str = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        json_encoders = {ObjectId: str}


class OrganizationResponse(OrganizationBase):
    id: str = Field(default_factory=lambda: str(ObjectId()), alias="_id")

    class Config:
        allow_population_by_field_name = True
        json_encoders = {ObjectId: str}
        orm_mode = True
