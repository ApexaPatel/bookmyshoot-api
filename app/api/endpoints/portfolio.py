from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.database import Database

from app.core import get_current_active_user
from app.db.mongodb import get_database
from app.models.portfolio import (
    PortfolioCreate,
    PortfolioListResponse,
    PortfolioResponse,
    PortfolioUpdate,
    prepare_portfolio_payload,
    serialize_portfolio,
)
from app.models.user import UserInDB, UserRole
from app.exceptions.plan_limits import PlanLimitError
from app.services.photographer_plan import get_plan_rules, get_plan_window, get_usage_period_bounds

router = APIRouter()


def ensure_photographer(user: UserInDB) -> None:
    if user.role != UserRole.PHOTOGRAPHER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only photographers can manage portfolios",
        )


async def validate_portfolio_limits(
    payload: PortfolioCreate | PortfolioUpdate,
    current_user: UserInDB,
    db: Database,
    exclude_portfolio_id: str | None = None,
    enforce_capacity: bool = True,
) -> dict:
    rules = get_plan_rules(getattr(current_user, "photographer_plan", "free"))
    gallery_count = len(payload.gallery)
    if gallery_count > rules.max_gallery_images:
        if rules.name == "Free":
            raise PlanLimitError(
                "FREE_PLAN_IMAGE_LIMIT_REACHED",
                "Free Plan allows only 5 images per photoshoot. Upgrade to upload more images.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{rules.name} plan allows up to {rules.max_gallery_images} gallery images per photoshoot",
        )

    if not rules.allow_future_event_dates and payload.shoot_date > datetime.utcnow().date():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{rules.name} plan only allows past or current event dates",
        )

    window_start, window_end = get_plan_window(current_user)
    usage_start, usage_end = get_usage_period_bounds(rules, current_user)
    if not enforce_capacity:
        return {
            "plan": rules.name,
            "price_inr": rules.price_inr,
            "max_photoshoots": rules.max_photoshoots,
            "max_gallery_images": rules.max_gallery_images,
            "monthly_limit": rules.monthly_limit,
            "plan_started_at": window_start,
            "plan_expires_at": window_end,
        }

    query = {"user_id": ObjectId(current_user.id)}
    if exclude_portfolio_id and ObjectId.is_valid(exclude_portfolio_id):
        query["_id"] = {"$ne": ObjectId(exclude_portfolio_id)}

    if rules.monthly_limit:
        if not usage_start or not usage_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{rules.name} plan is missing an active billing window",
            )
        if usage_end < datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{rules.name} plan has expired. Renew to add more photoshoots",
            )
        query["created_at"] = {"$gte": usage_start, "$lte": usage_end}

    existing_count = await db["portfolios"].count_documents(query)
    if existing_count >= rules.max_photoshoots:
        if rules.name == "Free":
            raise PlanLimitError(
                "FREE_PLAN_LIMIT_REACHED",
                "You have reached the limit of your Free Plan. Upgrade to add more.",
            )
        period = "this month" if rules.monthly_limit else "total"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{rules.name} plan allows up to {rules.max_photoshoots} photoshoots {period}",
        )

    remaining = max(rules.max_photoshoots - existing_count, 0)
    return {
        "plan": rules.name,
        "max_photoshoots": rules.max_photoshoots,
        "max_gallery_images": rules.max_gallery_images,
        "remaining_photoshoots": remaining,
        "monthly_limit": rules.monthly_limit,
        "plan_started_at": window_start,
        "plan_expires_at": window_end,
    }


@router.post("", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    payload: PortfolioCreate,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    ensure_photographer(current_user)
    await validate_portfolio_limits(payload, current_user, db)
    document = prepare_portfolio_payload(payload, current_user.id)
    document["created_at"] = datetime.utcnow()

    result = await db["portfolios"].insert_one(document)
    created = await db["portfolios"].find_one({"_id": result.inserted_id})
    return serialize_portfolio(created)


@router.get("", response_model=PortfolioListResponse)
async def list_portfolios(
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    ensure_photographer(current_user)
    cursor = db["portfolios"].find({"user_id": ObjectId(current_user.id)}).sort("shoot_date", -1)
    documents = await cursor.to_list(length=None)
    rules = get_plan_rules(getattr(current_user, "photographer_plan", "free"))
    window_start, window_end = get_plan_window(current_user)
    usage_start, usage_end = get_usage_period_bounds(rules, current_user)
    active_query = {"user_id": ObjectId(current_user.id)}
    if rules.monthly_limit and usage_start and usage_end:
        active_query["created_at"] = {"$gte": usage_start, "$lte": usage_end}
    active_count = await db["portfolios"].count_documents(active_query)
    cycle_ends_at = None if rules.name == "Free" else window_end
    return {
        "portfolios": [serialize_portfolio(doc) for doc in documents],
        "plan": {
            "code": rules.name.lower(),
            "name": rules.name,
            "price_inr": rules.price_inr,
            "max_photoshoots": rules.max_photoshoots,
            "max_gallery_images": rules.max_gallery_images,
            "photoshoots_used": active_count,
            "remaining_photoshoots": max(rules.max_photoshoots - active_count, 0),
            "monthly_limit": rules.monthly_limit,
            "plan_started_at": window_start,
            "plan_expires_at": window_end,
            "cycle_ends_at": cycle_ends_at,
        },
    }


@router.get("/{portfolio_id}", response_model=PortfolioResponse)
async def get_portfolio(
    portfolio_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    ensure_photographer(current_user)
    if not ObjectId.is_valid(portfolio_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid portfolio id")

    document = await db["portfolios"].find_one(
        {"_id": ObjectId(portfolio_id), "user_id": ObjectId(current_user.id)}
    )
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")
    return serialize_portfolio(document)


@router.put("/{portfolio_id}", response_model=PortfolioResponse)
async def update_portfolio(
    portfolio_id: str,
    payload: PortfolioUpdate,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    ensure_photographer(current_user)
    if not ObjectId.is_valid(portfolio_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid portfolio id")

    existing = await db["portfolios"].find_one(
        {"_id": ObjectId(portfolio_id), "user_id": ObjectId(current_user.id)}
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    await validate_portfolio_limits(
        payload,
        current_user,
        db,
        exclude_portfolio_id=portfolio_id,
        enforce_capacity=False,
    )
    updated_payload = prepare_portfolio_payload(payload, current_user.id)
    await db["portfolios"].update_one(
        {"_id": ObjectId(portfolio_id)},
        {"$set": updated_payload},
    )
    updated = await db["portfolios"].find_one({"_id": ObjectId(portfolio_id)})
    return serialize_portfolio(updated)


@router.delete("/{portfolio_id}", response_model=dict)
async def delete_portfolio(
    portfolio_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    ensure_photographer(current_user)
    if not ObjectId.is_valid(portfolio_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid portfolio id")

    result = await db["portfolios"].delete_one(
        {"_id": ObjectId(portfolio_id), "user_id": ObjectId(current_user.id)}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")
    return {"message": "Portfolio deleted successfully"}
