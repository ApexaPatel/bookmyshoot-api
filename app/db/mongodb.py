from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from typing import Optional
import os
import asyncio
from dotenv import load_dotenv
from functools import wraps
from app.core.config import settings

load_dotenv()

def async_retry(retries: int = 3, delay: float = 1.0):
    """Decorator for retrying async functions."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(retries):
                try:
                    return await func(*args, **kwargs)
                except (ConnectionFailure, ServerSelectionTimeoutError) as e:
                    last_exception = e
                    if attempt < retries - 1:  # Don't sleep on the last attempt
                        await asyncio.sleep(delay * (attempt + 1))  # Exponential backoff
            raise last_exception or Exception("Unknown error occurred")
        return wrapper
    return decorator

class MongoDB:
    _client: Optional[AsyncIOMotorClient] = None
    _db: Optional[Database] = None
    _lock = asyncio.Lock()

    @classmethod
    @async_retry(retries=3, delay=1.0)
    async def get_db(cls) -> Database:
        """Get the database instance. Connects if not already connected."""
        async with cls._lock:
            if cls._db is None:
                await cls.connect()
            return cls._db

    @classmethod
    @async_retry(retries=3, delay=1.0)
    async def connect(cls) -> None:
        """Connect to MongoDB and verify the database exists."""
        if cls._client is not None:
            return

        mongo_uri = os.getenv("MONGODB_URL", "mongodb://localhost:27017/")
        db_name = os.getenv("MONGODB_NAME", "bookmyshoot")
        
        try:
            # Connect to MongoDB with async client
            cls._client = AsyncIOMotorClient(
                mongo_uri,
                serverSelectionTimeoutMS=10000,
                socketTimeoutMS=10000,
                connectTimeoutMS=10000,
                maxPoolSize=50,
                maxIdleTimeMS=30000,
                retryWrites=True,
                retryReads=True
            )
            
            # Verify the connection with a ping
            await cls._client.admin.command('ping')
            
            # Set the database
            cls._db = cls._client[db_name]
            
            # Verify we can access the database
            await cls._db.command('ping')
            
            # Create indexes if they don't exist
            await cls._create_indexes()
            
            print(f"✅ Successfully connected to database: {db_name}")
            
        except Exception as e:
            # Clean up on error
            if cls._client:
                await cls._client.close()
                cls._client = None
            raise ConnectionError(f"Failed to connect to MongoDB: {str(e)}")
            
    @classmethod
    async def _create_indexes(cls) -> None:
        """Create necessary indexes for better query performance."""
        if cls._db is None:
            return
            
        # Example: Create index on users collection
        if 'users' in (await cls._db.list_collection_names()):
            await cls._db.users.create_index('email', unique=True)
            await cls._db.users.create_index('phone', unique=True)

        await cls._db.subscriptions.create_index([('user_id', 1), ('created_at', -1)])
        await cls._db.subscriptions.create_index('payment_id')

        # Add more indexes for other collections as needed

    @classmethod
    async def close_connection(cls) -> None:
        """Safely close the MongoDB connection."""
        if cls._client:
            try:
                await cls._client.close()
                print("✅ MongoDB connection closed")
            except Exception as e:
                print(f"⚠️  Error closing MongoDB connection: {str(e)}")
            finally:
                cls._client = None
                cls._db = None

# Initialize database connection on application startup
async def init_db() -> None:
    """Initialize the database connection."""
    try:
        await MongoDB.connect()
    except Exception as e:
        print(f"⚠️  Initial MongoDB connection failed: {str(e)}")
        raise

async def get_database() -> Database:
    """
    Get the database instance for dependency injection.
    
    Example:
        @app.get("/items/")
        async def read_items(db: Database = Depends(get_database)):
            items = await db["items"].find().to_list(None)
            return items
    """
    return await MongoDB.get_db()

# For FastAPI's startup event
async def on_startup():
    """Initialize database connection when the application starts."""
    try:
        await init_db()
    except Exception as e:
        print(f"❌ Failed to initialize database: {str(e)}")
        raise
