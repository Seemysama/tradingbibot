from __future__ import annotations
from fastapi import HTTPException

class ApiError(HTTPException):
    def __init__(self, status_code: int, message: str, type_: str | None = None, details: dict | None = None):
        self.type = type_ or self.__class__.__name__
        self.message = message
        self.details = details or {}
        super().__init__(status_code=status_code, detail={"type": self.type, "message": self.message, "details": self.details})

class SymbolNotFound(ApiError):
    def __init__(self, symbol: str):
        super().__init__(400, f"Unknown symbol: {symbol}")

class InvalidFormat(ApiError):
    def __init__(self, symbol: str):
        super().__init__(400, f"Invalid symbol format: {symbol}")

class Lockout(ApiError):
    def __init__(self):
        super().__init__(409, "Lockout active")

class UpstreamRateLimited(ApiError):
    def __init__(self, retry_after: float | None = None):
        details = {"retry_after": retry_after} if retry_after else {}
        super().__init__(429, "Upstream rate limited", details=details)
