from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.database import Database

from app.core import get_current_active_user
from app.db.mongodb import get_database
from app.models.portfolio import (
    PortfolioCreate,
    PortfolioResponse,
    PortfolioUpdate,
    prepare_portfolio_payload,
    serialize_portfolio,
)
from app.models.user import UserInDB, UserRole

router = APIRouter()


def ensure_photographer(user: UserInDB) -> None:
    if user.role != UserRole.PHOTOGRAPHER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only photographers can manage portfolios",
        )


@router.post("", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    payload: PortfolioCreate,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    ensure_photographer(current_user)
    document = prepare_portfolio_payload(payload, current_user.id)
    document["created_at"] = datetime.utcnow()

    result = await db["portfolios"].insert_one(document)
    created = await db["portfolios"].find_one({"_id": result.inserted_id})
    return serialize_portfolio(created)


@router.get("", response_model=list[PortfolioResponse])
async def list_portfolios(
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    ensure_photographer(current_user)
    cursor = db["portfolios"].find({"user_id": ObjectId(current_user.id)}).sort("shoot_date", -1)
    documents = await cursor.to_list(length=None)
    return [serialize_portfolio(doc) for doc in documents]


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
