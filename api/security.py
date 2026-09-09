from fastapi import Header, HTTPException, Query, status
from api.config import settings


async def verify_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None, alias="Authorization"),
    key: str | None = Query(None),
) -> bool:
    """
    Verify API Key from X-API-Key header, Authorization Bearer header, or key query parameter.
    """
    expected = settings.CRON_API_KEY

    token = x_api_key
    if not token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        else:
            token = authorization
    if not token and key:
        token = key

    if not token or token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing API Key",
        )
    return True
