from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.database import Database

from app.crud.organization import CRUDOrganization, get_organization_crud
from app.models.organization import OrganizationCreate, OrganizationResponse
from app.db.mongodb import get_database

router = APIRouter()


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    org_crud: CRUDOrganization = Depends(get_organization_crud),
):
    """Create a new organization. Returns the created organization with _id."""
    if not data.name or not data.name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization name is required",
        )
    org = await org_crud.create({
        "name": data.name.strip(),
        "location": data.location and data.location.strip() or None,
        "contact_number": data.contact_number and data.contact_number.strip() or None,
    })
    return OrganizationResponse(**org.dict(by_alias=False))


@router.get("", response_model=dict)
async def list_organizations(db: Database = Depends(get_database)):
    pipeline = [
        {
            "$lookup": {
                "from": "users",
                "localField": "_id",
                "foreignField": "organization_id",
                "as": "photographers",
            }
        },
        {
            "$project": {
                "_id": 1,
                "name": 1,
                "location": 1,
                "contact_number": 1,
                "created_at": 1,
                "photographer_count": {
                    "$size": {
                        "$filter": {
                            "input": "$photographers",
                            "as": "photographer",
                            "cond": {
                                "$and": [
                                    {"$eq": ["$$photographer.role", "photographer"]},
                                    {"$eq": ["$$photographer.is_active", True]},
                                ]
                            },
                        }
                    }
                },
            }
        },
        {"$sort": {"name": 1}},
    ]
    documents = await db["organizations"].aggregate(pipeline).to_list(length=None)
    return {
        "organizations": [
            {
                "id": str(doc["_id"]),
                "name": doc["name"],
                "location": doc.get("location"),
                "contact_number": doc.get("contact_number"),
                "photographer_count": doc.get("photographer_count", 0),
            }
            for doc in documents
        ]
    }


@router.get("/{organization_id}", response_model=dict)
async def get_organization_details(organization_id: str, db: Database = Depends(get_database)):
    if not ObjectId.is_valid(organization_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid organization id")

    pipeline = [
        {"$match": {"_id": ObjectId(organization_id)}},
        {
            "$lookup": {
                "from": "users",
                "localField": "_id",
                "foreignField": "organization_id",
                "as": "photographers",
            }
        },
        {
            "$project": {
                "_id": 1,
                "name": 1,
                "location": 1,
                "contact_number": 1,
                "photographers": {
                    "$map": {
                        "input": {
                            "$filter": {
                                "input": "$photographers",
                                "as": "photographer",
                                "cond": {
                                    "$and": [
                                        {"$eq": ["$$photographer.role", "photographer"]},
                                        {"$eq": ["$$photographer.is_active", True]},
                                    ]
                                },
                            }
                        },
                        "as": "photographer",
                        "in": {
                            "id": {"$toString": "$$photographer._id"},
                            "name": "$$photographer.full_name",
                            "email": "$$photographer.email",
                            "profile_picture": "$$photographer.profile_picture",
                            "cover_image": "$$photographer.cover_image",
                        },
                    }
                },
            }
        },
    ]
    documents = await db["organizations"].aggregate(pipeline).to_list(length=1)
    if not documents:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    doc = documents[0]
    return {
        "organization": {
            "id": str(doc["_id"]),
            "name": doc["name"],
            "location": doc.get("location"),
            "contact_number": doc.get("contact_number"),
            "photographer_count": len(doc.get("photographers", [])),
        },
        "photographers": doc.get("photographers", []),
    }


@router.get("/{organization_id}/photographers", response_model=dict)
async def get_organization_photographers(organization_id: str, db: Database = Depends(get_database)):
    if not ObjectId.is_valid(organization_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid organization id")

    photographers = await db["users"].find(
        {"organization_id": ObjectId(organization_id), "role": "photographer", "is_active": True},
        {"full_name": 1, "email": 1, "profile_picture": 1, "cover_image": 1},
    ).sort("full_name", 1).to_list(length=None)

    return {
        "photographers": [
            {
                "id": str(doc["_id"]),
                "name": doc.get("full_name") or "",
                "email": doc.get("email"),
                "profile_picture": doc.get("profile_picture"),
                "cover_image": doc.get("cover_image"),
            }
            for doc in photographers
        ]
    }
