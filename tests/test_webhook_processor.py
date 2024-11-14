from unittest import mock
from unittest.mock import patch
import time
import threading

INITIAL_DELAY = 1 
MAX_DELAY = 60        
MAX_FAILURES = 5 

@mock.patch('app.utils.request.send_http_request')
def test_load_webhooks(mock_send_http_request, webhook_processor, mock_repository):
    """Test loading webhooks from file and enqueuing them."""
    mock_send_http_request.return_value = True
    webhook_processor.load_webhooks()
    mock_repository.enqueue_webhook.assert_called_once()
    assert mock_repository.enqueue_webhook.call_count == 1


@mock.patch('requests.post')
def test_send_webhook_success(mock_post, webhook_processor, mock_repository):
    """Test successful sending of webhook."""
    mock_post.return_value.status_code = 200
    webhook = {
        "id": "1",
        "endpoint": "http://test.com",
        "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
        "retries": 0,
        "delay": 0,
        "status": "pending"
    }
    result = webhook_processor.send_webhook(webhook)
    
    assert result is True
    assert webhook["status"] == "successful"
    assert mock_repository.webhook_queue.empty()
    mock_repository.add_to_retry_queue.assert_not_called()
    mock_repository.add_to_dead_letter_queue.assert_not_called()
    

@mock.patch('requests.post')
def test_send_webhook_retry_with_exponential_backoff(mock_post, webhook_processor, mock_repository):
    """Test that a failed webhook is retried with an exponential backoff delay."""
    
    # Simulate a failed request by setting the response status code to 500
    mock_post.return_value.status_code = 500
    
    # Create a mock webhook with initial retry settings
    webhook = {
        "id": "1",
        "endpoint": "http://test.com",
        "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
        "retries": 0,
        "delay": 0,
        "status": "pending"
    }

    # Send the webhook to trigger the first retry
    webhook_processor.send_webhook(webhook)
    
    # Assert: After the first failure, `retries` should increment, and delay should follow exponential backoff
    assert webhook["retries"] == 1
    assert INITIAL_DELAY <= webhook["delay"] <= INITIAL_DELAY * 2

    # Check that the webhook was added back to the retry queue with the new delay
    mock_repository.add_to_retry_queue.assert_called_once_with(webhook, webhook["delay"])

    # Increase the delay to simulate waiting before the next retry
    time.sleep(webhook["delay"])

    # Retry the webhook to trigger the second failure and further backoff
    webhook_processor.send_webhook(webhook)

    # Assert: After the second failure, `retries` should increment, and delay should grow further
    assert webhook["retries"] == 2
    assert INITIAL_DELAY * 2 <= webhook["delay"] <= INITIAL_DELAY * 4

    # Ensure the webhook is again added back to the retry queue with the new backoff delay
    mock_repository.add_to_retry_queue.assert_called_with(webhook, webhook["delay"])

@mock.patch('requests.post')
def test_send_webhook_dead_letter(mock_post, webhook_processor, mock_repository):
    """Test that a webhook is moved to the dead letter queue after maximum failure threshold."""
    mock_post.return_value.status_code = 400  # Simulate a failed request
    webhook = {
        "id": "1",
        "endpoint": "http://test.com",
        "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
        "retries": MAX_FAILURES,
        "delay": MAX_DELAY,
        "status": "pending"
    }

    # Test that it goes to dead letter queue when retries and delay exceed limits
    result = webhook_processor.send_webhook(webhook)
    assert result is False # Ensure send_webhook returns False when failure occurs
    assert webhook["status"] == "failed"
    
    # Check if the webhook was added to the dead letter queue
    mock_repository.add_to_dead_letter_queue.assert_called_once_with(webhook)


@mock.patch('requests.post')
def test_idempotency_check(mock_post, webhook_processor, mock_repository):
    """Test that the same webhook ID is not processed more than once."""
    mock_post.return_value.status_code = 200

    # Add and process a webhook
    test_webhook = {
        "id": "1",
        "endpoint": "http://test.com",
        "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
        "retries": 0,
        "delay": 0,
        "status": "pending"
    }
    mock_repository.enqueue_webhook(test_webhook)
   
    webhook_processor.worker()  # Process the webhook

    # Attempt to process the same webhook again
    mock_repository.enqueue_webhook(test_webhook)
    with patch.object(webhook_processor, 'send_webhook') as mock_send_webhook:
        webhook_processor.worker()
        mock_send_webhook.assert_not_called(), "Duplicate webhook should not be reprocessed."


