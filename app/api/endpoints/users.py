from fastapi import APIRouter, Depends, HTTPException, status

from app.core import get_current_active_user
from app.crud.user import CRUDUser, get_user_crud
from app.models.user import BioUpdate, CoverImageUpdate, UserInDB, UserResponse, UserRole

router = APIRouter()


@router.put("/cover-image", response_model=UserResponse)
async def update_cover_image(
    body: CoverImageUpdate,
    current_user: UserInDB = Depends(get_current_active_user),
    user_crud: CRUDUser = Depends(get_user_crud),
):
    """
    Update the current user's cover image URL (e.g. after uploading via Cloudinary).
    **Photographers only.** Requires authentication. Replaces any existing cover_image.
    """
    if current_user.role != UserRole.PHOTOGRAPHER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only photographers can set a cover image",
        )
    updated = await user_crud.update(
        current_user.id,
        {"cover_image": body.cover_image},
        return_updated=True,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update cover image")
    return UserResponse(**updated.dict(exclude={"hashed_password"}, by_alias=False))


@router.put("/bio", response_model=UserResponse)
async def update_bio(
    body: BioUpdate,
    current_user: UserInDB = Depends(get_current_active_user),
    user_crud: CRUDUser = Depends(get_user_crud),
):
    """
    Update the current user's bio.
    Photographers only. Max 500 characters.
    """
    if current_user.role != UserRole.PHOTOGRAPHER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only photographers can set a bio",
        )
    updated = await user_crud.update(
        current_user.id,
        {"bio": body.bio},
        return_updated=True,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update bio")
    return UserResponse(**updated.dict(exclude={"hashed_password"}, by_alias=False))
