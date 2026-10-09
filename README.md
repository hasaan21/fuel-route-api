# Fuel Route API

A Django REST API that returns a U.S. driving route, cost-effective fuel stops, and
the total fuel purchased. The vehicle model is fixed at 500 miles of range,
10 miles per gallon, and a 50-gallon tank.

## Stack

- Python 3.12+, Django 6.1.2, Django REST framework 3.18.3
- Poetry with a committed lock file
- openrouteservice (HeiGIT free tier) for geocoding and directions
- U.S. Census batch geocoder and Gazetteer for one-time station geocoding
- Shapely and PyProj for route-corridor matching
- SQLite by default

## Setup

1. Install Python 3.12 or newer (up to 3.14) and Poetry 2.4 or newer.
2. Install dependencies and create local configuration:

   ```bash
   poetry install
   cp .env.example .env
   poetry run python manage.py migrate
   ```

3. Create a free openrouteservice key at <https://openrouteservice.org/plans/> and
   set `OPENROUTESERVICE_API_KEY` in `.env`.
4. Import the supplied fuel-price file:

   ```bash
   poetry run python manage.py import_fuel_prices \
     /path/to/fuel-prices-for-be-assessment.csv
   ```

   The command is idempotent. It deduplicates source records, submits unmatched
   addresses to the free Census batch endpoint once, and falls back to official
   Census place centroids. Coordinates and geocode quality are persisted locally.
   To update prices without network calls, add `--skip-geocoding`. To rerun only
   city-centroid fallbacks, add `--skip-census`.

5. Start the API:

   ```bash
   poetry run python manage.py runserver
   ```

Docker is also supported:

```bash
docker build -t fuel-route-api .
docker run --env-file .env -p 8000:8000 fuel-route-api
```

Run migrations and the import command in the container before serving real requests.

## API

### `POST /api/v1/routes/optimize/`

Each location accepts either a free-form U.S. address or latitude/longitude.

```json
{
  "start": {"address": "Oklahoma City, OK"},
  "finish": {"latitude": 35.0844, "longitude": -106.6504},
  "starting_fuel_gallons": 0
}
```

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/routes/optimize/ \
  -H 'Content-Type: application/json' \
  -d '{
    "start": {"address": "Oklahoma City, OK"},
    "finish": {"address": "Albuquerque, NM"},
    "starting_fuel_gallons": 0
  }'
```

The response contains:

- `route`: a GeoJSON `Feature` ready for Leaflet, MapLibre, or another map client
- `fuel_stops` and `fuel_stops_geojson`: stop details and map-ready points
- gallons, unit price, and subtotal for each fill
- `total_gallons_purchased` and `total_fuel_cost`
- route distance and duration

Errors use a stable envelope:

```json
{
  "error": {
    "code": "infeasible_fuel_plan",
    "detail": "The route contains a station gap greater than the vehicle's 500-mile range."
  }
}
```

Health check: `GET /api/v1/health/`.

## OpenAPI documentation

- Swagger UI: <http://127.0.0.1:8000/api/docs/>
- ReDoc: <http://127.0.0.1:8000/api/redoc/>
- OpenAPI schema: <http://127.0.0.1:8000/api/schema/>

The schema documents request validation, successful responses, structured errors,
and includes a runnable example for the route optimization endpoint.

## Routing calls and performance

- Coordinates: one external directions call.
- Uncached addresses: two geocoding calls and one directions call.
- Repeated locations and routes are served from the database cache until their TTLs
  expire, so they make no provider calls.
- Fuel stations are never geocoded during a route request. A bounding-box database
  query narrows candidates before local projection and optimization.

The free openrouteservice Standard plan currently requires an API key and applies
usage quotas. Routing uses `api.heigit.org`, while the hosted Pelias geocoder remains
at `api.openrouteservice.org`. Both URLs, timeouts, and cache TTLs are configurable
in `.env`.
The public OSRM demo was not used because it has no uptime guarantee and is not
intended as a production backend.

## Optimization behavior

The optimizer projects stations into a local equidistant coordinate system, filters
out stations over the configured detour limit, and builds a forward graph of every
station reachable within one tank. A label search keeps non-dominated combinations
of fuel carried and money spent, allowing it to skip stations whose discounts do not
justify their detours. Fuel purchases follow the optimal fill-or-buy-enough property,
and the globally cheapest feasible label is returned. Detour mileage consumes fuel.

`starting_fuel_gallons` defaults to zero. When that amount cannot reach a station,
a station in the configured origin area is treated as the initial fill and all such
starts are compared by total trip cost.
If no station path can bridge the route in 500-mile segments, the API returns a 422
instead of inventing a stop. Existing starting fuel is treated as already paid for,
so a trip completed entirely on starting fuel has zero new fuel spend.

City-centroid fallback coordinates are intentionally marked in each stop's
`geocode_quality`; they are less precise than Census address matches.

## Attribution

Route data is provided by openrouteservice by HeiGIT using map data
© OpenStreetMap contributors. Fuel prices come from the provided OPIS truck-stop
assessment dataset. Any UI displaying these results must preserve the required
openrouteservice and OpenStreetMap attribution.

## Quality checks

```bash
poetry check --lock
poetry run python manage.py check
poetry run ruff check .
poetry run pytest --cov
```
