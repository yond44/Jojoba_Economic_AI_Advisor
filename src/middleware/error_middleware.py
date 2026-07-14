"""Error Handler Middleware for FastAPI."""
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import traceback
from typing import Callable
from datetime import datetime

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> JSONResponse:
        try:
            response = await call_next(request)
            return response
        except HTTPException as exc:
            return self._handle_http_exception(request, exc)
        except (ValueError, TypeError) as exc:
            return self._handle_validation_error(request, exc)
        except Exception as exc:
            return self._handle_generic_exception(request, exc)

    @staticmethod
    def _handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        """Handle HTTP exceptions"""
        logger.warning(
            f"HTTP Exception | Path: {request.url.path} | "
            f"Status: {exc.status_code} | Detail: {exc.detail}"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "status_code": exc.status_code,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    @staticmethod
    def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
        """Handle validation errors (ValueError, TypeError, etc.)"""
        logger.error(
            f"Validation Error | Path: {request.url.path} | "
            f"Type: {type(exc).__name__} | Detail: {str(exc)}"
        )
        logger.debug(traceback.format_exc())
        
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": "Validation error",
                "detail": str(exc),
                "error_type": type(exc).__name__,
                "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    @staticmethod
    def _handle_generic_exception(request: Request, exc: Exception) -> JSONResponse:
        """Handle all other exceptions"""
        logger.error(
            f"Internal Server Error | Path: {request.url.path} | "
            f"Method: {request.method} | Error: {str(exc)}"
        )
        logger.error(traceback.format_exc())
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal server error",
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )