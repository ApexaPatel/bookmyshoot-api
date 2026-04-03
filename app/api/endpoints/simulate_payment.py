"""
College demo: simulated payment — no real gateway. Upgrades photographer plan after fake checkout.
"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from pymongo.database import Database

from app.constants.subscription_plans import PREMIUM_PRICE_INR, PRO_PRICE_INR
from app.core.security import get_current_active_user
from app.crud.subscription import CRUDSubscription
from app.crud.user import CRUDUser, get_user_crud
from app.db.mongodb import get_database
from app.models.user import PhotographerPlan, UserInDB, UserResponse, UserRole

logger = logging.getLogger(__name__)

router = APIRouter()

_PLAN_AMOUNTS = {"pro": float(PRO_PRICE_INR), "premium": float(PREMIUM_PRICE_INR)}


def _plan_rank(plan: PhotographerPlan) -> int:
    return {
        PhotographerPlan.FREE: 0,
        PhotographerPlan.PRO: 1,
        PhotographerPlan.PREMIUM: 2,
    }[plan]


def _coerce_plan(value: Any) -> PhotographerPlan:
    if isinstance(value, PhotographerPlan):
        return value
    try:
        return PhotographerPlan(str(value).lower())
    except ValueError:
        return PhotographerPlan.FREE


class SimulatePaymentBody(BaseModel):
    plan: Literal["pro", "premium"]
    simulate_success: bool = Field(
        True,
        description="If false, records a failed payment and does not upgrade the plan (demo toggle).",
    )


class SimulatePaymentResponse(BaseModel):
    success: bool
    message: str
    payment_id: Optional[str] = None
    user: Optional[UserResponse] = None


@router.post("/simulate-payment", response_model=SimulatePaymentResponse)
async def simulate_payment(
    body: SimulatePaymentBody,
    current_user: UserInDB = Depends(get_current_active_user),
    user_crud: CRUDUser = Depends(get_user_crud),
    db: Database = Depends(get_database),
):
    if current_user.role != UserRole.PHOTOGRAPHER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only photographers can upgrade plans",
        )

    target = PhotographerPlan(body.plan)
    current = _coerce_plan(current_user.photographer_plan)
    if _plan_rank(target) <= _plan_rank(current):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or redundant plan upgrade",
        )

    sub_crud = CRUDSubscription(db)
    payment_id = f"DEMO-TXN-{uuid.uuid4().hex[:12].upper()}"
    amount = _PLAN_AMOUNTS[body.plan]
    now = datetime.utcnow()
    expiry = now + timedelta(days=30)

    if not body.simulate_success:
        await sub_crud.insert(
            user_id=current_user.id,
            plan=body.plan,
            amount=amount,
            status="failed",
            payment_id=payment_id,
            start_date=now,
            expiry_date=None,
        )
        return SimulatePaymentResponse(
            success=False,
            message="Simulated payment failed (demo mode). Your plan was not changed.",
            payment_id=payment_id,
            user=UserResponse(**current_user.dict(exclude={"hashed_password"}, by_alias=False)),
        )

    await sub_crud.insert(
        user_id=current_user.id,
        plan=body.plan,
        amount=amount,
        status="success",
        payment_id=payment_id,
        start_date=now,
        expiry_date=expiry,
    )

    await user_crud.update(
        current_user.id,
        {
            "photographer_plan": target.value,
            "plan_started_at": now,
            "plan_expires_at": expiry,
        },
        return_updated=True,
    )
    updated = await user_crud.get(current_user.id)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to refresh user after upgrade")

    return SimulatePaymentResponse(
        success=True,
        message="Simulated payment successful. Plan upgraded for demo.",
        payment_id=payment_id,
        user=UserResponse(**updated.dict(exclude={"hashed_password"}, by_alias=False)),
    )
