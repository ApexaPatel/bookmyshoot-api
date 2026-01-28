from typing import List, Optional, Union, Dict, Any
from datetime import datetime, timedelta
from bson import ObjectId

from app.crud.base import CRUDBase
from app.models.event import Notification


class CRUDNotification(CRUDBase[Notification, dict, dict]):
    """CRUD operations for Notifications"""
    
    async def get_user_notifications(
        self,
        user_id: Union[str, ObjectId],
        skip: int = 0,
        limit: int = 20,
        unread_only: bool = False,
        days: Optional[int] = None
    ) -> List[Notification]:
        """Get notifications for a specific user."""
        filter_dict: Dict[str, Any] = {"user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id}
        
        if unread_only:
            filter_dict["is_read"] = False
            
        if days is not None:
            filter_dict["created_at"] = {
                "$gte": datetime.utcnow() - timedelta(days=days)
            }
            
        return await self.get_multi(
            filter_dict=filter_dict,
            skip=skip,
            limit=limit,
            sort=[("created_at", -1)]
        )
    
    async def mark_as_read(
        self, 
        notification_id: Union[str, ObjectId],
        user_id: Optional[Union[str, ObjectId]] = None
    ) -> bool:
        """Mark a specific notification as read."""
        filter_dict = {"_id": ObjectId(notification_id) if isinstance(notification_id, str) else notification_id}
        
        if user_id is not None:
            filter_dict["user_id"] = ObjectId(user_id) if isinstance(user_id, str) else user_id
            
        result = await self.update(
            notification_id,
            {"is_read": True},
            return_updated=False
        )
        
        return result is not None
    
    async def mark_all_as_read(
        self, 
        user_id: Union[str, ObjectId]
    ) -> int:
        """Mark all notifications for a user as read."""
        collection = await self.get_collection()
        result = await collection.update_many(
            {
                "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id,
                "is_read": False
            },
            {"$set": {"is_read": True}}
        )
        
        return result.modified_count or 0
    
    async def create_notification(
        self,
        user_id: Union[str, ObjectId],
        title: str,
        message: str,
        notification_type: str,
        related_entity_type: str,
        related_entity_id: Union[str, ObjectId],
        **extra_data: Any
    ) -> Notification:
        """Create a new notification with additional data."""
        notification_data = {
            "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id,
            "title": title,
            "message": message,
            "is_read": False,
            "type": notification_type,
            "related_entity_type": related_entity_type,
            "related_entity_id": ObjectId(related_entity_id) if isinstance(related_entity_id, str) else related_entity_id,
            "extra_data": extra_data,
            "created_at": datetime.utcnow()
        }
        
        return await self.create(notification_data)
    
    async def get_unread_count(
        self, 
        user_id: Union[str, ObjectId]
    ) -> int:
        """Get count of unread notifications for a user."""
        collection = await self.get_collection()
        return await collection.count_documents({
            "user_id": ObjectId(user_id) if isinstance(user_id, str) else user_id,
            "is_read": False
        })
    
    async def cleanup_old_notifications(
        self,
        days_old: int = 90
    ) -> int:
        """Clean up notifications older than specified days."""
        collection = await self.get_collection()
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        result = await collection.delete_many({
            "created_at": {"$lt": cutoff_date}
        })
        
        return result.deleted_count or 0


notification = CRUDNotification(Notification, "notifications")
