from typing import Optional
from datetime import datetime
from bson import ObjectId
from pymongo.database import Database
from fastapi import Depends

from app.models.organization import OrganizationInDB, OrganizationCreate
from app.db.mongodb import get_database


class CRUDOrganization:
    def __init__(self, db: Database):
        self.db = db
        self.collection = db["organizations"]

    async def create(self, data: dict) -> OrganizationInDB:
        now = datetime.utcnow()
        doc = {
            "_id": ObjectId(),
            "name": data["name"].strip(),
            "location": data.get("location") and data["location"].strip() or None,
            "contact_number": data.get("contact_number") and self._sanitize_contact(data["contact_number"]) or None,
            "created_at": now,
            "updated_at": now,
        }
        await self.collection.insert_one(doc)
        doc["id"] = str(doc.pop("_id"))
        return OrganizationInDB(**doc)

    def _sanitize_contact(self, value: str) -> str:
        return "".join(c for c in value if c.isdigit() or c in "+ ").strip() or value.strip()

    async def get_by_id(self, org_id: str) -> Optional[OrganizationInDB]:
        try:
            doc = await self.collection.find_one({"_id": ObjectId(org_id)})
            if not doc:
                return None
            doc["id"] = str(doc.pop("_id"))
            return OrganizationInDB(**doc)
        except Exception:
            return None


def get_organization_crud(db: Database = Depends(get_database)) -> CRUDOrganization:
    return CRUDOrganization(db)
