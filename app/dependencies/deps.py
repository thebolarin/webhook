from typing import Generator
from app.db.base_class import Base
from app.db.session import SessionLocal, TestSessionLocal, test_engine
from contextlib import contextmanager
import redis
from app.core.config import settings

@contextmanager
def get_db() -> Generator:
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()
  
@contextmanager      
def get_test_db() -> Generator:
    try:
        db = TestSessionLocal()
        Base.metadata.create_all(bind=test_engine)
        yield db
    finally:
        db.close()
        
def get_redis_client():
    return redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)

        