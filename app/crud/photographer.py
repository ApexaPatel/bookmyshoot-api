from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from datetime import datetime

from app.crud.base import CRUDBase
from app.models.event import PhotographerProfile, PortfolioImage, AvailabilitySlot, PricingTier, EventType, PhotographerProfileCreate, PhotographerProfileUpdate
from app.models.user import UserRole, UserInDB
from app.db.mongodb import get_database
from app.core.security import get_current_active_user


class CRUDPhotographer(CRUDBase[PhotographerProfile, dict, dict]):
    """CRUD operations for Photographer Profile"""
    
    async def get_by_user_id(self, user_id: Union[str, ObjectId]) -> Optional[PhotographerProfile]:
        """Get photographer profile by user ID."""
        return await self.get(user_id, "user_id")

    async def update_availability(
        self, 
        photographer_id: Union[str, ObjectId], 
        availability: List[AvailabilitySlot]
    ) -> Optional[PhotographerProfile]:
        """Update photographer's availability slots."""
        return await self.update(
            photographer_id,
            {"availability": [slot.dict() for slot in availability]}
        )

    async def add_portfolio_image(
        self, 
        photographer_id: Union[str, ObjectId], 
        image: PortfolioImage
    ) -> Optional[PhotographerProfile]:
        """Add an image to photographer's portfolio."""
        collection = await self.get_collection()
        result = await collection.update_one(
            {"_id": ObjectId(photographer_id)},
            {"$push": {"portfolio": image.dict()}}
        )
        if result.modified_count:
            return await self.get(photographer_id)
        return None

    async def update_pricing_tiers(
        self,
        photographer_id: Union[str, ObjectId],
        pricing_tiers: List[PricingTier]
    ) -> Optional[PhotographerProfile]:
        """Update photographer's pricing tiers."""
        return await self.update(
            photographer_id,
            {"pricing_tiers": [tier.dict() for tier in pricing_tiers]}
        )

    async def get_by_services(
        self,
        event_types: List[EventType],
        city: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[PhotographerProfile]:
        """Get photographers by services they offer and optionally filter by city."""
        filter_dict = {
            "is_verified": True,
            "is_available": True,
            "services_offered": {"$in": [et.value for et in event_types]}
        }
        
        if city:
            filter_dict["city"] = city
            
        return await self.get_multi(
            filter_dict=filter_dict,
            skip=skip,
            limit=limit,
            sort=[("rating_avg", -1), ("total_reviews", -1)]
        )

    async def update_rating(
        self,
        photographer_id: Union[str, ObjectId],
        new_rating: int
    ) -> Optional[PhotographerProfile]:
        """Update photographer's average rating and total reviews."""
        collection = await self.get_collection()
        
        # Get current values
        photographer = await collection.find_one({"_id": ObjectId(photographer_id)})
        if not photographer:
            return None
            
        current_rating = photographer.get("rating_avg", 0)
        total_reviews = photographer.get("total_reviews", 0)
        
        # Calculate new average
        new_avg = ((current_rating * total_reviews) + new_rating) / (total_reviews + 1)
        
        # Update with atomic operation
        result = await collection.update_one(
            {"_id": ObjectId(photographer_id)},
            {
                "$set": {
                    "rating_avg": round(new_avg, 2),
                    "total_reviews": total_reviews + 1
                }
            }
        )
        
        if result.modified_count:
            return await self.get(photographer_id)
        return None

    async def verify_photographer(
        self,
        photographer_id: Union[str, ObjectId],
        is_verified: bool = True
    ) -> bool:
        """Verify or un-verify a photographer."""
        result = await self.update(
            photographer_id,
            {"is_verified": is_verified},
            return_updated=False
        )
        return result is not None


# Initialize router
router = APIRouter()

# Initialize CRUD operations
def get_crud_photographer(db = Depends(get_database)):
    return CRUDPhotographer(PhotographerProfile, "photographer_profiles")

@router.post("/", response_model=PhotographerProfile, status_code=status.HTTP_201_CREATED)
async def create_photographer_profile(
    profile_in: PhotographerProfileCreate,
    crud: CRUDPhotographer = Depends(get_crud_photographer),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Create a new photographer profile"""
    # Check if user already has a profile
    existing_profile = await crud.get_by_user_id(current_user.id)
    if existing_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Photographer profile already exists for this user"
        )
    
    # Create the profile
    profile_data = profile_in.dict()
    profile_data["user_id"] = current_user.id
    return await crud.create(profile_data)

@router.get("/me", response_model=PhotographerProfile)
async def read_photographer_profile_me(
    crud: CRUDPhotographer = Depends(get_crud_photographer),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Get current user's photographer profile"""
    profile = await crud.get_by_user_id(current_user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Photographer profile not found")
    return profile

@router.get("/{photographer_id}", response_model=PhotographerProfile)
async def read_photographer_profile(
    photographer_id: str,
    crud: CRUDPhotographer = Depends(get_crud_photographer)
):
    """Get a photographer profile by ID"""
    profile = await crud.get(photographer_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Photographer profile not found")
    return profile

@router.put("/{photographer_id}", response_model=PhotographerProfile)
async def update_photographer_profile(
    photographer_id: str,
    profile_in: PhotographerProfileUpdate,
    crud: CRUDPhotographer = Depends(get_crud_photographer),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Update a photographer profile"""
    # Check if profile exists and belongs to current user
    profile = await crud.get(photographer_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Photographer profile not found")
    
    if str(profile.user_id) != str(current_user.id) and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to update this profile"
        )
    
    return await crud.update(photographer_id, profile_in.dict(exclude_unset=True))

# Initialize the CRUD instance
photographer = CRUDPhotographer(PhotographerProfile, "photographer_profiles")
