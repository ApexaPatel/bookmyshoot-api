from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from pymongo.database import Database

from app.core.password import get_password_hash
from app.core.security import get_current_admin_user
from app.db.mongodb import get_database
from app.models.user import UserInDB, UserRole

router = APIRouter(prefix="/admin")


def _oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail="Invalid id")
    return ObjectId(value)


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class DashboardSummary(BaseModel):
    new_photographers: int
    new_customers: int
    subscriptions_count: int
    total_shoots_booked: int


class DashboardGraphPoint(BaseModel):
    date: str
    photographers: int
    customers: int
    shoots: int
    subscriptions: int


class EventStat(BaseModel):
    event_type: str
    count: int


class PagedResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: List[Dict[str, Any]]


class AdminUserCreate(BaseModel):
    full_name: str = Field(..., min_length=2)
    email: EmailStr
    phone: str = Field(..., min_length=10, max_length=15)
    role: UserRole = UserRole.CUSTOMER
    password: str = Field(..., min_length=8)


class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, min_length=10, max_length=15)
    is_active: Optional[bool] = None
    role: Optional[UserRole] = None


class RoleUpdateBody(BaseModel):
    role: UserRole


class ExpenseCreate(BaseModel):
    title: str = Field(..., min_length=2)
    amount: float = Field(..., gt=0)
    description: Optional[str] = None


class ExpenseUpdate(BaseModel):
    title: Optional[str] = None
    amount: Optional[float] = Field(None, gt=0)
    description: Optional[str] = None


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    now = datetime.utcnow()
    month_start = _month_start(now)

    users = db["users"]
    bookings = db["bookings"]
    subscriptions = db["subscriptions"]

    new_photographers = await users.count_documents(
        {
            "role": UserRole.PHOTOGRAPHER.value,
            "is_deleted": {"$ne": True},
            "created_at": {"$gte": month_start},
        }
    )
    new_customers = await users.count_documents(
        {
            "role": UserRole.CUSTOMER.value,
            "is_deleted": {"$ne": True},
            "created_at": {"$gte": month_start},
        }
    )
    subscriptions_count = await subscriptions.count_documents(
        {"created_at": {"$gte": month_start}, "status": "success"}
    )
    total_shoots_booked = await bookings.count_documents({"created_at": {"$gte": month_start}})

    return DashboardSummary(
        new_photographers=new_photographers,
        new_customers=new_customers,
        subscriptions_count=subscriptions_count,
        total_shoots_booked=total_shoots_booked,
    )


@router.get("/dashboard/graph", response_model=List[DashboardGraphPoint])
async def dashboard_graph(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    users = db["users"]
    bookings = db["bookings"]
    subscriptions = db["subscriptions"]

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=29)

    user_pipeline = [
        {"$match": {"created_at": {"$gte": start}, "is_deleted": {"$ne": True}}},
        {
            "$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                "photographers": {
                    "$sum": {"$cond": [{"$eq": ["$role", UserRole.PHOTOGRAPHER.value]}, 1, 0]}
                },
                "customers": {
                    "$sum": {"$cond": [{"$eq": ["$role", UserRole.CUSTOMER.value]}, 1, 0]}
                },
            }
        },
    ]
    booking_pipeline = [
        {"$match": {"created_at": {"$gte": start}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}}, "count": {"$sum": 1}}},
    ]
    subscription_pipeline = [
        {"$match": {"created_at": {"$gte": start}, "status": "success"}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}}, "count": {"$sum": 1}}},
    ]

    user_rows = await users.aggregate(user_pipeline).to_list(length=60)
    booking_rows = await bookings.aggregate(booking_pipeline).to_list(length=60)
    subscription_rows = await subscriptions.aggregate(subscription_pipeline).to_list(length=60)

    user_map = {
        r["_id"]: {
            "photographers": int(r.get("photographers") or 0),
            "customers": int(r.get("customers") or 0),
        }
        for r in user_rows
    }
    booking_map = {r["_id"]: int(r["count"]) for r in booking_rows}
    subscription_map = {r["_id"]: int(r["count"]) for r in subscription_rows}

    out: List[DashboardGraphPoint] = []
    for i in range(30):
        d = start + timedelta(days=i)
        key = d.strftime("%Y-%m-%d")
        out.append(
            DashboardGraphPoint(
                date=key,
                photographers=user_map.get(key, {}).get("photographers", 0),
                customers=user_map.get(key, {}).get("customers", 0),
                shoots=booking_map.get(key, 0),
                subscriptions=subscription_map.get(key, 0),
            )
        )
    return out


