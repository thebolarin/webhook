import urllib.parse
import time
import threading
import random
import logging
from datetime import datetime
from app.utils.request import send_http_request
from app.dependencies import deps
from app.models.webhook import WebhookStatus

# Constants for retry and failure handling
INITIAL_DELAY = 1       # Initial delay in seconds for exponential backoff
MAX_DELAY = 60          # Maximum delay in seconds before marking as failed
MAX_FAILURES = 5        # Maximum failures allowed per endpoint
NUM_WORKERS = 5         # Number of concurrent worker threads

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Webhook Processor Class
class WebhookProcessorService:
    def __init__(self, webhook_file, webhook_service):
        self.webhook_file = webhook_file
        self.webhook_service = webhook_service
        self.stop_event = threading.Event()  # Event to stop the retry worker thread
        
    def load_webhooks(self, session):
        """Load webhooks from file and enqueue them."""
        try:
            with open(self.webhook_file, 'r') as f:
                lines = f.readlines()[1:]  # Skip the header line
                for line in lines:
                    parts = line.strip().split(", ")
                    if len(parts) == 4:
                        endpoint, order_id, name, event = parts
                        parsed_url = urllib.parse.urlparse(endpoint)
                        if not parsed_url.scheme:
                            logging.warning(f"Invalid URL '{endpoint}' (missing scheme). Skipping this webhook.")
                            continue

                        webhook = {
                            "order_id": order_id,
                            "endpoint": endpoint,
                            "event": event,
                            "payload": {
                                "order_id": order_id,
                                "name": name,
                                "event": event,
                            },
                            "retries": 0,
                            "delay": 0,
                        }
                       
                        new_webhook = self.webhook_service.create_webhook(webhook, session)
                        if not new_webhook:
                            logging.info("Webhook already created and processed.")
                            continue
                            
                        self.webhook_service.enqueue_webhook(new_webhook.id)
            logging.info("Webhooks loaded into the Redis queue.")
        except Exception as e:
            logging.error(f"Error loading webhooks: {e}")

    def send_webhook(self, webhook_id: int, session):
        """Attempt to send a webhook. On failure, add it to the retry queue with exponential backoff delay."""
        with session:
            webhook = self.webhook_service.fetch_webhook(webhook_id, session)
            
            if not webhook:
                return False
            
            endpoint = webhook.endpoint
            payload = webhook.payload
            retry_delay = webhook.delay
            retries = webhook.retries
            status = webhook.status

            # Check if webhook has already been processed successfully and prevent further processing
            if status == WebhookStatus.SUCCESSFUL:
                logging.info(f"Webhook {webhook_id} has already been successfully processed. Skipping.")
                return True
            
            # Check if webhook has already been failed and prevent further processing
            if status == WebhookStatus.FAILED:
                logging.info(f"Webhook {webhook_id} has already failed. Skipping retry.")
                return False
            
            with self.webhook_service.factory.create_lock("failure_counts_lock"):
                # Check if webhook endpoint failure is up to the max failure threshold
                failure_count = self.webhook_service.get_failure_count(endpoint)
                if failure_count >= MAX_FAILURES:
                    logging.warning(f"Max failures reached for {endpoint}. Moving to Dead Letter Queue.")
                    self.webhook_service.update_webhook(webhook_id, status="FAILED", db=session)
                    self.webhook_service.add_to_dead_letter_queue(webhook_id=webhook_id, error_reason="Max failures reached for endpoint")
                    return False
            
            # Check if retry delay exceeds the maximum allowed delay
            if retry_delay >= MAX_DELAY:
                logging.warning(f"Webhook {webhook_id} reached max delay of {MAX_DELAY}s and still failed. Moving to Dead Letter Queue.")

                # Update failure count and add to dead letter queue in a thread-safe manner
                with self.webhook_service.factory.create_lock("failure_counts_lock"):
                    endpoint_fail_count = self.webhook_service.increase_failure_count(endpoint)
                    if endpoint_fail_count >= MAX_FAILURES:
                        logging.warning(f"Max failures reached for endpoint {endpoint}. Moving webhook {webhook_id} to Dead Letter Queue..")

                # Move to dead letter queue
                self.webhook_service.update_webhook(webhook_id, status="FAILED", db=session)
                self.webhook_service.add_to_dead_letter_queue(webhook_id=webhook_id, error_reason="Max retry delay exceeded")
                return False
            
            last_retry_time = datetime.now()
            
            logging.info(f"Sending webhook {webhook_id} to {endpoint}.")
            success = send_http_request(endpoint, payload)

            if success:
                self.webhook_service.update_webhook(webhook_id, status="SUCCESSFUL", last_retry_time=last_retry_time, db=session)
                logging.info(f"Successfully sent webhook {webhook_id}.")
                return True
            else:
                delay = min(INITIAL_DELAY * 2 ** retries + random.uniform(0, 1), MAX_DELAY)
                retries += 1
                self.webhook_service.update_webhook(webhook_id, retries=retries,delay=delay, last_retry_time=last_retry_time, db=session)
                logging.warning(f"Failed to send webhook {webhook_id}. Retrying in {delay:.2f} seconds.")
                self.webhook_service.add_to_retry_queue(webhook_id, delay)
                return False

    def process_retry_queue(self, session):
        """Process webhooks in the retry queue based on delay timestamps."""
        logging.info("Retry queue processing started.")
        while not self.stop_event.is_set() or not self.webhook_service.retry_queue_empty():
            with self.webhook_service.factory.create_lock("retry_queue_lock"):
                webhook = self.webhook_service.get_retry_webhook()
                if webhook:
                    logging.info(f"Retrying webhook {webhook} at {datetime.now()}")
                    self.send_webhook(webhook, session)
                else:
                    time.sleep(1)  # Brief sleep if no webhooks are ready for retry
                

    def worker(self, session):
        """Worker thread function to process webhooks from the main queue."""
        while True:
            webhook = self.webhook_service.dequeue_webhook()
            if webhook:
                self.send_webhook(webhook, session)
            else:
                break

    # Create a thread-local session for each worker
    def worker_with_session(self):
        # Use get_db to get a thread-local session
        with deps.get_db() as session:
            self.worker(session)
            
    # Start retry worker thread
    def process_retry_queue_with_session(self):
        # Use get_db to get a thread-local session
        with deps.get_db() as session:
            self.process_retry_queue(session)
                
    def process_webhooks(self):
        """Main method to start worker threads and process webhooks."""
        with deps.get_db() as session:
            self.load_webhooks(session)
        
        # Start worker threads to process webhooks
        threads = [threading.Thread(target=self.worker_with_session) for _ in range(NUM_WORKERS)]
        for thread in threads:
            thread.start()

        retry_thread = threading.Thread(target=self.process_retry_queue_with_session)
        retry_thread.start()

        # Wait for threads to complete
        for thread in threads:
            thread.join()

        self.stop_event.set()  # Stop the retry worker thread
        retry_thread.join()

        logging.info("All webhooks have been processed.")
        logging.info(f"Dead-letter queue contains {self.webhook_service.redis.llen(self.webhook_service.dead_letter_queue_key)} failed webhooks.")
