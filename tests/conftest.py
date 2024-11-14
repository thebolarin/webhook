# conftest.py
import pytest
from app.services.webhook import WebhookProcessor
from unittest.mock import MagicMock, Mock
from unittest import mock
from queue import Queue, PriorityQueue
import threading
import time

@pytest.fixture
def mock_repository():
    """Fixture to set up a refined mock repository."""
    repository = MagicMock()
    
    # Simulate queues with `Queue` objects
    repository.webhook_queue = Queue()
    repository.retry_queue = PriorityQueue()

    # Basic return values for qsize methods
    repository.retry_queue.qsize = Mock(return_value=20)

    # Thread locks for multi-threaded access
    repository.failure_counts_lock = threading.Lock()
    repository.retry_queue_lock = threading.Lock()
    
    # Set up processed IDs and failure counts as sets and dicts
    repository.dead_letter_queue = []
    repository.failure_counts = {}
    repository.processed_ids = set()
    
    # Return the current failure count for a given endpoint
    def get_failure_count(endpoint):
        # Return failure count for the specified endpoint, default to 0 if not present
        return repository.failure_counts.get(endpoint, 0)
    
    # Set the mocked method to use the get_failure_count logic
    repository.get_failure_count = Mock(side_effect=get_failure_count)
    
    repository.check_processed_id = Mock(return_value=False)
    repository.enqueue_webhook = mock.Mock()
    # repository.enqueue_webhook = Mock(side_effect=lambda x: repository.webhook_queue.put(x))
    repository.add_to_retry_queue = Mock(side_effect=lambda x, delay: repository.retry_queue.put((time.time() + delay, x)))
    
    repository.add_to_dead_letter_queue = Mock(side_effect=lambda x: repository.dead_letter_queue.append(x))
    repository.add_processed_id = Mock(side_effect=lambda x: repository.processed_ids.add(x))
    
    # Add the `update_failure_count` method to the mock repository
    def update_failure_count(endpoint):
        # Increment failure count for the endpoint
        repository.failure_counts[endpoint] = repository.failure_counts.get(endpoint, 0) + 1
        return repository.failure_counts[endpoint]

    # Set the mocked `update_failure_count` method
    repository.update_failure_count = Mock(side_effect=update_failure_count)
    
    return repository


@pytest.fixture
def webhook_processor(mock_repository, tmp_path):
    """Fixture to set up a WebhookProcessor instance with a temporary webhook file."""
    webhook_file = tmp_path / "webhooks.txt"
    webhook_file.write_text("header\nhttp://test.com, 1, test_user, test_event\n")
    return WebhookProcessor(webhook_file, mock_repository)