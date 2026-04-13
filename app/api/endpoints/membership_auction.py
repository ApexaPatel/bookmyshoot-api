import os
import smtplib
import uuid
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from pymongo.database import Database

from app.core.security import get_current_active_user, get_current_admin_user
from app.db.mongodb import get_database
from app.models.user import UserInDB

router = APIRouter()

MEMBERSHIP_FEE_INR = 999.0
MEMBERSHIP_VALIDITY_DAYS = 365
MEMBERSHIP_DISCOUNT_RATE = 0.10
DEFAULT_AUCTION_CONFIG = {
    "bid_limits": {"pro": 20, "premium": 9999},
    "ranking_weights": {"pro": 0, "premium": 15},
}


def _oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail="Invalid id")
    return ObjectId(value)


def _is_member_active(user_doc: Dict[str, Any]) -> bool:
    if not user_doc.get("is_member"):
        return False
    expiry = user_doc.get("membership_expiry")
    return bool(expiry and expiry > datetime.utcnow())


async def _get_auction_config(db: Database) -> Dict[str, Any]:
    settings = await db["settings"].find_one({"key": "auction_config"})
    if not settings:
        return DEFAULT_AUCTION_CONFIG
    bid_limits = settings.get("bid_limits") or {}
    ranking_weights = settings.get("ranking_weights") or {}
    return {
        "bid_limits": {
            "pro": int(bid_limits.get("pro", DEFAULT_AUCTION_CONFIG["bid_limits"]["pro"])),
            "premium": int(bid_limits.get("premium", DEFAULT_AUCTION_CONFIG["bid_limits"]["premium"])),
        },
        "ranking_weights": {
            "pro": int(ranking_weights.get("pro", DEFAULT_AUCTION_CONFIG["ranking_weights"]["pro"])),
            "premium": int(ranking_weights.get("premium", DEFAULT_AUCTION_CONFIG["ranking_weights"]["premium"])),
        },
    }


