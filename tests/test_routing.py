import json

import httpx
import pytest
from django.test import override_settings

from fuel_routes.exceptions import InvalidLocationError
from fuel_routes.models import ProviderCache
from fuel_routes.services.routing import RoutingService

pytestmark = pytest.mark.django_db

ROUTE_PAYLOAD = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[-100, 35], [-99, 35]]},
            "properties": {"summary": {"distance": 1000, "duration": 100}},
        }
    ],
}


@override_settings(OPENROUTESERVICE_API_KEY="test-key")
def test_route_response_is_cached_after_one_provider_call():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=ROUTE_PAYLOAD)

    service = RoutingService(httpx.Client(transport=httpx.MockTransport(handler)))
    first = service.route((35.0, -100.0), (35.0, -99.0))
    second = service.route((35.0, -100.0), (35.0, -99.0))

    assert first == second
    assert len(requests) == 1
    assert json.loads(requests[0].content)["radiuses"] == [2000, 2000]
    assert ProviderCache.objects.filter(kind=ProviderCache.Kind.ROUTE).count() == 1


@override_settings(OPENROUTESERVICE_API_KEY="test-key")
def test_address_geocode_is_cached_and_restricted_to_us():
    requests = []
    payload = {
        "features": [
            {
                "geometry": {"coordinates": [-97.5164, 35.4676]},
                "properties": {"country_a": "USA"},
            }
        ]
    }

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    service = RoutingService(httpx.Client(transport=httpx.MockTransport(handler)))
    first = service.resolve_location({"address": "Oklahoma City, OK"})
    second = service.resolve_location({"address": "  oklahoma   city, ok "})

    assert first == second == (35.4676, -97.5164)
    assert len(requests) == 1
    assert requests[0].url.host == "api.openrouteservice.org"
    assert requests[0].url.path == "/geocode/search"


def test_coordinates_outside_us_are_rejected():
    service = RoutingService(httpx.Client(transport=httpx.MockTransport(lambda request: None)))

    with pytest.raises(InvalidLocationError):
        service.resolve_location({"latitude": 51.5072, "longitude": -0.1276})


@override_settings(OPENROUTESERVICE_API_KEY="test-key")
def test_transient_provider_error_is_retried_once():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json=ROUTE_PAYLOAD)

    service = RoutingService(httpx.Client(transport=httpx.MockTransport(handler)))

    assert service.route((35.0, -100.0), (35.0, -98.0)) == ROUTE_PAYLOAD
    assert attempts == 2
