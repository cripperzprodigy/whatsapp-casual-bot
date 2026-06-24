import os
import csv
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.state import GroupContactLedger, get_chat_settings
from app.config import settings

logger = logging.getLogger(__name__)

def process_active_sweep(  # Issue 13: added return type
    db: Session,
    chat_id: str,
    participants: List[Dict[str, Any]],
) -> None:
    """
    Performs an active sweep. Takes the raw participants list from
    the Gateway API and updates the Isolated Ledger for this group.
    """
    if not chat_id.endswith('@g.us'):
        logger.debug(f"contact_sync: Skipping non-group JID {chat_id}")
        return

    if not settings.AUTO_SYNC_CONTACTS:
        return

    current_time = datetime.now(timezone.utc)  # Issue 4: utcnow
    seen_numbers: set = set()

    for p in participants:
        jid = p.get("id", "")
        if not jid:
            continue
            
        # Extract raw number logic
        part = jid.split("@")[0]
        # Keep raw ID if it's non-numeric or long, otherwise extract standard number
        # Although the spec says "keep it as is", we can just assign the part to phone_number
        phone_number = part if not part.isdigit() else part
        
        seen_numbers.add(jid)
        is_admin = p.get("admin") in ["admin", "superadmin"]

        ledger_entry = db.query(GroupContactLedger).filter(
            GroupContactLedger.chat_id == chat_id,
            GroupContactLedger.jid == jid
        ).first()

        if ledger_entry:
            ledger_entry.is_admin = is_admin
            ledger_entry.is_active = True
            # We don't overwrite push_name here because
            # the active sweep from Gateway usually just
            # gives phone numbers, not Push Names.
        else:
            ledger_entry = GroupContactLedger(
                chat_id=chat_id,
                jid=jid,
                phone_number=phone_number,
                is_admin=is_admin,
                is_active=True,
                first_seen_at=current_time,
                last_seen_at=current_time
            )
            db.add(ledger_entry)

    # Mark anyone no longer in the sweep as inactive
    all_members = (
        db.query(GroupContactLedger)
        .filter(GroupContactLedger.chat_id == chat_id)
        .all()
    )
    for mem in all_members:
        if mem.jid not in seen_numbers:
            mem.is_active = False

    db.commit()
    export_group_contacts(db, chat_id, force=True)


def update_contact(  # Issue 13: added return type
    db: Session,
    chat_id: str,
    jid: str,
    push_name: str,
    is_admin: bool = False,
) -> None:
    """
    Passively updates a contact in the isolated ledger when they
    send a message.
    """
    if not chat_id.endswith('@g.us'):
        logger.debug(f"contact_sync: Skipping non-group JID {chat_id}")
        return

    if not settings.AUTO_SYNC_CONTACTS:
        return

    part = jid.split("@")[0]
    phone_number = part if not part.isdigit() else part

    ledger_entry = db.query(GroupContactLedger).filter(
        GroupContactLedger.chat_id == chat_id,
        GroupContactLedger.jid == jid,
    ).first()

    current_time = datetime.now(timezone.utc)  # Issue 4: utcnow

    if ledger_entry:
        ledger_entry.last_seen_at = current_time
        # They spoke, so they are definitely active
        ledger_entry.is_active = True
        if (
            push_name
            and push_name != "Unknown"
            and ledger_entry.push_name != push_name
        ):
            ledger_entry.push_name = push_name
            # If name changed, force export
            db.commit()
            export_group_contacts(db, chat_id, force=True)
            return
        if is_admin and not ledger_entry.is_admin:
            ledger_entry.is_admin = True
    else:
        ledger_entry = GroupContactLedger(
            chat_id=chat_id, 
            jid=jid,
            phone_number=phone_number, 
            push_name=push_name, 
            is_admin=is_admin,
            first_seen_at=current_time,
            last_seen_at=current_time
        )
        db.add(ledger_entry)

    db.commit()
    export_group_contacts(db, chat_id)


