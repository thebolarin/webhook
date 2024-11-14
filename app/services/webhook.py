import urllib.parse
import time
import threading

import random
import logging
from datetime import datetime
from app.utils.request import send_http_request

# Constants for retry and failure handling
INITIAL_DELAY = 1       # Initial delay in seconds for exponential backoff
MAX_DELAY = 60          # Maximum delay in seconds before marking as failed
MAX_FAILURES = 5        # Maximum failures allowed per endpoint
NUM_WORKERS = 5         # Number of concurrent worker threads

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Webhook Processor Class
class WebhookProcessor:
    def __init__(self, webhook_file, repository):
        self.webhook_file = webhook_file
        self.repository = repository
        self.stop_event = threading.Event()  # Event to stop the retry worker thread

    def load_webhooks(self):
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
                            "id": order_id,
                            "endpoint": endpoint,
                            "payload": {
                                "order_id": order_id,
                                "name": name,
                                "event": event,
                            },
                            "retries": 0,
                            "delay": 0,
                            "status": "pending"
                        }
                        self.repository.enqueue_webhook(webhook)

            logging.info(f"{self.repository.webhook_queue.qsize()} webhooks loaded into the queue.")
        except Exception as e:
            logging.error(f"Error loading webhooks: {e}")

    def send_webhook(self, webhook):
        """Attempt to send a webhook. On failure, add it to the retry queue with an exponential backoff delay."""
        webhook_id = webhook["id"]
        endpoint = webhook["endpoint"]
        payload = webhook["payload"]
        retry_delay = webhook["delay"]
        retries = webhook["retries"]
        status = webhook["status"]
        
        # Check if webhook has already been processed successfully and prevent further processing
        if status == "successful":
            logging.info(f"Webhook {webhook_id} has already been successfully processed. Skipping.")
            return True
        
        # Check if webhook has already been failed and prevent further processing
        if status == "failed":
            logging.info(f"Webhook {webhook_id} has already failed. Skipping retry.")
            return False
        
        with self.repository.failure_counts_lock:
            failure_count = self.repository.get_failure_count(endpoint)
            
            # Check if webhook endpoint failure is up to the max failure threshold
            if failure_count >= MAX_FAILURES:
                logging.warning(f"Maximum failures reached for {endpoint}. Skipping further retries for this endpoint.")
                webhook["status"] = "failed"  # Mark as failed
                self.repository.add_to_dead_letter_queue(webhook)
                return False
       
        # Check if retry delay exceeds the maximum allowed delay
        if retry_delay >= MAX_DELAY:
            logging.warning(f"Webhook {webhook_id} reached max delay of {MAX_DELAY}s and still failed. Moving to Dead Letter Queue.")

            # Update failure count and add to dead letter queue in a thread-safe manner
            with self.repository.failure_counts_lock:
                endpoint_fail_count = self.repository.update_failure_count(endpoint)
                if endpoint_fail_count >= MAX_FAILURES:
                    logging.warning(f"Max failures reached for endpoint {endpoint}. Moving webhook {webhook_id} to Dead Letter Queue..")

            # Move to dead letter queue
            self.repository.add_to_dead_letter_queue(webhook)
            webhook["status"] = "failed"  # Mark as failed
            return False
        

        logging.info(f"Attempting to send webhook {webhook_id} to {endpoint}.")
        success = send_http_request(endpoint, payload)
    
        if success:
            webhook["status"] = "successful"  # Mark as successful
            logging.info(f"Successfully sent webhook {webhook_id} to {endpoint}")
            return True
        else:
            retries = webhook.get("retries")
            delay = min(INITIAL_DELAY * 2 ** retries + random.uniform(0, 1), MAX_DELAY)
            webhook["retries"] += 1
            webhook["delay"] = delay
            logging.warning(f"Failed to send webhook {webhook_id}. Retrying in {delay:.2f} seconds.")

            self.repository.add_to_retry_queue(webhook, delay)
            return False

    def process_retry_queue(self):
        """Process webhooks in the retry queue based on delay timestamps."""
        logging.info("Retry queue processing started.")
        while not self.stop_event.is_set() or not self.repository.retry_queue.empty():
            current_time = time.time()
            
            # Check if there's a webhook in the retry queue and if its retry time has passed
            with self.repository.retry_queue_lock:
                if not self.repository.retry_queue.empty():
                    retry_time, webhook = self.repository.retry_queue.queue[0]  # Peek at the first item

                    # If retry time has elapsed, retry sending the webhook
                    if retry_time <= current_time:
                        self.repository.retry_queue.get()  # Remove the item from the queue
                        logging.info(f"Retrying webhook {webhook['id']} at {datetime.fromtimestamp(current_time)}")
                        self.send_webhook(webhook)
                    else:
                        # Sleep only until the next retry time
                        time_to_next_retry = retry_time - current_time
                        logging.debug(f"Next retry for webhook {webhook['id']} in {time_to_next_retry} seconds.")
                        time.sleep(min(time_to_next_retry, 1))  # Wait until next retry or re-check in 1 second
                else:
                    # If retry queue is empty, sleep briefly before checking again
                    time.sleep(1)

    def worker(self):
        """Worker thread function to process webhooks from the main queue."""
        while not self.repository.webhook_queue.empty():
            webhook = self.repository.dequeue_webhook()
            if webhook:
                self.send_webhook(webhook)

    def process_webhooks(self):
        """Main method to start worker threads and process webhooks."""
        self.load_webhooks()

        # Start main worker threads to process webhooks
        threads = [threading.Thread(target=self.worker) for _ in range(NUM_WORKERS)]
        for thread in threads:
            thread.start()

        # Start retry worker thread
        retry_thread = threading.Thread(target=self.process_retry_queue)
        retry_thread.start()

        # Wait for threads to complete
        for thread in threads:
            thread.join()

        self.stop_event.set()  # Stop the retry worker thread
        retry_thread.join()

        logging.info("All webhooks have been processed.")
        logging.info(f"Dead-letter queue contains {len(self.repository.dead_letter_queue)} failed webhooks.")

