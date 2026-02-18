import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.advices.base_response_handler import BaseResponseHandler
from app.exceptions.exceptions import (
    InvalidCredentialsException,
    InvalidOperationException,
    ResourceAlreadyExistsException,
    ResourceNotFoundException,
    UnauthorizedAccessException,
)

logger = logging.getLogger(__name__)


class GlobalExceptionHandler:
    """
    Global exception handler for the application.
    This class is responsible for handling exceptions and returning appropriate API error responses.
    """

    @staticmethod
    def register_exception_handlers(app: FastAPI) -> None:
        """
        Register exception handlers for the FastAPI application.
        :param app: FastAPI application instance
        """

        @app.exception_handler(ResourceNotFoundException)
        async def handle_resource_not_found(
            _request: Request, exc: ResourceNotFoundException
        ) -> JSONResponse:
            return BaseResponseHandler.error_response(
                message="Resource Not Found",
                status_code=404,
                errors={"detail": exc.message},
            )

        @app.exception_handler(InvalidCredentialsException)
        async def handle_invalid_credentials(
            _request: Request, exc: InvalidCredentialsException
        ) -> JSONResponse:
            return BaseResponseHandler.error_response(
                message="Invalid Credentials",
                status_code=401,
                errors={"detail": exc.message},
            )

        @app.exception_handler(UnauthorizedAccessException)
        async def handle_unauthorized_access(
            _request: Request, exc: UnauthorizedAccessException
        ) -> JSONResponse:
            return BaseResponseHandler.error_response(
                message="Unauthorized Access",
                status_code=401,
                errors={"detail": exc.message},
            )

        @app.exception_handler(ResourceAlreadyExistsException)
        async def handle_resource_already_exists(
            _request: Request, exc: ResourceAlreadyExistsException
        ) -> JSONResponse:
            return BaseResponseHandler.error_response(
                message="Resource Already Exists",
                status_code=409,
                errors={"detail": exc.message},
            )

        @app.exception_handler(InvalidOperationException)
        async def handle_invalid_operation(
            _request: Request, exc: InvalidOperationException
        ) -> JSONResponse:
            return BaseResponseHandler.error_response(
                message="Invalid Operation",
                status_code=400,
                errors={"detail": exc.message},
            )

        @app.exception_handler(HTTPException)
        async def fastapi_http_exception_handler(
            _request: Request, exc: HTTPException
        ) -> JSONResponse:
            return BaseResponseHandler.error_response(
                message=exc.detail,
                status_code=exc.status_code,
                errors={"detail": exc.detail},
            )

        @app.exception_handler(StarletteHTTPException)
        async def http_exception_handler(
            _request: Request, exc: StarletteHTTPException
        ) -> JSONResponse:
            return BaseResponseHandler.error_response(
                message=exc.detail,
                status_code=exc.status_code,
                errors={"detail": exc.detail},
            )

        @app.exception_handler(RequestValidationError)
        async def validation_exception_handler(
            _request: Request, exc: RequestValidationError
        ) -> JSONResponse:
            error_dict = {}
            for error in exc.errors():
                field = error["loc"][-1] if error["loc"] else "unknown"
                error_dict[str(field)] = error["msg"]

            return BaseResponseHandler.validation_error_response(error_dict)

        @app.exception_handler(Exception)
        async def handle_exception(_request: Request, exc: Exception) -> JSONResponse:
            logger.error(f"Unexpected error occurred: {exc}")
            return BaseResponseHandler.error_response(
                message="Internal Server Error",
                status_code=500,
                errors={"detail": str(exc)},
            )
