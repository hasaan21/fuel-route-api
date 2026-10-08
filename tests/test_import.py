import io
import zipfile
from pathlib import Path

import pytest
from django.core.management import call_command

from fuel_routes.models import FuelStation
from fuel_routes.services.station_geocoding import apply_geocodes, load_gazetteer

pytestmark = pytest.mark.django_db

HEADER = "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"


def write_csv(path: Path, price: str = "3.00733333") -> None:
    row = f'7,WOODShed,"I-44, EXIT 283 & US-69",Big Cabin,OK,307,{price}\n'
    path.write_text(HEADER + row + row, encoding="utf-8")


def test_import_is_idempotent_deduplicates_and_updates_price(tmp_path):
    source = tmp_path / "prices.csv"
    write_csv(source)

    call_command("import_fuel_prices", source, skip_geocoding=True)
    assert FuelStation.objects.count() == 1
    assert str(FuelStation.objects.get().retail_price) == "3.00733333"

    write_csv(source, "2.99999999")
    call_command("import_fuel_prices", source, skip_geocoding=True)

    assert FuelStation.objects.count() == 1
    assert str(FuelStation.objects.get().retail_price) == "2.99999999"


def test_gazetteer_fallback_matches_normalized_city_name():
    content = (
        "USPS|GEOID|NAME|INTPTLAT|INTPTLONG\n"
        "OK|001|Big Cabin town|36.537865|-95.220239\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("places.txt", content)

    places = load_gazetteer(archive=buffer.getvalue())
    records = [
        {
            "fingerprint": "abc",
            "city": "Big Cabin",
            "state": "OK",
            "latitude": None,
            "longitude": None,
            "geocode_quality": "",
        }
    ]
    exact_count, fallback_count = apply_geocodes(records, {}, places)

    assert exact_count == 0
    assert fallback_count == 1
    assert records[0]["latitude"] == pytest.approx(36.537865)
    assert records[0]["geocode_quality"] == "city_centroid"
