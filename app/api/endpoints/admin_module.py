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


def _json_safe(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


class DashboardSummary(BaseModel):
    new_photographers: int
    new_customers: int
    subscriptions_count: int
    memberships_count: int
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


class PhotographerPricingUpdate(BaseModel):
    base_price: Optional[float] = None
    price_per_hour: Optional[float] = None
    base_prices: Optional[Dict[str, float]] = None
    location_multipliers: Optional[Dict[str, float]] = None
    feature_prices: Optional[Dict[str, float]] = None
    tags: Optional[List[str]] = None
    event_specialties: Optional[List[str]] = None
    service_locations: Optional[List[str]] = None
    rating: Optional[float] = None
    experience_years: Optional[int] = None


class PastShootCreate(BaseModel):
    photographer_id: str
    event_type: str
    location: str
    duration_hours: float = Field(..., gt=0)
    features: List[str] = Field(default_factory=list)
    final_price: float = Field(..., gt=0)
    date: datetime


class PlanUpdateBody(BaseModel):
    price: Optional[float] = Field(None, ge=0)
    billing_cycle: Optional[str] = None
    features: Optional[List[str]] = None
    is_active: Optional[bool] = None
    max_bids: Optional[int] = Field(None, ge=0)
    portfolio_limit: Optional[int] = Field(None, ge=0)
    priority_weight: Optional[int] = Field(None, ge=0)


class MembershipUpdateBody(BaseModel):
    price: Optional[float] = Field(None, ge=0)
    duration_days: Optional[int] = Field(None, ge=1)
    features: Optional[List[str]] = None
    is_active: Optional[bool] = None


def _default_plans() -> List[Dict[str, Any]]:
    now = datetime.utcnow()
    return [
        {
            "id": "free",
            "name": "free",
            "price": 0,
            "billing_cycle": "monthly",
            "features": ["basic_profile", "direct_booking", "limited_visibility", "portfolio_10_shoots_5_images"],
            "is_active": True,
            "max_bids": 0,
            "portfolio_limit": 10,
            "priority_weight": 0,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "pro",
            "name": "pro",
            "price": 299,
            "billing_cycle": "monthly",
            "features": ["access_auction", "place_bid", "multiple_bids", "higher_visibility", "portfolio_extended"],
            "is_active": True,
            "max_bids": 20,
            "portfolio_limit": 20,
            "priority_weight": 0,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "premium",
            "name": "premium",
            "price": 399,
            "billing_cycle": "monthly",
            "features": [
                "access_auction",
                "place_bid",
                "priority_ranking",
                "high_visibility",
                "advanced_analytics",
                "featured_badge",
            ],
            "is_active": True,
            "max_bids": 9999,
            "portfolio_limit": 28,
            "priority_weight": 15,
            "created_at": now,
            "updated_at": now,
        },
    ]


def _default_membership() -> Dict[str, Any]:
    now = datetime.utcnow()
    return {
        "id": "membership",
        "price": 999,
        "duration_days": 365,
        "features": ["10_percent_discount", "auction_access", "priority_booking_experience"],
        "is_active": True,
        "updated_at": now,
        "created_at": now,
    }


async def _ensure_plan_membership_seed(db: Database) -> None:
    plans_col = db["plans"]
    for plan in _default_plans():
        existing = await plans_col.find_one({"name": plan["name"]})
        if not existing:
            await plans_col.insert_one(plan)
    membership_col = db["membership_config"]
    existing_membership = await membership_col.find_one({"id": "membership"})
    if not existing_membership:
        await membership_col.insert_one(_default_membership())


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
    ledger = db["payments_ledger"]

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
    memberships_count = await ledger.count_documents(
        {"type": "membership", "direction": "credit", "created_at": {"$gte": month_start}}
    )
    total_shoots_booked = await bookings.count_documents({"created_at": {"$gte": month_start}})

    return DashboardSummary(
        new_photographers=new_photographers,
        new_customers=new_customers,
        subscriptions_count=subscriptions_count,
        memberships_count=memberships_count,
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


@router.get("/users/{user_id}/details")
async def user_details_admin(
    user_id: str,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    users_col = db["users"]
    user_doc = await users_col.find_one({"_id": _oid(user_id), "is_deleted": {"$ne": True}})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    auctions = await db["auctions"].find({"user_id": user_doc["_id"]}).sort("created_at", -1).to_list(length=500)
    bookings = await db["bookings"].find(
        {"$or": [{"user_id": user_doc["_id"]}, {"customer_id": user_doc["_id"]}]}
    ).sort("event_date", -1).to_list(length=500)
    quotations = await db["quotations"].find({"user_id": user_doc["_id"]}).sort("created_at", -1).to_list(length=500)

    photographer_ids = {b.get("photographer_id") for b in bookings if b.get("photographer_id")} | {
        q.get("photographer_id") for q in quotations if q.get("photographer_id")
    }
    photographer_rows = []
    if photographer_ids:
        photographer_rows = await users_col.find({"_id": {"$in": list(photographer_ids)}}).to_list(length=1000)
    photographer_map = {str(p["_id"]): p for p in photographer_rows if p.get("_id")}

    auction_ids = [a["_id"] for a in auctions if a.get("_id")]
    auction_bids: List[Dict[str, Any]] = []
    if auction_ids:
        auction_bids = await db["auction_bids"].find({"event_id": {"$in": auction_ids}}).sort("created_at", 1).to_list(length=5000)
    bids_by_auction: Dict[str, List[Dict[str, Any]]] = {}
    for bid in auction_bids:
        key = str(bid.get("event_id"))
        bids_by_auction.setdefault(key, []).append(bid)

    booking_rows = await db["bookings"].find({"event_id": {"$in": auction_ids}}).to_list(length=1000) if auction_ids else []
    booking_by_auction = {str(b.get("event_id")): b for b in booking_rows if b.get("event_id")}

    bidder_ids = {b.get("photographer_id") for b in auction_bids if b.get("photographer_id")}
    bidder_rows: List[Dict[str, Any]] = []
    if bidder_ids:
        bidder_rows = await users_col.find({"_id": {"$in": list(bidder_ids)}}).to_list(length=1000)
    bidder_map = {str(u["_id"]): u for u in bidder_rows if u.get("_id")}

    auctions_out = []
    for a in auctions:
        selected_pid = str(a["selected_photographer_id"]) if a.get("selected_photographer_id") else None
        selected_bid_id = str(a["selected_bid_id"]) if a.get("selected_bid_id") else None
        bid_rows = bids_by_auction.get(str(a["_id"]), [])
        bids_out = []
        selected_price = None
        for bid in bid_rows:
            bid_id = str(bid.get("_id"))
            pid = str(bid.get("photographer_id")) if bid.get("photographer_id") else None
            bdoc = bidder_map.get(pid or "", {})
            item = {
                "id": bid_id,
                "photographer_id": pid,
                "photographer_name": bdoc.get("full_name") or bdoc.get("name"),
                "amount": float(bid.get("bid_amount") or 0),
                "message": bid.get("message"),
                "created_at": bid.get("created_at"),
                "is_selected": bid_id == selected_bid_id,
            }
            if item["is_selected"]:
                selected_price = item["amount"]
            bids_out.append(item)
        booking = booking_by_auction.get(str(a["_id"]))
        auctions_out.append(
            {
                "id": str(a["_id"]),
                "title": a.get("title"),
                "status": a.get("status"),
                "event_date": a.get("event_date"),
                "created_at": a.get("created_at"),
                "selected_photographer_id": selected_pid,
                "selected_photographer_name": (bidder_map.get(selected_pid or "") or {}).get("full_name")
                or (bidder_map.get(selected_pid or "") or {}).get("name"),
                "selected_bid_id": selected_bid_id,
                "selected_price": selected_price,
                "final_price": a.get("final_price") or (booking or {}).get("final_price"),
                "booking_confirmed": bool(booking and booking.get("status") in {"confirmed", "upcoming", "completed"}),
                "booking_status": (booking or {}).get("status"),
                "booking_id": str((booking or {}).get("_id")) if (booking or {}).get("_id") else None,
                "bids": bids_out,
            }
        )

    bookings_out = []
    for b in bookings:
        pid = str(b.get("photographer_id")) if b.get("photographer_id") else None
        pdoc = photographer_map.get(pid or "", {})
        bookings_out.append(
            {
                "id": str(b["_id"]),
                "event_date": b.get("event_date"),
                "status": b.get("status"),
                "photographer_id": pid,
                "photographer_name": pdoc.get("full_name") or pdoc.get("name"),
            }
        )

    quotations_out = []
    for q in quotations:
        pid = str(q.get("photographer_id")) if q.get("photographer_id") else None
        pdoc = photographer_map.get(pid or "", {})
        quotations_out.append(
            {
                "id": str(q["_id"]),
                "photographer_id": pid,
                "photographer_name": pdoc.get("full_name") or pdoc.get("name"),
                "initial_amount": q.get("latest_amount"),
                "negotiated_amount": q.get("latest_amount"),
                "status": q.get("status"),
                "created_at": q.get("created_at"),
            }
        )

    return {
        "user": {
            "id": str(user_doc["_id"]),
            "name": user_doc.get("full_name") or user_doc.get("name"),
            "email": user_doc.get("email"),
            "role": user_doc.get("role"),
            "membership_active": bool(user_doc.get("is_member") and user_doc.get("membership_expiry") and user_doc.get("membership_expiry") > datetime.utcnow()),
        },
        "auctions": auctions_out,
        "bookings": bookings_out,
        "quotations": quotations_out,
    }


@router.get("/photographers/{user_id}/details")
async def photographer_details_admin(
    user_id: str,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    users_col = db["users"]
    photographer = await users_col.find_one({"_id": _oid(user_id), "role": UserRole.PHOTOGRAPHER.value, "is_deleted": {"$ne": True}})
    if not photographer:
        raise HTTPException(status_code=404, detail="Photographer not found")

    bookings = await db["bookings"].find({"photographer_id": photographer["_id"]}).sort("event_date", -1).to_list(length=1000)
    customer_ids = {b.get("user_id") for b in bookings if b.get("user_id")} | {b.get("customer_id") for b in bookings if b.get("customer_id")}
    customer_rows = []
    if customer_ids:
        customer_rows = await users_col.find({"_id": {"$in": list(customer_ids)}}).to_list(length=1000)
    customer_map = {str(c["_id"]): c for c in customer_rows if c.get("_id")}

    now = datetime.utcnow()
    upcoming: List[Dict[str, Any]] = []
    past: List[Dict[str, Any]] = []
    for b in bookings:
        uid = str(b.get("user_id") or b.get("customer_id")) if (b.get("user_id") or b.get("customer_id")) else None
        cdoc = customer_map.get(uid or "", {})
        item = {
            "id": str(b["_id"]),
            "event_title": b.get("event_title") or b.get("title"),
            "event_type": b.get("event_type"),
            "location": b.get("location"),
            "event_date": b.get("event_date"),
            "status": b.get("status"),
            "payment_status": b.get("payment_status") or "pending",
            "final_price": b.get("final_price"),
            "user_id": uid,
            "user_name": cdoc.get("full_name") or cdoc.get("name"),
        }
        if b.get("event_date") and b.get("event_date") >= now:
            upcoming.append(item)
        else:
            past.append(item)

    return {
        "photographer": {
            "id": str(photographer["_id"]),
            "name": photographer.get("full_name") or photographer.get("name"),
            "email": photographer.get("email"),
            "role": photographer.get("role"),
        },
        "upcoming_bookings": upcoming,
        "past_bookings": past,
    }


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


@router.get("/photographers/plan-stats")
async def photographer_plan_stats(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    users = db["users"]
    query = {"is_deleted": {"$ne": True}, "role": UserRole.PHOTOGRAPHER.value}
    free_count = await users.count_documents({**query, "photographer_plan": "free"})
    pro_count = await users.count_documents({**query, "photographer_plan": "pro"})
    premium_count = await users.count_documents({**query, "photographer_plan": "premium"})
    paid_count = pro_count + premium_count
    total = free_count + paid_count
    conversion_rate = round((paid_count / total) * 100, 1) if total > 0 else 0.0
    return {
        "free": free_count,
        "pro": pro_count,
        "premium": premium_count,
        "paid": paid_count,
        "total": total,
        "conversion_rate": conversion_rate,
    }


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
    ledger = db["payments_ledger"]

    sub_month = await subscriptions.aggregate(
        [{"$match": {"created_at": {"$gte": month_start}, "status": "success"}}, {"$group": {"_id": None, "v": {"$sum": "$amount"}}}]
    ).to_list(length=1)
    photo_month = await bookings.aggregate(
        [{"$match": {"created_at": {"$gte": month_start}}}, {"$group": {"_id": None, "v": {"$sum": "$total_amount"}}}]
    ).to_list(length=1)
    membership_month = await ledger.aggregate(
        [{"$match": {"created_at": {"$gte": month_start}, "type": "membership", "direction": "credit"}}, {"$group": {"_id": None, "v": {"$sum": "$amount"}}}]
    ).to_list(length=1)
    exp_month = await expenses.aggregate(
        [{"$match": {"created_at": {"$gte": month_start}, "is_deleted": {"$ne": True}}}, {"$group": {"_id": None, "v": {"$sum": "$amount"}}}]
    ).to_list(length=1)

    subscription_revenue = float((sub_month[0]["v"] if sub_month else 0) or 0)
    membership_revenue = float((membership_month[0]["v"] if membership_month else 0) or 0)
    total_revenue = subscription_revenue + membership_revenue
    photoshoot_revenue = float((photo_month[0]["v"] if photo_month else 0) or 0)
    total_expenses = float((exp_month[0]["v"] if exp_month else 0) or 0)
    current_balance = total_revenue + photoshoot_revenue - total_expenses

    return {
        "current_balance": current_balance,
        "total_revenue_month": total_revenue,
        "subscription_revenue_month": subscription_revenue,
        "membership_revenue_month": membership_revenue,
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
    user_ids: List[ObjectId] = []
    for row in rows:
        uid = row.get("user_id")
        if isinstance(uid, str) and ObjectId.is_valid(uid):
            user_ids.append(ObjectId(uid))
    user_docs = await db["users"].find({"_id": {"$in": user_ids}}, {"full_name": 1, "email": 1}).to_list(length=max(1, len(user_ids)))
    user_map = {str(u["_id"]): u for u in user_docs}
    for r in rows:
        user_doc = user_map.get(str(r.get("user_id")) or "")
        r["user_email"] = (user_doc or {}).get("email")
        r["user_name"] = (user_doc or {}).get("full_name")
        r["id"] = str(r.pop("_id"))
    return {"total": total, "page": page, "limit": limit, "items": rows}


@router.get("/subscriptions/revenue-stats")
async def subscription_revenue_stats(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    col = db["subscriptions"]
    total_rows = await col.aggregate(
        [
            {"$match": {"status": "success"}},
            {
                "$group": {
                    "_id": None,
                    "total_amount": {"$sum": {"$ifNull": ["$amount", 0]}},
                    "total_purchases": {"$sum": 1},
                    "unique_users": {"$addToSet": "$user_id"},
                }
            },
        ]
    ).to_list(length=1)
    by_plan_rows = await col.aggregate(
        [
            {"$match": {"status": "success"}},
            {
                "$group": {
                    "_id": "$plan",
                    "amount": {"$sum": {"$ifNull": ["$amount", 0]}},
                    "count": {"$sum": 1},
                }
            },
        ]
    ).to_list(length=20)
    total_amount = float((total_rows[0]["total_amount"] if total_rows else 0) or 0)
    total_purchases = int((total_rows[0]["total_purchases"] if total_rows else 0) or 0)
    unique_photographers = len((total_rows[0].get("unique_users") if total_rows else []) or [])
    by_plan: Dict[str, Dict[str, Any]] = {}
    for row in by_plan_rows:
        key = str(row.get("_id") or "unknown").lower()
        by_plan[key] = {
            "amount": float(row.get("amount") or 0),
            "count": int(row.get("count") or 0),
        }
    return {
        "total_amount": total_amount,
        "total_purchases": total_purchases,
        "unique_photographers": unique_photographers,
        "by_plan": by_plan,
    }


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
        safe = _json_safe(r)
        r.clear()
        r.update(safe)
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


@router.get("/payments/memberships")
async def payments_memberships(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    users = db["users"]
    membership_cfg = await db["membership_config"].find_one({"id": "membership"}) or {}
    membership_price = float(membership_cfg.get("price") or 999)
    membership_duration_days = int(membership_cfg.get("duration_days") or 365)
    query: Dict[str, Any] = {"type": "membership", "direction": "credit"}
    if from_date or to_date:
        created_filter: Dict[str, Any] = {}
        if from_date:
            created_filter["$gte"] = from_date
        if to_date:
            created_filter["$lte"] = to_date
        query["created_at"] = created_filter

    col = db["payments_ledger"]
    rows = await col.find(query).sort("created_at", -1).to_list(length=5000)
    user_ids = []
    for row in rows:
        user_id = row.get("user_id")
        if isinstance(user_id, ObjectId):
            user_ids.append(user_id)
    user_docs = await users.find({"_id": {"$in": user_ids}}).to_list(length=max(1, len(user_ids)))
    user_map = {str(u["_id"]): u for u in user_docs}

    filtered: List[Dict[str, Any]] = []
    for row in rows:
        uid = row.get("user_id")
        uid_str = str(uid) if uid else None
        user_doc = user_map.get(uid_str or "")
        expiry = user_doc.get("membership_expiry") if user_doc else None
        calculated_status = "active" if (expiry and expiry > datetime.utcnow()) else "expired"
        out = {
            "id": str(row.get("_id")),
            "user_id": uid_str,
            "user_name": (user_doc or {}).get("full_name"),
            "user_email": (user_doc or {}).get("email"),
            "plan": "Membership",
            "plan_price": membership_price,
            "plan_duration_days": membership_duration_days,
            "amount_paid": float(row.get("amount") or 0),
            "purchase_date": row.get("created_at"),
            "expiry_date": expiry,
            "status": calculated_status,
            "created_at": row.get("created_at"),
        }
        if search:
            q = search.lower()
            if q not in str(out.get("user_name") or "").lower() and q not in str(out.get("user_email") or "").lower():
                continue
        if status and out["status"] != status:
            continue
        filtered.append(out)

    total = len(filtered)
    skip = (page - 1) * limit
    items = filtered[skip : skip + limit]
    return {"total": total, "page": page, "limit": limit, "items": items}


@router.get("/revenue-summary")
async def revenue_summary(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    subscriptions = db["subscriptions"]
    ledger = db["payments_ledger"]
    sub_total = await subscriptions.aggregate(
        [{"$match": {"status": "success"}}, {"$group": {"_id": None, "v": {"$sum": "$amount"}}}]
    ).to_list(length=1)
    membership_total = await ledger.aggregate(
        [{"$match": {"type": "membership", "direction": "credit"}}, {"$group": {"_id": None, "v": {"$sum": "$amount"}}}]
    ).to_list(length=1)
    subscription_revenue = float((sub_total[0]["v"] if sub_total else 0) or 0)
    membership_revenue = float((membership_total[0]["v"] if membership_total else 0) or 0)
    return {
        "subscription_revenue": subscription_revenue,
        "membership_revenue": membership_revenue,
        "total_revenue": subscription_revenue + membership_revenue,
    }


@router.get("/membership-stats")
async def membership_stats(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    ledger = db["payments_ledger"]
    now = datetime.utcnow()
    this_month_start = _month_start(now)
    prev_month_end = this_month_start - timedelta(microseconds=1)
    prev_month_start = prev_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month_memberships = await ledger.count_documents(
        {"type": "membership", "direction": "credit", "created_at": {"$gte": this_month_start}}
    )
    last_month_memberships = await ledger.count_documents(
        {"type": "membership", "direction": "credit", "created_at": {"$gte": prev_month_start, "$lt": this_month_start}}
    )
    return {
        "this_month_memberships": this_month_memberships,
        "last_month_memberships": last_month_memberships,
    }


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


@router.patch("/photographers/{user_id}/pricing")
async def update_photographer_pricing(
    user_id: str,
    payload: PhotographerPricingUpdate,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    updates = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    if not updates:
        return {"message": "No changes"}
    res = await db["users"].update_one(
        {"_id": _oid(user_id), "role": "photographer", "is_deleted": {"$ne": True}},
        {"$set": {"pricing": updates, "updated_at": datetime.utcnow()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Photographer not found")
    return {"message": "Photographer pricing updated"}


@router.post("/past-shoots")
async def create_past_shoot(
    payload: PastShootCreate,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    photographer = await db["users"].find_one({"_id": _oid(payload.photographer_id), "role": "photographer"})
    if not photographer:
        raise HTTPException(status_code=404, detail="Photographer not found")
    doc = payload.dict()
    doc["event_type"] = doc["event_type"].strip().lower()
    doc["features"] = [f.strip().lower() for f in (doc.get("features") or [])]
    res = await db["past_shoots"].insert_one(doc)
    return {"id": str(res.inserted_id), "message": "Past shoot added"}


@router.get("/past-shoots")
async def list_past_shoots(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    skip = (page - 1) * limit
    col = db["past_shoots"]
    total = await col.count_documents({})
    rows = await col.find().sort("date", -1).skip(skip).limit(limit).to_list(length=limit)
    for r in rows:
        r["id"] = str(r.pop("_id"))
    return {"total": total, "page": page, "limit": limit, "items": rows}


@router.get("/pricing/stats")
async def pricing_stats(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    rows = await db["past_shoots"].aggregate(
        [
            {"$group": {"_id": "$event_type", "avg_price": {"$avg": "$final_price"}, "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
    ).to_list(length=200)
    demand = [{"event_type": str(r.get("_id") or "unknown"), "avg_price": float(r.get("avg_price") or 0), "count": int(r.get("count") or 0)} for r in rows]
    return {"event_pricing": demand}


@router.get("/plans")
async def get_plans(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    await _ensure_plan_membership_seed(db)
    rows = await db["plans"].find({}).sort("updated_at", -1).to_list(length=100)
    unique_by_name: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("name") or "").strip().lower()
        if not name or name in unique_by_name:
            continue
        row["mongo_id"] = str(row.pop("_id"))
        unique_by_name[name] = row
    ordered_names = ["free", "pro", "premium"]
    items = [unique_by_name[n] for n in ordered_names if n in unique_by_name]
    return {"items": items}


@router.put("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    payload: PlanUpdateBody,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    await _ensure_plan_membership_seed(db)
    allowed = {"free", "pro", "premium"}
    plan_key = plan_id.strip().lower()
    if plan_key not in allowed:
        raise HTTPException(status_code=400, detail="Invalid plan id")
    updates = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    if not updates:
        return {"message": "No changes"}
    updates["updated_at"] = datetime.utcnow()
    res = await db["plans"].update_one({"name": plan_key}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan_key in {"pro", "premium"} and any(k in updates for k in ["max_bids", "priority_weight"]):
        auction_set: Dict[str, Any] = {}
        if "max_bids" in updates:
            auction_set[f"bid_limits.{plan_key}"] = int(updates["max_bids"])
        if "priority_weight" in updates:
            auction_set[f"ranking_weights.{plan_key}"] = int(updates["priority_weight"])
        if auction_set:
            await db["settings"].update_one(
                {"key": "auction_config"},
                {"$set": {"key": "auction_config", **auction_set, "updated_at": datetime.utcnow()}},
                upsert=True,
            )
    return {"message": "Plan updated"}


@router.get("/membership")
async def get_membership_config(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    await _ensure_plan_membership_seed(db)
    config = await db["membership_config"].find_one({"id": "membership"})
    if not config:
        raise HTTPException(status_code=404, detail="Membership config not found")
    config["mongo_id"] = str(config.pop("_id"))
    users = db["users"]
    active_members = await users.count_documents(
        {"is_member": True, "membership_expiry": {"$gt": datetime.utcnow()}, "is_deleted": {"$ne": True}}
    )
    revenue_rows = await db["payments_ledger"].aggregate(
        [{"$match": {"type": "membership", "direction": "credit"}}, {"$group": {"_id": None, "v": {"$sum": "$amount"}}}]
    ).to_list(length=1)
    total_revenue = float((revenue_rows[0]["v"] if revenue_rows else 0) or 0)
    return {
        "config": config,
        "metrics": {"active_members": active_members, "total_revenue": total_revenue},
    }


@router.put("/membership")
async def update_membership_config(
    payload: MembershipUpdateBody,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    await _ensure_plan_membership_seed(db)
    updates = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    if not updates:
        return {"message": "No changes"}
    updates["updated_at"] = datetime.utcnow()
    await db["membership_config"].update_one({"id": "membership"}, {"$set": updates}, upsert=True)
    return {"message": "Membership config updated"}
