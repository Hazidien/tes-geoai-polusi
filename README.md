# WebGIS Remote Sensing

A portfolio-quality WebGIS for remote-sensing analysis, built for GitHub Codespaces.

## Current features
- Interactive Leaflet map
- User-defined polygon and rectangle AOI; only one AOI is active
- Start/end date with day, month, and year selection
- Air Pollution → CO
- Google Earth Engine Sentinel-5P CO processing
- Raster overlay from GEE
- AOI statistics and image count
- Daily or monthly CO time-series chart
- Chart popup that can be opened and closed
- Welcome popup with developer name (Hazidien) and WebGIS purpose
- PDF report containing the analysis map, parameters, time series, and explanation
- GeoTIFF export
- Validation and human-readable errors

## Stack
Python · FastAPI · Google Earth Engine · HTML · CSS · JavaScript · Leaflet · Leaflet-Geoman · Chart.js

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
Set `GEE_PROJECT_ID` and `GOOGLE_APPLICATION_CREDENTIALS` in `.env`. Never commit credential JSON or API keys.

The update keeps the existing Earth Engine initialization in `backend/config.py`; no new GEE verification flow is introduced by the UI/chart/PDF changes.

## Dataset
`COPERNICUS/S5P/NRTI/L3_CO` — `CO_column_number_density`.

The value represents satellite column number density in mol/m² and is not a direct ground-level concentration or ISPU value.

## Reference method
The CO workflow follows the supplied Geoaccess Indonesia training material: Sentinel-5P CO collection, AOI/date filtering, temporal mean, regional aggregation, time-series charting, and GeoTIFF export. The material's CO section is on pages 33–41 of the supplied module PDF.
