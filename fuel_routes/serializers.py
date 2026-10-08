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
