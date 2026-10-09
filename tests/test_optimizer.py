from decimal import Decimal

import pytest

from fuel_routes.exceptions import InfeasibleFuelPlanError
from fuel_routes.models import FuelStation
from fuel_routes.services.optimizer import METERS_PER_MILE, optimize_fuel_plan

pytestmark = pytest.mark.django_db


def station(
    opis_id: str,
    longitude: float,
    price: str,
    *,
    latitude: float = 35.0,
) -> FuelStation:
    return FuelStation.objects.create(
        fingerprint=opis_id * 64,
        opis_id=opis_id,
        name=f"Station {opis_id}",
        address="I-40",
        city="Test",
        state="OK",
        rack_id=opis_id,
        retail_price=Decimal(price),
        latitude=latitude,
        longitude=longitude,
        geocode_quality="test",
    )


def route(distance_miles: float) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-100.0, 35.0], [-90.0, 35.0]],
                },
                "properties": {
                    "summary": {
                        "distance": distance_miles * METERS_PER_MILE,
                        "duration": distance_miles * 60,
                    }
                },
            }
        ],
    }


def test_uses_cheaper_reachable_station_and_totals_cost():
    station("a", -100.0, "3.00")
    station("b", -95.0, "2.50")

    result = optimize_fuel_plan(route(700), starting_fuel_gallons=0)

    assert [stop["station_id"] for stop in result["fuel_stops"]] == ["a", "b"]
    assert result["total_gallons_purchased"] == pytest.approx(70, abs=0.2)
    assert result["total_fuel_cost"] == pytest.approx(192.5, abs=1)
    assert result["fuel_stops_geojson"]["features"][0]["geometry"]["type"] == "Point"


def test_full_starting_tank_needs_no_purchase_for_short_route():
    result = optimize_fuel_plan(route(400), starting_fuel_gallons=50)

    assert result["fuel_stops"] == []
    assert result["total_fuel_cost"] == 0
    assert result["ending_fuel_gallons"] == pytest.approx(10)


def test_exact_500_mile_range_boundary_is_feasible():
    station("a", -100.0, "3.00")

    result = optimize_fuel_plan(route(500), starting_fuel_gallons=0)

    assert result["total_gallons_purchased"] == pytest.approx(50)
    assert result["fuel_stops"][0]["subtotal"] == pytest.approx(150)


def test_reports_infeasible_station_gap():
    station("a", -100.0, "3.00")

    with pytest.raises(InfeasibleFuelPlanError, match="station gap"):
        optimize_fuel_plan(route(700), starting_fuel_gallons=0)


def test_detour_increases_fuel_purchased():
    station("a", -100.0, "3.00")
    station("b", -95.0, "2.50", latitude=35.05)

    result = optimize_fuel_plan(route(600), starting_fuel_gallons=0)

    assert result["total_gallons_purchased"] > 60
    assert result["fuel_stops"][1]["detour_miles"] > 0


def test_skips_small_discount_when_detour_costs_more_than_savings():
    station("a", -100.0, "3.00")
    station("b", -96.667, "2.99", latitude=35.2)

    result = optimize_fuel_plan(route(300), starting_fuel_gallons=0)

    assert [stop["station_id"] for stop in result["fuel_stops"]] == ["a"]
    assert result["total_fuel_cost"] == pytest.approx(90, abs=0.2)


def test_uses_cheaper_downstream_stations_even_when_destination_is_in_range():
    station("a", -100.0, "3.099")
    station("b", -97.83, "2.93")
    station("c", -95.275, "2.845")

    result = optimize_fuel_plan(route(544), starting_fuel_gallons=0)

    selected = [stop["station_id"] for stop in result["fuel_stops"]]
    assert selected == ["a", "b", "c"]
    assert result["total_fuel_cost"] < 160
