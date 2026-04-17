import os
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo.database import Database

from app.core.security import get_current_active_user
from app.db.mongodb import get_database
from app.models.user import UserInDB

router = APIRouter()


FEATURE_DEFAULT_COSTS: Dict[str, float] = {
    "cinematography": 8000.0,
    "drone": 5000.0,
    "album": 4000.0,
}


class QuotationRequest(BaseModel):
    event_type: str
    location: str
    duration: float = Field(..., gt=0)
    budget: Optional[float] = Field(None, gt=0)
    budget_min: Optional[float] = Field(None, gt=0)
    budget_max: Optional[float] = Field(None, gt=0)
    features: List[str] = Field(default_factory=list)


class SuggestedPhotographer(BaseModel):
    id: str
    name: str
    estimated_price: float
    rating: float
    match_score: int
    tags: List[str] = Field(default_factory=list)


class QuotationResponse(BaseModel):
    estimated_price: float
    price_range: List[float]
    confidence: str
    suggested_photographers: List[SuggestedPhotographer]


def _resolve_budget(req: QuotationRequest) -> Dict[str, float]:
    if req.budget:
        return {"min": req.budget, "max": req.budget}
    return {
        "min": req.budget_min or 0.0,
        "max": req.budget_max or float("inf"),
    }


def _rule_price(
    event_type: str,
    location: str,
    duration: float,
    features: List[str],
    pricing: Dict[str, Any],
) -> float:
    base_prices = pricing.get("base_prices") or {}
    base_price = float(base_prices.get(event_type, pricing.get("base_price", 15000)) or 15000)
    hourly_rate = float(pricing.get("price_per_hour", 2000) or 2000)

    location_multipliers = pricing.get("location_multipliers") or {}
    location_multiplier = float(location_multipliers.get(location, 1.0) or 1.0)

    feature_prices = pricing.get("feature_prices") or {}
    features_total = 0.0
    for feature in features:
        features_total += float(feature_prices.get(feature, FEATURE_DEFAULT_COSTS.get(feature, 0.0)) or 0.0)

    total = (base_price + (duration * hourly_rate) + features_total) * location_multiplier
    return round(total, 2)


def _confidence_from_count(n: int) -> str:
    if n >= 12:
        return "high"
    if n >= 5:
        return "medium"
    return "low"


@router.post("/get-quotation-and-suggestions", response_model=QuotationResponse)
async def get_quotation_and_suggestions(
    payload: QuotationRequest,
    db: Database = Depends(get_database),
):
    users_col = db["users"]
    past_shoots_col = db["past_shoots"]

    budget = _resolve_budget(payload)
    req_features = [f.strip().lower() for f in payload.features if f.strip()]
    event_type = payload.event_type.strip().lower()
    location = payload.location.strip()

    # AI v1 approximation: historical average/min/max for same event + location.
    history_filter = {"event_type": event_type, "location": location}
    historical = await past_shoots_col.find(history_filter).sort("date", -1).limit(200).to_list(length=200)
    historical_prices = [float(h.get("final_price") or 0) for h in historical if h.get("final_price") is not None]
    history_count = len(historical_prices)
    hist_avg = sum(historical_prices) / history_count if history_count else 0.0
    hist_min = min(historical_prices) if historical_prices else 0.0
    hist_max = max(historical_prices) if historical_prices else 0.0

    photographers = await users_col.find(
        {
            "role": "photographer",
            "is_deleted": {"$ne": True},
        }
    ).to_list(length=1000)

    suggestions: List[SuggestedPhotographer] = []
    fallback_prices: List[float] = []

    for p in photographers:
        pricing = p.get("pricing") or {}
        expertise = [e.lower() for e in (pricing.get("event_specialties") or [])]
        photographer_tags = [t.lower() for t in (pricing.get("tags") or [])]
        photographer_locations = [loc.lower() for loc in (pricing.get("service_locations") or [])]

        if expertise and event_type not in expertise:
            continue
        if photographer_locations and location.lower() not in photographer_locations:
            continue

        rule_price = _rule_price(event_type, location, payload.duration, req_features, pricing)
        fallback_prices.append(rule_price)

        if hist_avg > 0:
            estimated_price = round((rule_price * 0.7) + (hist_avg * 0.3), 2)
        else:
            estimated_price = rule_price

        rating = float(p.get("rating") or pricing.get("rating") or 4.0)
        experience_years = float(p.get("experience_years") or pricing.get("experience_years") or 0.0)

        budget_max = budget["max"]
        budget_min = budget["min"]
        within_budget = budget_min <= estimated_price <= budget_max
        slightly_above = estimated_price <= (budget_max * 1.15) if budget_max != float("inf") else False

        score = 0
        score += 55 if within_budget else (35 if slightly_above else 10)
        score += min(int(rating * 8), 35)
        score += min(int(experience_years * 2), 10)
        score = max(0, min(100, score))

        tags: List[str] = []
        if within_budget:
            tags.append("Within Budget")
        elif slightly_above:
            tags.append("Slightly Above Budget")
        if score >= 90:
            tags.append("Best Match")
        if "premium" in photographer_tags:
            tags.append("Premium")
        if "budget-friendly" in photographer_tags:
            tags.append("Budget Friendly")

        suggestions.append(
            SuggestedPhotographer(
                id=str(p.get("_id")),
                name=p.get("full_name") or "Photographer",
                estimated_price=estimated_price,
                rating=round(rating, 1),
                match_score=score,
                tags=tags,
            )
        )

    suggestions.sort(key=lambda x: (-x.match_score, x.estimated_price))
    suggestions = suggestions[:12]

    if historical_prices:
        estimated_price = round(hist_avg, 2)
        price_range = [round(hist_min, 2), round(hist_max, 2)]
    elif fallback_prices:
        avg = sum(fallback_prices) / len(fallback_prices)
        estimated_price = round(avg, 2)
        price_range = [round(min(fallback_prices), 2), round(max(fallback_prices), 2)]
    else:
        estimated_price = 0.0
        price_range = [0.0, 0.0]

    return QuotationResponse(
        estimated_price=estimated_price,
        price_range=price_range,
        confidence=_confidence_from_count(history_count),
        suggested_photographers=suggestions,
    )


