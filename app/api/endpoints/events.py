from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.db.mongodb import get_database
from app.models.event import EventType

router = APIRouter()


@router.get("/suggestions", response_model=dict)
async def get_event_suggestions(db: Database = Depends(get_database)):
    portfolio_names = await db["portfolios"].distinct("event_name")
    enum_names = [event.value.replace("_", " ").title() for event in EventType]
    suggestions = sorted({name.strip() for name in [*portfolio_names, *enum_names] if isinstance(name, str) and name.strip()})
    return {"suggestions": suggestions}
