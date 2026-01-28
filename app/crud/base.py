from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union
from pydantic import BaseModel
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument
from pymongo.results import DeleteResult, UpdateResult

ModelType = TypeVar("ModelType", bound=BaseModel)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)

class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: Type[ModelType], collection_name: str):
        """
        Base class for CRUD operations.
        
        Args:
            model: The Pydantic model class
            collection_name: Name of the MongoDB collection
        """
        self.model = model
        self.collection_name = collection_name

    async def get_collection(self) -> AsyncIOMotorCollection:
        from app.db.mongodb import get_database
        db = await get_database()
        return db[self.collection_name]

    async def get(self, id: Union[str, ObjectId]) -> Optional[ModelType]:
        """Get a single document by ID."""
        collection = await self.get_collection()
        if isinstance(id, str):
            id = ObjectId(id)
        
        doc = await collection.find_one({"_id": id})
        if doc:
            return self.model(**self._convert_objectid_to_str(doc))
        return None

    async def get_multi(
        self, 
        skip: int = 0, 
        limit: int = 100,
        filter_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[List[tuple]] = None
    ) -> List[ModelType]:
        """Get multiple documents with optional filtering and pagination."""
        collection = await self.get_collection()
        filter_dict = filter_dict or {}
        
        cursor = collection.find(filter_dict).skip(skip).limit(limit)
        if sort:
            cursor = cursor.sort(sort)
            
        return [self.model(**self._convert_objectid_to_str(doc)) async for doc in cursor]

    async def create(self, obj_in: CreateSchemaType) -> ModelType:
        """Create a new document."""
        collection = await self.get_collection()
        obj_dict = obj_in.dict(exclude_unset=True)
        
        # Handle nested models
        obj_dict = self._prepare_for_db(obj_dict)
        
        result = await collection.insert_one(obj_dict)
        return await self.get(result.inserted_id)

    async def update(
        self, 
        id: Union[str, ObjectId], 
        obj_in: Union[UpdateSchemaType, Dict[str, Any]],
        return_updated: bool = True
    ) -> Optional[ModelType]:
        """Update a document."""
        collection = await self.get_collection()
        if isinstance(id, str):
            id = ObjectId(id)
            
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.dict(exclude_unset=True)
        
        # Handle nested models and remove None values
        update_data = self._prepare_for_db(update_data)
        
        result = await collection.find_one_and_update(
            {"_id": id},
            {"$set": update_data},
            return_document=ReturnDocument.AFTER if return_updated else ReturnDocument.BEFORE
        )
        
        if result and return_updated:
            return self.model(**self._convert_objectid_to_str(result))
        return None

    async def delete(self, id: Union[str, ObjectId]) -> bool:
        """Delete a document."""
        collection = await self.get_collection()
        if isinstance(id, str):
            id = ObjectId(id)
            
        result = await collection.delete_one({"_id": id})
        return result.deleted_count > 0

    def _prepare_for_db(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare data for database storage."""
        result = {}
        for key, value in data.items():
            if isinstance(value, dict):
                result[key] = self._prepare_for_db(value)
            elif isinstance(value, list):
                result[key] = [self._prepare_for_db(v) if isinstance(v, dict) else v for v in value]
            elif hasattr(value, 'dict'):
                result[key] = self._prepare_for_db(value.dict())
            else:
                result[key] = value
        return result

    def _convert_objectid_to_str(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert ObjectId to string in the response."""
        result = {}
        for key, value in data.items():
            if isinstance(value, ObjectId):
                result[key] = str(value)
            elif isinstance(value, dict):
                result[key] = self._convert_objectid_to_str(value)
            elif isinstance(value, list):
                result[key] = [self._convert_objectid_to_str(v) if isinstance(v, dict) else 
                             (str(v) if isinstance(v, ObjectId) else v) for v in value]
            else:
                result[key] = value
        return result
