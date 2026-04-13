from fastapi import APIRouter
from app.api.endpoints import (
    admin_module,
    admin_subscriptions,
    auth,
    events,
    membership_auction,
    organizations,
    photographers,
    portfolio,
    quotation,
    simulate_payment,
    upload,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(membership_auction.router, tags=["membership-auction"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(organizations.router, prefix="/organizations", tags=["organizations"])
api_router.include_router(photographers.router, prefix="/photographers", tags=["photographers"])
api_router.include_router(quotation.router, tags=["quotation"])
api_router.include_router(simulate_payment.router, tags=["demo-billing"])
api_router.include_router(admin_subscriptions.router, tags=["admin"])
api_router.include_router(admin_module.router, tags=["admin-module"])
