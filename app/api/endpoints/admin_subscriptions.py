"""Admin-only subscription metrics and listing (demo billing)."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from pymongo.database import Database

from app.core.security import get_current_superuser
from app.crud.subscription import CRUDSubscription, user_display_map
from app.crud.user import get_user_crud, CRUDUser
from app.db.mongodb import get_database
from app.models.user import UserInDB

router = APIRouter(prefix="/admin")


class SubscriptionMetrics(BaseModel):
    total_subscriptions: int
    active_subscriptions: int
    revenue_demo_total_inr: float


class AdminSubscriptionRow(BaseModel):
    id: str
    user_id: str
    user_name: str
    user_email: str
    plan: str
    amount: float
    status: str
    payment_id: str
    start_date: datetime
    expiry_date: Optional[datetime]
    created_at: datetime


@router.get("/subscriptions/metrics", response_model=SubscriptionMetrics)
async def subscription_metrics(
    _: UserInDB = Depends(get_current_superuser),
    db: Database = Depends(get_database),
):
    crud = CRUDSubscription(db)
    now = datetime.utcnow()
    total = await crud.count_all()
    active = await crud.count_active_success(now)
    revenue = await crud.sum_revenue_success()
    return SubscriptionMetrics(
        total_subscriptions=total,
        active_subscriptions=active,
        revenue_demo_total_inr=revenue,
    )


@router.get("/subscriptions", response_model=List[AdminSubscriptionRow])
async def list_subscriptions(
    _: UserInDB = Depends(get_current_superuser),
    db: Database = Depends(get_database),
    user_crud: CRUDUser = Depends(get_user_crud),
):
    crud = CRUDSubscription(db)
    rows = await crud.list_recent(500)
    oids: List[ObjectId] = []
    for r in rows:
        uid = r.get("user_id")
        if uid and ObjectId.is_valid(str(uid)):
            oids.append(ObjectId(str(uid)))

    users_by_id: Dict[str, Dict[str, str]] = {}
    if oids:
        cursor = user_crud.collection.find({"_id": {"$in": oids}})
        ulist = await cursor.to_list(length=len(oids))
        users_by_id = user_display_map(ulist)

    out: List[AdminSubscriptionRow] = []
    for r in rows:
        oid = str(r.get("_id"))
        uid = str(r.get("user_id", ""))
        disp = users_by_id.get(uid, {"full_name": "—", "email": "—"})
        out.append(
            AdminSubscriptionRow(
                id=oid,
                user_id=uid,
                user_name=disp["full_name"],
                user_email=disp["email"],
                plan=str(r.get("plan", "")),
                amount=float(r.get("amount") or 0),
                status=str(r.get("status", "")),
                payment_id=str(r.get("payment_id", "")),
                start_date=r.get("start_date") or datetime.utcnow(),
                expiry_date=r.get("expiry_date"),
                created_at=r.get("created_at") or datetime.utcnow(),
            )
        )
    return out
