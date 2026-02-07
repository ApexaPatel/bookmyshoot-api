from fastapi import APIRouter
from app.api.endpoints import auth, organizations, photographers

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(organizations.router, prefix="/organizations", tags=["organizations"])
api_router.include_router(photographers.router, prefix="/photographers", tags=["photographers"])