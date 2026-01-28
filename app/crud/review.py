from typing import List, Optional, Union, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from bson import ObjectId

from app.crud.base import CRUDBase
from app.models.event import Review, ReviewCreate, ReviewUpdate
from app.models.user import UserInDB, UserRole
from app.db.mongodb import get_database
from app.core.security import get_current_active_user


class CRUDReview(CRUDBase[Review, dict, dict]):
    """CRUD operations for Reviews"""
    
    async def get_for_photographer(
        self, 
        photographer_id: Union[str, ObjectId],
        skip: int = 0,
        limit: int = 10,
        min_rating: Optional[int] = None
    ) -> List[Review]:
        """Get all reviews for a specific photographer."""
        filter_dict = {"photographer_id": ObjectId(photographer_id) if isinstance(photographer_id, str) else photographer_id}
        
        if min_rating is not None:
            filter_dict["rating"] = {"$gte": min_rating}
            
        return await self.get_multi(
            filter_dict=filter_dict,
            skip=skip,
            limit=limit,
            sort=[("created_at", -1)]
        )
    
    async def get_for_booking(
        self, 
        booking_id: Union[str, ObjectId]
    ) -> Optional[Review]:
        """Get review for a specific booking."""
        return await self.get_by_field("booking_id", booking_id)
    
    async def create_with_photographer_update(
        self, 
        review_in: dict
    ) -> Review:
        """Create a new review and update photographer's rating."""
        # Create the review
        review = await self.create(review_in)
        
        if review and review.rating:
            # Update photographer's average rating
            await photographer.update_rating(
                review.photographer_id,
                review.rating
            )
            
        return review
    
    async def get_review_stats(
        self, 
        photographer_id: Union[str, ObjectId]
    ) -> Dict[str, Any]:
        """Get review statistics for a photographer."""
        collection = await self.get_collection()
        
        if isinstance(photographer_id, str):
            photographer_id = ObjectId(photographer_id)
        
        # Calculate average rating and count
        pipeline = [
            {"$match": {"photographer_id": photographer_id}},
            {"$group": {
                "_id": "$photographer_id",
                "average_rating": {"$avg": "$rating"},
                "total_reviews": {"$sum": 1},
                "rating_counts": {
                    "$push": {
                        "rating": "$rating",
                        "count": 1
                    }
                }
            }},
            {"$unwind": "$rating_counts"},
            {"$group": {
                "_id": {
                    "photographer_id": "$_id",
                    "rating": "$rating_counts.rating"
                },
                "average_rating": {"$first": "$average_rating"},
                "total_reviews": {"$first": "$total_reviews"},
                "count": {"$sum": 1}
            }},
            {"$group": {
                "_id": "$_id.photographer_id",
                "average_rating": {"$first": "$average_rating"},
                "total_reviews": {"$first": "$total_reviews"},
                "ratings": {
                    "$push": {
                        "rating": "$_id.rating",
                        "count": "$count"
                    }
                }
            }}
        ]
        
        result = await collection.aggregate(pipeline).to_list(1)
        
        if not result:
            return {
                "average_rating": 0,
                "total_reviews": 0,
                "ratings": []
            }
            
        return {
            "average_rating": round(result[0].get("average_rating", 0), 1),
            "total_reviews": result[0].get("total_reviews", 0),
            "ratings": result[0].get("ratings", [])
        }
    
    async def get_by_customer(
        self, 
        customer_id: Union[str, ObjectId],
        skip: int = 0,
        limit: int = 10
    ) -> List[Review]:
        """Get all reviews by a specific customer."""
        return await self.get_multi(
            filter_dict={"customer_id": ObjectId(customer_id) if isinstance(customer_id, str) else customer_id},
            skip=skip,
            limit=limit,
            sort=[("created_at", -1)]
        )


# Initialize router
router = APIRouter()

# Initialize CRUD operations
def get_crud_review(db = Depends(get_database)):
    return CRUDReview(Review, "reviews")

@router.post("/", response_model=Review, status_code=status.HTTP_201_CREATED)
async def create_review(
    review_in: ReviewCreate,
    crud: CRUDReview = Depends(get_crud_review),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Create a new review"""
    # Check if the photographer exists
    from app.crud.photographer import photographer as photographer_crud
    photographer = await photographer_crud.get(review_in.photographer_id)
    if not photographer:
        raise HTTPException(status_code=404, detail="Photographer not found")
    
    # Check if user has already reviewed this photographer
    existing_review = await crud.get_by_photographer_and_reviewer(
        photographer_id=review_in.photographer_id,
        reviewer_id=current_user.id
    )
    if existing_review:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already reviewed this photographer"
        )
    
    # Create the review
    review_data = review_in.dict()
    review_data["reviewer_id"] = current_user.id
    return await crud.create(review_data)

@router.get("/photographer/{photographer_id}", response_model=List[Review])
async def get_photographer_reviews(
    photographer_id: str,
    skip: int = 0,
    limit: int = 10,
    min_rating: Optional[int] = Query(None, ge=1, le=5),
    crud: CRUDReview = Depends(get_crud_review)
):
    """Get reviews for a specific photographer"""
    return await crud.get_for_photographer(
        photographer_id=photographer_id,
        skip=skip,
        limit=limit,
        min_rating=min_rating
    )

@router.get("/{review_id}", response_model=Review)
async def get_review(
    review_id: str,
    crud: CRUDReview = Depends(get_crud_review)
):
    """Get a review by ID"""
    review = await crud.get(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review

@router.put("/{review_id}", response_model=Review)
async def update_review(
    review_id: str,
    review_in: ReviewUpdate,
    crud: CRUDReview = Depends(get_crud_review),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Update a review"""
    # Check if review exists
    review = await crud.get(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    
    # Check permissions
    if str(review.reviewer_id) != str(current_user.id) and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to update this review"
        )
    
    # Update the review
    return await crud.update(review_id, review_in.dict(exclude_unset=True))

@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: str,
    crud: CRUDReview = Depends(get_crud_review),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Delete a review"""
    # Check if review exists
    review = await crud.get(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    
    # Check permissions
    if str(review.reviewer_id) != str(current_user.id) and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to delete this review"
        )
    
    # Delete the review
    await crud.remove(review_id)
    return None

# Initialize the CRUD instance
review = CRUDReview(Review, "reviews")
