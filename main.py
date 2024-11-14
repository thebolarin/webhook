from fastapi import FastAPI
from app.services.webhook import WebhookProcessor
from app.crud.webhook import WebhookRepository

app = FastAPI()

@app.get("/")
async def read_root():
    return {"message": "Hello World"}
    
@app.get("/send")
async def process_webhooks():
    repository = WebhookRepository()
    sender = WebhookProcessor(webhook_file="webhooks.txt", repository=repository)
    sender.process_webhooks()
    return {"status": "Webhooks sent successfully"}
