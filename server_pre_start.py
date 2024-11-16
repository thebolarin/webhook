import logging
from tenacity import after_log, before_log, retry, stop_after_attempt, wait_fixed
from sqlalchemy.sql import text
from app.db.session import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_tries = 60 * 5  # 5 minutes
wait_seconds = 1

@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
def init() -> None:
    """Initialize the database connection."""
    try:
        db = SessionLocal()
        try:
            # Explicitly declare the textual SQL expression as text
            logger.info("Attempting to connect to the database...")
            db.execute(text("SELECT 1"))
            logger.info("Database connection established successfully.")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to initialize the database connection: {e}")
        raise e

def main() -> None:
    """Main entry point for initializing the service."""
    logger.info("Initializing service")
    init()
    logger.info("Service finished initializing")

if __name__ == "__main__":
    main()
