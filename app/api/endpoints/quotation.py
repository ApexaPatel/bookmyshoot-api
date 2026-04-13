from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from pymongo.database import Database

from app.db.mongodb import get_database

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
