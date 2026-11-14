"""HTTP error responses and the RUN_ERROR frame: public messages, never internals."""

import json
import logging
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse


class AgentServiceExceptionHandler:
    def __init__(self, logger: Any):
        self._logger = logger

    async def handle_http_exception(self, request: Request, exc: HTTPException) -> JSONResponse:
        level = logging.WARNING if exc.status_code < 500 else logging.ERROR
        self._logger.log(
            level,
            "http_exception",
            "HTTP exception raised",
            exc_info=exc.status_code >= 500,
            status_code=exc.status_code,
            detail=exc.detail if exc.status_code >= 500 else None,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": self._public_http_detail(exc)},
            headers=exc.headers,
        )

    async def handle_validation_exception(
        self, request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # RequestValidationError.errors() takes no arguments (`include_input` is
        # pydantic's ValidationError API, so passing it raised a TypeError and
        # turned every 422 into a 500), and its entries carry the raw `input`,
        # which can be a password or a token. Log where and why, never what.
        errors = [
            {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        self._logger.warning(
            "request_validation_failed",
            "Request validation failed",
            errors=errors,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": "Invalid request. Please check the submitted fields and try again."},
        )

    async def handle_unhandled_exception(self, request: Request, exc: Exception) -> JSONResponse:
        self._logger.exception(
            "unhandled_exception",
            "Unhandled exception raised during request processing",
            exception_type=exc.__class__.__name__,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Something went wrong. Please try again."},
        )

    @staticmethod
    def _public_http_detail(exc: HTTPException) -> str | dict[str, Any]:
        if isinstance(exc.detail, str) and exc.detail.strip():
            return exc.detail
        # A structured client error the caller acts on (a resume's stale and
        # pending interrupt ids): kept whole. Only for 4xx with a message, so a
        # server error can never leak structured internals.
        if (
            exc.status_code < 500
            and isinstance(exc.detail, dict)
            and isinstance(exc.detail.get("message"), str)
        ):
            return exc.detail
        return "Request could not be completed. Please try again."


#: How every RUN_ERROR frame starts, so a stream can tell it sent one.
RUN_ERROR_FRAME_PREFIX = b'data: {"type": "RUN_ERROR"'


class AgentStreamErrorHandler:
    def encode_run_error(
        self,
        logger: Any,
        exc: BaseException,
        *,
        agent_slug: str,
        public_message: str = "The agent could not complete this run. Please try again.",
    ) -> bytes:
        logger.error(
            "agent_run_error",
            "Agent run failed",
            exc_info=True,
            agent_slug=agent_slug,
            exception_type=type(exc).__name__,
        )
        # An error that carries its own user-facing text (a model without a
        # key) says what to do; everything else stays generic.
        own = getattr(exc, "public_message", None)
        if isinstance(own, str) and own.strip():
            public_message = own
        err = {"type": "RUN_ERROR", "message": public_message}
        return ("data: " + json.dumps(err) + "\n\n").encode("utf-8")


agent_stream_error_handler = AgentStreamErrorHandler()
