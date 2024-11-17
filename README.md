# Webhook Processing Service
This application processes and sends webhooks to specified endpoints, handling retries with an exponential backoff strategy to manage failures. It is designed for scalability, using a queue-based approach to manage webhook delivery, a retry mechanism to handle temporary failures, and a dead-letter queue to track unrecoverable errors.

## Features

- **Exponential Backoff Retry**: Retries failed webhooks with an increasing delay, capped at 1 minute.
- **Dead-letter Queue**: Webhooks that exceed the retry threshold are stored in a dead-letter queue.
- **Concurrency and Threading**: Supports concurrent processing using worker threads for efficient processing.
- **Failure Threshold**: Stops sending to any endpoint after 5 consecutive failures.
- **Thread-safe Locking**: Ensures reliable access to shared resources like queues and failure counts.

## Technologies Used

- **Python**: Core language for application logic.
- **Redis**: Used as a message queue for storing and retrying webhook tasks.
- **MySQL**: Persistent database for storing webhook records and tracking their statuses.
- **Threading**: Implements concurrent processing of webhooks with thread safety.

## Setup and Installation
#### Prerequisites
- Python 3.8+
- Redis: Used as the queue storage.
- MySQL: Used as the database for storing webhook records.
- Dependencies: Ensure you have access to pip for installing required Python packages.

### 1. Clone the Repository
```sh
git clone https://github.com/thebolarin/webhookprocessor.git
cd webhookprocessor
```

### 2. Create a .env File
Create a .env file in the root directory of the project using the sample in the .env.example file

### 3. Build and Start the Containers
```bash
docker-compose up -d --build
```

### 4. Database Migrations
To ensure that the database is up-to-date before using the application, follow these steps:

1. **Apply the latest migrations**  
   Run the following command to upgrade the database to the latest migration state:
   ```bash
   docker-compose exec web alembic upgrade head
   ```

2. If you make changes to the models and need to create a new migration, run:
   ```bash
   docker-compose exec web alembic revision --autogenerate -m "Your migration message"
   ```
    Then apply the migration:
    ```bash
   docker-compose exec web alembic upgrade head
   ```

### 6. Running the test
Run the command below to run the integration tests for the application
```bash
docker-compose exec web pytest -v
```

## Explanation of the Main Components

1. ***WebhookProcessorService***
    - ***load_webhooks***: Loads webhooks from a file into the Redis queue.
    - ***send_webhook***: Attempts to send a webhook, with retries on failure.
    - ***process_retry_queue***: Processes webhooks in the retry queue based on their scheduled retry times.
    - ***worker_with_session***: Starts a worker thread to process webhooks concurrently.
2. ***WebhookService***:
Manages database and Redis operations, including enqueueing, dequeueing, updating, and tracking webhooks state.

## Design Decisions
1. Exponential Backoff with Randomized Delay: Exponential backoff is applied to each failed webhook with random jitter. This ensures that retries are spread over time, reducing the risk of overwhelming the endpoint if there’s a temporary outage.

2. Dead-letter Queue: Allows for tracking of unresolvable failures without blocking the entire queue, improving robustness.
3. Threading for Concurrency: Using multiple worker threads improves processing speed for high-volume webhook delivery, making the system more scalable.
4. Redis for Queue Management: Redis serves as the backend for both the main processing queue and the retry queue, enabling fast access and persistence for enqueue and dequeue operations. For the retry queue, a priority queue (using Redis sorted sets) is used, which stores webhooks based on the scheduled retry time. This allows the retry processor to efficiently fetch only the webhooks ready to be retried, optimizing delay handling.
8. Failure Thresholds: Endpoints are given up to 5 retry attempts before being marked as permanently failed. After reaching the threshold, any further webhooks for that endpoint are redirected to a dead-letter queue, maintaining endpoint stability without continuous retries.
5. Database for Persistence: MySQL stores the persistent record of webhooks, their status, and retry attempts, ensuring durability across service restarts.
6. Separation of Concerns: The solution is split into two main classes: WebhookProcessorService for processing logic and WebhookService for queue management. This approach isolates concerns for easier maintenance and testing.
7. Failure Thresholds: Endpoints are given up to 5 retry attempts before being marked as permanently failed. After reaching the threshold, any further webhooks for that endpoint are redirected to a dead-letter queue, maintaining endpoint stability without continuous retries.
8. Concurrency: Using multiple worker threads allows parallel processing of webhooks, improving throughput. Each worker uses a separate Redis queue to dequeue webhooks, while a retry thread manages delayed retries, contributing to scalability and speed.
9. Monitoring: Logs will display processing details, including success, retry, and failure notifications.
10. Webhook Deduplication and Idempotency: Ensuring unique payloads before sending is beneficial if duplicate events are common, reducing unnecessary retries.

## Security Considerations
1. Sanitization of Endpoint URLs: URL parsing ensures only valid URLs are processed, reducing the chance of sending requests to unintended destinations.
2. Thread Safety and Redis Locks: Locks (e.g., failure_counts_lock and retry_queue_lock) ensure that updates to failure counters and retries are thread-safe, avoiding race conditions in a concurrent environment.

3. Failure Count Tracking: Limits the number of retries for an endpoint, preventing potential abuse or accidental spamming of endpoints.
4. Error Logging: By logging errors and invalid URLs, we can monitor any potential issues without exposing sensitive payload data in logs.

## Trade-offs
1. Threading over AsyncIO: Threading allows leveraging CPU-bound concurrency without adding the complexity of an async framework. However, an asynchronous approach might be more efficient under extreme load.
2. Fixed Retry Backoff: While exponential backoff helps reduce load on endpoints, it can cause delays in reattempting connections for temporary network issues.
3. Dead-letter Queue vs Real-time Handling: The dead-letter queue allows tracking of unrecoverable errors but does not automatically retry them unless manually processed. This keeps the system manageable, though it requires periodic monitoring.
4. Asynchronous Webhook Handler: The webhook processor currently needs to be triggered before webhooks are processed. However an asynchronus approach might be more efficient where it continously listens to the webhook queue.
