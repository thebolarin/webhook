from unittest import mock
from unittest.mock import patch
import time
import threading
from app.dependencies import deps
from app.models.webhook import WebhookStatus, Webhook
from datetime import datetime

INITIAL_DELAY = 1 
MAX_DELAY = 60        
MAX_FAILURES = 5 

@mock.patch('app.utils.request.send_http_request')
def test_load_webhooks(mock_send_http_request, webhook_processor, webhook_service):
    """Test loading webhooks from file and enqueuing them."""
    mock_send_http_request.return_value = True
    
    with deps.get_test_db() as session:
        webhook_processor.load_webhooks(session)
        webhook_service.enqueue_webhook.assert_called_once()
        assert webhook_service.enqueue_webhook.call_count == 1


@mock.patch('requests.post')
def test_send_webhook_success(mock_post, webhook_processor, webhook_service):
    """Test successful sending of webhook."""
    mock_post.return_value.status_code = 200
    webhook = {
        "order_id": "1",
        "event": "test_event",
        "endpoint": "http://test.com",
        "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
        "retries": 0,
        "delay": 0,
    }
    
    with deps.get_test_db() as session:
        new_webhook = webhook_service.create_webhook(webhook, session)
        assert new_webhook.status == WebhookStatus.PENDING
        webhook_service.enqueue_webhook(new_webhook.id)
        
    with deps.get_test_db() as session:   
        result = webhook_processor.send_webhook(new_webhook.id, session)
        assert result is True
        assert webhook_service.webhook_queue_empty() is True
        
    with deps.get_test_db() as session:
        updated_webhook = session.query(Webhook).filter_by(id=new_webhook.id).first()
        assert updated_webhook.status == WebhookStatus.SUCCESSFUL
        
        assert webhook_service.add_to_retry_queue_count == 0
        assert webhook_service.add_to_dead_letter_queue_count == 0
    

@mock.patch('requests.post')
def test_send_webhook_retry_with_exponential_backoff(mock_post, webhook_processor, webhook_service):
    """Test that a failed webhook is retried with an exponential backoff delay."""
    
    # Simulate a failed request by setting the response status code to 500
    mock_post.return_value.status_code = 500
    
    # Create a mock webhook with initial retry settings
    webhook = {
        "order_id": "1",
        "event": "test_event",
        "endpoint": "http://test.com",
        "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
        "retries": 0,
        "delay": 0,
    }

    with deps.get_test_db() as session:
        new_webhook = webhook_service.create_webhook(webhook, session)
        assert new_webhook.status == WebhookStatus.PENDING
        
    with deps.get_test_db() as session:
        # Send the webhook to trigger the first retry
        webhook_processor.send_webhook(new_webhook.id, session)
        
        updated_webhook = session.query(Webhook).filter_by(id=new_webhook.id).first()
      
        # After the first failure, `retries` should increment, and delay should follow exponential backoff
        assert updated_webhook.retries == 1
        assert INITIAL_DELAY <= updated_webhook.delay <= INITIAL_DELAY * 2

        # Check that the webhook was added back to the retry queue with the new delay
        assert webhook_service.add_to_retry_queue_count == 1
       

        # Increase the delay to simulate waiting before the next retry
        time.sleep(updated_webhook.delay)
        
    with deps.get_test_db() as session:
        # Retry the webhook to trigger the second failure and further backoff
        webhook_processor.send_webhook(new_webhook.id, session)

        updated_webhook = session.query(Webhook).filter_by(id=new_webhook.id).first()
        # Assert: After the second failure, `retries` should increment, and delay should grow further
        assert updated_webhook.retries == 2
        assert INITIAL_DELAY * 2 <= updated_webhook.delay <= INITIAL_DELAY * 4

        # Ensure the webhook is again added back to the retry queue with the new backoff delay
        # webhook_service.add_to_retry_queue.assert_called_with(updated_webhook.id, updated_webhook.delay)
        assert webhook_service.add_to_retry_queue_count == 2

