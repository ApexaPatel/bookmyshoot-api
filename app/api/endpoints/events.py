from typing import Any, Dict, List

from bson import ObjectId
from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.core.security import get_current_active_user
from app.db.mongodb import get_database
from app.models.event import EventType
from app.models.user import UserInDB

router = APIRouter()


@router.get("/suggestions", response_model=dict)
async def get_event_suggestions(db: Database = Depends(get_database)):
    portfolio_names = await db["portfolios"].distinct("event_name")
    enum_names = [event.value.replace("_", " ").title() for event in EventType]
    suggestions = sorted({name.strip() for name in [*portfolio_names, *enum_names] if isinstance(name, str) and name.strip()})
    return {"suggestions": suggestions}


def _status_for_panel(quotation_status: str, booking_status: str) -> str:
    if booking_status == "completed":
        return "completed"
    if booking_status in {"confirmed", "upcoming"}:
        return "confirmed"
    if quotation_status in {"booked"}:
        return "confirmed"
    return "open"


@router.get("/user", response_model=dict)
async def get_user_events(
    current_user: UserInDB = Depends(get_current_active_user),
    db: Database = Depends(get_database),
):
    if current_user.role != "customer":
        return {"events": []}

    user_id = ObjectId(current_user.id)
    quotations: List[Dict[str, Any]] = await db["quotations"].find({"user_id": user_id}).sort("created_at", -1).to_list(length=500)

    quotation_ids = [row["_id"] for row in quotations if row.get("_id")]
    booking_rows: List[Dict[str, Any]] = []
    if quotation_ids:
        booking_rows = await db["bookings"].find({"quotation_id": {"$in": quotation_ids}}).to_list(length=500)
    bookings_by_quote = {str(row.get("quotation_id")): row for row in booking_rows if row.get("quotation_id")}

    photographer_ids = {
        row.get("photographer_id") for row in quotations if row.get("photographer_id")
    } | {
        row.get("photographer_id") for row in booking_rows if row.get("photographer_id")
    }
    photographer_rows: List[Dict[str, Any]] = []
    if photographer_ids:
        photographer_rows = await db["users"].find({"_id": {"$in": list(photographer_ids)}}).to_list(length=500)
    photographer_name_by_id = {str(row["_id"]): row.get("name") for row in photographer_rows if row.get("_id")}

    events: List[Dict[str, Any]] = []
    for quotation in quotations:
        details = quotation.get("event_details") or {}
        booking = bookings_by_quote.get(str(quotation.get("_id")))
        booking_status = (booking or {}).get("status")
        quotation_status = quotation.get("status")
        photographer_id = (booking or {}).get("photographer_id") or quotation.get("photographer_id")
        events.append(
            {
                "id": str(quotation.get("_id")),
                "title": details.get("title") or "Event",
                "event_type": details.get("event_type"),
                "location": details.get("location") or "",
                "date": details.get("event_date"),
                "status": _status_for_panel(str(quotation_status or ""), str(booking_status or "")),
                "budget": details.get("budget"),
                "quoted_amount": quotation.get("latest_amount"),
                "photographer_id": str(photographer_id) if photographer_id else None,
                "photographer_name": photographer_name_by_id.get(str(photographer_id)) if photographer_id else None,
                "quotation_id": str(quotation.get("_id")),
            }
        )
    return {"events": events}
