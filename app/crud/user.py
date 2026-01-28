from typing import Optional, Dict, Any
from datetime import datetime
from bson import ObjectId
from pymongo.database import Database
from pymongo.results import InsertOneResult, UpdateResult

from app.models.user import UserInDB, UserCreate, UserUpdate, UserRole
from app.core.security import get_password_hash, verify_password

class CRUDUser:
    def __init__(self, db: Database):
        self.db = db
        self.collection = db["users"]
    
    async def get_by_email(self, email: str) -> Optional[UserInDB]:
        """Get a user by email."""
        user_data = await self.collection.find_one({"email": email.lower()})
        if user_data:
            user_data["id"] = str(user_data["_id"])
            return UserInDB(**user_data)
        return None
    
    async def get(self, user_id: str) -> Optional[UserInDB]:
        """Get a user by ID."""
        try:
            user_data = await self.collection.find_one({"_id": ObjectId(user_id)})
            if user_data:
                user_data["id"] = str(user_data["_id"])
                return UserInDB(**user_data)
            return None
        except Exception:
            return None
    
    async def create(self, user_in: UserCreate) -> UserInDB:
        """Create a new user."""
        # Check if user with email already exists
        existing_user = await self.get_by_email(user_in.email)
        if existing_user:
            raise ValueError("User with this email already exists")
        
        # Hash the password
        hashed_password = get_password_hash(user_in.password)
        
        # Prepare user data
        user_data = user_in.dict(exclude={"password"})
        user_data["hashed_password"] = hashed_password
        user_data["email"] = user_data["email"].lower()
        user_data["created_at"] = datetime.utcnow()
        user_data["updated_at"] = datetime.utcnow()
        
        # Insert into database
        result: InsertOneResult = await self.collection.insert_one(user_data)
        
        # Return the created user
        created_user = await self.get(str(result.inserted_id))
        if not created_user:
            raise ValueError("Failed to create user")
        return created_user
    
    async def update(self, user_id: str, user_in: UserUpdate) -> Optional[UserInDB]:
        """Update a user."""
        update_data = user_in.dict(exclude_unset=True)
        
        # If password is being updated, hash it
        if "password" in update_data:
            hashed_password = get_password_hash(update_data["password"])
            del update_data["password"]
            update_data["hashed_password"] = hashed_password
        
        if not update_data:
            return await self.get(user_id)
        
        update_data["updated_at"] = datetime.utcnow()
        
        result: UpdateResult = await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            return None
            
        return await self.get(user_id)
    
    async def authenticate(self, email: str, password: str) -> Optional[UserInDB]:
        """Authenticate a user."""
        user = await self.get_by_email(email)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user
    
    async def is_active(self, user: UserInDB) -> bool:
        """Check if user is active."""
        return user.is_active
    
    async def is_superuser(self, user: UserInDB) -> bool:
        """Check if user is a superuser (admin)."""
        return user.role == UserRole.ADMIN
    
    async def is_photographer(self, user: UserInDB) -> bool:
        """Check if user is a photographer."""
        return user.role == UserRole.PHOTOGRAPHER
