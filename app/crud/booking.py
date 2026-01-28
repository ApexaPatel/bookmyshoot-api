from typing import List, Optional, Union, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from bson import ObjectId
from pymongo import ReturnDocument

from app.crud.base import CRUDBase
from app.models.event import Booking, BookingCreate, BookingUpdate, BookingStatus, EventType, ComboType
from app.models.user import UserRole, UserInDB
from app.db.mongodb import get_database
from app.core.security import get_current_active_user


class CRUDBooking(CRUDBase[Booking, dict, dict]):
    """CRUD operations for Bookings"""
    
    async def get_by_customer(
        self, 
        customer_id: Union[str, ObjectId],
        skip: int = 0,
        limit: int = 100,
        status: Optional[BookingStatus] = None
    ) -> List[Booking]:
        """Get all bookings for a specific customer."""
        filter_dict = {"customer_id": ObjectId(customer_id) if isinstance(customer_id, str) else customer_id}
        if status:
            filter_dict["status"] = status
            
        return await self.get_multi(
            filter_dict=filter_dict,
            skip=skip,
            limit=limit,
            sort=[("start_time", -1)]
        )
    
    async def get_by_photographer(
        self, 
        photographer_id: Union[str, ObjectId],
        skip: int = 0,
        limit: int = 100,
        status: Optional[BookingStatus] = None
    ) -> List[Booking]:
        """Get all bookings for a specific photographer."""
        filter_dict = {"photographer_id": ObjectId(photographer_id) if isinstance(photographer_id, str) else photographer_id}
        if status:
            filter_dict["status"] = status
            
        return await self.get_multi(
            filter_dict=filter_dict,
            skip=skip,
            limit=limit,
            sort=[("start_time", -1)]
        )
    
    async def check_availability(
        self,
        photographer_id: Union[str, ObjectId],
        start_time: datetime,
        end_time: datetime,
        exclude_booking_id: Optional[Union[str, ObjectId]] = None
    ) -> bool:
        """Check if photographer is available for the given time slot."""
        filter_dict = {
            "photographer_id": ObjectId(photographer_id) if isinstance(photographer_id, str) else photographer_id,
            "status": {"$in": [BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS]},
            "$or": [
                # New booking starts during existing booking
                {"start_time": {"$lt": end_time}, "end_time": {"$gt": start_time}},
                # New booking ends during existing booking
                {"start_time": {"$lt": end_time}, "end_time": {"$gt": start_time}}
            ]
        }
        
        if exclude_booking_id:
            filter_dict["_id"] = {"$ne": ObjectId(exclude_booking_id) if isinstance(exclude_booking_id, str) else exclude_booking_id}
        
        collection = await self.get_collection()
        existing_booking = await collection.find_one(filter_dict)
        return existing_booking is None
    
    async def update_status(
        self,
        booking_id: Union[str, ObjectId],
        new_status: BookingStatus,
        updated_by: UserRole,
        cancellation_reason: Optional[str] = None
    ) -> Optional[Booking]:
        """Update booking status with validation."""
        update_data = {"status": new_status}
        
        if new_status == BookingStatus.CANCELLED and cancellation_reason:
            update_data["cancellation_reason"] = cancellation_reason
        
        # Add audit info
        update_data["updated_at"] = datetime.utcnow()
        update_data["updated_by"] = updated_by
        
        return await self.update(booking_id, update_data)
    
    async def get_upcoming(
        self,
        user_id: Union[str, ObjectId],
        user_role: UserRole,
        limit: int = 5
    ) -> List[Booking]:
        """Get upcoming bookings for a user."""
        field = "customer_id" if user_role == UserRole.CUSTOMER else "photographer_id"
        
        return await self.get_multi(
            filter_dict={
                field: ObjectId(user_id) if isinstance(user_id, str) else user_id,
                "status": {"$in": [BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS]},
                "start_time": {"$gt": datetime.utcnow()}
            },
            limit=limit,
            sort=[("start_time", 1)]
        )
    
    async def get_booking_stats(
        self,
        photographer_id: Union[str, ObjectId]
    ) -> Dict[str, Any]:
        """Get booking statistics for a photographer."""
        collection = await self.get_collection()
        
        # Convert to ObjectId if it's a string
        if isinstance(photographer_id, str):
            photographer_id = ObjectId(photographer_id)
        
        # Get total bookings count
        total = await collection.count_documents({"photographer_id": photographer_id})
        
        # Get bookings by status
        pipeline = [
            {"$match": {"photographer_id": photographer_id}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$project": {"status": "$_id", "count": 1, "_id": 0}}
        ]
        
        status_counts = {}
        async for doc in collection.aggregate(pipeline):
            status_counts[doc["status"]] = doc["count"]
        
        # Get monthly booking count for the last 6 months
        six_months_ago = datetime.utcnow()
        six_months_ago = six_months_ago.replace(month=six_months_ago.month-6)
        
        monthly_pipeline = [
            {"$match": {
                "photographer_id": photographer_id,
                "created_at": {"$gte": six_months_ago}
            }},
            {"$group": {
                "_id": {
                    "year": {"$year": "$created_at"},
                    "month": {"$month": "$created_at"}
                },
                "count": {"$sum": 1}
            }},
            {"$sort": {"_id.year": 1, "_id.month": 1}}
        ]
        
        monthly_counts = []
        async for doc in collection.aggregate(monthly_pipeline):
            monthly_counts.append({
                "year": doc["_id"]["year"],
                "month": doc["_id"]["month"],
                "count": doc["count"]
            })
        
        return {
            "total_bookings": total,
            "status_counts": status_counts,
            "monthly_counts": monthly_counts
        }


# Initialize router
router = APIRouter()

# Initialize CRUD operations
def get_crud_booking(db = Depends(get_database)):
    return CRUDBooking(Booking, "bookings")

@router.post("/", response_model=Booking, status_code=status.HTTP_201_CREATED)
async def create_booking(
    booking_in: BookingCreate,
    crud: CRUDBooking = Depends(get_crud_booking),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Create a new booking"""
    # Check if the photographer exists
    from app.crud.photographer import photographer as photographer_crud
    photographer = await photographer_crud.get(booking_in.photographer_id)
    if not photographer:
        raise HTTPException(status_code=404, detail="Photographer not found")
    
    # Create the booking
    booking_data = booking_in.dict()
    booking_data["customer_id"] = current_user.id
    booking_data["status"] = BookingStatus.PENDING
    return await crud.create(booking_data)

@router.get("/{booking_id}", response_model=Booking)
async def read_booking(
    booking_id: str,
    crud: CRUDBooking = Depends(get_crud_booking),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Get a booking by ID"""
    booking = await crud.get(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Check permissions
    if (str(booking.customer_id) != str(current_user.id) and 
        str(booking.photographer_id) != str(current_user.id) and 
        current_user.role != UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to view this booking"
        )
    
    return booking

@router.get("/", response_model=List[Booking])
async def list_bookings(
    skip: int = 0,
    limit: int = 100,
    status: Optional[BookingStatus] = None,
    crud: CRUDBooking = Depends(get_crud_booking),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """List bookings with optional filtering by status"""
    if current_user.role == UserRole.CUSTOMER:
        return await crud.get_by_customer(
            customer_id=current_user.id,
            skip=skip,
            limit=limit,
            status=status
        )
    elif current_user.role == UserRole.PHOTOGRAPHER:
        return await crud.get_by_photographer(
            photographer_id=current_user.id,
            skip=skip,
            limit=limit,
            status=status
        )
    else:  # Admin
        return await crud.get_multi(skip=skip, limit=limit, filter_dict={"status": status} if status else {})

@router.put("/{booking_id}", response_model=Booking)
async def update_booking(
    booking_id: str,
    booking_in: BookingUpdate,
    crud: CRUDBooking = Depends(get_crud_booking),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Update a booking"""
    # Check if booking exists
    booking = await crud.get(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Check permissions
    if (str(booking.customer_id) != str(current_user.id) and 
        str(booking.photographer_id) != str(current_user.id) and 
        current_user.role != UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to update this booking"
        )
    
    # Update the booking
    return await crud.update(booking_id, booking_in.dict(exclude_unset=True))

@router.patch("/{booking_id}/status", response_model=Booking)
async def update_booking_status(
    booking_id: str,
    status: BookingStatus,
    crud: CRUDBooking = Depends(get_crud_booking),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Update booking status"""
    # Check if booking exists
    booking = await crud.get(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Check permissions and validate status transition
    if current_user.role == UserRole.CUSTOMER:
        if str(booking.customer_id) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions to update this booking"
            )
        # Customers can only cancel bookings
        if status != BookingStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Customers can only cancel bookings"
            )
    elif current_user.role == UserRole.PHOTOGRAPHER:
        if str(booking.photographer_id) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions to update this booking"
            )
    # Admins can do anything
    
    # Update the booking status
    return await crud.update_status(booking_id, status)

# Initialize the CRUD instance
booking = CRUDBooking(Booking, "bookings")