class PastShootCreate(BaseModel):
    photographer_id: str
    event_type: str
    location: str
    duration_hours: float
    features: List[str] = Field(default_factory=list)
    final_price: float
    date: datetime


class QuoteRequestBody(BaseModel):
    photographer_id: str
    event_title: str
    event_type: str
    location: str
    event_start_date: datetime
    event_end_date: datetime
    duration_hours: Optional[float] = Field(None, gt=0)
    description: Optional[str] = None
    budget: Optional[float] = Field(None, gt=0)


class QuoteRespondBody(BaseModel):
    quotation_id: str
    amount: float = Field(..., gt=0)
    message: Optional[str] = None


class QuoteReviseBody(BaseModel):
    quotation_id: str
    action: str = Field(..., description="accept | counter | revise")
    counter_amount: Optional[float] = Field(None, gt=0)
    message: Optional[str] = None


class BookingConfirmBody(BaseModel):
    quotation_id: str
    pay_stage: str = Field("during_booking", description="during_booking | after_shoot")


class PaymentInitiateBody(BaseModel):
    booking_id: str
    amount: Optional[float] = None
    simulate_success: bool = True


class TaskCompleteBody(BaseModel):
    task_id: str


class BookingCancelBody(BaseModel):
    booking_id: str


class BookingCompleteBody(BaseModel):
    booking_id: str


def _oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail="Invalid id")
    return ObjectId(value)


def _is_member_active(user_doc: Dict[str, Any]) -> bool:
    if not user_doc.get("is_member"):
        return False
    expiry = user_doc.get("membership_expiry")
    return bool(expiry and expiry > datetime.utcnow())


def _send_email(to_email: Optional[str], subject: str, html_body: str) -> None:
    if not to_email:
        return
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("EMAIL_USERNAME")
    password = os.getenv("EMAIL_PASSWORD")
    if not (smtp_server and username and password):
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(username, password)
        server.sendmail(username, [to_email], msg.as_string())


def _format_event_date_time(value: Any) -> Dict[str, str]:
    if isinstance(value, datetime):
        dt = value
    elif value:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return {"date": str(value), "time": "TBD"}
    else:
        return {"date": "TBD", "time": "TBD"}
    return {
        "date": dt.strftime("%d %B %Y"),
        "time": dt.strftime("%I:%M %p"),
    }


