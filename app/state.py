from sqlalchemy import Column, String, Boolean, JSON, Integer, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine
from datetime import datetime, timezone, timedelta
from app.config import settings

Base = declarative_base()

class ChatSettings(Base):
    __tablename__ = 'chat_settings'
    
    chat_id = Column(String, primary_key=True, index=True)
    # If None, the bot falls back to the GLOBAL_AUTO_TRANSLATE env config
    auto_translate_enabled = Column(Boolean, nullable=True, default=None)
    # If None, the bot falls back to the GLOBAL_TARGET_LANGUAGE env config
    default_target_language = Column(String, nullable=True, default=None)
    # If None, the bot falls back to the GLOBAL_IGNORED_LANGUAGES env config
    ignored_languages = Column(JSON, nullable=True, default=None)
    
    assistant_mode_enabled = Column(Boolean, default=False)
    bot_is_admin = Column(Boolean, default=False)
    group_name = Column(String, nullable=True)
    last_roster_export_at = Column(DateTime(timezone=True), nullable=True)

class GroupContactLedger(Base):
    __tablename__ = 'group_contact_ledger'
    
    chat_id = Column(String, primary_key=True)
    jid = Column(String, primary_key=True)
    phone_number = Column(String, nullable=True)
    
    push_name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    
    first_seen_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )  # Issue 4: replace deprecated utcnow
    last_seen_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )  # Issue 4: replace deprecated utcnow

class Task(Base):
    __tablename__ = 'tasks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, index=True)
    description = Column(String)
    is_done = Column(Boolean, default=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )  # Issue 4: replace deprecated utcnow

class Note(Base):
    __tablename__ = 'notes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, index=True)
    content = Column(String)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )  # Issue 4: replace deprecated utcnow

class MessageBuffer(Base):
    __tablename__ = 'message_buffer'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, index=True)
    sender_id = Column(String)
    sender_name = Column(String)
    content = Column(String)
    timestamp = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )  # Issue 4: replace deprecated utcnow


class GlobalSettings(Base):
    __tablename__ = 'global_settings'
    
    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

class BotAdmin(Base):
    __tablename__ = 'bot_admins'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, unique=True, index=True, nullable=False)
    role = Column(String, nullable=False)
    granted_by = Column(String, nullable=False)
    granted_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_active = Column(Boolean, default=True, nullable=False)


class SessionState(Base):
    """SQLite-backed session state for critical per-chat fields (Task 3 — Durability).

    Provides:
    - Persistence across process restarts for fields that must survive crashes.
    - Optimistic locking via ``session_version`` (etag) to detect concurrent writes.
    - Recovery support: rows stuck with ``is_processing=True`` after a crash are
      reset by ``recover_stale_sessions()`` on startup.
    """

    __tablename__ = 'session_state'

    chat_id = Column(String, primary_key=True, index=True)
    current_tool = Column(String, nullable=True)
    typing_state = Column(Boolean, default=False)
    tool_scratchpad = Column(JSON, nullable=True, default=list)
    # Optimistic locking counter — increment on every write.
    session_version = Column(Integer, default=0, nullable=False)
    is_processing = Column(Boolean, default=False)
    last_active = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine
)

def init_db():
    from app.db_migration import migrate_group_contact_ledger
    migrate_group_contact_ledger()
    Base.metadata.create_all(bind=engine)
    # Recovery mode: reset stale in-flight sessions from previous crash (Task 3)
    with SessionLocal() as db:
        recovered = recover_stale_sessions(db)
        if recovered:
            import logging
            logging.getLogger(__name__).info(
                f"[Startup Recovery] Reset {recovered} stale session(s)."
            )

def get_global_setting(db, key: str, default: str = None) -> str:
    setting = db.query(GlobalSettings).filter(GlobalSettings.key == key).first()
    if setting:
        return setting.value
    return default

