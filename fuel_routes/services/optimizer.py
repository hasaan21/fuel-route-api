from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from typing import Any

from django.conf import settings
from django.db.models import Q
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point

from fuel_routes.exceptions import InfeasibleFuelPlanError
from fuel_routes.models import FuelStation

METERS_PER_MILE = 1609.344
MONEY = Decimal("0.01")


@dataclass(frozen=True)
class Candidate:
    station: FuelStation
    marker_miles: float
    detour_miles: float
    actual_marker_miles: float | None = None

    @property
    def price(self) -> Decimal:
        return self.station.retail_price


def optimize_fuel_plan(
    route_geojson: dict[str, Any],
    starting_fuel_gallons: float,
) -> dict[str, Any]:
    feature = route_geojson["features"][0]
    summary = feature["properties"]["summary"]
    route_miles = float(summary["distance"]) / METERS_PER_MILE
    duration_seconds = float(summary["duration"])
    candidates = _nearby_stations(feature["geometry"]["coordinates"], route_miles)

    max_range = settings.FUEL_MAX_RANGE_MILES
    mpg = settings.FUEL_EFFICIENCY_MPG
    tank_capacity = settings.FUEL_TANK_CAPACITY_GALLONS
    current_fuel = starting_fuel_gallons

    if route_miles <= current_fuel * mpg:
        return _result(
            route_miles,
            duration_seconds,
            candidates,
            [],
            current_fuel - route_miles / mpg,
        )

    initial_range = current_fuel * mpg
    initial = [
        candidate
        for candidate in candidates
        if candidate.marker_miles + candidate.detour_miles <= initial_range
    ]
    origin_fill = False
    if not initial:
        initial = [
            candidate
            for candidate in candidates
            if candidate.marker_miles <= settings.ORIGIN_FILL_RADIUS_MILES
        ]
        origin_fill = True

    if not initial:
        raise InfeasibleFuelPlanError(
            "No fuel station is available near the origin or within the starting fuel range."
        )

    first = min(initial, key=lambda item: (item.price, -item.marker_miles))
    if origin_fill:
        current = replace(first, marker_miles=0.0, actual_marker_miles=first.marker_miles)
        current_fuel = 0.0
    else:
        distance_to_first = first.marker_miles + first.detour_miles
        current_fuel -= distance_to_first / mpg
        current = first

    stops: list[dict[str, Any]] = []
    visited: set[int] = set()

    while True:
        if current.station.pk in visited:
            raise InfeasibleFuelPlanError("A feasible, forward-only fuel plan could not be found.")
        visited.add(current.station.pk)

        destination_distance = current.detour_miles + route_miles - current.marker_miles
        if destination_distance <= max_range:
            required = destination_distance / mpg
            purchased = max(0.0, required - current_fuel)
            _record_purchase(stops, current, purchased, current_fuel)
            current_fuel = current_fuel + purchased - required
            break

        reachable = [
            candidate
            for candidate in candidates
            if candidate.marker_miles > current.marker_miles + 0.1
            and _distance_between(current, candidate) <= max_range
            and candidate.station.pk not in visited
        ]
        if not reachable:
            raise InfeasibleFuelPlanError(
                "The route contains a station gap greater than the vehicle's 500-mile range."
            )

        reachable.sort(key=lambda item: item.marker_miles)
        cheaper = [candidate for candidate in reachable if candidate.price < current.price]
        if cheaper:
            next_stop = cheaper[0]
            target_fuel = _distance_between(current, next_stop) / mpg
        else:
            next_stop = min(reachable, key=lambda item: (item.price, -item.marker_miles))
            target_fuel = tank_capacity

        purchased = max(0.0, target_fuel - current_fuel)
        _record_purchase(stops, current, purchased, current_fuel)
        current_fuel += purchased
        travel_gallons = _distance_between(current, next_stop) / mpg
        if travel_gallons > current_fuel + 1e-6:
            raise InfeasibleFuelPlanError("The calculated fuel plan exceeds tank capacity.")
        current_fuel -= travel_gallons
        current = next_stop

    return _result(route_miles, duration_seconds, candidates, stops, current_fuel)


