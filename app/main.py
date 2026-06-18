import logging
from fastapi import FastAPI
from app.router_webhook import router as webhook_router
from app.router_system import router as system_router
from app.state import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WhatsApp Casual Bot")

@app.on_event("startup")
async def startup_event():
    logger.info("Initializing Database...")
    init_db()
    logger.info("Database Initialized.")

app.include_router(webhook_router)
app.include_router(system_router)

@app.get("/")
def read_root():
    return {"status": "running"}
