from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core import create_access_token, get_password_hash, get_current_active_user
from app.core.config import settings
from app.crud.user import CRUDUser, get_user_crud
from app.crud.organization import CRUDOrganization, get_organization_crud
from app.models.user import UserCreate, UserInDB, UserResponse, Token, ProfileImageUpdate

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: UserInDB = Depends(get_current_active_user)):
    """
    Return current authenticated user. Used to restore session on app load.
    Returns 401 if token is invalid or expired.
    """
    return UserResponse(**current_user.dict(exclude={"hashed_password"}, by_alias=False))


@router.put("/profile-image", response_model=UserResponse)
async def update_profile_image(
    body: ProfileImageUpdate,
    current_user: UserInDB = Depends(get_current_active_user),
    user_crud: CRUDUser = Depends(get_user_crud),
):
    """
    Update the current user's profile image URL (e.g. after uploading to Firebase Storage).
    Requires authentication. Replaces any existing profile_picture.
    """
    updated = await user_crud.update(
        current_user.id,
        {"profile_picture": body.profile_picture},
        return_updated=True,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update profile image")
    return UserResponse(**updated.dict(exclude={"hashed_password"}, by_alias=False))


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    user_in: UserCreate,
    user_crud: CRUDUser = Depends(get_user_crud),
    org_crud: CRUDOrganization = Depends(get_organization_crud),
):
    """
    Create a new user account. If is_part_of_organization is True and organization is provided,
    creates the organization first then the user with organization_id.
    """
    existing_user = await user_crud.get_by_email(user_in.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Build user data; exclude password and nested organization
    user_data = user_in.dict(exclude={"password", "organization"})
    user_data["hashed_password"] = get_password_hash(user_in.password)
    user_data.setdefault("is_active", True)
    user_data.setdefault("is_verified", False)
    user_data.setdefault("role", "customer")
    user_data.setdefault("preferences", {})
    now = datetime.utcnow()
    user_data["created_at"] = now
    user_data["updated_at"] = now

    # If photographer part of organization, create organization first then link
    if getattr(user_in, "is_part_of_organization", False) and user_in.organization:
        org = await org_crud.create({
            "name": user_in.organization.name.strip(),
            "location": user_in.organization.location and user_in.organization.location.strip() or None,
            "contact_number": user_in.organization.contact_number and user_in.organization.contact_number.strip() or None,
        })
        user_data["organization_id"] = org.id
        user_data["is_part_of_organization"] = True
    else:
        user_data["organization_id"] = None
        user_data["is_part_of_organization"] = getattr(user_in, "is_part_of_organization", False)

    user = await user_crud.create(user_data)
    response_data = user.dict(exclude={"hashed_password"}, by_alias=False)
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
