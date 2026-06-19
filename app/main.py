import logging
import logging.config
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.router_webhook import router as webhook_router
from app.router_system import router as system_router
from app.state import init_db, SessionLocal
from app.config import settings
from app.permissions import bootstrap_owner

# Issue 16: structured production logging with timestamp + module name
logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": (
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            ),
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        # Issue 16: honour LOG_LEVEL env var
        "level": settings.LOG_LEVEL.upper(),
        "handlers": ["console"],
    },
})

logger = logging.getLogger(__name__)

# Issue 8: initialise rate limiter (applied per-route in router_webhook)
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="WhatsApp Casual Bot")

# Issue 8: attach limiter + its exception handler to the app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(webhook_router)
app.include_router(system_router)


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("Initializing Database...")
    try:
        init_db()
        logger.info("Database initialized successfully.")
    except Exception as exc:  # Issue 6: surface DB init failures clearly
        logger.critical(
            "FATAL: Database initialization failed. "
            "Check DATABASE_URL and file permissions. Error: %s",
            exc,
        )
        raise

    try:
        with SessionLocal() as db:
            await bootstrap_owner(db)
    except Exception as exc:
        logger.error("Error bootstrapping owner: %s", exc)
        raise


@app.get("/")
def read_root() -> dict:
    return {"status": "running"}
