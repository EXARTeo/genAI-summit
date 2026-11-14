from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError

from core.error_handling import ServiceExceptionHandler
from core.logging.events import get_logger

logger = get_logger("sandbox_runner.exceptions")
exception_handler = ServiceExceptionHandler(logger)


async def _http_exception_handler(request: Request, exc: HTTPException):
    return await exception_handler.handle_http_exception(request, exc)


async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    return await exception_handler.handle_validation_exception(request, exc)


async def _unhandled_exception_handler(request: Request, exc: Exception):
    return await exception_handler.handle_unhandled_exception(request, exc)


def register_exception_handlers(app: FastAPI) -> None:
    # 429s are HTTPExceptions raised by core.security.rate_limit (with
    # Retry-After / X-RateLimit-* headers) and pass through the HTTP handler.
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