@mock.patch('requests.post')
def test_send_webhook_dead_letter(mock_post, webhook_processor, webhook_service):
    """Test that a webhook is moved to the dead letter queue after maximum failure threshold."""
    mock_post.return_value.status_code = 400  # Simulate a failed request
    
    webhook = {
        "order_id": "1",
        "event": "test_event",
        "endpoint": "http://test.com",
        "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
        "retries": MAX_FAILURES,
        "delay": MAX_DELAY
    }

    with deps.get_test_db() as session:
        new_webhook = webhook_service.create_webhook(webhook, session)
        assert new_webhook.status == WebhookStatus.PENDING
        # webhook_service.enqueue_webhook(new_webhook.id)

    with deps.get_test_db() as session:
        # Test that it goes to dead letter queue when retries and delay exceed limits
        result = webhook_processor.send_webhook(new_webhook.id, session)
        assert result is False # Ensure send_webhook returns False when failure occurs
        
        updated_webhook = session.query(Webhook).filter_by(id=new_webhook.id).first()
        assert updated_webhook.status == WebhookStatus.FAILED
        
        # Check if the webhook was added to the dead letter queue
        assert webhook_service.add_to_dead_letter_queue_count == 1


@mock.patch('requests.post')
def test_idempotency_check(mock_post, webhook_processor, webhook_service):
    """Test that the same webhook ID is not processed more than once."""
    mock_post.return_value.status_code = 200

    # Add and process a webhook
    test_webhook = {
        "order_id": "1",
        "event": "test_event",
        "endpoint": "http://test.com",
        "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
        "retries": 0,
        "delay": 0,
        "status": "pending"
    }
    
    with deps.get_test_db() as session:
        new_webhook = webhook_service.create_webhook(test_webhook, session)
        assert new_webhook.status == WebhookStatus.PENDING
        webhook_service.enqueue_webhook(new_webhook.id)

    with deps.get_test_db() as session:
        webhook_processor.worker(session)  # Process the webhook

    # Attempt to process the same webhook again
    webhook_service.enqueue_webhook(new_webhook.id)
    with patch.object(webhook_processor, 'send_webhook') as mock_send_webhook:
        with deps.get_test_db() as session:
            webhook_processor.worker(session)
        mock_send_webhook.assert_not_called(), "Duplicate webhook should not be reprocessed."

def worker_with_session(webhook_processor):
            # Use get_db to get a thread-local session
            with deps.get_test_db() as session:
                webhook_processor.worker(session)
                          
