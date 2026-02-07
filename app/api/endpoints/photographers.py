from typing import List, Optional, Any
from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.db.mongodb import get_database

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
                "profile_picture": 1,
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
            "profile_picture": doc.get("profile_picture"),
            "is_part_of_organization": doc.get("is_part_of_organization", False),
            "organization_id": str(doc["organization_id"]) if doc.get("organization_id") else None,
            "organizationId": doc.get("organizationId"),
        })
    return {"photographers": photographers}
