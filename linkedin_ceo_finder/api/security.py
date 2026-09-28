"""Xác thực bảo mật API Key cho LinkedIn CEO Finder."""

import os
from typing import Optional
from fastapi import Header, HTTPException, Query, status


async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    key: Optional[str] = Query(None),
) -> bool:
    """Xác thực API Key từ X-API-Key header, Authorization Bearer header, hoặc query parameter 'key'."""
    expected = os.getenv("CRON_API_KEY", "")
    if not expected:
        try:
            from crawler.api.config import settings
            expected = settings.CRON_API_KEY
        except Exception:
            pass

    token = x_api_key
    if not token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        else:
            token = authorization
    if not token and key:
        token = key

    if not expected or not token or token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing API Key (X-API-Key header)",
        )
    return True