def export_group_contacts(  # Issue 13: added return type
    db: Session, chat_id: str, force: bool = False
) -> None:
    """
    Exports the group contacts to CSV and MD files.
    Throttles exports to once per ROSTER_EXPORT_THROTTLE_SECONDS
    to prevent disk thrashing, unless forced.
    """
    if not chat_id.endswith('@g.us'):
        logger.debug(f"contact_sync: Skipping non-group JID {chat_id}")
        return

    if not settings.AUTO_SYNC_CONTACTS:
        return

    chat_settings = get_chat_settings(db, chat_id)

    # Issue 14: use config constant instead of magic number 60
    throttle = timedelta(
        seconds=settings.ROSTER_EXPORT_THROTTLE_SECONDS
    )
    now = datetime.now(timezone.utc)  # Issue 4: utcnow
    if not force and chat_settings.last_roster_export_at:
        last_export = chat_settings.last_roster_export_at
        if last_export.tzinfo is None:
            last_export = last_export.replace(tzinfo=timezone.utc)
        if now - last_export < throttle:
            return

    # Fetch all members of this group ledger
    memberships = (
        db.query(GroupContactLedger)
        .filter(GroupContactLedger.chat_id == chat_id)
        .order_by(GroupContactLedger.is_active.desc())
        .all()
    )
    if not memberships:
        return

    group_name = chat_settings.group_name or "Unknown Group"
    bot_is_admin = chat_settings.bot_is_admin

    import re
    group_id = chat_id.replace("@g.us", "")
    
    # Sanitization logic for group name
    sanitized_name = group_name.lower()
    sanitized_name = re.sub(r'[^a-z0-9]', '_', sanitized_name)
    sanitized_name = re.sub(r'_+', '_', sanitized_name)
    sanitized_name = sanitized_name.strip('_')
    
    folder_name = f"{group_id}_{sanitized_name}"

    # Issue 10: use configurable export dir from settings
    export_dir = os.path.join(
        settings.CONTACTS_EXPORT_DIR,
        folder_name,
    )
    os.makedirs(export_dir, exist_ok=True)

    csv_path = os.path.join(export_dir, "contacts.csv")
    md_path = os.path.join(export_dir, "summary.md")

    # Write CSV
    fieldnames = [
        "group_id", "group_name", "jid", "phone_number", "name", "is_admin", "is_active"
    ]
    with open(
        csv_path, mode="w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for mem in memberships:
            writer.writerow({
                "group_id": group_id,
                "group_name": group_name,
                "jid": mem.jid,
                "phone_number": mem.phone_number,
                "name": mem.push_name or "Unknown",
                "is_admin": mem.is_admin,
                "is_active": mem.is_active
            })

    # Write MD
    with open(md_path, mode='w', encoding='utf-8') as f:
        f.write(f"# Group: {group_name}\n\n")
        f.write(f"**Chat ID:** `{chat_id}`\n")
        f.write(f"**Bot is Admin:** `{'Yes' if bot_is_admin else 'No'}`\n")
        
        active_count = sum(1 for m in memberships if m.is_active)
        f.write(f"**Total Historical Members Tracked:** {len(memberships)}\n")
        f.write(f"**Currently Active:** {active_count}\n\n")
        
        f.write("## Members Roster\n\n")
        f.write("| Phone Number | Name | Admin | Status |\n")
        f.write("| --- | --- | --- | --- |\n")
        for mem in memberships:
            admin_status = "✅" if mem.is_admin else "❌"
            status = "🟢 Active" if mem.is_active else "🔴 Left"
            name = mem.push_name or "Unknown"
            f.write(
                f"| `{mem.phone_number}` | {name}"
                f" | {admin_status} | {status} |\n"
            )

    # Update throttle timestamp
    chat_settings.last_roster_export_at = now
    db.commit()
    logger.info(f"Exported isolated ledger for {chat_id} to {export_dir}")
