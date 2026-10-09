from django.db import connection
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from fuel_routes.serializers import (
    ErrorResponseSerializer,
    HealthResponseSerializer,
    OptimizeRouteResponseSerializer,
    OptimizeRouteSerializer,
)
from fuel_routes.services.optimizer import optimize_fuel_plan
from fuel_routes.services.routing import RoutingService


@extend_schema(
    summary="Check API health",
    responses={200: HealthResponseSerializer},
    tags=["System"],
)
@api_view(["GET"])
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return Response({"status": "ok"})


class OptimizeRouteView(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        summary="Optimize fuel stops along a U.S. route",
        description=(
            "Returns route GeoJSON, cost-effective fuel stops, and total fuel cost "
            "for a 500-mile-range vehicle achieving 10 MPG."
        ),
        request=OptimizeRouteSerializer,
        responses={
            200: OptimizeRouteResponseSerializer,
            400: ErrorResponseSerializer,
            422: ErrorResponseSerializer,
            503: ErrorResponseSerializer,
        },
        examples=[
            OpenApiExample(
                "Address to coordinates",
                value={
                    "start": {"address": "Oklahoma City, OK"},
                    "finish": {"latitude": 35.0844, "longitude": -106.6504},
                    "starting_fuel_gallons": 0,
                },
                request_only=True,
            )
        ],
        tags=["Routes"],
    )
    def post(self, request):
        serializer = OptimizeRouteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        routing = RoutingService()
        start = routing.resolve_location(data["start"])
        finish = routing.resolve_location(data["finish"])
        route = routing.route(start, finish)
        plan = optimize_fuel_plan(route, data["starting_fuel_gallons"])

        return Response(
            {
                "start": {"latitude": start[0], "longitude": start[1]},
                "finish": {"latitude": finish[0], "longitude": finish[1]},
                "route": route["features"][0],
                **plan,
            },
            status=status.HTTP_200_OK,
        )
