import time
import logging
from redlock import RedLockFactory
from ..crud.crud_webhook import webhook
from app import schemas
from sqlalchemy.orm import Session
from app.models.webhook import Webhook
from app.core.config import settings
import json

class WebhookService:
    def __init__(self, redis_client, redlock_factory=None):
        self.redis = redis_client
        self.webhook_queue_key = "webhook_queue"
        self.retry_queue_key = "retry_queue"  # Sorted set for retry queue with timestamps as scores
        self.dead_letter_queue_key = "dead_letter_queue"  # List for dead-letter queue
        self.failure_counts_key = "failure_counts"  # Hash for tracking failure counts per endpoint
        self.add_to_retry_queue_count = 0
        self.add_to_dead_letter_queue_count = 0
        self.factory = redlock_factory or RedLockFactory(connection_details=[{"host": settings.REDIS_HOST, "port": settings.REDIS_PORT, "db": 0}])

    def enqueue_webhook(self, webhook):
        """Add a webhook to the main processing queue."""
        self.redis.rpush(self.webhook_queue_key, webhook)  # Redis List for main queue

    def dequeue_webhook(self):
        """Remove a webhook from the main queue."""
        webhook = self.redis.lpop(self.webhook_queue_key)
        if webhook:
            return webhook  # Convert back to dict
        return None

    def add_to_retry_queue(self, webhook, delay):
        """Add a webhook to the retry queue with a specific delay."""
        retry_time = time.time() + delay
        self.redis.zadd(self.retry_queue_key, {str(webhook): retry_time})
        logging.info(f"Webhook {webhook} added to retry queue with delay {delay:.2f} seconds.")
        
        # Increment the retry queue counter
        self.add_to_retry_queue_count += 1

    def get_retry_webhook(self):
        """Retrieve and remove the next webhook from the retry queue if ready."""
        current_time = time.time()
        # Get webhooks ready for retry (score <= current time)
        ready_webhooks = self.redis.zrangebyscore(self.retry_queue_key, 0, current_time, start=0, num=1)
        if ready_webhooks:
            webhook_str = ready_webhooks[0]
            self.redis.zrem(self.retry_queue_key, webhook_str)
            return eval(webhook_str)  # Convert back to dict
        return None
    
    def retry_queue_size(self):
        return self.redis.zcard("retry_queue")
    
    def webhook_queue_empty(self):
        """Check if the Redis retry queue is empty."""
        return self.redis.zcard("retry_queue") == 0
    
    def retry_queue_empty(self):
        """Check if the Redis retry queue is empty."""
        return self.redis.zcard("retry_queue") == 0

    def add_to_dead_letter_queue(self, webhook_id, error_reason):
        """Add a permanently failed webhook to the dead-letter queue."""
        data: str = json.dumps({
            "webhook_id": webhook_id,
            "error_reason": error_reason
        })
        self.redis.lpush(self.dead_letter_queue_key, data) 
        
        # Increment the dead-letter queue counter
        self.add_to_dead_letter_queue_count += 1

    def get_failure_count(self, endpoint):
        """Get the current failure count for an endpoint."""
        return int(self.redis.hget(self.failure_counts_key, endpoint) or 0)

    def increase_failure_count(self, endpoint):
        """Increment the failure count for an endpoint in Redis and return the latest count."""
        # Increment the count in Redis and retrieve the updated count
        current_count = self.redis.hincrby(self.failure_counts_key, endpoint, 1)
        return current_count
    
    def create_webhook(self, new_webhook, db: Session):
        order_id = new_webhook["order_id"]
        event = new_webhook["event"]
        endpoint = new_webhook["endpoint"]
        payload = new_webhook["payload"]
        retry_delay = new_webhook["delay"]
        retries = new_webhook["retries"]
        
        webhook_exist = webhook.get_by_order(db, order_id=order_id, event=event)
        if webhook_exist:
            return None
        
        webhook_in = schemas.WebhookCreate(
            order_id=order_id, 
            event=event, 
            endpoint=endpoint,
            payload=payload, 
            delay=retry_delay,
            retries=retries
        )
        created_webhook = webhook.create(db, obj_in=webhook_in)
        return created_webhook

    def fetch_webhook(self, webhook_id, db: Session):
        return webhook.get(db, id=webhook_id)
    
    def update_webhook(self, webhook_id, db: Session, status=None, retries=None,last_retry_time=None, delay=None):
        # Retrieve the webhook entry by its ID
        webhook = db.query(Webhook).filter(Webhook.id == webhook_id).one_or_none()
        
        if webhook is None:
            return
        
        # Update fields as needed
        if status:
            webhook.status = status
        if retries:
            webhook.retries = retries
        if delay:
            webhook.delay = delay
        if last_retry_time:
            webhook.last_attempt_at = last_retry_time

        # Commit the transaction
        db.commit()
        print(f"Updated webhook with ID {webhook_id}")