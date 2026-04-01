from typing import List, Optional, Any
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.database import Database

from app.db.mongodb import get_database
from app.models.portfolio import serialize_portfolio

router = APIRouter()


@router.get("", response_model=dict)
async def list_photographers(db: Database = Depends(get_database)):
    """
    Public API: list photographers with populated organization (name, location).
    Only active users with role=photographer are returned.
    """
    users = db["users"]
    pipeline = [
        {"$match": {"role": "photographer", "is_active": True}},
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
            "$project": {
                "_id": 1,
                "full_name": 1,
                "email": 1,
                "bio": 1,
                "profile_picture": 1,
                "cover_image": 1,
                "is_part_of_organization": 1,
                "organization_id": 1,
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
        photographers.append({
            "id": str(doc["_id"]),
            "name": doc.get("full_name") or doc.get("name", ""),
            "email": doc.get("email", ""),
            "bio": doc.get("bio"),
            "profile_picture": doc.get("profile_picture"),
            "cover_image": doc.get("cover_image"),
            "is_part_of_organization": doc.get("is_part_of_organization", False),
            "organization_id": str(doc["organization_id"]) if doc.get("organization_id") else None,
            "organizationId": doc.get("organizationId"),
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