def _booking_confirmation_email_html(
    customer_name: str,
    event_name: str,
    event_date: Any,
    location: str,
    photographer_name: str,
    booking_id: str,
) -> str:
    dt = _format_event_date_time(event_date)
    app_base_url = (os.getenv("APP_BASE_URL") or "http://localhost:5173").rstrip("/")
    booking_link = f"{app_base_url}/my-bookings"
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Booking Confirmation</title>
</head>
<body style="margin:0; padding:0; background-color:#f4f4f7; font-family:Arial, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f7; padding:20px;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px; width:100%; background:#ffffff; border-radius:12px; overflow:hidden; box-shadow:0 4px 10px rgba(0,0,0,0.05);">
          <tr>
            <td align="center" style="background:linear-gradient(90deg, #6C63FF, #8E85FF); padding:24px;">
              <h1 style="color:#ffffff; margin:0; font-size:26px;">BookMyPhotoshoot</h1>
              <p style="color:#e0e0ff; margin:8px 0 0;">Capture Your Moments, Forever 📸</p>
            </td>
          </tr>
          <tr>
            <td style="padding:22px 22px 10px;">
              <p style="font-size:16px; margin:0;">Hello <strong>{customer_name}</strong>,</p>
              <p style="font-size:16px; margin:12px 0 0;">Your booking has been successfully confirmed! 🎉</p>
            </td>
          </tr>
          <tr>
            <td style="padding:0 22px 20px;">
              <table width="100%" cellpadding="10" cellspacing="0" style="border:1px solid #ececf2; border-radius:10px;">
                <tr><td><strong>📌 Event Name:</strong></td><td>{event_name}</td></tr>
                <tr><td><strong>📅 Date:</strong></td><td><strong>{dt["date"]}</strong></td></tr>
                <tr><td><strong>⏰ Time:</strong></td><td><strong>{dt["time"]}</strong></td></tr>
                <tr><td><strong>📍 Location:</strong></td><td>{location}</td></tr>
                <tr><td><strong>👤 Booked By:</strong></td><td>{customer_name}</td></tr>
                <tr><td><strong>📷 Photographer:</strong></td><td>{photographer_name}</td></tr>
                <tr><td><strong>🧾 Booking ID:</strong></td><td>{booking_id}</td></tr>
              </table>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:4px 22px 20px;">
              <a href="{booking_link}" style="background:#6C63FF; color:#ffffff; text-decoration:none; padding:12px 24px; border-radius:8px; display:inline-block; font-weight:bold;">
                View Booking Details
              </a>
            </td>
          </tr>
          <tr>
            <td style="padding:0 22px 20px;">
              <p style="font-size:14px; color:#555; margin:0;">
                Please arrive 10 minutes before your scheduled time.<br>
                For any changes, contact your photographer.
              </p>
            </td>
          </tr>
          <tr>
            <td align="center" style="background:#f9f9fb; padding:15px; border-top:1px solid #ececf2;">
              <p style="margin:0; font-size:14px; color:#777;">Thank you for choosing <strong>BookMyPhotoshoot 💜</strong></p>
              <p style="margin:8px 0 0; font-size:12px; color:#999;">Need help? contact@bookmyphotoshoot.demo</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


@router.post("/quotation/request")
async def quotation_request(
    body: QuoteRequestBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can request quotations")
    photographer = await db["users"].find_one({"_id": _oid(body.photographer_id), "role": "photographer", "is_deleted": {"$ne": True}})
    if not photographer:
        raise HTTPException(status_code=404, detail="Photographer not found")
    now = datetime.utcnow()
    start_dt = body.event_start_date
    end_dt = body.event_end_date
    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="Event end date must be after start date")
    diff_hours = (end_dt - start_dt).total_seconds() / 3600
    computed_duration_hours = round(diff_hours, 2)
    if computed_duration_hours <= 0:
        raise HTTPException(status_code=400, detail="Event duration must be greater than 0")
    duration_hours = float(body.duration_hours or computed_duration_hours)
    if start_dt.date() == end_dt.date():
        duration_hours = computed_duration_hours
    quotation_doc = {
        "user_id": _oid(current_user.id),
        "photographer_id": _oid(body.photographer_id),
        "event_details": {
            "title": body.event_title.strip(),
            "event_type": body.event_type.strip().lower(),
            "location": body.location.strip(),
            "event_start_date": start_dt,
            "event_end_date": end_dt,
            "event_date": start_dt,
            "duration_hours": duration_hours,
            "description": body.description,
            "budget": body.budget,
        },
        "status": "requested",
        "latest_amount": None,
        "booked_at": None,
        "created_at": now,
        "updated_at": now,
    }
    res = await db["quotations"].insert_one(quotation_doc)
    return {"quotation_id": str(res.inserted_id), "status": "requested"}


