from django.db import models


class FuelStation(models.Model):
    fingerprint = models.CharField(max_length=64, unique=True)
    opis_id = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.CharField(max_length=32)
    retail_price = models.DecimalField(max_digits=10, decimal_places=8)
    latitude = models.FloatField(null=True, blank=True, db_index=True)
    longitude = models.FloatField(null=True, blank=True, db_index=True)
    geocode_quality = models.CharField(max_length=32, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["state", "city", "name"]
        indexes = [
            models.Index(fields=["latitude", "longitude"], name="station_lat_lon_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state})"


class ProviderCache(models.Model):
    class Kind(models.TextChoices):
        GEOCODE = "geocode", "Geocode"
        ROUTE = "route", "Route"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    cache_key = models.CharField(max_length=64)
    payload = models.JSONField()
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "cache_key"], name="unique_provider_cache_key")
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.cache_key[:12]}"
