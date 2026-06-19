import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.state import BotAdmin
from app.config import settings

logger = logging.getLogger(__name__)

OWNER_ROLE = "owner"
ADMIN_ROLE = "admin"
PUBLIC_ROLE = "public"
VALID_ROLES = {OWNER_ROLE, ADMIN_ROLE}

# This is intentionally runtime-only. It enables a one-time ownership claim
# when the bot starts with no configured owner and no BOT_OWNER_ID.
CLAIM_OWNERSHIP_ENABLED = False


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def get_user_role(db: Session, user_id: str) -> str:
    if not user_id:
        return PUBLIC_ROLE

    owner = (
        db.query(BotAdmin)
        .filter(
            BotAdmin.user_id == user_id,
            BotAdmin.role == OWNER_ROLE,
            BotAdmin.is_active.is_(True),
        )
        .first()
    )
    if owner:
        return OWNER_ROLE

    admin = (
        db.query(BotAdmin)
        .filter(
            BotAdmin.user_id == user_id,
            BotAdmin.role == ADMIN_ROLE,
            BotAdmin.is_active.is_(True),
        )
        .first()
    )
    if admin:
        return ADMIN_ROLE

    return PUBLIC_ROLE


async def is_owner(db: Session, user_id: str) -> bool:
    return (await get_user_role(db, user_id)) == OWNER_ROLE


async def is_admin(db: Session, user_id: str) -> bool:
    role = await get_user_role(db, user_id)
    return role == ADMIN_ROLE or role == OWNER_ROLE


async def grant_role(
    db: Session, target_id: str, role: str, granted_by: str
) -> BotAdmin:
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role: {role}")

    existing = (
        db.query(BotAdmin)
        .filter(BotAdmin.user_id == target_id)
        .first()
    )
    now = _now_utc()

    if existing:
        existing.role = role
        existing.granted_by = granted_by
        existing.granted_at = now
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return existing

    admin = BotAdmin(
        user_id=target_id,
        role=role,
        granted_by=granted_by,
        granted_at=now,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


async def revoke_role(db: Session, target_id: str, role: str) -> bool:
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role: {role}")

    target = (
        db.query(BotAdmin)
        .filter(
            BotAdmin.user_id == target_id,
            BotAdmin.role == role,
            BotAdmin.is_active.is_(True),
        )
        .first()
    )
    if not target:
        return False

    if role == OWNER_ROLE:
        owner_count = (
            db.query(BotAdmin)
            .filter(
                BotAdmin.role == OWNER_ROLE,
                BotAdmin.is_active.is_(True),
            )
            .count()
        )
        if owner_count <= 1:
            return False

    target.is_active = False
    db.commit()
    return True


async def bootstrap_owner(db: Session) -> None:
    active_owner_count = (
        db.query(BotAdmin)
        .filter(
            BotAdmin.role == OWNER_ROLE,
            BotAdmin.is_active.is_(True),
        )
        .count()
    )
    if active_owner_count > 0:
        return

    owner_id = settings.BOT_OWNER_ID
    if owner_id:
        await grant_role(db, owner_id, OWNER_ROLE, owner_id)
        logger.info("Bootstrap Owner created from ENV: %s", owner_id)
        return

    global CLAIM_OWNERSHIP_ENABLED
    CLAIM_OWNERSHIP_ENABLED = True
    logger.warning(
        "No owner configured. Claim ownership via !claim_ownership in a private chat."
    )


async def try_claim_ownership(
    db: Session, user_id: str, is_group_chat: bool
) -> bool:
    global CLAIM_OWNERSHIP_ENABLED
    if is_group_chat or not CLAIM_OWNERSHIP_ENABLED:
        return False

    active_owner_count = (
        db.query(BotAdmin)
        .filter(
            BotAdmin.role == OWNER_ROLE,
            BotAdmin.is_active.is_(True),
        )
        .count()
    )
    if active_owner_count > 0:
        CLAIM_OWNERSHIP_ENABLED = False
        return False

    await grant_role(db, user_id, OWNER_ROLE, user_id)
    CLAIM_OWNERSHIP_ENABLED = False
    logger.info("Bootstrap Owner claimed by user: %s", user_id)
    return True


async def list_active_roles(db: Session, role: str):
    return (
        db.query(BotAdmin)
        .filter(BotAdmin.role == role, BotAdmin.is_active.is_(True))
        .all()
    )
