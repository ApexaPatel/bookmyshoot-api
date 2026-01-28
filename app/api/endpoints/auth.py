from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core import create_access_token, get_password_hash
from app.core.config import settings
from app.crud.user import CRUDUser, get_user_crud
from app.models.user import UserCreate, UserInDB, UserResponse, Token

router = APIRouter()

@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    user_in: UserCreate,
    user_crud: CRUDUser = Depends(get_user_crud)
):
    """
    Create a new user account.
    """
    # Check if user already exists
    existing_user = await user_crud.get_by_email(user_in.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Hash the password
    hashed_password = get_password_hash(user_in.password)
    
    # Create user data dictionary with hashed_password
    user_data = user_in.dict(exclude={"password"})  # Exclude the plain password
    user_data["hashed_password"] = hashed_password  # Add the hashed password
    
    # Set default values for required fields
    user_data.setdefault("is_active", True)
    user_data.setdefault("is_verified", False)
    user_data.setdefault("role", "customer")
    user_data.setdefault("preferences", {})
    
    # Set timestamps
    now = datetime.utcnow()
    user_data["created_at"] = now
    user_data["updated_at"] = now
    
    # Create the user using the dictionary directly
    user = await user_crud.create(user_data)
    
    # Convert to response model (exclude hashed_password)
    response_data = user.dict(exclude={"hashed_password"})
    return UserResponse(**response_data)

@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    user_crud: CRUDUser = Depends(get_user_crud)
):
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    user = await user_crud.authenticate(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email, "role": user.role},
        expires_delta=access_token_expires
    )
    
    # Update last login time
    user_data = user.dict()
    user_data["last_login"] = datetime.utcnow()
    await user_crud.update(user.id, user_data)
    
    # Convert user to response model to exclude sensitive data
    user_response = UserResponse(**user.dict())
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": int(access_token_expires.total_seconds()),
        "user": user_response
    }