@router.get("/dashboard/event-stats", response_model=List[EventStat])
async def dashboard_event_stats(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    bookings = db["bookings"]
    rows = await bookings.aggregate(
        [
            {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
    ).to_list(length=100)
    return [EventStat(event_type=str(r.get("_id") or "unknown"), count=int(r.get("count") or 0)) for r in rows]


@router.get("/users", response_model=PagedResponse)
async def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    sort: Literal["newest", "oldest"] = Query("newest"),
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    users = db["users"]
    query: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if role:
        query["role"] = role
    if search:
        query["$or"] = [
            {"full_name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
        ]

    direction = -1 if sort == "newest" else 1
    skip = (page - 1) * limit
    total = await users.count_documents(query)
    rows = await users.find(query).sort("created_at", direction).skip(skip).limit(limit).to_list(length=limit)
    for r in rows:
        r["id"] = str(r.pop("_id"))
    return PagedResponse(total=total, page=page, limit=limit, items=rows)


@router.post("/users")
async def create_user_admin(
    payload: AdminUserCreate,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    users = db["users"]
    existing = await users.find_one({"email": payload.email.lower(), "is_deleted": {"$ne": True}})
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")
    now = datetime.utcnow()
    doc = {
        "full_name": payload.full_name,
        "email": payload.email.lower(),
        "phone": payload.phone,
        "bio": None,
        "profile_picture": None,
        "cover_image": None,
        "is_active": True,
        "is_verified": False,
        "role": payload.role.value,
        "hashed_password": get_password_hash(payload.password),
        "photographer_plan": "free",
        "plan_started_at": None,
        "plan_expires_at": None,
        "is_part_of_organization": False,
        "organization_id": None,
        "preferences": {},
        "is_deleted": False,
        "created_at": now,
        "updated_at": now,
    }
    res = await users.insert_one(doc)
    return {"id": str(res.inserted_id), "message": "User created"}


@router.put("/users/{user_id}")
async def update_user_admin(
    user_id: str,
    payload: AdminUserUpdate,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    updates = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    if not updates:
        return {"message": "No changes"}
    updates["updated_at"] = datetime.utcnow()
    res = await db["users"].update_one({"_id": _oid(user_id), "is_deleted": {"$ne": True}}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User updated"}


@router.patch("/users/{user_id}/role")
async def patch_user_role(
    user_id: str,
    payload: RoleUpdateBody,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    res = await db["users"].update_one(
        {"_id": _oid(user_id), "is_deleted": {"$ne": True}},
        {"$set": {"role": payload.role.value, "updated_at": datetime.utcnow()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Role updated"}


@router.delete("/users/{user_id}")
async def delete_user_admin(
    user_id: str,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    res = await db["users"].update_one(
        {"_id": _oid(user_id), "is_deleted": {"$ne": True}},
        {"$set": {"is_deleted": True, "updated_at": datetime.utcnow()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User soft deleted"}


@router.get("/photographers", response_model=PagedResponse)
async def list_photographers(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    plan: Optional[str] = Query(None),
    sort: Literal["newest", "oldest"] = Query("newest"),
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    query: Dict[str, Any] = {"is_deleted": {"$ne": True}, "role": UserRole.PHOTOGRAPHER.value}
    if plan:
        query["photographer_plan"] = plan
    if search:
        query["$or"] = [
            {"full_name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
        ]
    direction = -1 if sort == "newest" else 1
    skip = (page - 1) * limit
    users = db["users"]
    total = await users.count_documents(query)
    rows = await users.find(query).sort("created_at", direction).skip(skip).limit(limit).to_list(length=limit)
    for r in rows:
        r["id"] = str(r.pop("_id"))
    return PagedResponse(total=total, page=page, limit=limit, items=rows)


@router.post("/photographers")
async def create_photographer_admin(
    payload: AdminUserCreate,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    p = AdminUserCreate(**{**payload.dict(), "role": UserRole.PHOTOGRAPHER})
    return await create_user_admin(p, _, db)


@router.put("/photographers/{user_id}")
async def update_photographer_admin(
    user_id: str,
    payload: AdminUserUpdate,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    return await update_user_admin(user_id, payload, _, db)


@router.delete("/photographers/{user_id}")
async def delete_photographer_admin(
    user_id: str,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    return await delete_user_admin(user_id, _, db)


@router.get("/payments/summary")
async def payments_summary(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    now = datetime.utcnow()
    month_start = _month_start(now)

    subscriptions = db["subscriptions"]
    bookings = db["bookings"]
    expenses = db["expenses"]

    sub_month = await subscriptions.aggregate(
        [{"$match": {"created_at": {"$gte": month_start}, "status": "success"}}, {"$group": {"_id": None, "v": {"$sum": "$amount"}}}]
    ).to_list(length=1)
    photo_month = await bookings.aggregate(
        [{"$match": {"created_at": {"$gte": month_start}}}, {"$group": {"_id": None, "v": {"$sum": "$total_amount"}}}]
    ).to_list(length=1)
    exp_month = await expenses.aggregate(
        [{"$match": {"created_at": {"$gte": month_start}, "is_deleted": {"$ne": True}}}, {"$group": {"_id": None, "v": {"$sum": "$amount"}}}]
    ).to_list(length=1)

    total_revenue = float((sub_month[0]["v"] if sub_month else 0) or 0)
    photoshoot_revenue = float((photo_month[0]["v"] if photo_month else 0) or 0)
    total_expenses = float((exp_month[0]["v"] if exp_month else 0) or 0)
    current_balance = total_revenue + photoshoot_revenue - total_expenses

    return {
        "current_balance": current_balance,
        "total_revenue_month": total_revenue,
        "total_expenses_month": total_expenses,
        "photoshoot_revenue_month": photoshoot_revenue,
    }


@router.get("/payments/subscriptions")
async def payments_subscriptions(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    skip = (page - 1) * limit
    col = db["subscriptions"]
    total = await col.count_documents({})
    rows = await col.find().sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
    for r in rows:
        r["id"] = str(r.pop("_id"))
    return {"total": total, "page": page, "limit": limit, "items": rows}


@router.get("/payments/photoshoots")
async def payments_photoshoots(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    skip = (page - 1) * limit
    col = db["bookings"]
    total = await col.count_documents({})
    rows = await col.find().sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
    for r in rows:
        r["id"] = str(r.pop("_id"))
    return {"total": total, "page": page, "limit": limit, "items": rows}


@router.get("/payments/expenses")
async def payments_expenses(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    skip = (page - 1) * limit
    col = db["expenses"]
    query = {"is_deleted": {"$ne": True}}
    total = await col.count_documents(query)
    rows = await col.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
    for r in rows:
        r["id"] = str(r.pop("_id"))
    return {"total": total, "page": page, "limit": limit, "items": rows}


@router.post("/expenses")
async def create_expense(
    payload: ExpenseCreate,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    now = datetime.utcnow()
    expense_doc = {
        "title": payload.title,
        "amount": payload.amount,
        "description": payload.description,
        "is_deleted": False,
        "created_at": now,
        "updated_at": now,
    }
    res = await db["expenses"].insert_one(expense_doc)
    await db["payments_ledger"].insert_one(
        {
            "type": "expense",
            "amount": payload.amount,
            "direction": "debit",
            "reference_id": str(res.inserted_id),
            "created_at": now,
        }
    )
    return {"id": str(res.inserted_id), "message": "Expense created"}


@router.put("/expenses/{expense_id}")
async def update_expense(
    expense_id: str,
    payload: ExpenseUpdate,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    updates = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    if not updates:
        return {"message": "No changes"}
    updates["updated_at"] = datetime.utcnow()
    res = await db["expenses"].update_one(
        {"_id": _oid(expense_id), "is_deleted": {"$ne": True}},
        {"$set": updates},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"message": "Expense updated"}


@router.delete("/expenses/{expense_id}")
async def delete_expense(
    expense_id: str,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    res = await db["expenses"].update_one(
        {"_id": _oid(expense_id), "is_deleted": {"$ne": True}},
        {"$set": {"is_deleted": True, "updated_at": datetime.utcnow()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"message": "Expense soft deleted"}
