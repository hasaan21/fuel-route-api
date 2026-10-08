from django.db import connection
from django.http import JsonResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from fuel_routes.serializers import OptimizeRouteSerializer
from fuel_routes.services.optimizer import optimize_fuel_plan
from fuel_routes.services.routing import RoutingService


def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok"})


class OptimizeRouteView(APIView):
    authentication_classes = []
    permission_classes = []

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
