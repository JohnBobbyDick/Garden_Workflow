"""Unified API error format: ``{"error": {"code", "message", "details"}}`` (messages pass through the masker)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.masking import global_masker

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def not_found(what: str = "объект") -> ApiError:
    return ApiError(404, "not_found", f"{what} не найден")


def forbidden(message: str = "недостаточно прав") -> ApiError:
    return ApiError(403, "forbidden", message)


def bad_request(message: str, code: str = "bad_request", details: Any = None) -> ApiError:
    return ApiError(400, code, message, details)


def conflict(message: str, code: str = "conflict") -> ApiError:
    return ApiError(409, code, message)


def unauthorized(message: str = "требуется вход", code: str = "unauthorized") -> ApiError:
    return ApiError(401, code, message)


def error_body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": global_masker.mask(message),
                      "details": global_masker.mask_obj(details) if details is not None else None}}


_STATUS_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
                 405: "method_not_allowed", 409: "conflict", 413: "payload_too_large", 422: "validation_error",
                 429: "rate_limited"}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status, headers=headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, "error")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg"), "type": e.get("type")}
                   for e in exc.errors()]
        return JSONResponse(error_body("validation_error", "некорректные данные запроса", details), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("unhandled error: %s", exc)
        return JSONResponse(error_body("internal_error", "внутренняя ошибка сервера"), status_code=500)