def _send_email(to_emails: List[str], subject: str, html_body: str) -> None:
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("EMAIL_USERNAME")
    password = os.getenv("EMAIL_PASSWORD")
    if not (smtp_server and username and password):
        print("⚠️  SMTP not configured; skipping auction email.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = ", ".join(to_emails)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(username, password)
        server.sendmail(username, to_emails, msg.as_string())


class MembershipPurchaseBody(BaseModel):
    payment_reference: Optional[str] = None
    simulate_success: bool = True


class AuctionCreateBody(BaseModel):
    title: str
    event_type: str
    location: str
    event_date: datetime
    description: Optional[str] = None
    budget: Optional[float] = Field(None, gt=0)
    required_features: List[str] = Field(default_factory=list)
    bidding_deadline: datetime


class AuctionBidBody(BaseModel):
    event_id: str
    bid_amount: float = Field(..., gt=0)
    message: Optional[str] = None


class AuctionSelectBody(BaseModel):
    event_id: str
    bid_id: str


class AuctionCancelBody(BaseModel):
    event_id: str


class AuctionConfigBody(BaseModel):
    pro_bid_limit: int = Field(20, ge=1, le=100000)
    premium_bid_limit: int = Field(9999, ge=1, le=100000)
    pro_ranking_weight: int = Field(0, ge=0, le=100)
    premium_ranking_weight: int = Field(15, ge=0, le=100)


async def _finalize_booking_from_bid(db: Database, auction_doc: Dict[str, Any], bid_doc: Dict[str, Any], source_status: str) -> Dict[str, Any]:
    users = db["users"]
    bookings = db["bookings"]
    auctions = db["auctions"]

    user_doc = await users.find_one({"_id": auction_doc["user_id"]})
    member_discount = MEMBERSHIP_DISCOUNT_RATE if user_doc and _is_member_active(user_doc) else 0.0
    bid_amount = float(bid_doc.get("bid_amount") or 0)
    discount_value = round(bid_amount * member_discount, 2)
    final_price = round(bid_amount - discount_value, 2)

    booking_doc = {
        "event_id": auction_doc["_id"],
        "customer_id": auction_doc["user_id"],
        "photographer_id": bid_doc["photographer_id"],
        "event_type": auction_doc.get("event_type"),
        "location": auction_doc.get("location"),
        "event_date": auction_doc.get("event_date"),
        "required_features": auction_doc.get("required_features", []),
        "bid_amount": bid_amount,
        "final_price": final_price,
        "discount_applied": discount_value,
        "membership_discount_rate": member_discount,
        "status": "confirmed",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    booking_res = await bookings.insert_one(booking_doc)

    await auctions.update_one(
        {"_id": auction_doc["_id"]},
        {
            "$set": {
                "status": source_status,
                "selected_photographer_id": bid_doc["photographer_id"],
                "selected_bid_id": bid_doc["_id"],
                "booking_id": booking_res.inserted_id,
                "final_price": final_price,
                "discount_applied": discount_value,
                "updated_at": datetime.utcnow(),
            }
        },
    )
    return {"booking_id": str(booking_res.inserted_id), "final_price": final_price, "discount_applied": discount_value}


async def _run_auto_assignment(db: Database) -> int:
    auctions = db["auctions"]
    bids = db["auction_bids"]
    users = db["users"]

    now = datetime.utcnow()
    auction_cfg = await _get_auction_config(db)
    rank_weights = auction_cfg["ranking_weights"]
    open_auctions = await auctions.find(
        {"status": "open", "bidding_deadline": {"$lte": now}}
    ).to_list(length=500)

    auto_assigned_count = 0
    for auction in open_auctions:
        event_bids = await bids.find({"event_id": auction["_id"]}).to_list(length=1000)
        if not event_bids:
            await auctions.update_one(
                {"_id": auction["_id"]},
                {"$set": {"status": "failed_no_bids", "updated_at": datetime.utcnow()}},
            )
            continue

        ranked = []
        for bid in event_bids:
            p = await users.find_one({"_id": bid["photographer_id"]}, {"rating": 1, "photographer_plan": 1})
            rated = float((p or {}).get("rating") or 0.0)
            plan = str((p or {}).get("photographer_plan") or "free").lower()
            plan_boost = int(rank_weights.get(plan, 0))
            rank_score = plan_boost + min(int(rated * 5), 25)
            ranked.append((-(rank_score), float(bid.get("bid_amount") or 0), -rated, bid))
        ranked.sort(key=lambda x: (x[0], x[1], x[2]))
        winning_bid = ranked[0][2]
        await _finalize_booking_from_bid(db, auction, winning_bid, source_status="auto_assigned")
        auto_assigned_count += 1
    return auto_assigned_count


@router.post("/membership/purchase")
async def purchase_membership(
    body: MembershipPurchaseBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    membership_cfg = await db["membership_config"].find_one({"id": "membership"})
    membership_price = float((membership_cfg or {}).get("price") or MEMBERSHIP_FEE_INR)
    membership_days = int((membership_cfg or {}).get("duration_days") or MEMBERSHIP_VALIDITY_DAYS)
    membership_active = bool((membership_cfg or {}).get("is_active", True))
    if not membership_active:
        raise HTTPException(status_code=400, detail="Membership purchases are currently disabled")

    payment_id = body.payment_reference or f"DEMO-TXN-{uuid.uuid4().hex[:12].upper()}"
    if not body.simulate_success:
        return {
            "success": False,
            "message": "Simulated payment failed (demo mode). Membership was not activated.",
            "payment_id": payment_id,
            "membership_fee": membership_price,
            "discount_rate": MEMBERSHIP_DISCOUNT_RATE,
        }

    start = datetime.utcnow()
    expiry = start + timedelta(days=membership_days)
    await db["users"].update_one(
        {"_id": _oid(current_user.id)},
        {
            "$set": {
                "is_member": True,
                "membership_start": start,
                "membership_expiry": expiry,
                "updated_at": start,
            }
        },
    )
    await db["payments_ledger"].insert_one(
        {
            "type": "membership",
            "amount": membership_price,
            "direction": "credit",
            "user_id": _oid(current_user.id),
            "reference_id": payment_id,
            "created_at": start,
        }
    )
    return {
        "success": True,
        "message": "Membership activated",
        "payment_id": payment_id,
        "membership_fee": membership_price,
        "membership_start": start,
        "membership_expiry": expiry,
        "discount_rate": MEMBERSHIP_DISCOUNT_RATE,
    }


@router.post("/auction/create")
async def create_auction(
    body: AuctionCreateBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    now = datetime.utcnow()
    if body.bidding_deadline <= now:
        raise HTTPException(status_code=400, detail="Bidding deadline must be in the future")
    if body.event_date < now:
        raise HTTPException(status_code=400, detail="Event date must be in the future")

    doc = {
        "user_id": _oid(current_user.id),
        "title": body.title.strip(),
        "event_type": body.event_type.strip().lower(),
        "location": body.location.strip(),
        "event_date": body.event_date,
        "description": body.description,
        "budget": body.budget,
        "required_features": [f.strip().lower() for f in body.required_features if f.strip()],
        "bidding_deadline": body.bidding_deadline,
        "status": "open",
        "selected_photographer_id": None,
        "selected_bid_id": None,
        "booking_id": None,
        "reminder_3_sent": False,
        "reminder_2_sent": False,
        "reminder_1_sent": False,
        "created_at": now,
        "updated_at": now,
    }
    res = await db["auctions"].insert_one(doc)
    return {"message": "Auction created", "event_id": str(res.inserted_id)}


@router.get("/auction/list")
async def list_auctions(
    mine: bool = Query(False),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    await _run_auto_assignment(db)
    query: Dict[str, Any] = {}

    if current_user.role == "photographer":
        if current_user.photographer_plan not in ["pro", "premium"]:
            raise HTTPException(status_code=403, detail="Only Pro & Premium photographers can access auctions")
        query["status"] = "open" if not status_filter else status_filter
    elif mine:
        query["user_id"] = _oid(current_user.id)
        if status_filter:
            query["status"] = status_filter
    elif status_filter:
        query["status"] = status_filter

    rows = await db["auctions"].find(query).sort("created_at", -1).to_list(length=500)
    out = []
    for row in rows:
        out.append(
            {
                "id": str(row["_id"]),
                "user_id": str(row["user_id"]),
                "title": row.get("title"),
                "event_type": row.get("event_type"),
                "location": row.get("location"),
                "event_date": row.get("event_date"),
                "description": row.get("description"),
                "budget": row.get("budget"),
                "required_features": row.get("required_features", []),
                "bidding_deadline": row.get("bidding_deadline"),
                "status": row.get("status"),
                "selected_photographer_id": str(row["selected_photographer_id"]) if row.get("selected_photographer_id") else None,
            }
        )
    return {"auctions": out}


@router.get("/auction/{event_id}/bids")
async def list_auction_bids(
    event_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    auction = await db["auctions"].find_one({"_id": _oid(event_id)})
    if not auction:
        raise HTTPException(status_code=404, detail="Auction not found")
    if str(auction["user_id"]) != current_user.id and current_user.role not in ["super_admin", "admin", "staff"]:
        raise HTTPException(status_code=403, detail="Only auction owner can view bids")

    bids = await db["auction_bids"].find({"event_id": auction["_id"]}).sort("bid_amount", 1).to_list(length=1000)
    photographer_ids = [b["photographer_id"] for b in bids if b.get("photographer_id")]
    users = await db["users"].find(
        {"_id": {"$in": photographer_ids}},
        {"full_name": 1, "rating": 1, "photographer_plan": 1},
    ).to_list(length=len(photographer_ids))
    users_map = {str(u["_id"]): u for u in users}
    auction_cfg = await _get_auction_config(db)
    rank_weights = auction_cfg["ranking_weights"]
    out = []
    for bid in bids:
        p = users_map.get(str(bid["photographer_id"]), {})
        plan = str(p.get("photographer_plan") or "free").lower()
        plan_boost = int(rank_weights.get(plan, 0))
        rating = float(p.get("rating") or 0.0)
        ranking_score = plan_boost + min(int(rating * 5), 25)
        out.append(
            {
                "id": str(bid["_id"]),
                "photographer_id": str(bid["photographer_id"]),
                "photographer_name": p.get("full_name", "Photographer"),
                "rating": rating,
                "photographer_plan": plan,
                "priority_ranked": plan == "premium",
                "ranking_score": ranking_score,
                "bid_amount": float(bid.get("bid_amount") or 0.0),
                "message": bid.get("message"),
                "created_at": bid.get("created_at"),
                "updated_at": bid.get("updated_at"),
            }
        )
    out.sort(key=lambda x: (-x["ranking_score"], x["bid_amount"]))
    return {"bids": out}


@router.post("/auction/bid")
async def place_or_update_bid(
    body: AuctionBidBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    if current_user.role != "photographer":
        raise HTTPException(status_code=403, detail="Only photographers can place bids")
    if current_user.photographer_plan not in ["pro", "premium"]:
        raise HTTPException(status_code=403, detail="Only Pro & Premium photographers can place bids")

    event_oid = _oid(body.event_id)
    auction = await db["auctions"].find_one({"_id": event_oid})
    if not auction:
        raise HTTPException(status_code=404, detail="Auction not found")
    if auction.get("status") != "open":
        raise HTTPException(status_code=400, detail="Auction is not open")
    if auction.get("bidding_deadline") <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Bidding deadline has passed")

    bids = db["auction_bids"]
    auction_cfg = await _get_auction_config(db)
    bid_limits = auction_cfg["bid_limits"]
    now = datetime.utcnow()
    existing = await bids.find_one({"event_id": event_oid, "photographer_id": _oid(current_user.id)})
    if existing:
        await bids.update_one(
            {"_id": existing["_id"]},
            {"$set": {"bid_amount": body.bid_amount, "message": body.message, "updated_at": now}},
        )
        return {"message": "Bid updated", "bid_id": str(existing["_id"])}

    active_bids = await bids.aggregate(
        [
            {"$match": {"photographer_id": _oid(current_user.id)}},
            {"$lookup": {"from": "auctions", "localField": "event_id", "foreignField": "_id", "as": "auction"}},
            {"$unwind": "$auction"},
            {"$match": {"auction.status": "open"}},
            {"$count": "count"},
        ]
    ).to_list(length=1)
    active_bids_count = int(active_bids[0]["count"]) if active_bids else 0
    max_bid_limit = int(bid_limits.get(current_user.photographer_plan, 0))
    if max_bid_limit and active_bids_count >= max_bid_limit:
        raise HTTPException(
            status_code=400,
            detail=f"Your {current_user.photographer_plan.title()} plan allows up to {max_bid_limit} active bids. Upgrade plan to increase limit.",
        )

    res = await bids.insert_one(
        {
            "event_id": event_oid,
            "photographer_id": _oid(current_user.id),
            "bid_amount": body.bid_amount,
            "message": body.message,
            "created_at": now,
            "updated_at": now,
        }
    )
    return {"message": "Bid submitted", "bid_id": str(res.inserted_id)}


@router.post("/auction/select")
async def select_bidder(
    body: AuctionSelectBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    event_oid = _oid(body.event_id)
    bid_oid = _oid(body.bid_id)
    auction = await db["auctions"].find_one({"_id": event_oid})
    if not auction:
        raise HTTPException(status_code=404, detail="Auction not found")
    if str(auction["user_id"]) != current_user.id:
        raise HTTPException(status_code=403, detail="Only auction owner can select bidder")
    if auction.get("status") != "open":
        raise HTTPException(status_code=400, detail="Auction already finalized/cancelled")

    bid = await db["auction_bids"].find_one({"_id": bid_oid, "event_id": event_oid})
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")

    result = await _finalize_booking_from_bid(db, auction, bid, source_status="finalized")
    return {"message": "Photographer selected", **result}


@router.post("/auction/cancel")
async def cancel_auction(
    body: AuctionCancelBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    event_oid = _oid(body.event_id)
    auction = await db["auctions"].find_one({"_id": event_oid})
    if not auction:
        raise HTTPException(status_code=404, detail="Auction not found")
    if str(auction["user_id"]) != current_user.id:
        raise HTTPException(status_code=403, detail="Only auction owner can cancel")
    if auction.get("status") != "open":
        raise HTTPException(status_code=400, detail="Auction cannot be cancelled")
    if auction.get("selected_photographer_id"):
        raise HTTPException(status_code=400, detail="Auction already has selected photographer")

    await db["auctions"].update_one(
        {"_id": event_oid},
        {"$set": {"status": "cancelled", "updated_at": datetime.utcnow()}},
    )

    bidder_ids = await db["auction_bids"].distinct("photographer_id", {"event_id": event_oid})
    if bidder_ids:
        bidders = await db["users"].find({"_id": {"$in": bidder_ids}}, {"email": 1}).to_list(length=len(bidder_ids))
        emails = [b.get("email") for b in bidders if b.get("email")]
        if emails:
            _send_email(
                emails,
                "Auction Cancelled",
                f"<p>The auction '{auction.get('title')}' was cancelled by the user.</p>",
            )
    return {"message": "Auction cancelled"}


@router.post("/auction/process-reminders")
async def process_auction_reminders(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    auctions = db["auctions"]
    users = db["users"]
    now = datetime.utcnow()

    open_auctions = await auctions.find({"status": "open"}).to_list(length=500)
    sent = {"t_minus_3": 0, "t_minus_2": 0, "t_minus_1": 0}
    for auction in open_auctions:
        owner = await users.find_one({"_id": auction["user_id"]}, {"email": 1, "full_name": 1})
        if not owner or not owner.get("email"):
            continue

        delta_days = (auction["bidding_deadline"] - now).days
        if delta_days == 3 and not auction.get("reminder_3_sent"):
            _send_email([owner["email"]], "Auction Reminder: 3 days left", f"<p>Your auction '{auction.get('title')}' has 3 days left.</p>")
            await auctions.update_one({"_id": auction["_id"]}, {"$set": {"reminder_3_sent": True}})
            sent["t_minus_3"] += 1
        elif delta_days == 2 and not auction.get("reminder_2_sent"):
            _send_email([owner["email"]], "Auction Reminder: 2 days left", f"<p>Your auction '{auction.get('title')}' has 2 days left.</p>")
            await auctions.update_one({"_id": auction["_id"]}, {"$set": {"reminder_2_sent": True}})
            sent["t_minus_2"] += 1
        elif delta_days <= 1 and not auction.get("reminder_1_sent"):
            _send_email([owner["email"]], "Auction Final Reminder", f"<p>Your auction '{auction.get('title')}' is ending soon. Finalize before deadline.</p>")
            await auctions.update_one({"_id": auction["_id"]}, {"$set": {"reminder_1_sent": True}})
            sent["t_minus_1"] += 1

    return {"message": "Reminder processing complete", "sent": sent}


@router.post("/auction/process-deadlines")
async def process_auction_deadlines(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    assigned = await _run_auto_assignment(db)
    return {"message": "Deadline processing complete", "auto_assigned": assigned}


@router.get("/admin/auctions/overview")
async def admin_auctions_overview(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    auctions = db["auctions"]
    total = await auctions.count_documents({})
    completed = await auctions.count_documents({"status": {"$in": ["finalized", "auto_assigned"]}})
    cancelled = await auctions.count_documents({"status": "cancelled"})
    open_count = await auctions.count_documents({"status": "open"})
    bids_count = await db["auction_bids"].count_documents({})
    bids_by_plan = await db["auction_bids"].aggregate(
        [
            {"$lookup": {"from": "users", "localField": "photographer_id", "foreignField": "_id", "as": "photographer"}},
            {"$unwind": "$photographer"},
            {"$group": {"_id": "$photographer.photographer_plan", "count": {"$sum": 1}}},
        ]
    ).to_list(length=20)
    by_plan = {str(row.get("_id") or "free"): int(row.get("count") or 0) for row in bids_by_plan}
    auction_cfg = await _get_auction_config(db)
    return {
        "total_auctions": total,
        "completed_auctions": completed,
        "cancelled_auctions": cancelled,
        "open_auctions": open_count,
        "total_bids": bids_count,
        "bids_by_plan": by_plan,
        "config": auction_cfg,
    }


@router.get("/admin/auctions/config")
async def get_auction_config(
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    return await _get_auction_config(db)


@router.put("/admin/auctions/config")
async def update_auction_config(
    body: AuctionConfigBody,
    _: UserInDB = Depends(get_current_admin_user),
    db: Database = Depends(get_database),
):
    payload = {
        "bid_limits": {
            "pro": int(body.pro_bid_limit),
            "premium": int(body.premium_bid_limit),
        },
        "ranking_weights": {
            "pro": int(body.pro_ranking_weight),
            "premium": int(body.premium_ranking_weight),
        },
    }
    await db["settings"].update_one(
        {"key": "auction_config"},
        {"$set": {"key": "auction_config", **payload, "updated_at": datetime.utcnow()}},
        upsert=True,
    )
    return {"message": "Auction config updated", **payload}
