import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db.sqlite import init_db
from app.routers import admin, applicants, auth, claim, health, intern, onboarding, program, sponsor
from app.services.sessions import COOKIE_NAME

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown events."""
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    docs_url="/docs" if settings.is_development else None,
    redoc_url=None,
    lifespan=lifespan,
)

# Mount static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(claim.router)
app.include_router(onboarding.router)
app.include_router(intern.router)
app.include_router(sponsor.router)
app.include_router(admin.router)
app.include_router(applicants.router)
app.include_router(program.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with appropriate responses."""
    if exc.status_code == 401:
        response = RedirectResponse(url="/", status_code=302)
        response.delete_cookie(COOKIE_NAME)
        logger.info("Redirecting unauthenticated request to login: %s", request.url.path)
        return response

    if exc.status_code == 403:
        return HTMLResponse(
            status_code=403,
            content="""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Access Denied</title>
<style>
  body{font-family:system-ui,sans-serif;display:flex;align-items:center;
       justify-content:center;min-height:100vh;margin:0;background:#f5f5f5;}
  .box{background:#fff;padding:2.5rem 3rem;border-radius:12px;
       box-shadow:0 2px 12px rgba(0,0,0,.08);text-align:center;max-width:420px;}
  h1{margin:0 0 .75rem;font-size:1.5rem;color:#062F49;}
  p{color:#555;margin:.5rem 0;}
  a{color:#5893BC;}
</style>
</head>
<body><div class="box">
  <h1>Access Denied</h1>
  <p>You don't have permission to view this page.</p>
  <p><a href="/">Return to sign-in</a></p>
</div></body></html>""",
        )

    if exc.status_code == 503:
        logger.warning("503 on %s: %s", request.url.path, exc.detail)
        return HTMLResponse(
            status_code=503,
            content="""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Be right back</title>
<meta http-equiv="refresh" content="15;url=">
<style>
  body{font-family:system-ui,sans-serif;display:flex;align-items:center;
       justify-content:center;min-height:100vh;margin:0;background:#f5f5f5;}
  .box{background:#fff;padding:2.5rem 3rem;border-radius:12px;
       box-shadow:0 2px 12px rgba(0,0,0,.08);text-align:center;max-width:420px;}
  h1{margin:0 0 .75rem;font-size:1.5rem;color:#062F49;}
  p{color:#555;margin:.5rem 0;}
  a{color:#5893BC;}
</style>
</head>
<body><div class="box">
  <h1>Be right back</h1>
  <p>The server is temporarily busy. Your session is safe.</p>
  <p>This page will <a href="">reload automatically</a> in 15 seconds.</p>
</div></body></html>""",
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred",
        },
    )
