import asyncio
import logging
from typing import List
from app.whatsapp_gateway import send_text_message
from app.state import SessionLocal, get_global_setting
from app.config import settings

logger = logging.getLogger(__name__)

async def _send_batch_with_flood_control(chat_id: str, target_jids: List[str], text: str):
    """
    Background task to send private messages in batches with flood control.
    Runs asynchronously and fetches fresh limits on execution.
    """
    db = SessionLocal()
    try:
        limit_str = get_global_setting(db, "pm_flood_limit", str(settings.PM_FLOOD_LIMIT))
        interval_str = get_global_setting(db, "pm_flood_interval_seconds", str(settings.PM_FLOOD_INTERVAL_SECONDS))
        
        try:
            limit = int(limit_str)
            interval = int(interval_str)
        except ValueError:
            limit = settings.PM_FLOOD_LIMIT
            interval = settings.PM_FLOOD_INTERVAL_SECONDS
            
        total = len(target_jids)
        logger.info(f"Starting batched PMs. Total targets: {total}. Limit: {limit} per {interval}s")
        
        for i in range(0, total, limit):
            batch = target_jids[i:i+limit]
            
            # Send the batch
            tasks = []
            for jid in batch:
                tasks.append(send_text_message(jid, text))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # send_text_message now returns a GatewaySendResult
            success_count = sum(1 for r in results if getattr(r, "success", False) is True)
            queued_count = sum(1 for r in results if getattr(r, "queued", False) is True)
            
            logger.info(f"Batch completed: sent {success_count}/{len(batch)} (queued: {queued_count})")
            
            # If there are more batches, sleep
            if i + limit < total:
                logger.info(f"Sleeping for {interval}s before next batch...")
                await asyncio.sleep(interval)
                
        # Notify sender when done
        await send_text_message(chat_id, f"✅ Batched PM operation completed. Total attempted: {total}.")
    except Exception as e:
        logger.error(f"Error in batched PM service: {e}")
        await send_text_message(chat_id, f"❌ Error during batched PM operation: {e}")
    finally:
        db.close()

def start_batched_pm_task(chat_id: str, target_jids: List[str], text: str):
    """
    Fires off the background task. 
    Using asyncio.create_task to ensure it runs concurrently.
    """
    asyncio.create_task(_send_batch_with_flood_control(chat_id, target_jids, text))

