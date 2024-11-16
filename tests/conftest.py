# conftest.py
import pytest
from app.services.webhook_processor import WebhookProcessorService
from app.services.webhook import WebhookService
from unittest.mock import MagicMock, Mock
from unittest import mock
from app.db.session import test_engine
from app.db.base_class import Base
import fakeredis
from app.dependencies import deps

@pytest.fixture(scope="function")
def setup_database():
    """
    Create and drop tables for each test to ensure isolation.
    This fixture sets up a clean state for each test.
    """
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)

@pytest.fixture(scope="function", autouse=True)
def apply_migrations(setup_database):
    """
    Override the `get_db` dependency to use the test database session for each test.
    """
    yield

@pytest.fixture
def redis_client():
    redis_client = fakeredis.FakeRedis()
    return redis_client

@pytest.fixture
def mock_redlock_factory():
    mock_factory = MagicMock()
    mock_lock = MagicMock()
    mock_lock.acquire = MagicMock(return_value=True)
    mock_lock.release = MagicMock()
    mock_factory.create_lock = MagicMock(return_value=mock_lock)
    return mock_factory

@pytest.fixture
def webhook_service(redis_client, mock_redlock_factory):
    """Fixture to set up a WebhookService instance with fakeredis and mocked RedLockFactory."""
    webhook_repo = WebhookService(redis_client=redis_client, redlock_factory=mock_redlock_factory)
    webhook_repo.enqueue_webhook = mock.Mock()
    webhook_repo.retry_queue_size = Mock(return_value=20)
    return webhook_repo

@pytest.fixture
def webhook_processor(webhook_service, tmp_path):
    """Fixture to set up a WebhookProcessor instance with a temporary webhook file."""
    webhook_file = tmp_path / "webhooks.txt"
    webhook_file.write_text("header\nhttp://test.com, 1, test_user, test_event\n")
    return WebhookProcessorService(webhook_file, webhook_service)