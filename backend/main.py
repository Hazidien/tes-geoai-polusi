from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.staticfiles import StaticFiles

from backend.modules.air_pollution.aoi import shapefile_zip_to_geojson
from backend.modules.air_pollution.pollutants import analyze_pollutant

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'frontend'

app = FastAPI(title='GeoAI Remote Sensing WebGIS', version='0.3.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


class AnalysisRequest(BaseModel):
    module: Literal['air_pollution']
    variable: Literal['CO', 'NO2', 'SO2']
    aoi: dict = Field(...)
    start_date: date
    end_date: date
    aggregation: Literal['mean', 'median', 'min', 'max'] = 'mean'


@app.get('/api/health')
def health():
    return {'status': 'ok'}


@app.post('/api/aoi/upload')
async def upload_aoi(file: UploadFile = File(...)):
    filename = file.filename or ''
    if not filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail='Upload a Shapefile ZIP (.zip) containing .shp, .shx, .dbf, and .prj files.')
    try:
        content = await file.read()
        return shapefile_zip_to_geojson(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Could not read the shapefile: {exc}') from exc


@app.post('/api/analyze')
def analyze(request: AnalysisRequest):
    if request.end_date <= request.start_date:
        raise HTTPException(status_code=400, detail='End date must be after start date.')
    if request.aoi.get('type') not in {'Polygon', 'MultiPolygon'}:
        raise HTTPException(status_code=400, detail='AOI must be a GeoJSON Polygon or MultiPolygon.')
    try:
        payload = request.model_dump(mode='json')
        return analyze_pollutant(payload)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'GEE processing failed: {exc}') from exc


@app.get('/')
def frontend():
    return FileResponse(FRONTEND / 'index.html')


app.mount('/css', StaticFiles(directory=FRONTEND / 'css'), name='css')
app.mount('/js', StaticFiles(directory=FRONTEND / 'js'), name='js')
