from pydantic import BaseSettings
from typing import List
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings(BaseSettings):
    # Application settings
    PROJECT_NAME: str = "BookMyShoot API"
    API_V1_STR: str = "/api"
    
    # Security settings
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-please-change-in-production")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 1440))  # 24 hours
    
    # MongoDB settings
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017/")
    DATABASE_NAME: str = "bookmyshoot"
    
    # CORS settings
    BACKEND_CORS_ORIGINS: List[str] = ["*"]  # In production, replace with your frontend URL
    
    class Config:
        case_sensitive = True

# Create settings instance
settings = Settings()
