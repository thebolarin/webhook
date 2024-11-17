from fastapi import FastAPI
from app.services.webhook_processor import WebhookProcessorService
from app.services.webhook import WebhookService

from app.middlewares.exception import ExceptionHandlerMiddleware
from app.dependencies import deps
from server_pre_start import init
from contextlib import asynccontextmanager
from app.core.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init()
    except Exception as e:
        print(f"Failed to initialize the database: {e}")
        exit(1)
    
    yield
    
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url="/openapi.json",
    lifespan=lifespan 
)

app.add_middleware(ExceptionHandlerMiddleware)

@app.get("/")
async def read_root():
    return {"message": "Hello World"}

@app.post("/webhooks/process")
async def process_webhooks():
    redis_client = deps.get_redis_client()
    webhook_service = WebhookService(redis_client)
    processor = WebhookProcessorService(webhook_file="webhooks.txt", webhook_service=webhook_service)
    processor.process_webhooks()
    return {"status": "Webhooks sent successfully"}
