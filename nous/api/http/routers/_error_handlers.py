"""Shared error response helpers for HTTP routers."""

from starlette.responses import JSONResponse


def error_500(message: str = "Internal server error") -> JSONResponse:
    """Return a generic 500 Internal Server Error."""
    return JSONResponse({"error": message}, status_code=500)


def error_from_result(result) -> JSONResponse:
    """Return 500 with error message extracted from a Failure result."""
    return JSONResponse({"error": str(result.error)}, status_code=500)