@router.post("/quotation/respond")
async def quotation_respond(
    body: QuoteRespondBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    if current_user.role != "photographer":
        raise HTTPException(status_code=403, detail="Only photographers can respond")
    quotation = await db["quotations"].find_one({"_id": _oid(body.quotation_id)})
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
    if str(quotation["photographer_id"]) != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed for this quotation")
    if quotation.get("status") in {"booked", "expired"}:
        raise HTTPException(status_code=400, detail="Quotation is no longer editable")
    now = datetime.utcnow()
    await db["quotation_messages"].insert_one(
        {
            "quotation_id": quotation["_id"],
            "sender": "photographer",
            "amount": body.amount,
            "message": body.message,
            "created_at": now,
        }
    )
    await db["quotations"].update_one(
        {"_id": quotation["_id"]},
        {"$set": {"status": "quoted", "latest_amount": body.amount, "updated_at": now}},
    )
    return {"message": "Quotation submitted", "status": "quoted"}


@router.post("/quotation/revise")
async def quotation_revise(
    body: QuoteReviseBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    action = body.action.strip().lower()
    if action not in {"accept", "counter", "revise"}:
        raise HTTPException(status_code=400, detail="Invalid action")
    quotation = await db["quotations"].find_one({"_id": _oid(body.quotation_id)})
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
    is_customer = str(quotation["user_id"]) == current_user.id
    is_photographer = str(quotation["photographer_id"]) == current_user.id
    if not (is_customer or is_photographer):
        raise HTTPException(status_code=403, detail="Not allowed for this quotation")
    now = datetime.utcnow()
    if action == "accept":
        await db["quotations"].update_one(
            {"_id": quotation["_id"]},
            {"$set": {"status": "accepted", "updated_at": now}},
        )
        await db["quotation_messages"].insert_one(
            {
                "quotation_id": quotation["_id"],
                "sender": "customer" if is_customer else "photographer",
                "amount": quotation.get("latest_amount"),
                "message": body.message or "Accepted",
                "created_at": now,
            }
        )
        return {"message": "Quotation accepted", "status": "accepted"}

    amount = body.counter_amount
    if amount is None:
        raise HTTPException(status_code=400, detail="counter_amount is required for counter/revise")
    if action == "counter" and not is_customer:
        raise HTTPException(status_code=403, detail="Only customer can counter quote")
    if action == "revise" and not is_photographer:
        raise HTTPException(status_code=403, detail="Only photographer can revise quote")
    await db["quotation_messages"].insert_one(
        {
            "quotation_id": quotation["_id"],
            "sender": "customer" if is_customer else "photographer",
            "amount": amount,
            "message": body.message,
            "created_at": now,
        }
    )
    await db["quotations"].update_one(
        {"_id": quotation["_id"]},
        {"$set": {"status": "negotiation", "latest_amount": amount, "updated_at": now}},
    )
    return {"message": "Negotiation update sent", "status": "negotiation"}


def _is_overlap(existing_start: datetime, existing_duration: float, new_start: datetime, new_duration: float) -> bool:
    existing_end = existing_start + timedelta(hours=float(existing_duration or 0))
    new_end = new_start + timedelta(hours=float(new_duration or 0))
    return existing_start < new_end and new_start < existing_end


@router.post("/booking/confirm")
async def booking_confirm(
    body: BookingConfirmBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    quotation = await db["quotations"].find_one({"_id": _oid(body.quotation_id)})
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
    if str(quotation["user_id"]) != current_user.id:
        raise HTTPException(status_code=403, detail="Only requesting customer can confirm booking")
    if quotation.get("status") not in {"accepted", "quoted", "negotiation"}:
        raise HTTPException(status_code=400, detail="Quotation is not in confirmable state")

    event = quotation.get("event_details") or {}
    event_start_date = event.get("event_start_date") or event.get("event_date")
    event_end_date = event.get("event_end_date")
    duration_hours = float(event.get("duration_hours") or 1)
    if event_start_date and event_end_date:
        computed_hours = (event_end_date - event_start_date).total_seconds() / 3600
        if computed_hours > 0:
            duration_hours = float(round(computed_hours, 2))
    event_date = event_start_date
    if not event_date:
        raise HTTPException(status_code=400, detail="Missing event date")

    active_bookings = await db["bookings"].find(
        {
            "photographer_id": quotation["photographer_id"],
            "status": {"$in": ["confirmed", "upcoming", "completed"]},
        }
    ).to_list(length=500)
    for booking in active_bookings:
        existing_start = booking.get("event_date")
        if not existing_start:
            continue
        if _is_overlap(existing_start, float(booking.get("duration") or 1), event_date, duration_hours):
            raise HTTPException(status_code=400, detail="Photographer is not available for this timeslot")

    customer = await db["users"].find_one({"_id": quotation["user_id"]})
    photographer = await db["users"].find_one({"_id": quotation["photographer_id"]})
    quoted_price = float(quotation.get("latest_amount") or 0)
    if quoted_price <= 0:
        raise HTTPException(status_code=400, detail="Quotation amount is not set")
    is_member = bool(customer and _is_member_active(customer))
    discount_rate = 0.10 if is_member else 0.0
    discount_applied = round(quoted_price * discount_rate, 2)
    final_price = round(quoted_price - discount_applied, 2)

    now = datetime.utcnow()
    invoice_number = f"INV-{now.strftime('%Y%m%d')}-{str(ObjectId())[-6:].upper()}"
    booking_doc = {
        "quotation_id": quotation["_id"],
        "user_id": quotation["user_id"],
        "photographer_id": quotation["photographer_id"],
        "final_price": final_price,
        "quoted_price": quoted_price,
        "discount_applied": discount_applied,
        "discount_rate": discount_rate,
        "status": "confirmed",
        "event_title": event.get("title"),
        "event_type": event.get("event_type"),
        "location": event.get("location"),
        "event_date": event_date,
        "event_end_date": event_end_date,
        "duration": duration_hours,
        "description": event.get("description"),
        "budget": event.get("budget"),
        "payment_stage": body.pay_stage,
        "payment_status": "pending",
        "invoice": {
            "invoice_number": invoice_number,
            "generated_at": now,
            "event_details": event,
            "quoted_price": quoted_price,
            "discount_applied": discount_applied,
            "final_price": final_price,
        },
        "created_at": now,
        "updated_at": now,
    }
    booking_res = await db["bookings"].insert_one(booking_doc)
    task_res = await db["tasks"].insert_one(
        {
            "booking_id": booking_res.inserted_id,
            "photographer_id": quotation["photographer_id"],
            "event_date": event_date,
            "duration": duration_hours,
            "status": "upcoming",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["quotations"].update_one(
        {"_id": quotation["_id"]},
        {"$set": {"status": "booked", "booked_at": now, "booking_id": booking_res.inserted_id, "updated_at": now}},
    )

    _send_email(
        (photographer or {}).get("email"),
        "Booking Confirmed",
        f"<p>A booking was confirmed for {event.get('title') or 'your event'} on {event_date}.</p>",
    )
    _send_email(
        (customer or {}).get("email"),
        "Your Booking is Confirmed",
        _booking_confirmation_email_html(
            customer_name=(customer or {}).get("full_name") or (customer or {}).get("name") or "Customer",
            event_name=event.get("title") or "Your Event",
            event_date=event_date,
            location=event.get("location") or "Location not specified",
            photographer_name=(photographer or {}).get("full_name") or (photographer or {}).get("name") or "Photographer",
            booking_id=str(booking_res.inserted_id),
        ),
    )

    return {
        "message": "Booking confirmed",
        "booking_id": str(booking_res.inserted_id),
        "task_id": str(task_res.inserted_id),
        "invoice_number": invoice_number,
        "final_price": final_price,
        "discount_applied": discount_applied,
    }


@router.get("/bookings/user")
async def get_user_bookings(
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    rows = await db["bookings"].find({"user_id": _oid(current_user.id)}).sort("event_date", -1).to_list(length=500)
    for row in rows:
        row["id"] = str(row.pop("_id"))
        row["quotation_id"] = str(row.get("quotation_id")) if row.get("quotation_id") else None
        row["user_id"] = str(row.get("user_id")) if row.get("user_id") else None
        row["photographer_id"] = str(row.get("photographer_id")) if row.get("photographer_id") else None
    now = datetime.utcnow()
    upcoming = [r for r in rows if r.get("event_date") and r["event_date"] >= now]
    past = [r for r in rows if r.get("event_date") and r["event_date"] < now]
    return {"upcoming": upcoming, "past": past}


@router.get("/bookings/photographer")
async def get_photographer_bookings(
    month_only: bool = Query(False),
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    if current_user.role != "photographer":
        raise HTTPException(status_code=403, detail="Only photographers can view this")
    query: Dict[str, Any] = {"photographer_id": _oid(current_user.id)}
    if month_only:
        start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        query["event_date"] = {"$gte": start}
    rows = await db["bookings"].find(query).sort("event_date", -1).to_list(length=1000)
    for row in rows:
        row["id"] = str(row.pop("_id"))
        row["quotation_id"] = str(row.get("quotation_id")) if row.get("quotation_id") else None
        row["user_id"] = str(row.get("user_id")) if row.get("user_id") else None
        row["photographer_id"] = str(row.get("photographer_id")) if row.get("photographer_id") else None
    return {"items": rows}


@router.post("/payment/initiate")
async def initiate_payment(
    body: PaymentInitiateBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    booking = await db["bookings"].find_one({"_id": _oid(body.booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if str(booking.get("user_id")) != current_user.id:
        raise HTTPException(status_code=403, detail="Only booking customer can pay")
    amount = float(body.amount or booking.get("final_price") or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid payment amount")
    now = datetime.utcnow()
    payment_status = "success" if body.simulate_success else "failed"
    payment_res = await db["payments"].insert_one(
        {
            "booking_id": booking["_id"],
            "user_id": booking.get("user_id"),
            "photographer_id": booking.get("photographer_id"),
            "amount": amount,
            "status": payment_status,
            "created_at": now,
            "updated_at": now,
        }
    )
    if body.simulate_success:
        await db["bookings"].update_one(
            {"_id": booking["_id"]},
            {"$set": {"payment_status": "success", "payout_status": "initiated", "updated_at": now}},
        )
    return {"payment_id": str(payment_res.inserted_id), "payment_status": payment_status}


@router.post("/task/complete")
async def task_complete(
    body: TaskCompleteBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    task = await db["tasks"].find_one({"_id": _oid(body.task_id)})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if str(task.get("photographer_id")) != current_user.id:
        raise HTTPException(status_code=403, detail="Only assigned photographer can complete task")
    now = datetime.utcnow()
    await db["tasks"].update_one({"_id": task["_id"]}, {"$set": {"status": "completed", "updated_at": now}})
    booking = await db["bookings"].find_one({"_id": task.get("booking_id")})
    if booking:
        await db["bookings"].update_one({"_id": booking["_id"]}, {"$set": {"status": "completed", "updated_at": now}})
        customer = await db["users"].find_one({"_id": booking.get("user_id")})
        if booking.get("payment_status") != "success":
            _send_email(
                (customer or {}).get("email"),
                "Payment Reminder",
                "<p>Your shoot is marked completed. Please complete payment to close the booking.</p>",
            )
    return {"message": "Task marked as completed"}


@router.post("/booking/cancel")
async def cancel_booking(
    body: BookingCancelBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    booking = await db["bookings"].find_one({"_id": _oid(body.booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.get("status") == "cancelled":
        return {"message": "Booking already cancelled"}

    role = (current_user.role or "").lower()
    is_admin = role in {"admin", "staff", "super_admin"}
    owns_as_customer = str(booking.get("user_id") or booking.get("customer_id")) == current_user.id
    owns_as_photographer = str(booking.get("photographer_id")) == current_user.id
    if not (is_admin or owns_as_customer or owns_as_photographer):
        raise HTTPException(status_code=403, detail="Not allowed to cancel this booking")

    event_date = booking.get("event_date")
    if owns_as_photographer and event_date:
        days_diff = (event_date - datetime.utcnow()).total_seconds() / 86400
        if days_diff < 7:
            raise HTTPException(status_code=400, detail="Photographer cannot cancel booking within 7 days")

    cancelled_by = "admin" if is_admin else ("photographer" if owns_as_photographer else "user")
    now = datetime.utcnow()
    await db["bookings"].update_one(
        {"_id": booking["_id"]},
        {"$set": {"status": "cancelled", "cancelled_by": cancelled_by, "updated_at": now}},
    )
    event_id = booking.get("event_id")
    if event_id:
        await db["auctions"].update_one(
            {"_id": event_id},
            {"$set": {"status": "cancelled", "updated_at": now}},
        )
    return {"message": "Booking cancelled", "cancelled_by": cancelled_by}


@router.post("/booking/complete")
async def complete_booking(
    body: BookingCompleteBody,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    booking = await db["bookings"].find_one({"_id": _oid(body.booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if str(booking.get("photographer_id")) != current_user.id:
        raise HTTPException(status_code=403, detail="Only assigned photographer can complete booking")

    status = str(booking.get("status") or "").lower()
    if status in {"completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Booking cannot be marked completed")

    start_dt = booking.get("event_date")
    if not isinstance(start_dt, datetime):
        raise HTTPException(status_code=400, detail="Booking start date is missing")

    today = datetime.utcnow().date()
    if today < start_dt.date():
        raise HTTPException(status_code=400, detail="Booking can only be completed on or after the event start date")

    now = datetime.utcnow()
    await db["bookings"].update_one(
        {"_id": booking["_id"]},
        {"$set": {"status": "completed", "updated_at": now}},
    )
    await db["tasks"].update_many(
        {"booking_id": booking["_id"], "photographer_id": booking.get("photographer_id")},
        {"$set": {"status": "completed", "updated_at": now}},
    )

    customer = await db["users"].find_one({"_id": booking.get("user_id")})
    if booking.get("payment_status") != "success":
        _send_email(
            (customer or {}).get("email"),
            "Payment Reminder",
            "<p>Your shoot is marked completed. Please complete payment to close the booking.</p>",
        )

    return {"message": "Booking marked as completed"}


@router.get("/quotation/mine")
async def my_quotations(
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    query = {"user_id": _oid(current_user.id)} if current_user.role == "customer" else {"photographer_id": _oid(current_user.id)}
    rows = await db["quotations"].find(query).sort("created_at", -1).to_list(length=500)
    user_ids = {row.get("user_id") for row in rows if row.get("user_id")} | {
        row.get("photographer_id") for row in rows if row.get("photographer_id")
    }
    users_by_id: Dict[str, Dict[str, Any]] = {}
    if user_ids:
        user_rows = await db["users"].find({"_id": {"$in": list(user_ids)}}).to_list(length=1000)
        users_by_id = {str(u.get("_id")): u for u in user_rows if u.get("_id")}
    for row in rows:
        row["id"] = str(row.pop("_id"))
        row["user_id"] = str(row.get("user_id")) if row.get("user_id") else None
        row["photographer_id"] = str(row.get("photographer_id")) if row.get("photographer_id") else None
        row["booking_id"] = str(row.get("booking_id")) if row.get("booking_id") else None
        row["customer_name"] = (users_by_id.get(row["user_id"]) or {}).get("full_name") or (users_by_id.get(row["user_id"]) or {}).get("name")
        row["photographer_name"] = (users_by_id.get(row["photographer_id"]) or {}).get("full_name") or (
            users_by_id.get(row["photographer_id"]) or {}
        ).get("name")
    return {"items": rows}


@router.get("/quotation/{quotation_id}/messages")
async def quotation_messages(
    quotation_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    quotation = await db["quotations"].find_one({"_id": _oid(quotation_id)})
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
    if str(quotation.get("user_id")) != current_user.id and str(quotation.get("photographer_id")) != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed")
    rows = await db["quotation_messages"].find({"quotation_id": quotation["_id"]}).sort("created_at", 1).to_list(length=1000)
    items = []
    for row in rows:
        items.append(
            {
                "id": str(row.get("_id")),
                "quotation_id": str(row.get("quotation_id")),
                "sender": row.get("sender"),
                "amount": row.get("amount"),
                "message": row.get("message"),
                "created_at": row.get("created_at"),
            }
        )
    return {"items": items}
