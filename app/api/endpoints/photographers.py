from datetime import datetime
from typing import List, Optional, Any, Dict
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pymongo.database import Database
from pydantic import BaseModel, Field
from jose import JWTError, jwt

from app.db.mongodb import get_database
from app.models.portfolio import serialize_portfolio
from app.core.config import settings
from app.core.security import get_current_active_user
from app.models.user import UserInDB
from app.crud.user import CRUDUser

router = APIRouter()
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False)


class ReviewEligibilityResponse(BaseModel):
    can_review: bool
    reason: Optional[str] = None
    booking_context: Optional[Dict[str, Any]] = None


class ReviewCreateBody(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None


class VisibilityUpdateBody(BaseModel):
    visibility: str = Field(..., regex="^(private|public)$")


async def _get_optional_user(token: Optional[str], db: Database) -> Optional[UserInDB]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if not email:
            return None
    except JWTError:
        return None
    user = await CRUDUser(db).get_by_email(email)
    return user


async def _get_review_eligibility(db: Database, user: Optional[UserInDB], photographer_oid: ObjectId) -> ReviewEligibilityResponse:
    if not user:
        return ReviewEligibilityResponse(can_review=False, reason="NOT_LOGGED_IN")

    bookings_col = db["bookings"]
    any_booking = await bookings_col.find_one(
        {"customer_id": ObjectId(user.id), "photographer_id": photographer_oid}
    )
    if not any_booking:
        return ReviewEligibilityResponse(can_review=False, reason="NO_BOOKING")

    completed_booking = await bookings_col.find_one(
        {
            "customer_id": ObjectId(user.id),
            "photographer_id": photographer_oid,
            "status": "completed",
        },
        sort=[("updated_at", -1), ("created_at", -1)],
    )
    if not completed_booking:
        return ReviewEligibilityResponse(can_review=False, reason="NOT_COMPLETED")

    booking_context = {
        "booking_id": str(completed_booking.get("_id")),
        "completed_at": completed_booking.get("updated_at") or completed_booking.get("created_at"),
        "status": completed_booking.get("status"),
    }
    return ReviewEligibilityResponse(can_review=True, booking_context=booking_context)


async def _refresh_photographer_rating(db: Database, photographer_oid: ObjectId) -> None:
    rows = await db["reviews"].aggregate(
        [
            {"$match": {"photographer_id": photographer_oid}},
            {"$group": {"_id": None, "avg": {"$avg": "$rating"}, "count": {"$sum": 1}}},
        ]
    ).to_list(length=1)
    avg_rating = float(rows[0].get("avg") or 0.0) if rows else 0.0
    total_reviews = int(rows[0].get("count") or 0) if rows else 0
    await db["users"].update_one(
        {"_id": photographer_oid},
        {"$set": {"rating": round(avg_rating, 1), "total_reviews": total_reviews, "updated_at": datetime.utcnow()}},
    )


@router.get("", response_model=dict)
async def list_photographers(db: Database = Depends(get_database)):
    """
    Public API: list photographers with populated organization (name, location).
    Only active users with role=photographer are returned.
    """
    users = db["users"]
    pipeline = [
        {"$match": {"role": "photographer", "is_active": True, "visibility": "public"}},
        {"$sort": {"created_at": -1}},
        {
            "$lookup": {
                "from": "organizations",
                "localField": "organization_id",
                "foreignField": "_id",
                "as": "_org",
            }
        },
        {
            "$lookup": {
                "from": "portfolios",
                "let": {"uid": "$_id"},
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$user_id", "$$uid"]}}},
                    {"$project": {"event_name": 1, "city": 1, "destinations": 1}},
                ],
                "as": "_portfolios",
            }
        },
        {
            "$addFields": {
                "portfolio_events": {
                    "$map": {
                        "input": "$_portfolios",
                        "as": "p",
                        "in": {"$toLower": {"$trim": {"input": {"$ifNull": ["$$p.event_name", ""]}}}},
                    }
                },
                "portfolio_cities": {
                    "$filter": {
                        "input": {
                            "$reduce": {
                                "input": "$_portfolios",
                                "initialValue": [],
                                "in": {
                                    "$concatArrays": [
                                        "$$value",
                                        [{"$toLower": {"$trim": {"input": {"$ifNull": ["$$this.city", ""]}}}}],
                                        {
                                            "$map": {
                                                "input": {"$ifNull": ["$$this.destinations", []]},
                                                "as": "d",
                                                "in": {"$toLower": {"$trim": {"input": "$$d"}}},
                                            }
                                        },
                                    ]
                                },
                            }
                        },
                        "as": "x",
                        "cond": {"$gt": [{"$strLenCP": "$$x"}, 0]},
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 1,
                "full_name": 1,
                "email": 1,
                "bio": 1,
                "location": 1,
                "profile_picture": 1,
                "cover_image": 1,
                "rating": 1,
                "total_reviews": 1,
                "is_part_of_organization": 1,
                "organization_id": 1,
                "visibility": 1,
                "portfolio_events": 1,
                "portfolio_cities": 1,
                "organizationId": {
                    "$cond": {
                        "if": {"$eq": [{"$size": "$_org"}, 1]},
                        "then": {
                            "name": {"$arrayElemAt": ["$_org.name", 0]},
                            "location": {"$arrayElemAt": ["$_org.location", 0]},
                        },
                        "else": None,
                    }
                },
            }
        },
    ]
    cursor = users.aggregate(pipeline)
    photographers: List[dict] = []
    async for doc in cursor:
        raw_events = doc.get("portfolio_events") or []
        portfolio_events = sorted({str(x).strip().lower() for x in raw_events if str(x).strip()})
        raw_cities = doc.get("portfolio_cities") or []
        portfolio_cities = sorted({str(x).strip().lower() for x in raw_cities if str(x).strip()})
        photographers.append({
            "id": str(doc["_id"]),
            "name": doc.get("full_name") or doc.get("name", ""),
            "email": doc.get("email", ""),
            "bio": doc.get("bio"),
            "location": (doc.get("location") or "").strip() or None,
            "profile_picture": doc.get("profile_picture"),
            "cover_image": doc.get("cover_image"),
            "rating": float(doc.get("rating") or 0),
            "total_reviews": int(doc.get("total_reviews") or 0),
            "is_part_of_organization": doc.get("is_part_of_organization", False),
            "organization_id": str(doc["organization_id"]) if doc.get("organization_id") else None,
            "visibility": doc.get("visibility") or "private",
            "organizationId": doc.get("organizationId"),
            "portfolio_events": portfolio_events,
            "portfolio_cities": portfolio_cities,
        })
    return {"photographers": photographers}


@router.get("/{photographer_id}", response_model=dict)
async def get_photographer_details(photographer_id: str, db: Database = Depends(get_database)):
    if not ObjectId.is_valid(photographer_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid photographer id")

    pipeline = [
        {"$match": {"_id": ObjectId(photographer_id), "role": "photographer", "is_active": True}},
        {
            "$lookup": {
                "from": "organizations",
                "localField": "organization_id",
                "foreignField": "_id",
                "as": "_org",
            }
        },
        {
            "$project": {
                "_id": 1,
                "full_name": 1,
                "email": 1,
                "bio": 1,
                "profile_picture": 1,
                "cover_image": 1,
                "rating": 1,
                "total_reviews": 1,
                "organization": {
                    "$cond": {
                        "if": {"$eq": [{"$size": "$_org"}, 1]},
                        "then": {
                            "id": {"$toString": {"$arrayElemAt": ["$_org._id", 0]}},
                            "name": {"$arrayElemAt": ["$_org.name", 0]},
                            "location": {"$arrayElemAt": ["$_org.location", 0]},
                        },
                        "else": None,
                    }
                },
            }
        },
    ]
    docs = await db["users"].aggregate(pipeline).to_list(length=1)
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photographer not found")

    doc = docs[0]
    return {
        "photographer": {
            "id": str(doc["_id"]),
            "name": doc.get("full_name") or "",
            "email": doc.get("email"),
            "bio": doc.get("bio"),
            "profile_picture": doc.get("profile_picture"),
            "cover_image": doc.get("cover_image"),
            "rating": float(doc.get("rating") or 0),
            "total_reviews": int(doc.get("total_reviews") or 0),
            "organization": doc.get("organization"),
        }
    }


@router.get("/{photographer_id}/portfolios", response_model=dict)
async def get_photographer_portfolios(photographer_id: str, db: Database = Depends(get_database)):
    if not ObjectId.is_valid(photographer_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid photographer id")

    docs = await db["portfolios"].find({"user_id": ObjectId(photographer_id)}).sort("shoot_date", -1).to_list(length=None)
    return {"portfolios": [serialize_portfolio(doc).dict() for doc in docs]}


@router.get("/{photographer_id}/events", response_model=dict)
async def get_photographer_events(photographer_id: str, db: Database = Depends(get_database)):
    if not ObjectId.is_valid(photographer_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid photographer id")

    events = await db["portfolios"].distinct("event_name", {"user_id": ObjectId(photographer_id)})
    return {"events": sorted([event for event in events if isinstance(event, str) and event.strip()])}


@router.get("/{photographer_id}/gallery", response_model=dict)
async def get_photographer_gallery(
    photographer_id: str,
    event: str,
    location: Optional[str] = None,
    db: Database = Depends(get_database),
):
    if not ObjectId.is_valid(photographer_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid photographer id")
    if not event or not event.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Event query is required")

    query = {"user_id": ObjectId(photographer_id), "event_name": event.strip()}
    if location and location.strip():
        locations = [item.strip() for item in location.split(",") if item.strip()]
        if locations:
            query["city"] = {"$in": locations}

    docs = await db["portfolios"].find(
        query,
        {"gallery": 1, "event_name": 1, "shoot_date": 1, "city": 1},
    ).sort("shoot_date", -1).to_list(length=None)

    images = []
    for doc in docs:
        for image in doc.get("gallery", []):
            images.append(
                {
                    "url": image.get("url"),
                    "is_thumbnail": image.get("is_thumbnail", False),
                    "event_name": doc.get("event_name"),
                    "shoot_date": doc.get("shoot_date"),
                    "city": doc.get("city"),
                }
            )

    return {"images": images}


@router.get("/{photographer_id}/reviews", response_model=dict)
async def get_photographer_reviews(
    photographer_id: str,
    limit: int = 20,
    db: Database = Depends(get_database),
):
    if not ObjectId.is_valid(photographer_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid photographer id")

    rows = await db["reviews"].find({"photographer_id": ObjectId(photographer_id)}).sort("created_at", -1).limit(limit).to_list(length=limit)
    reviewer_ids = [r.get("user_id") for r in rows if r.get("user_id")]
    users_map: Dict[str, str] = {}
    if reviewer_ids:
        users = await db["users"].find({"_id": {"$in": reviewer_ids}}, {"full_name": 1}).to_list(length=len(reviewer_ids))
        users_map = {str(u["_id"]): u.get("full_name") or "User" for u in users}

    reviews = []
    for r in rows:
        reviewer_id = str(r.get("user_id")) if r.get("user_id") else None
        reviews.append(
            {
                "id": str(r.get("_id")),
                "photographer_id": str(r.get("photographer_id")),
                "user_id": reviewer_id,
                "reviewer_name": users_map.get(reviewer_id, "User"),
                "booking_id": str(r.get("booking_id")) if r.get("booking_id") else None,
                "rating": int(r.get("rating") or 0),
                "comment": r.get("comment"),
                "created_at": r.get("created_at"),
                "updated_at": r.get("updated_at"),
            }
        )
    return {"reviews": reviews}


@router.get("/{photographer_id}/review-eligibility", response_model=ReviewEligibilityResponse)
async def get_review_eligibility(
    photographer_id: str,
    token: Optional[str] = Depends(optional_oauth2_scheme),
    db: Database = Depends(get_database),
):
    if not ObjectId.is_valid(photographer_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid photographer id")
    user = await _get_optional_user(token, db)
    return await _get_review_eligibility(db, user, ObjectId(photographer_id))


@router.post("/{photographer_id}/review", response_model=dict)
async def upsert_review(
    photographer_id: str,
    body: ReviewCreateBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    if not ObjectId.is_valid(photographer_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid photographer id")
    photographer_oid = ObjectId(photographer_id)

    eligibility = await _get_review_eligibility(db, current_user, photographer_oid)
    if not eligibility.can_review:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can only review photographers after completing a booking",
        )

    reviews_col = db["reviews"]
    booking_id = ObjectId(eligibility.booking_context["booking_id"]) if eligibility.booking_context else None
    now = datetime.utcnow()
    existing = await reviews_col.find_one({"photographer_id": photographer_oid, "user_id": ObjectId(current_user.id)})

    comment = body.comment.strip() if body.comment else None
    if existing:
        await reviews_col.update_one(
            {"_id": existing["_id"]},
            {"$set": {"rating": body.rating, "comment": comment, "booking_id": booking_id, "updated_at": now}},
        )
        review_id = str(existing["_id"])
    else:
        res = await reviews_col.insert_one(
            {
                "photographer_id": photographer_oid,
                "user_id": ObjectId(current_user.id),
                "booking_id": booking_id,
                "rating": body.rating,
                "comment": comment,
                "created_at": now,
                "updated_at": now,
            }
        )
        review_id = str(res.inserted_id)

    await _refresh_photographer_rating(db, photographer_oid)
    return {"message": "Review submitted", "review_id": review_id}


@router.patch("/me/visibility", response_model=dict)
async def update_my_visibility(
    body: VisibilityUpdateBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    if current_user.role != "photographer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only photographers can update visibility")

    visibility_value = body.visibility.strip().lower()
    if visibility_value not in {"private", "public"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid visibility value")

    await db["users"].update_one(
        {"_id": ObjectId(current_user.id), "role": "photographer"},
        {"$set": {"visibility": visibility_value, "updated_at": datetime.utcnow()}},
    )
    return {"message": "Visibility updated", "visibility": visibility_value}
