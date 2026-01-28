from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pymongo import MongoClient
from pydantic import BaseModel
from typing import List, Optional
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="BookMyShoot API",
    description="Backend API for BookMyShoot - A platform to book photographers",
    version="1.0.0"
)

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection
DATABASE_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017/")
client = MongoClient(DATABASE_URL)
db = client["bookmyshoot"]

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Health check endpoint
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "BookMyShoot API is running"}

# Root endpoint
@app.get("/")
async def root():
    return {"message": "Welcome to BookMyShoot API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
