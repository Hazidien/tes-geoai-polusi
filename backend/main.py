from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.staticfiles import StaticFiles

from backend.modules.air_pollution.co import analyze_co

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'frontend'

app = FastAPI(title='GeoAI Remote Sensing WebGIS', version='0.1.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


class AnalysisRequest(BaseModel):
    module: Literal['air_pollution']
    variable: Literal['CO']
    aoi: dict = Field(...)
    start_date: date
    end_date: date
    aggregation: Literal['mean', 'median', 'min', 'max'] = 'mean'


@app.get('/api/health')
def health():
    return {'status': 'ok'}


@app.post('/api/analyze')
def analyze(request: AnalysisRequest):
    if request.end_date <= request.start_date:
        raise HTTPException(status_code=400, detail='End date must be after start date.')
    if request.aoi.get('type') not in {'Polygon', 'MultiPolygon'}:
        raise HTTPException(status_code=400, detail='AOI must be a GeoJSON Polygon or MultiPolygon.')
    try:
        # Serialize Pydantic date objects to ISO strings before passing the
        # request to Earth Engine, which expects date-like string values here.
        payload = request.model_dump(mode='json')
        return analyze_co(payload)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'GEE processing failed: {exc}') from exc


@app.get('/')
def frontend():
    return FileResponse(FRONTEND / 'index.html')


app.mount('/css', StaticFiles(directory=FRONTEND / 'css'), name='css')
app.mount('/js', StaticFiles(directory=FRONTEND / 'js'), name='js')