@mock.patch('requests.post')
def test_concurrent_processing(mock_post, webhook_processor, mock_repository):
    """Test concurrent processing of multiple webhooks to ensure no deadlock."""
    mock_post.return_value.status_code = 200

    # Enqueue multiple webhooks
    for i in range(10):
        mock_repository.enqueue_webhook({
            "id": str(i),
            "endpoint": "http://test.com",
            "payload": {"order_id": str(i), "name": "test_user", "event": "test_event"},
            "retries": 0,
            "delay": 0,
            "status": "pending"
        })

    # Run worker threads to process webhooks concurrently
    threads = [threading.Thread(target=webhook_processor.worker) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Ensure all webhooks are processed
    assert webhook_processor.repository.webhook_queue.empty(), "All webhooks should be processed concurrently without deadlock."


@mock.patch('requests.post')
def test_retry_queue_overload(mock_post, webhook_processor, mock_repository):
    """Test the behavior when the retry queue is heavily loaded."""
    mock_post.return_value.status_code = 500

    # Add multiple webhooks to force them into retry with backoff delay
    for i in range(20):
        mock_repository.enqueue_webhook({
            "id": str(i),
            "endpoint": "http://test.com",
            "payload": {"order_id": str(i), "name": "test_user", "event": "test_event"},
            "retries": 0,
            "delay": 0,
            "status": "pending"
        })

    # Process initial queue to force retries
    threads = [threading.Thread(target=webhook_processor.worker) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
        
    # Check if all webhooks are in retry queue with initial delay
    with mock_repository.retry_queue_lock:
        retry_queue_size = mock_repository.retry_queue.qsize()
        
    assert retry_queue_size == 20, "All failed webhooks should be in the retry queue."


def test_process_retry_queue_only_processes_after_delay(webhook_processor, mock_repository):
    """Test that process_retry_queue only processes webhooks after the retry delay has passed."""
    
    # create a mock webhook with a retry delay and add it to the retry queue
    webhook = {
        "id": "1",
        "endpoint": "http://test.com",
        "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
        "retries": 1,
        "delay": 5,  # 5 seconds delay,
        "status": "pending"
    }
    
    # Add the webhook to the retry queue with a delay timestamp
    delay_timestamp = time.time() + webhook["delay"]
    mock_repository.retry_queue.put((delay_timestamp, webhook))

    # Mock the send_webhook method to verify if it's called only after the delay
    webhook_processor.send_webhook = mock.Mock()

    # start process_retry_queue in a separate thread
    retry_thread = threading.Thread(target=webhook_processor.process_retry_queue)
    retry_thread.start()

    # Wait for a time shorter than the delay to ensure it does not get processed prematurely
    time.sleep(2)
    webhook_processor.send_webhook.assert_not_called()  # Verify that it hasn't been called yet

    # Wait until the delay has passed
    time.sleep(4)  # Total 6 seconds now
    webhook_processor.send_webhook.assert_called_once_with(webhook)  # Should now be called once

    # Stop the retry queue processing thread
    webhook_processor.stop_event.set()
    retry_thread.join()


def test_process_retry_queue_processes_in_order(webhook_processor, mock_repository):
    """Test that webhooks in the retry queue are processed in order of their retry delays."""
    
    # create mock webhooks with different delays and add them to the retry queue
    webhook1 = {
        "id": "1",
        "endpoint": "http://test.com",
        "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
        "retries": 1,
        "delay": 2,  # 2 seconds delay
        "status": "pending"
    }
    
    webhook2 = {
        "id": "2",
        "endpoint": "http://test.com",
        "payload": {"order_id": "2", "name": "test_user_2", "event": "test_event_2"},
        "retries": 1,
        "delay": 4,  # 4 seconds delay
        "status": "pending"
    }
    
    webhook3 = {
        "id": "3",
        "endpoint": "http://test.com",
        "payload": {"order_id": "3", "name": "test_user_3", "event": "test_event_3"},
        "retries": 1,
        "delay": 1,  # 1 second delay
        "status": "pending"
    }
    
    # Add webhooks to the retry queue with respective delay timestamps
    mock_repository.retry_queue.put((time.time() + webhook1["delay"], webhook1))
    mock_repository.retry_queue.put((time.time() + webhook2["delay"], webhook2))
    mock_repository.retry_queue.put((time.time() + webhook3["delay"], webhook3))

    # Use a list to track the order of processed webhooks
    processed_order = []

    # Mock the send_webhook method to record processing order instead of actually sending
    def mock_send_webhook(webhook):
        processed_order.append(webhook["id"])
    
    webhook_processor.send_webhook = mock_send_webhook

    # Start the process_retry_queue in a separate thread
    retry_thread = threading.Thread(target=webhook_processor.process_retry_queue)
    retry_thread.start()

    # Wait for all delays to pass
    time.sleep(5)  # Total time needed to process all webhooks in order

    # Check that webhooks were processed in the order of their delays
    assert processed_order == ["3", "1", "2"]

    # Stop the retry queue processing thread
    webhook_processor.stop_event.set()
    retry_thread.join()


@mock.patch('requests.post')
def test_retry_delay_cap_and_dead_letter(mock_post, webhook_processor, mock_repository):
    """Test that retry delay is capped at 60 seconds, and webhooks are moved to dead-letter queue after reaching max delay."""

    # Simulate a failed request by setting the response status code to 500
    mock_post.return_value.status_code = 500
    
    # Create a mock webhook with initial retry settings
    webhook = {
        "id": "1",
        "endpoint": "http://test.com",
        "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
        "retries": 0,
        "delay": 0,
        "status": "pending"
    }

    # Simulate multiple retries
    for _ in range(10):  # Simulate 10 retries (should hit the MAX_DELAY after several retries)
        webhook_processor.send_webhook(webhook)

        # Assert: Ensure the delay doesn't exceed 60 seconds
        if webhook["delay"] >= MAX_DELAY:
            # Once the delay reaches MAX_DELAY, it should no longer increase
            assert webhook["delay"] == MAX_DELAY
        else:
            # Ensure exponential backoff works properly before MAX_DELAY
            assert INITIAL_DELAY <= webhook["delay"] <= INITIAL_DELAY * 2 ** webhook["retries"]

    # After several retries, the delay should be capped at MAX_DELAY (60 seconds)
    assert webhook["delay"] == MAX_DELAY
    assert webhook["retries"] == 7  # Number of retries should have incremented

    # Ensure the webhook has been added to the dead-letter queue after max retries
    mock_repository.add_to_dead_letter_queue.assert_called_once_with(webhook)

    # The webhook should no longer be in the retry queue
    assert mock_repository.add_to_retry_queue.call_count == 7


@mock.patch('requests.post')
def test_stop_retrying_after_5_failures(mock_post, webhook_processor, mock_repository):
    """Test that after 5 failed attempts, the system stops trying to send further webhooks to the same endpoint."""

    # Simulate a failed request by setting the response status code to 500
    mock_post.return_value.status_code = 500
    
    mock_repository.failure_counts["http://test.com"] = 4
    
    # Create a mock webhook with initial retry settings
    webhook1 = {
        "id": "1",
        "endpoint": "http://test.com",
        "payload": {"order_id": "1", "name": "test_user", "event": "test_event"},
        "retries": 0,
        "delay": 0,
        "status": "pending"
    }
    
    webhook2 = {
        "id": "2",
        "endpoint": "http://test.com",
        "payload": {"order_id": "2", "name": "test_user", "event": "test_event"},
        "retries": 0,
        "delay": 0,
        "status": "pending"
    }

    # Simulate 5 failed attempts to send the webhook
    for _ in range(10):
        webhook_processor.send_webhook(webhook1)

    assert webhook1["retries"] == 7 
    assert webhook1["status"] == "failed"
   
    # Ensure the webhook has been added to the dead-letter queue after 7 failures
    mock_repository.add_to_dead_letter_queue.assert_called_once_with(webhook1)
    assert mock_repository.failure_counts["http://test.com"] == 5

    webhook_processor.send_webhook(webhook2)
    
    # Ensure that the webhook is not retried again and moved to DLQ
    assert webhook2["retries"] == 0
    assert webhook2["status"] == "failed"
    mock_repository.add_to_dead_letter_queue.assert_any_call(webhook2)
    assert not any(call == (webhook2) for call in mock_repository.add_to_retry_queue.call_args_list)





