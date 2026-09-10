# WebGIS Remote Sensing

A portfolio-quality WebGIS for remote-sensing analysis, built for GitHub Codespaces.

## MVP
- Interactive Leaflet map
- User-defined polygon and rectangle AOI
- Start/end date
- Air Pollution → CO
- Google Earth Engine Sentinel-5P CO processing
- Raster overlay from GEE
- AOI statistics and image count
- Validation and human-readable errors

## Stack
Python · FastAPI · Google Earth Engine · HTML · CSS · JavaScript · Leaflet · Leaflet-Geoman

## Run in Codespaces

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Open the forwarded port 8000.

## GEE authentication
Set `GEE_PROJECT_ID` and `GOOGLE_APPLICATION_CREDENTIALS` in `.env`. Never commit credential JSON or API keys. The application fails clearly when GEE is not configured.

## Dataset
`COPERNICUS/S5P/NRTI/L3_CO` — `CO_column_number_density`.

The value represents satellite column number density and is not a ground-level concentration.

## Roadmap
NO2 → SO2 → time series → CSV/GeoTIFF → PDF report
