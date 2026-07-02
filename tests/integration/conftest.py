import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import AsyncMock, patch

from app.main import app
from app.state import Base, get_db

# Use in-memory SQLite DB for tests
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session", autouse=True)
def setup_db():
    # Setup testing database
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db_session():
    # Clear data for each test by dropping and recreating or just letting tests run in transaction (easier to drop all)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

from httpx import AsyncClient, ASGITransport
import pytest_asyncio

@pytest_asyncio.fixture
async def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
            
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()

@pytest.fixture(autouse=True)
def mock_gateway():
    from app.whatsapp_gateway import GatewaySendResult
    with patch("app.whatsapp_gateway.send_text_message", new_callable=AsyncMock) as mock_send, \
         patch("app.whatsapp_gateway.fetch_group_metadata", new_callable=AsyncMock) as mock_fetch, \
         patch("app.whatsapp_gateway.check_gateway_health", new_callable=AsyncMock) as mock_health, \
         patch("app.whatsapp_gateway.resolve_contact_info", new_callable=AsyncMock) as mock_resolve, \
         patch("app.whatsapp_gateway.resolve_contact_info_batch", new_callable=AsyncMock) as mock_resolve_batch, \
         patch("app.whatsapp_gateway.resolve_quote_id", new_callable=AsyncMock) as mock_resolve_quote:
        
        mock_send.return_value = GatewaySendResult(success=True, status_code=200)
        mock_fetch.return_value = {"id": "123-group", "subject": "Test Group", "participants": [{"id": "123@c.us", "admin": None}]}
        mock_health.return_value = {"isConnected": True, "requires_qr": False}
        mock_resolve.return_value = {"success": True, "jid": "123@c.us", "name": "Test User"}
        mock_resolve_batch.return_value = [{"success": True, "jid": "123@c.us", "name": "Test User"}]
        mock_resolve_quote.return_value = "false_123_456"
        
        yield {
            "send": mock_send,
            "fetch": mock_fetch,
            "health": mock_health,
            "resolve": mock_resolve,
            "resolve_batch": mock_resolve_batch,
            "resolve_quote": mock_resolve_quote
        }

@pytest.fixture(autouse=True)
def mock_llm():
    with patch("app.ai_client.ask_llm", new_callable=AsyncMock) as mock_ask_llm:
        mock_ask_llm.return_value = "Mocked LLM Response"
        yield mock_ask_llm

@pytest.fixture(autouse=True)
def mock_search():
    with patch("app.services.search_service.HybridSearchService.search", new_callable=AsyncMock) as mock_hybrid_search, \
         patch("app.services.agentic_search_service.AgenticSearchOrchestrator.execute_iterative_search", new_callable=AsyncMock) as mock_agentic_search:
        
        mock_hybrid_search.return_value = {"results": [{"content": "search doc", "metadata": {}}], "strategy": "hybrid"}
        mock_agentic_search.return_value = "Mocked agentic synthesis answer"
        
        yield {
            "hybrid": mock_hybrid_search,
            "agentic": mock_agentic_search
        }
