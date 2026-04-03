"""Demo subscription / simulated payment records in MongoDB."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymongo.database import Database


class CRUDSubscription:
    def __init__(self, db: Database):
        self._col = db["subscriptions"]

    async def insert(
        self,
        *,
        user_id: str,
        plan: str,
        amount: float,
        status: str,
        payment_id: str,
        start_date: datetime,
        expiry_date: Optional[datetime],
    ) -> str:
        doc: Dict[str, Any] = {
            "user_id": user_id,
            "plan": plan,
            "amount": amount,
            "status": status,
            "payment_id": payment_id,
            "start_date": start_date,
            "expiry_date": expiry_date,
            "created_at": datetime.utcnow(),
        }
        res = await self._col.insert_one(doc)
        return str(res.inserted_id)

    async def list_recent(self, limit: int = 500) -> List[Dict[str, Any]]:
        cursor = self._col.find().sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def count_all(self) -> int:
        return await self._col.count_documents({})

    async def count_active_success(self, now: datetime) -> int:
        return await self._col.count_documents(
            {
                "status": "success",
                "expiry_date": {"$gt": now},
            }
        )

    async def sum_revenue_success(self) -> float:
        pipeline = [
            {"$match": {"status": "success"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]
        agg = await self._col.aggregate(pipeline).to_list(length=1)
        if not agg:
            return 0.0
        return float(agg[0].get("total") or 0)


def user_display_map(users: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for u in users:
        oid = u.get("_id")
        if oid is None:
            continue
        sid = str(oid)
        out[sid] = {
            "full_name": u.get("full_name") or "—",
            "email": u.get("email") or "—",
        }
    return out
