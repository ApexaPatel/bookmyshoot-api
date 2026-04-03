from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PlanRules:
    name: str
    price_inr: int
    max_photoshoots: int
    max_gallery_images: int
    monthly_limit: bool
    allow_future_event_dates: bool


PLAN_RULES = {
    "free": PlanRules(
        name="Free",
        price_inr=0,
        max_photoshoots=10,
        max_gallery_images=5,
        monthly_limit=False,
        allow_future_event_dates=True,
    ),
    "pro": PlanRules(
        name="Pro",
        price_inr=299,
        max_photoshoots=20,
        max_gallery_images=7,
        monthly_limit=True,
        allow_future_event_dates=False,
    ),
    "premium": PlanRules(
        name="Premium",
        price_inr=399,
        max_photoshoots=28,
        max_gallery_images=10,
        monthly_limit=True,
        allow_future_event_dates=False,
    ),
}


def get_plan_rules(plan: str | None) -> PlanRules:
    return PLAN_RULES.get((plan or "free").lower(), PLAN_RULES["free"])


def get_plan_window(user) -> tuple[datetime | None, datetime | None]:
    return getattr(user, "plan_started_at", None), getattr(user, "plan_expires_at", None)


def get_usage_period_bounds(rules: PlanRules, user) -> tuple[datetime | None, datetime | None]:
    """Paid plans: subscription window. Free plan: no date filter (lifetime total)."""
    if not rules.monthly_limit:
        return None, None
    return get_plan_window(user)
