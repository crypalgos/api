from typing import Any

from fastapi.responses import JSONResponse

from app.advices.responses import (
    ApiErrorSchema,
    ErrorResponseSchema,
    SuccessResponseSchema,
)


class BaseResponseHandler:
    """
    Base response handler for consistent API responses.
    FastAPI automatically serializes Pydantic models to JSON.
    """

    @staticmethod
    def success_response(
        data: Any = None,
        status_code: int = 200,
    ) -> JSONResponse:
        """
        Create a successful API response.
        :param data: The data to include in the response
        :param status_code: HTTP status code (default: 200)
        :return: JSONResponse - FastAPI auto-serializes to JSON
        Note: To use custom status codes, set Response.status_code in your route:
            response = BaseResponseHandler.success_response(data)
            return Response(content=response.model_dump_json(), status_code=201)
        """
        return JSONResponse(
            status_code=status_code,
            content=SuccessResponseSchema(data=data).model_dump(mode="json"),
        )

    @staticmethod
    def error_response(
        message: str, status_code: int, errors: dict | None = None
    ) -> JSONResponse:
        """
        Create an error API response with custom status code.
        :param message: Error message
        :param status_code: HTTP status code
        :param errors: Optional additional error details
        :return: JSONResponse with error details
        Note: Error responses need JSONResponse to set custom status codes
        """
        api_error = ApiErrorSchema(
            status_code=status_code, message=message, errors=errors
        )
        response = ErrorResponseSchema(api_error=api_error)
        # Use model_dump_json() for direct JSON serialization (faster than jsonable_encoder)
        return JSONResponse(
            status_code=status_code, content=response.model_dump(mode="json")
        )

    @staticmethod
    def created_response(data: Any = None) -> JSONResponse:
        """
        Create a 201 Created response.
        :param data: The data to include in the response
        :return: JSONResponse with 201 status code
        """
        response = SuccessResponseSchema(data=data)
        return JSONResponse(status_code=201, content=response.model_dump(mode="json"))

    @staticmethod
    def not_found_response(message: str = "Resource not found") -> JSONResponse:
        """
        Create a 404 Not Found response.
        :param message: Error message (default: "Resource not found")
        :return: JSONResponse with 404 status code
        """
        return BaseResponseHandler.error_response(message=message, status_code=404)

    @staticmethod
    def unauthorized_response(message: str = "Unauthorized") -> JSONResponse:
        """
        Create a 401 Unauthorized response.
        :param message: Error message (default: "Unauthorized")
        :return: JSONResponse with 401 status code
        """
        return BaseResponseHandler.error_response(message=message, status_code=401)

    @staticmethod
    def forbidden_response(message: str = "Forbidden") -> JSONResponse:
        """
        Create a 403 Forbidden response.
        :param message: Error message (default: "Forbidden")
        :return: JSONResponse with 403 status code
        """
        return BaseResponseHandler.error_response(message=message, status_code=403)

    @staticmethod
    def conflict_response(message: str = "Resource already exists") -> JSONResponse:
        """
        Create a 409 Conflict response.
        :param message: Error message (default: "Resource already exists")
        :return: JSONResponse with 409 status code
        """
        return BaseResponseHandler.error_response(message=message, status_code=409)

    @staticmethod
    def validation_error_response(errors: dict) -> JSONResponse:
        """
        Create a 422 Validation Error response.
        :param errors: Validation error details
        :return: JSONResponse with 422 status code
        """
        return BaseResponseHandler.error_response(
            message="Validation Error", status_code=422, errors=errors
        )

    @staticmethod
    def internal_server_error_response(
        message: str = "Internal Server Error",
    ) -> JSONResponse:
        """
        Create a 500 Internal Server Error response.
        :param message: Error message (default: "Internal Server Error")
        :return: JSONResponse with 500 status code
        """
        return BaseResponseHandler.error_response(message=message, status_code=500)
