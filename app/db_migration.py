import logging
from sqlalchemy import text
from app.state import engine

logger = logging.getLogger(__name__)

def migrate_group_contact_ledger():
    with engine.begin() as conn:
        # Check if jid column exists
        try:
            result = conn.execute(text("PRAGMA table_info(group_contact_ledger)"))
            columns = [row[1] for row in result.fetchall()]
            if 'jid' in columns:
                return # Already migrated
            
            logger.info("Migrating group_contact_ledger schema...")
            
            # 1. Create new table
            conn.execute(text('''
                CREATE TABLE group_contact_ledger_new (
                    chat_id VARCHAR NOT NULL,
                    jid VARCHAR NOT NULL,
                    phone_number VARCHAR,
                    push_name VARCHAR,
                    is_admin BOOLEAN,
                    is_active BOOLEAN,
                    first_seen_at DATETIME,
                    last_seen_at DATETIME,
                    PRIMARY KEY (chat_id, jid)
                )
            '''))
            
            # 2. Copy data
            # Assume existing phone_number is a standard whatsapp number. Append @s.whatsapp.net to create a fallback jid.
            conn.execute(text('''
                INSERT INTO group_contact_ledger_new 
                (chat_id, jid, phone_number, push_name, is_admin, is_active, first_seen_at, last_seen_at)
                SELECT 
                    chat_id,
                    phone_number || '@s.whatsapp.net',
                    phone_number,
                    push_name,
                    is_admin,
                    is_active,
                    first_seen_at,
                    last_seen_at
                FROM group_contact_ledger
            '''))
            
            # 3. Drop old table
            conn.execute(text("DROP TABLE group_contact_ledger"))
            
            # 4. Rename new table
            conn.execute(text("ALTER TABLE group_contact_ledger_new RENAME TO group_contact_ledger"))
            
            logger.info("Migration of group_contact_ledger completed successfully.")
        except Exception as e:
            logger.error(f"Migration failed or not required (table might not exist yet): {e}")

