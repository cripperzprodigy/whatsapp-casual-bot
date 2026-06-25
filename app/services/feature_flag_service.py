import logging
from sqlalchemy.orm import Session
from app.state import get_global_setting, set_global_setting
from app.config import settings

logger = logging.getLogger(__name__)

class FeatureFlagService:
    @classmethod
    def is_enabled(cls, db: Session, feature_name: str) -> bool:
        # Check runtime override in DB first
        runtime_val = get_global_setting(db, f"feature_{feature_name}")
        if runtime_val is not None:
            return runtime_val.lower() == "true"

        # Fallback to ENV default
        env_attr = f"ENABLE_{feature_name.upper()}"
        return getattr(settings, env_attr, False)

    @classmethod
    async def toggle_feature(cls, db: Session, feature_name: str, state: bool, sender_id: str) -> bool:
        from app.permissions import is_owner

        # Verify Owner
        if not await is_owner(db, sender_id):
            raise PermissionError("Only Owner can toggle features")

        # Save to DB
        set_global_setting(db, f"feature_{feature_name}", str(state))

        state_str = "ENABLED" if state else "DISABLED"
        logger.info(f"Feature '{feature_name}' was {state_str} by Owner {sender_id}.")
        return True
