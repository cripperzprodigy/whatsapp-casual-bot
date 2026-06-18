import os
import csv
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.state import Contact, GroupMember, get_chat_settings
from app.config import settings

logger = logging.getLogger(__name__)

def update_contact(db: Session, chat_id: str, phone_number: str, push_name: str, is_admin: bool = False):
    """
    Passively updates or inserts a contact into the database when they send a message,
    and associates them with the group.
    """
    if not settings.AUTO_SYNC_CONTACTS:
        return

    # 1. Update Contact Table
    contact = db.query(Contact).filter(Contact.phone_number == phone_number).first()
    if contact:
        contact.last_seen = datetime.utcnow()
        if push_name and push_name != "Unknown" and contact.push_name != push_name:
            contact.push_name = push_name
    else:
        contact = Contact(phone_number=phone_number, push_name=push_name)
        db.add(contact)

    # 2. Update GroupMember Table
    membership = db.query(GroupMember).filter(
        GroupMember.chat_id == chat_id, 
        GroupMember.phone_number == phone_number
    ).first()
    
    if not membership:
        membership = GroupMember(chat_id=chat_id, phone_number=phone_number, is_admin=is_admin)
        db.add(membership)
    elif is_admin and not membership.is_admin:
        # Passively upgrading to admin if we detect it
        membership.is_admin = True

    db.commit()

def export_group_contacts(db: Session, chat_id: str):
    """
    Exports the group contacts to CSV and MD files in `exports/groups/{chat_id}/`
    """
    if not settings.AUTO_SYNC_CONTACTS:
        return

    # Fetch all members of this group
    memberships = db.query(GroupMember).filter(GroupMember.chat_id == chat_id).all()
    if not memberships:
        return

    # Get Chat Settings for the group name and bot status
    chat_settings = get_chat_settings(db, chat_id)
    group_name = chat_settings.group_name or "Unknown Group"
    bot_is_admin = chat_settings.bot_is_admin

    export_dir = os.path.join("exports", "groups", chat_id.replace('@g.us', ''))
    os.makedirs(export_dir, exist_ok=True)

    csv_path = os.path.join(export_dir, "contacts.csv")
    md_path = os.path.join(export_dir, "summary.md")

    # Gather data
    contact_data = []
    for mem in memberships:
        contact = db.query(Contact).filter(Contact.phone_number == mem.phone_number).first()
        name = contact.push_name if contact and contact.push_name else "Unknown"
        contact_data.append({
            "Phone Number": mem.phone_number,
            "Name": name,
            "Is Admin": mem.is_admin
        })

    # Write CSV
    with open(csv_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["Phone Number", "Name", "Is Admin"])
        writer.writeheader()
        writer.writerows(contact_data)

    # Write MD
    with open(md_path, mode='w', encoding='utf-8') as f:
        f.write(f"# Group: {group_name}\n\n")
        f.write(f"**Chat ID:** `{chat_id}`\n")
        f.write(f"**Bot is Admin:** `{'Yes' if bot_is_admin else 'No'}`\n")
        f.write(f"**Total Members Synced:** {len(contact_data)}\n\n")
        f.write("## Members Roster\n\n")
        f.write("| Phone Number | Name | Admin |\n")
        f.write("| --- | --- | --- |\n")
        for c in contact_data:
            admin_status = "✅" if c["Is Admin"] else "❌"
            f.write(f"| `{c['Phone Number']}` | {c['Name']} | {admin_status} |\n")

    logger.info(f"Exported contacts for {chat_id} to {export_dir}")
