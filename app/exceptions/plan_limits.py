"""Structured errors for plan limit violations (used by exception handler in main)."""


class PlanLimitError(Exception):
    def __init__(self, error_code: str, message: str, status_code: int = 403):
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