@mock.patch('requests.post')
def test_concurrent_processing(mock_post, webhook_processor, webhook_service):
    """Test concurrent processing of multiple webhooks to ensure no deadlock."""
    mock_post.return_value.status_code = 200

    # Enqueue multiple webhooks
    for i in range(10):
        with deps.get_test_db() as session:
            new_webhook = webhook_service.create_webhook({
            "order_id": str(i),
            "event": "test_event",
            "endpoint": "http://test.com",
            "payload": {"order_id": str(i), "name": "test_user", "event": "test_event"},
            "retries": 0,
            "delay": 0,
            "status": "pending"
        }, session)
            assert new_webhook.status == WebhookStatus.PENDING
            webhook_service.enqueue_webhook(new_webhook.id)
    
    # Run worker threads to process webhooks concurrently
    threads = [threading.Thread(target=worker_with_session(webhook_processor)) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Ensure all webhooks are processed
    assert webhook_processor.webhook_service.webhook_queue_empty, "All webhooks should be processed concurrently without deadlock."


@mock.patch('requests.post')
def test_retry_queue_overload(mock_post, webhook_processor, webhook_service):
    """Test the behavior when the retry queue is heavily loaded."""
    mock_post.return_value.status_code = 500

    # Add multiple webhooks to force them into retry with backoff delay
    for i in range(20):
       with deps.get_test_db() as session:
            new_webhook = webhook_service.create_webhook({
                "order_id": str(i),
                "event": "test_event",
                "endpoint": "http://test.com",
                "payload": {"order_id": str(i), "name": "test_user", "event": "test_event"},
                "retries": 0,
                "delay": 0,
            }, session)
            assert new_webhook.status == WebhookStatus.PENDING
            webhook_service.enqueue_webhook(new_webhook.id)

    # Process initial queue to force retries
    threads = [threading.Thread(target=worker_with_session(webhook_processor)) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
        
    # Check if all webhooks are in retry queue with initial delay
    with webhook_service.factory.create_lock("retry_queue_lock"):
        retry_queue_size = webhook_service.retry_queue_size()
        
    assert retry_queue_size == 20, "All failed webhooks should be in the retry queue."


def process_retry_queue_with_session(webhook_processor):
            # Use get_db to get a thread-local session
            with deps.get_test_db() as session:
                webhook_processor.process_retry_queue(session)

def test_process_retry_queue_only_processes_after_delay(webhook_processor, webhook_service):
    """Test that process_retry_queue only processes webhooks after the retry delay has passed."""
    
    # create a mock webhook with a retry delay and add it to the retry queue
    with deps.get_test_db() as session:
            new_webhook = webhook_service.create_webhook({
                "order_id":  "1",
                "event": "test_event",
                "endpoint": "http://test.com",
                "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
                "retries": 1,
                "delay": 5,  # 5 seconds delay,
            }, session)
    
    # Add the webhook to the retry queue with a delay timestamp
    assert webhook_service.retry_queue_empty()
    webhook_service.add_to_retry_queue(new_webhook.id, new_webhook.delay)
  
    # # Mock the send_webhook method to verify if it's called only after the delay
    webhook_processor.send_webhook = mock.Mock()
   
    # # start process_retry_queue in a separate thread
    retry_thread = threading.Thread(target=webhook_processor.process_retry_queue, args=(session,))
    retry_thread.start()

    # # Wait for a time shorter than the delay to ensure it does not get processed prematurely
    time.sleep(2)
   
    webhook_processor.send_webhook.assert_not_called()  # Verify that it hasn't been called yet

    # # Wait until the delay has passed
    time.sleep(4)  # Total 6 seconds now
    with deps.get_test_db() as session:
        webhook_processor.send_webhook.assert_called_once()  # Should now be called once

    # # Stop the retry queue processing thread
    webhook_processor.stop_event.set()
    retry_thread.join()


def test_process_retry_queue_processes_in_order(webhook_processor, webhook_service):
    """Test that webhooks in the retry queue are processed in order of their retry delays."""
    
    # create mock webhooks with different delays and add them to the retry queue
    with deps.get_test_db() as session:
            webhook1 = webhook_service.create_webhook({
                "order_id":  "1",
                "event": "test_event",
                "endpoint": "http://test.com",
                "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
                "retries": 1,
                "delay": 2,  # 2 seconds delay
            }, session)
            
    with deps.get_test_db() as session:       
            webhook2 = webhook_service.create_webhook({
                "order_id":  "2",
                "event": "test_event",
                "endpoint": "http://test.com",
                "payload": {"order_id": "2", "name": "test_user", "event": "test_event"},
                "retries": 1,
                "delay": 4,  # 4 seconds delay
            }, session)
            
    with deps.get_test_db() as session:        
            webhook3 = webhook_service.create_webhook({
                "order_id":  "3",
                "event": "test_event",
                "endpoint": "http://test.com",
                "payload": {"order_id": "3", "name": "test_user", "event": "test_event"},
                "retries": 1,
                "delay": 1,  # 1 second delay
            }, session)
    
    
    # Add webhooks to the retry queue with respective delay timestamps
    assert webhook_service.retry_queue_empty()
    webhook_service.add_to_retry_queue(webhook1.id, webhook1.delay)
    webhook_service.add_to_retry_queue(webhook2.id, webhook2.delay)
    webhook_service.add_to_retry_queue(webhook3.id, webhook3.delay)

    # Use a list to track the order of processed webhooks
    processed_order = []

    # Mock the send_webhook method to record processing order instead of actually sending
    def mock_send_webhook(webhook_id, session):
        processed_order.append(webhook_id)
    
    webhook_processor.send_webhook = mock_send_webhook

    # Start the process_retry_queue in a separate thread
    retry_thread = threading.Thread(target=webhook_processor.process_retry_queue, args=(session,))
    retry_thread.start()

    # Wait for all delays to pass
    time.sleep(5)  # Total time needed to process all webhooks in order

    # Check that webhooks were processed in the order of their delays
    assert processed_order == [3, 1, 2]

    # Stop the retry queue processing thread
    webhook_processor.stop_event.set()
    retry_thread.join()


@mock.patch('requests.post')
def test_retry_delay_cap_and_dead_letter(mock_post, webhook_processor, webhook_service):
    """Test that retry delay is capped at 60 seconds, and webhooks are moved to dead-letter queue after reaching max delay."""

    # Simulate a failed request by setting the response status code to 500
    mock_post.return_value.status_code = 500
    
    # Create a mock webhook with initial retry settings
    
    with deps.get_test_db() as session:
        webhook = webhook_service.create_webhook({
                    "order_id":  "1",
                    "event": "test_event",
                    "endpoint": "http://test.com",
                    "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
                    "retries": 0,
                    "delay": 0,
                }, session)

    # Simulate multiple retries
    for _ in range(10):  # Simulate 10 retries (should hit the MAX_DELAY after several retries)
        with deps.get_test_db() as session:
            webhook_processor.send_webhook(webhook.id, session)
            updated_webhook = session.query(Webhook).filter_by(id=webhook.id).first()
            # Assert: Ensure the delay doesn't exceed 60 seconds
            if updated_webhook.delay >= MAX_DELAY:
                # Once the delay reaches MAX_DELAY, it should no longer increase
                assert updated_webhook.delay == MAX_DELAY
            else:
                # Ensure exponential backoff works properly before MAX_DELAY
                assert INITIAL_DELAY <= updated_webhook.delay <= INITIAL_DELAY * 2 ** updated_webhook.retries

    with deps.get_test_db() as session:
        updated_webhook = session.query(Webhook).filter_by(id=webhook.id).first()
        # After several retries, the delay should be capped at MAX_DELAY (60 seconds)
        assert updated_webhook.delay == MAX_DELAY
        assert updated_webhook.retries == 7  # Number of retries should have incremented

    # Ensure the webhook has been added to the dead-letter queue after max retries
    assert webhook_service.add_to_dead_letter_queue_count == 1

    # The webhook should no longer be in the retry queue
    assert webhook_service.add_to_retry_queue_count == 7


@mock.patch('requests.post')
def test_stop_retrying_after_5_failures(mock_post, webhook_processor, webhook_service):
    """Test that after 5 failed attempts, the system stops trying to send further webhooks to the same endpoint."""

    # Simulate a failed request by setting the response status code to 500
    mock_post.return_value.status_code = 500
    
    for i in range(4):
        webhook_service.increase_failure_count("http://test.com")
    
    assert webhook_service.get_failure_count("http://test.com") == 4
    
    # Create a mock webhook with initial retry settings
    with deps.get_test_db() as session:
        webhook1 = webhook_service.create_webhook({
            "order_id":  "1",
            "event": "test_event",
            "endpoint": "http://test.com",
            "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
            "retries": 0,
            "delay": 0,
        }, session)
        
    with deps.get_test_db() as session:
        webhook2 = webhook_service.create_webhook({
            "order_id":  "2",
            "event": "test_event",
            "endpoint": "http://test.com",
            "payload": {"order_id": "2", "name": "test_user", "event": "test_event"},
            "retries": 0,
            "delay": 0,
        }, session)

    # Simulate 5 failed attempts to send the webhook
    for _ in range(10):
        webhook_processor.send_webhook(webhook1.id, session)

    with deps.get_test_db() as session:
        updated_webhook = session.query(Webhook).filter_by(id=webhook1.id).first()
            
        assert updated_webhook.retries == 7 
        assert updated_webhook.status == WebhookStatus.FAILED
   
    # Ensure the webhook has been added to the dead-letter queue after 7 failures
    assert webhook_service.add_to_dead_letter_queue_count == 1
    assert webhook_service.get_failure_count("http://test.com") == 5

    webhook_processor.send_webhook(webhook2.id, session)
    
    with deps.get_test_db() as session:
        updated_webhook = session.query(Webhook).filter_by(id=webhook2.id).first()
            
        # Ensure that the webhook is not retried again and moved to DLQ
        assert updated_webhook.retries == 0 
        assert updated_webhook.status == WebhookStatus.FAILED
    

    assert webhook_service.add_to_dead_letter_queue_count > 1



