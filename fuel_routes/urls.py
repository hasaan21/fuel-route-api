from django.urls import path

from fuel_routes.views import OptimizeRouteView, health

urlpatterns = [
    path("health/", health, name="health"),
    path("routes/optimize/", OptimizeRouteView.as_view(), name="optimize-route"),
]
