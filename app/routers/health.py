from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.sqlite import check_db_health
from app.services.sheets import get_sheets_client

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """
    Health check endpoint.

    Returns:
        - 200 OK if all checks pass
        - 503 Service Unavailable if any check fails
    """
    sheets_client = get_sheets_client()

    checks = {
        "sqlite": check_db_health(),
        "sheets": sheets_client.check_connection(),
    }

    all_healthy = all(checks.values())
    status = "ok" if all_healthy else "degraded"

    response_data = {
        "status": status,
        "checks": checks,
        "version": settings.version,
    }

    if all_healthy:
        return response_data
    else:
        return JSONResponse(status_code=503, content=response_data)
