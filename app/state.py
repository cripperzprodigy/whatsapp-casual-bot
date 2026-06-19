from sqlalchemy import Column, String, Boolean, JSON, Integer, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine
from datetime import datetime
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
    use_local_llm_for_simple_tasks = Column(Boolean, default=True)
    use_cloud_llm_for_complex_tasks = Column(Boolean, default=True)
    bot_is_admin = Column(Boolean, default=False)
    group_name = Column(String, nullable=True)
    last_roster_export_at = Column(DateTime, nullable=True)

class GroupContactLedger(Base):
    __tablename__ = 'group_contact_ledger'
    
    chat_id = Column(String, primary_key=True)
    phone_number = Column(String, primary_key=True)
    
    push_name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)

class Task(Base):
    __tablename__ = 'tasks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, index=True)
    description = Column(String)
    is_done = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Note(Base):
    __tablename__ = 'notes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, index=True)
    content = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class MessageBuffer(Base):
    __tablename__ = 'message_buffer'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, index=True)
    sender_id = Column(String)
    sender_name = Column(String)
    content = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_chat_settings(db, chat_id: str) -> ChatSettings:
    settings_obj = db.query(ChatSettings).filter(ChatSettings.chat_id == chat_id).first()
    if not settings_obj:
        settings_obj = ChatSettings(chat_id=chat_id)
        db.add(settings_obj)
        db.commit()
        db.refresh(settings_obj)
    return settings_obj

def add_message_to_buffer(db, chat_id: str, sender_id: str, sender_name: str, content: str):
    msg = MessageBuffer(chat_id=chat_id, sender_id=sender_id, sender_name=sender_name, content=content)
    db.add(msg)
    
    # Prune old messages
    count = db.query(MessageBuffer).filter(MessageBuffer.chat_id == chat_id).count()
    if count > settings.MESSAGE_BUFFER_SIZE:
        oldest = db.query(MessageBuffer).filter(MessageBuffer.chat_id == chat_id).order_by(MessageBuffer.timestamp.asc()).first()
        db.delete(oldest)
    
    db.commit()
