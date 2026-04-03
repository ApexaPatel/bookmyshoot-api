"""
Configurable per-plan limits (single source for validation + docs).
Keys align with photographer_plan strings: free, pro, premium.
"""

PLAN_LIMITS = {
    "FREE": {
        "maxPhotoshoots": 10,
        "maxImagesPerPhotoshoot": 5,
        "lifetimePhotoshoots": True,
    },
    "PRO": {
        "maxPhotoshoots": 20,
        "maxImagesPerPhotoshoot": 7,
        "lifetimePhotoshoots": False,
    },
    "PREMIUM": {
        "maxPhotoshoots": 28,
        "maxImagesPerPhotoshoot": 10,
        "lifetimePhotoshoots": False,
    },
}
