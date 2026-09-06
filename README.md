# GeoAI Remote Sensing WebGIS — Air Pollution

A development MVP for user-defined AOI analysis of Sentinel-5P carbon monoxide (CO) in Google Earth Engine.

## Current capability

- Leaflet map with OpenStreetMap basemap
- Draw a polygon or rectangle as the AOI
- Select start/end dates
- Aggregate the temporal Sentinel-5P CO composite with mean, median, minimum, or maximum as a spatial statistic over the AOI
- Return AOI statistics and a Google Earth Engine map tile
- CO variable: `CO_column_number_density` (`mol/m²`)
- Scientific note: this is column number density, not ground-level CO concentration

## Earth Engine project

The configured Google Cloud project is `tes-geoai`. It must be registered for Earth Engine and have the Earth Engine API enabled.

## Local / Codespaces development

1. Copy `.env.example` to `.env`.
2. Keep `GEE_PROJECT_ID=tes-geoai`.
3. Authenticate the development environment with your Google account:

   ```bash
   earthengine authenticate
   ```

4. Start the API:

   ```bash
   uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
   ```

5. Open the forwarded port and use the WebGIS.

The authentication credential is stored in the development environment, not in Git. Never commit a credential JSON, OAuth token, or `.env` file.

## API

- `GET /api/health`
- `POST /api/analyze`

Example request shape:

```json
{
  "module": "air_pollution",
  "variable": "CO",
  "aoi": {
    "type": "Polygon",
    "coordinates": [[[112.6, -7.4], [113.0, -7.4], [113.0, -7.1], [112.6, -7.1], [112.6, -7.4]]]
  },
  "start_date": "2026-09-01",
  "end_date": "2026-09-07",
  "aggregation": "mean"
}
```

## Project boundary

This repository is intentionally separate from the personal portfolio repository. Do not copy the GeoAI application into `Hazidien/hazidien-portfolio` unless explicitly requested.
