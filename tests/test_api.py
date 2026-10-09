from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

ROUTE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[-100, 35], [-99, 35]]},
            "properties": {"summary": {"distance": 1000, "duration": 100}},
        }
    ],
}
PLAN = {
    "distance_miles": 100.0,
    "duration_seconds": 3600,
    "candidate_stations_considered": 2,
    "fuel_stops": [],
    "fuel_stops_geojson": {"type": "FeatureCollection", "features": []},
    "total_gallons_purchased": 10.0,
    "total_fuel_cost": 30.0,
    "ending_fuel_gallons": 0.0,
}


def test_health_endpoint():
    response = APIClient().get("/api/v1/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_and_interactive_docs_are_available():
    client = APIClient()

    schema = client.get("/api/schema/", HTTP_ACCEPT="application/json")

    assert schema.status_code == 200
    assert "/api/v1/routes/optimize/" in schema.json()["paths"]
    assert client.get("/api/docs/").status_code == 200
    assert client.get("/api/redoc/").status_code == 200


@patch("fuel_routes.views.optimize_fuel_plan", return_value=PLAN)
@patch("fuel_routes.views.RoutingService.route", return_value=ROUTE)
@patch(
    "fuel_routes.views.RoutingService.resolve_location",
    side_effect=[(35.0, -100.0), (35.0, -99.0)],
)
def test_optimize_route_returns_geojson_and_totals(resolve, route, optimize):
    response = APIClient().post(
        "/api/v1/routes/optimize/",
        {
            "start": {"address": "Oklahoma City, OK"},
            "finish": {"latitude": 35.0, "longitude": -99.0},
            "starting_fuel_gallons": 5,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"]["geometry"]["type"] == "LineString"
    assert body["fuel_stops_geojson"]["type"] == "FeatureCollection"
    assert body["total_fuel_cost"] == 30.0
    assert "assumptions" not in body
    assert "attribution" not in body
    optimize.assert_called_once_with(ROUTE, 5.0)


def test_invalid_location_shape_returns_structured_400():
    response = APIClient().post(
        "/api/v1/routes/optimize/",
        {
            "start": {"address": "Tulsa", "latitude": 36.15, "longitude": -95.99},
            "finish": {"address": "Oklahoma City"},
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_fuel_above_tank_capacity_is_rejected():
    response = APIClient().post(
        "/api/v1/routes/optimize/",
        {
            "start": {"latitude": 35.0, "longitude": -100.0},
            "finish": {"latitude": 35.0, "longitude": -99.0},
            "starting_fuel_gallons": 51,
        },
        format="json",
    )

    assert response.status_code == 400
