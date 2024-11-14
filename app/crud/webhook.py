import time
import threading
import logging
from queue import Queue, PriorityQueue
from typing import Dict

# In-Memory Repositories
class WebhookRepository:
    def __init__(self):
        self.webhook_queue = Queue()  # Thread-safe queue for incoming webhooks
        self.retry_queue = PriorityQueue()  # Priority queue for retries with timestamp priority
        self.dead_letter_queue = []  # List to store permanently failed webhooks
        self.failure_counts: Dict[str, int] = {}  # Failure counts per webhook ID
        self.webhook_queue_lock = threading.Lock()
        self.retry_queue_lock = threading.Lock()
        self.failure_counts_lock = threading.Lock()

    def enqueue_webhook(self, webhook):
        with self.webhook_queue_lock:
            self.webhook_queue.put(webhook)

    def dequeue_webhook(self):
        with self.webhook_queue_lock:
            return self.webhook_queue.get() if not self.webhook_queue.empty() else None

    def add_to_retry_queue(self, webhook, delay):
        retry_time = time.time() + delay
        # with self.retry_queue_lock:
        self.retry_queue.put((retry_time, webhook))
        logging.info(f"Webhook {webhook['id']} added to retry queue with delay {delay:.2f} seconds.")

    def get_retry_webhook(self):
        with self.retry_queue_lock:
            return self.retry_queue.get() if not self.retry_queue.empty() else None

    def add_to_dead_letter_queue(self, webhook):
        with self.webhook_queue_lock:
            self.dead_letter_queue.append(webhook)

    def increase_failure_count(self, endpoint):
        with self.failure_counts_lock:
            self.failure_counts[endpoint] = self.failure_counts.get(endpoint, 0) + 1

    def get_failure_count(self, endpoint):
            return self.failure_counts.get(endpoint, 0)
        
    def update_failure_count(self, endpoint):
            self.failure_counts[endpoint] = self.failure_counts.get(endpoint, 0) + 1
            return self.failure_counts[endpoint]


