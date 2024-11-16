from starlette.requests import Request
from fastapi.responses import JSONResponse  
from starlette.middleware.base import BaseHTTPMiddleware 
import logging 
logger = logging.getLogger(__name__)  

class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            exception_type = type(e).__name__
            logger.exception(f"An unexpected error of type {exception_type} occurred: {e}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "An unexpected error occurred"}
            )

