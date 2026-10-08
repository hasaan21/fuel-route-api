from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


class ServiceError(Exception):
    code = "service_error"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, detail: str, *, code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code


class InvalidLocationError(ServiceError):
    code = "invalid_location"
    status_code = status.HTTP_400_BAD_REQUEST


class RouteNotFoundError(ServiceError):
    code = "route_not_found"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY


class InfeasibleFuelPlanError(ServiceError):
    code = "infeasible_fuel_plan"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY


def api_exception_handler(exc, context):
    if isinstance(exc, ServiceError):
        return Response(
            {"error": {"code": exc.code, "detail": exc.detail}},
            status=exc.status_code,
        )

    response = exception_handler(exc, context)
    if response is not None and response.status_code >= 400:
        response.data = {
            "error": {
                "code": "validation_error"
                if response.status_code == status.HTTP_400_BAD_REQUEST
                else "request_error",
                "detail": response.data,
            }
        }
    return response
