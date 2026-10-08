import hashlib
import json
from datetime import timedelta
from typing import Any

import httpx
from django.conf import settings
from django.utils import timezone

from fuel_routes.exceptions import InvalidLocationError, RouteNotFoundError, ServiceError
from fuel_routes.models import ProviderCache


def _cache_key(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def _in_usa(latitude: float, longitude: float) -> bool:
    boxes = (
        (24.0, 50.0, -125.0, -66.0),  # contiguous states
        (51.0, 72.0, -180.0, -129.0),  # Alaska
        (18.0, 23.0, -161.0, -154.0),  # Hawaii
    )
    return any(
        min_lat <= latitude <= max_lat and min_lon <= longitude <= max_lon
        for min_lat, max_lat, min_lon, max_lon in boxes
    )


class RoutingService:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=settings.ROUTING_TIMEOUT_SECONDS)
        self.base_url = settings.OPENROUTESERVICE_BASE_URL.rstrip("/")
        self.geocode_url = settings.OPENROUTESERVICE_GEOCODE_URL
        self.api_key = settings.OPENROUTESERVICE_API_KEY

    def resolve_location(self, location: dict[str, Any]) -> tuple[float, float]:
        if "latitude" in location:
            latitude = float(location["latitude"])
            longitude = float(location["longitude"])
            if not _in_usa(latitude, longitude):
                raise InvalidLocationError("Coordinates must be within the United States.")
            return latitude, longitude

        if not self.api_key:
            raise ServiceError(
                "OPENROUTESERVICE_API_KEY is required when an address must be geocoded.",
                code="provider_not_configured",
            )

        address = " ".join(location["address"].lower().split())
        key = _cache_key({"address": address})
        cached = self._get_cache(ProviderCache.Kind.GEOCODE, key)
        if cached:
            return cached["latitude"], cached["longitude"]

        response = self._request(
            "GET",
            self.geocode_url,
            params={"text": location["address"], "boundary.country": "US", "size": 1},
        )
        features = response.json().get("features", [])
        if not features:
            raise InvalidLocationError(f"Could not find U.S. location: {location['address']}")

        feature = features[0]
        properties = feature.get("properties", {})
        country_code = (properties.get("country_a") or properties.get("country_code") or "").upper()
        longitude, latitude = feature["geometry"]["coordinates"]
        if country_code not in {"USA", "US"} or not _in_usa(latitude, longitude):
            raise InvalidLocationError(
                "Start and finish locations must be within the United States."
            )

        payload = {"latitude": latitude, "longitude": longitude}
        self._set_cache(
            ProviderCache.Kind.GEOCODE,
            key,
            payload,
            settings.GEOCODE_CACHE_TTL_SECONDS,
        )
        return latitude, longitude

    def route(
        self,
        start: tuple[float, float],
        finish: tuple[float, float],
    ) -> dict[str, Any]:
        if not self.api_key:
            raise ServiceError(
                "OPENROUTESERVICE_API_KEY is required to calculate a route.",
                code="provider_not_configured",
            )

        coordinates = [
            [round(start[1], 5), round(start[0], 5)],
            [round(finish[1], 5), round(finish[0], 5)],
        ]
        key = _cache_key({"profile": "driving-car", "coordinates": coordinates})
        cached = self._get_cache(ProviderCache.Kind.ROUTE, key)
        if cached:
            return cached

        response = self._request(
            "POST",
            f"{self.base_url}/openrouteservice/v2/directions/driving-car/geojson",
            json={
                "coordinates": coordinates,
                "radiuses": [settings.ROUTING_SNAP_RADIUS_METERS] * len(coordinates),
                "instructions": False,
                "elevation": False,
            },
        )
        payload = response.json()
        if not payload.get("features"):
            raise RouteNotFoundError("No drivable route was found between the supplied locations.")
        self._set_cache(
            ProviderCache.Kind.ROUTE,
            key,
            payload,
            settings.ROUTING_CACHE_TTL_SECONDS,
        )
        return payload

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = self.api_key
        headers["User-Agent"] = "fuel-route-api/0.1"
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                response = self.client.request(method, url, headers=headers, **kwargs)
                if response.status_code == 404:
                    raise RouteNotFoundError("The routing provider could not find a route.")
                if response.status_code < 500 and response.status_code != 429:
                    response.raise_for_status()
                    return response
                last_error = ServiceError(
                    f"Routing provider returned HTTP {response.status_code}.",
                    code="provider_unavailable",
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
            except httpx.HTTPStatusError as exc:
                detail = "Routing provider rejected the request."
                if exc.response.status_code in {400, 404}:
                    raise RouteNotFoundError(detail) from exc
                raise ServiceError(detail, code="provider_error") from exc
            if attempt == 1:
                break

        raise ServiceError(
            "Routing provider is temporarily unavailable.",
            code="provider_unavailable",
        ) from last_error

    @staticmethod
    def _get_cache(kind: str, key: str) -> dict[str, Any] | None:
        cached = ProviderCache.objects.filter(
            kind=kind,
            cache_key=key,
            expires_at__gt=timezone.now(),
        ).first()
        return cached.payload if cached else None

    @staticmethod
    def _set_cache(kind: str, key: str, payload: dict[str, Any], ttl: int) -> None:
        ProviderCache.objects.update_or_create(
            kind=kind,
            cache_key=key,
            defaults={"payload": payload, "expires_at": timezone.now() + timedelta(seconds=ttl)},
        )