def _nearby_stations(coordinates: list[list[float]], route_miles: float) -> list[Candidate]:
    if len(coordinates) < 2:
        return []

    longitudes = [coordinate[0] for coordinate in coordinates]
    latitudes = [coordinate[1] for coordinate in coordinates]
    padding = max(0.35, settings.MAX_STATION_DETOUR_MILES / 50)
    queryset = FuelStation.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
        latitude__range=(min(latitudes) - padding, max(latitudes) + padding),
        longitude__range=(min(longitudes) - padding, max(longitudes) + padding),
    ).filter(Q(retail_price__gt=0))

    center_lon = (min(longitudes) + max(longitudes)) / 2
    center_lat = (min(latitudes) + max(latitudes)) / 2
    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={center_lat} +lon_0={center_lon} +datum=WGS84 +units=m"
    )
    transformer = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    densified = _densify_coordinates(coordinates)
    projected_route = LineString([transformer.transform(*coordinate) for coordinate in densified])
    if projected_route.length == 0:
        return []

    candidates: list[Candidate] = []
    for station in queryset.iterator(chunk_size=1000):
        point = Point(transformer.transform(station.longitude, station.latitude))
        detour_miles = point.distance(projected_route) / METERS_PER_MILE
        if detour_miles > settings.MAX_STATION_DETOUR_MILES:
            continue
        marker = projected_route.project(point) / projected_route.length * route_miles
        candidates.append(
            Candidate(
                station=station,
                marker_miles=marker,
                detour_miles=detour_miles,
            )
        )

    candidates.sort(key=lambda item: item.marker_miles)
    return candidates


def _distance_between(current: Candidate, following: Candidate) -> float:
    return (
        current.detour_miles
        + following.marker_miles
        - current.marker_miles
        + following.detour_miles
    )


def _densify_coordinates(coordinates: list[list[float]]) -> list[list[float]]:
    """Limit long geographic segments before projection to avoid chord-distance artifacts."""
    result = [coordinates[0]]
    for start, finish in zip(coordinates, coordinates[1:], strict=False):
        span = max(abs(finish[0] - start[0]), abs(finish[1] - start[1]))
        steps = max(1, ceil(span / 0.25))
        for step in range(1, steps + 1):
            fraction = step / steps
            result.append(
                [
                    start[0] + (finish[0] - start[0]) * fraction,
                    start[1] + (finish[1] - start[1]) * fraction,
                ]
            )
    return result


def _record_purchase(
    stops: list[dict[str, Any]],
    candidate: Candidate,
    purchased: float,
    fuel_on_arrival: float,
) -> None:
    if purchased <= 0.0001:
        return
    gallons = Decimal(str(purchased)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    subtotal = (gallons * candidate.price).quantize(MONEY, rounding=ROUND_HALF_UP)
    station = candidate.station
    stops.append(
        {
            "station_id": station.opis_id,
            "name": station.name,
            "address": station.address,
            "city": station.city,
            "state": station.state,
            "location": {"latitude": station.latitude, "longitude": station.longitude},
            "route_mile": round(
                candidate.actual_marker_miles
                if candidate.actual_marker_miles is not None
                else candidate.marker_miles,
                2,
            ),
            "detour_miles": round(candidate.detour_miles, 2),
            "price_per_gallon": float(candidate.price),
            "fuel_on_arrival_gallons": round(max(0.0, fuel_on_arrival), 3),
            "gallons_purchased": float(gallons),
            "subtotal": float(subtotal),
            "geocode_quality": station.geocode_quality,
        }
    )


def _result(
    route_miles: float,
    duration_seconds: float,
    candidates: list[Candidate],
    stops: list[dict[str, Any]],
    ending_fuel: float,
) -> dict[str, Any]:
    total_gallons = sum(
        (Decimal(str(stop["gallons_purchased"])) for stop in stops),
        start=Decimal("0"),
    )
    total_cost = sum(
        (Decimal(str(stop["subtotal"])) for stop in stops),
        start=Decimal("0"),
    )
    return {
        "distance_miles": round(route_miles, 2),
        "duration_seconds": round(duration_seconds),
        "candidate_stations_considered": len(candidates),
        "fuel_stops": stops,
        "fuel_stops_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            stop["location"]["longitude"],
                            stop["location"]["latitude"],
                        ],
                    },
                    "properties": {
                        key: value
                        for key, value in stop.items()
                        if key not in {"location"}
                    },
                }
                for stop in stops
            ],
        },
        "total_gallons_purchased": float(total_gallons.quantize(Decimal("0.001"))),
        "total_fuel_cost": float(total_cost.quantize(MONEY)),
        "ending_fuel_gallons": round(max(0.0, ending_fuel), 3),
    }
