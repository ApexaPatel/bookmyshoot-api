from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from bson import ObjectId
from pymongo.database import Database
from fastapi import Depends

from app.models.user import UserInDB, UserCreate, UserUpdate, UserRole, UserResponse, User
from app.core.password import verify_password
from app.db.mongodb import get_database

class CRUDUser:
    def __init__(self, db: Database):
        self.db = db
        self.collection = db["users"]
    
    async def get_by_email(self, email: str) -> Optional[UserInDB]:
        """Get a user by email."""
        user_data = await self.collection.find_one({"email": email.lower()})
        if user_data:
            # Convert ObjectId to string and ensure all required fields are present
            user_dict = dict(user_data)
            user_dict["id"] = str(user_dict.pop("_id"))
            # Ensure all required fields have default values if missing
            user_dict.setdefault("is_active", True)
            user_dict.setdefault("is_verified", False)
            user_dict.setdefault("role", "customer")
            user_dict.setdefault("preferences", {})
            # Ensure hashed_password is present
            if "hashed_password" not in user_dict:
                return None
            return UserInDB(**user_dict)
        return None
    
    async def get(self, user_id: str) -> Optional[UserInDB]:
        """Get a user by ID."""
        try:
            user_data = await self.collection.find_one({"_id": ObjectId(user_id)})
            if user_data:
                # Convert ObjectId to string and ensure all required fields are present
                user_dict = dict(user_data)
                user_dict["id"] = str(user_dict.pop("_id"))
                # Ensure all required fields have default values if missing
                user_dict.setdefault("is_active", True)
                user_dict.setdefault("is_verified", False)
                user_dict.setdefault("role", "customer")
                user_dict.setdefault("preferences", {})
                # Ensure hashed_password is present
                if "hashed_password" not in user_dict:
                    return None
                return UserInDB(**user_dict)
            return None
        except Exception as e:
            print(f"Error getting user by ID: {e}")
            return None
    
    async def create(self, user_data: dict) -> UserInDB:
        """Create a new user."""
        try:
            # Handle the ID field properly
            if "id" in user_data:
                user_data["_id"] = ObjectId(user_data.pop("id"))
            else:
                user_data["_id"] = ObjectId()
            
            # Ensure hashed_password is set
            if "hashed_password" not in user_data:
                raise ValueError("hashed_password is required")
            
            # Set timestamps if not provided
            now = datetime.utcnow()
            user_data.setdefault("created_at", now)
            user_data.setdefault("updated_at", now)
            
            # Insert the new user
            await self.collection.insert_one(user_data)
            
            # Get the created user
            created_user = await self.collection.find_one({"_id": user_data["_id"]})
            if not created_user:
                raise ValueError("Failed to create user")
            
            # Convert ObjectId to string for the id field
            created_user["id"] = str(created_user.pop("_id"))
            
            # Ensure all required fields have default values if missing
            created_user.setdefault("is_active", True)
            created_user.setdefault("is_verified", False)
            created_user.setdefault("role", "customer")
            created_user.setdefault("preferences", {})
            
            return UserInDB(**created_user)
        
        except Exception as e:
            print(f"Error creating user: {e}")
            raise
        return created_user

    async def authenticate(self, email: str, password: str) -> Optional[UserInDB]:
        """Authenticate a user."""
        user = await self.get_by_email(email)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
            
        # Update last login time
        await self.collection.update_one(
            {"_id": ObjectId(user.id)},
            {"$set": {"last_login": datetime.utcnow()}}
        )
        return user

    async def is_active(self, user: Union[User, UserInDB]) -> bool:
        """Check if user is active."""
        return user.is_active

    async def is_superuser(self, user: Union[User, UserInDB]) -> bool:
        """Check if user is super admin."""
        return user.role == UserRole.SUPER_ADMIN

    async def update_last_login(self, user_id: Union[str, ObjectId]) -> None:
        """Update user's last login timestamp."""
        from datetime import datetime
        await self.update(user_id, {"last_login": datetime.utcnow()}, return_updated=False)

    async def get_multi_by_role(
        self, 
        role: UserRole, 
        skip: int = 0, 
        limit: int = 100,
        is_active: Optional[bool] = None
    ) -> List[User]:
        """Get multiple users filtered by role."""
        filter_dict = {"role": role}
        if is_active is not None:
            filter_dict["is_active"] = is_active
            
        return await self.get_multi(
            skip=skip,
            limit=limit,
            filter_dict=filter_dict,
            sort=[("created_at", -1)]
        )

    async def update(self, user_id: Union[str, ObjectId], user_data: dict, return_updated: bool = True) -> Optional[UserInDB]:
        """Update a user."""
        try:
            # Convert string ID to ObjectId if needed
            user_oid = ObjectId(user_id) if isinstance(user_id, str) else user_id
            
            # Remove id from update data to prevent modification
            user_data.pop("id", None)
            user_data.pop("_id", None)
            
            # Add updated_at timestamp
            user_data["updated_at"] = datetime.utcnow()
            
            # Update the user
            result = await self.collection.update_one(
                {"_id": user_oid},
                {"$set": user_data}
            )
            
            if result.modified_count == 0:
                return None
                
            if not return_updated:
                return True
                
            # Get the updated user
            updated_user = await self.collection.find_one({"_id": user_oid})
            if updated_user:
                # Convert ObjectId to string for the id field
                updated_user["id"] = str(updated_user.pop("_id"))
                return UserInDB(**updated_user)
            return None
            
        except Exception as e:
            print(f"Error updating user: {e}")
            if not return_updated:
                return False
            return None
            
    async def verify_email(self, user_id: Union[str, ObjectId]) -> bool:
        """Mark user's email as verified."""
        result = await self.update(user_id, {"is_verified": True}, return_updated=False)
        return result is not None


def get_user_crud(db: Database = Depends(get_database)) -> CRUDUser:
    return CRUDUser(db)

user_crud = Depends(get_user_crud)
