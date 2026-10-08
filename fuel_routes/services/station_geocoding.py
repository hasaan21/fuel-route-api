import csv
import io
import re
import unicodedata
import zipfile
from collections.abc import Iterable
from typing import Any

import httpx

CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2025_Gazetteer/2025_Gaz_place_national.zip"
)


def census_batch_geocode(
    records: list[dict[str, Any]],
    client: httpx.Client | None = None,
) -> dict[str, tuple[float, float]]:
    """Return record-keyed (latitude, longitude) matches from one Census batch."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for record in records:
        writer.writerow(
            [
                record["fingerprint"],
                record["address"],
                record["city"],
                record["state"],
                "",
            ]
        )

    requester = client or httpx.Client(timeout=120)
    response = requester.post(
        CENSUS_BATCH_URL,
        data={"benchmark": "Public_AR_Current"},
        files={"addressFile": ("fuel-stations.csv", output.getvalue(), "text/csv")},
    )
    response.raise_for_status()

    matches: dict[str, tuple[float, float]] = {}
    for row in csv.reader(io.StringIO(response.text)):
        if len(row) < 6 or row[2].strip().lower() != "match":
            continue
        try:
            longitude, latitude = (float(value) for value in row[5].split(",", maxsplit=1))
        except (TypeError, ValueError):
            continue
        matches[row[0]] = (latitude, longitude)
    return matches


def load_gazetteer(
    *,
    archive: bytes | None = None,
    client: httpx.Client | None = None,
) -> dict[tuple[str, str], tuple[float, float]]:
    if archive is None:
        requester = client or httpx.Client(timeout=120)
        response = requester.get(GAZETTEER_URL)
        response.raise_for_status()
        archive = response.content

    places: dict[tuple[str, str], tuple[float, float]] = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        text_name = next(name for name in bundle.namelist() if name.endswith(".txt"))
        with bundle.open(text_name) as raw_file:
            text_file = io.TextIOWrapper(raw_file, encoding="utf-8-sig")
            reader = csv.DictReader(text_file, delimiter="|")
            for row in reader:
                state = (row.get("USPS") or "").strip().upper()
                name = normalize_place(row.get("NAME") or "")
                try:
                    latitude = float((row.get("INTPTLAT") or "").strip())
                    longitude = float((row.get("INTPTLONG") or "").strip())
                except ValueError:
                    continue
                if state and name:
                    places.setdefault((state, name), (latitude, longitude))
    return places


def apply_geocodes(
    records: Iterable[dict[str, Any]],
    exact: dict[str, tuple[float, float]],
    places: dict[tuple[str, str], tuple[float, float]],
) -> tuple[int, int]:
    exact_count = fallback_count = 0
    for record in records:
        coordinates = exact.get(record["fingerprint"])
        if coordinates:
            record["latitude"], record["longitude"] = coordinates
            record["geocode_quality"] = "census_exact"
            exact_count += 1
            continue

        coordinates = places.get((record["state"].upper(), normalize_place(record["city"])))
        if coordinates:
            record["latitude"], record["longitude"] = coordinates
            record["geocode_quality"] = "city_centroid"
            fallback_count += 1
    return exact_count, fallback_count


def normalize_place(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+(city|town|village|borough|cdp)$", "", value)
