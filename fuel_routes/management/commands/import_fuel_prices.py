import csv
import hashlib
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from django.core.management.base import BaseCommand, CommandError

from fuel_routes.models import FuelStation
from fuel_routes.services.station_geocoding import (
    apply_geocodes,
    census_batch_geocode,
    load_gazetteer,
)

REQUIRED_COLUMNS = {
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
}


class Command(BaseCommand):
    help = "Import and one-time geocode the supplied OPIS fuel-price CSV."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=Path)
        parser.add_argument(
            "--skip-geocoding",
            action="store_true",
            help=(
                "Import prices without calling Census services; existing coordinates are retained."
            ),
        )
        parser.add_argument(
            "--gazetteer-archive",
            type=Path,
            help="Optional downloaded Census Gazetteer ZIP used for city-centroid fallbacks.",
        )
        parser.add_argument(
            "--skip-census",
            action="store_true",
            help="Skip exact address matching and only apply Gazetteer city centroids.",
        )

    def handle(self, *args, **options):
        csv_path: Path = options["csv_path"]
        if not csv_path.is_file():
            raise CommandError(f"CSV file does not exist: {csv_path}")

        records = self._read_records(csv_path)
        if not records:
            raise CommandError("The CSV contains no valid fuel-station records.")

        existing = {
            station.fingerprint: station
            for station in FuelStation.objects.filter(fingerprint__in=records)
        }
        for fingerprint, station in existing.items():
            records[fingerprint]["latitude"] = station.latitude
            records[fingerprint]["longitude"] = station.longitude
            records[fingerprint]["geocode_quality"] = station.geocode_quality

        if not options["skip_geocoding"]:
            self._geocode(
                records,
                options.get("gazetteer_archive"),
                skip_census=options["skip_census"],
            )

        to_create: list[FuelStation] = []
        to_update: list[FuelStation] = []
        update_fields = [
            "opis_id",
            "name",
            "address",
            "city",
            "state",
            "rack_id",
            "retail_price",
            "latitude",
            "longitude",
            "geocode_quality",
        ]
        for fingerprint, record in records.items():
            station = existing.get(fingerprint)
            if station is None:
                to_create.append(FuelStation(**record))
                continue
            for field in update_fields:
                setattr(station, field, record[field])
            to_update.append(station)

        FuelStation.objects.bulk_create(to_create, batch_size=1000)
        if to_update:
            FuelStation.objects.bulk_update(to_update, update_fields, batch_size=1000)

        geocoded = sum(record["latitude"] is not None for record in records.values())
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(records)} unique stations "
                f"({len(to_create)} created, {len(to_update)} updated, {geocoded} geocoded)."
            )
        )

    def _read_records(self, path: Path) -> dict[str, dict]:
        records: dict[str, dict] = {}
        with path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"CSV is missing required columns: {', '.join(sorted(missing))}")

            for line_number, row in enumerate(reader, start=2):
                try:
                    price = Decimal(row["Retail Price"].strip())
                except (InvalidOperation, AttributeError):
                    self.stderr.write(f"Skipping line {line_number}: invalid retail price.")
                    continue
                values = [
                    row[column].strip()
                    for column in (
                        "OPIS Truckstop ID",
                        "Truckstop Name",
                        "Address",
                        "City",
                        "State",
                        "Rack ID",
                    )
                ]
                fingerprint = hashlib.sha256(
                    "\x1f".join(value.casefold() for value in values).encode()
                ).hexdigest()
                records[fingerprint] = {
                    "fingerprint": fingerprint,
                    "opis_id": values[0],
                    "name": values[1],
                    "address": values[2],
                    "city": values[3],
                    "state": values[4].upper(),
                    "rack_id": values[5],
                    "retail_price": price,
                    "latitude": None,
                    "longitude": None,
                    "geocode_quality": "",
                }
        return records

    def _geocode(
        self,
        records: dict[str, dict],
        gazetteer_path: Path | None,
        *,
        skip_census: bool,
    ) -> None:
        pending = [record for record in records.values() if record["latitude"] is None]
        if not pending:
            return

        exact = {}
        if not skip_census:
            try:
                exact = census_batch_geocode(pending)
            except httpx.HTTPError as exc:
                self.stderr.write(self.style.WARNING(f"Census batch geocoding failed: {exc}"))

        try:
            archive = gazetteer_path.read_bytes() if gazetteer_path else None
            places = load_gazetteer(archive=archive)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            self.stderr.write(self.style.WARNING(f"Gazetteer fallback failed: {exc}"))
            places = {}

        exact_count, fallback_count = apply_geocodes(pending, exact, places)
        self.stdout.write(
            f"Geocoding: {exact_count} exact Census matches, "
            f"{fallback_count} city-centroid fallbacks."
        )