def set_global_setting(db, key: str, value: str):
    setting = db.query(GlobalSettings).filter(GlobalSettings.key == key).first()
    if setting:
        setting.value = str(value)
    else:
        setting = GlobalSettings(key=key, value=str(value))
        db.add(setting)
    db.commit()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_chat_settings(db, chat_id: str) -> ChatSettings:
    settings_obj = (
        db.query(ChatSettings)
        .filter(ChatSettings.chat_id == chat_id)
        .first()
    )
    if not settings_obj:
        settings_obj = ChatSettings(chat_id=chat_id)
        db.add(settings_obj)
        db.commit()
        db.refresh(settings_obj)
    return settings_obj


# ── Session State helpers (Task 3 — Durability & Optimistic Locking) ─────────


def get_or_create_session_state(db, chat_id: str) -> "SessionState":
    """Return the persistent SessionState row for *chat_id*, creating it if absent."""
    row = db.query(SessionState).filter(SessionState.chat_id == chat_id).first()
    if not row:
        row = SessionState(chat_id=chat_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def update_session_state_atomic(
    db,
    chat_id: str,
    updates: dict,
    expected_version: int,
) -> bool:
    """Update session state fields using optimistic locking.

    Returns True if the update succeeded (version matched), False if a concurrent
    write was detected (version mismatch — caller should retry or abort).

    The ``session_version`` counter is always incremented on success.
    """
    row = db.query(SessionState).filter(SessionState.chat_id == chat_id).first()
    if not row:
        # Row doesn't exist yet — safe to create and set version=1
        row = SessionState(chat_id=chat_id, session_version=1, **updates)
        db.add(row)
        db.commit()
        return True

    if row.session_version != expected_version:
        # Concurrent modification detected
        import logging
        logging.getLogger(__name__).warning(
            f"[SessionState] Optimistic lock conflict for chat={chat_id}: "
            f"expected_version={expected_version}, actual={row.session_version}"
        )
        return False

    for key, value in updates.items():
        setattr(row, key, value)
    row.session_version = row.session_version + 1
    row.last_active = datetime.now(timezone.utc)
    db.commit()
    return True


def recover_stale_sessions(db, stale_age_seconds: int = 300) -> int:
    """Reset any sessions stuck in processing state older than *stale_age_seconds*.

    Call once at startup to clean up sessions left mid-flight by a crashed process.
    Returns the number of sessions reset.
    """
    import logging
    logger = logging.getLogger(__name__)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_age_seconds)
    stale = (
        db.query(SessionState)
        .filter(
            SessionState.is_processing == True,  # noqa: E712
            SessionState.last_active < cutoff,
        )
        .all()
    )
    count = 0
    for row in stale:
        row.is_processing = False
        row.current_tool = None
        row.tool_scratchpad = []
        row.session_version = row.session_version + 1
        logger.warning(
            f"[Recovery] Reset stale session for chat={row.chat_id} "
            f"(last_active={row.last_active})"
        )
        count += 1
    if count:
        db.commit()
    return count

def add_message_to_buffer(  # Issue 13: added return type
    db,
    chat_id: str,
    sender_id: str,
    sender_name: str,
    content: str,
) -> None:
    msg = MessageBuffer(
        chat_id=chat_id,
        sender_id=sender_id,
        sender_name=sender_name,
        content=content,
    )
    db.add(msg)

    # Issue 2: use while to drain any overflow caused by
    # burst messages arriving simultaneously.
    count = (
        db.query(MessageBuffer)
        .filter(MessageBuffer.chat_id == chat_id)
        .count()
    )
    while count > settings.MESSAGE_BUFFER_SIZE:
        oldest = (
            db.query(MessageBuffer)
            .filter(MessageBuffer.chat_id == chat_id)
            .order_by(MessageBuffer.timestamp.asc())
            .first()
        )
        if not oldest:
            break
        db.delete(oldest)
        count -= 1

    db.commit()
