from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class SOEError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False, status_code: int = 400):
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(message)


def error_payload(code: str, message: str, retryable: bool, request_id: str) -> dict:
    return {"error": {"code": code, "message": message, "retryable": retryable, "request_id": request_id}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SOEError)
    async def soe_error_handler(request: Request, exc: SOEError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(content=error_payload(exc.code, exc.message, exc.retryable, request_id), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(content=error_payload("VALIDATION_ERROR", str(exc), False, request_id), status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(content=error_payload("INTERNAL_ERROR", "An unexpected server error occurred.", False, request_id), status_code=500)
