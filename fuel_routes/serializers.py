from rest_framework import serializers


class LocationSerializer(serializers.Serializer):
    address = serializers.CharField(max_length=500, required=False)
    latitude = serializers.FloatField(required=False, min_value=-90, max_value=90)
    longitude = serializers.FloatField(required=False, min_value=-180, max_value=180)

    def validate(self, attrs):
        has_address = bool(attrs.get("address"))
        has_coordinates = "latitude" in attrs and "longitude" in attrs
        if has_address == has_coordinates:
            raise serializers.ValidationError(
                "Provide either address or both latitude and longitude."
            )
        if ("latitude" in attrs) != ("longitude" in attrs):
            raise serializers.ValidationError("Latitude and longitude must be provided together.")
        return attrs


class OptimizeRouteSerializer(serializers.Serializer):
    start = LocationSerializer()
    finish = LocationSerializer()
    starting_fuel_gallons = serializers.FloatField(
        default=0.0,
        min_value=0.0,
        max_value=50.0,
    )


class CoordinateSerializer(serializers.Serializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class FuelStopSerializer(serializers.Serializer):
    station_id = serializers.CharField()
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    location = CoordinateSerializer()
    route_mile = serializers.FloatField()
    detour_miles = serializers.FloatField()
    price_per_gallon = serializers.FloatField()
    fuel_on_arrival_gallons = serializers.FloatField()
    gallons_purchased = serializers.FloatField()
    subtotal = serializers.FloatField()
    geocode_quality = serializers.CharField()


class OptimizeRouteResponseSerializer(serializers.Serializer):
    start = CoordinateSerializer()
    finish = CoordinateSerializer()
    route = serializers.JSONField(help_text="GeoJSON Feature containing the route LineString.")
    distance_miles = serializers.FloatField()
    duration_seconds = serializers.IntegerField()
    candidate_stations_considered = serializers.IntegerField()
    fuel_stops = FuelStopSerializer(many=True)
    fuel_stops_geojson = serializers.JSONField(
        help_text="GeoJSON FeatureCollection containing the selected fuel stops."
    )
    total_gallons_purchased = serializers.FloatField()
    total_fuel_cost = serializers.FloatField()
    ending_fuel_gallons = serializers.FloatField()


class ErrorDetailSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.JSONField()


class ErrorResponseSerializer(serializers.Serializer):
    error = ErrorDetailSerializer()


class HealthResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
