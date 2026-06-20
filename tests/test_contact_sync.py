import pytest
from app.contact_sync import update_contact, process_active_sweep, export_group_contacts
from app.state import GroupContactLedger, ChatSettings, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
import shutil
from app.config import settings

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_jid_extraction(db_session):
    chat_id = "group1@g.us"
    jid = "628123456789@s.whatsapp.net"
    update_contact(db_session, chat_id, jid, push_name="John Doe", is_admin=False)
    
    contact = db_session.query(GroupContactLedger).first()
    assert contact.jid == jid
    assert contact.phone_number == "628123456789"
    assert contact.push_name == "John Doe"

def test_internal_id_extraction(db_session):
    chat_id = "group2@g.us"
    jid = "157286668472501@s.whatsapp.net"
    update_contact(db_session, chat_id, jid, push_name="Jane Doe", is_admin=True)
    
    contact = db_session.query(GroupContactLedger).first()
    assert contact.jid == jid
    assert contact.phone_number == "157286668472501"

def test_export_sanitization_and_csv(db_session):
    chat_id = "98765@g.us"
    jid = "111222333@s.whatsapp.net"
    
    chat_settings = ChatSettings(chat_id=chat_id, group_name="Test @Group #1!!")
    db_session.add(chat_settings)
    
    ledger_entry = GroupContactLedger(
        chat_id=chat_id,
        jid=jid,
        phone_number="111222333",
        push_name="Alice",
        is_admin=True,
        is_active=True
    )
    db_session.add(ledger_entry)
    db_session.commit()
    
    export_group_contacts(db_session, chat_id, force=True)
    
    expected_folder = "98765_test_group_1"
    export_dir = os.path.join(settings.CONTACTS_EXPORT_DIR, expected_folder)
    
    assert os.path.exists(export_dir)
    
    csv_path = os.path.join(export_dir, "contacts.csv")
    assert os.path.exists(csv_path)
    
    with open(csv_path, 'r') as f:
        content = f.read()
        assert "group_id,group_name,jid,phone_number,name,is_admin,is_active" in content
        assert "98765,Test @Group #1!!,111222333@s.whatsapp.net,111222333,Alice,True,True" in content

    # Cleanup
    if os.path.exists(settings.CONTACTS_EXPORT_DIR):
        shutil.rmtree(settings.CONTACTS_EXPORT_DIR)
