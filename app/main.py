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
from app.whatsapp_gateway import check_gateway_health

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


from app.config import settings, BotIdentityManager

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

    try:
        health_status = await check_gateway_health()
        if health_status.get("requires_qr", False) or not health_status.get("isConnected", True):
            logger.warning("WhatsApp Gateway reports it is not connected or requires a QR scan. Please check http://localhost:8000/whatsapp/qr")
    except Exception as exc:
        logger.warning(f"Could not reach WhatsApp gateway during startup: {exc}")

    # Pre-warm bot identity cache on startup
    detected = BotIdentityManager.get_bot_number()
    if detected:
        logger.info(f"[Startup] Bot identity resolved: {detected}")
        env_number = getattr(settings, 'BOT_NUMBER', None)
        if env_number and env_number != detected:
            logger.critical(f"[Startup] CRITICAL WARNING: Bot identity mismatch! ENV: {env_number}, Gateway: {detected}")
            if getattr(settings, 'AUTO_SYNC_BOT_NUMBER', False):
                logger.info("[Startup] AUTO_SYNC_BOT_NUMBER is True. Syncing...")
                if BotIdentityManager.sync_bot_number_to_env():
                    from app.config import safe_reload_settings
                    safe_reload_settings()
    else:
        logger.warning(
            "[Startup] Bot identity could not be resolved. "
            "Explicit @mention detection will be degraded until the "
            "WhatsApp gateway is reachable."
        )



@app.get("/")
def read_root() -> dict:
    return {"status": "running"}
