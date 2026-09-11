from datetime import date
from pathlib import Path
import io
import os
import tempfile
import uuid

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import rasterio
from rasterio.plot import reshape_as_image
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors

from backend.modules.air_pollution.co import analyze_co, build_co_image

app = FastAPI(title='WebGIS Remote Sensing', version='0.2.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / 'frontend'
UPLOAD_DIR = Path(tempfile.gettempdir()) / 'webgis_uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.mount('/css', StaticFiles(directory=FRONTEND_DIR / 'css'), name='css')
app.mount('/js', StaticFiles(directory=FRONTEND_DIR / 'js'), name='js')

class AnalysisRequest(BaseModel):
    module: str = Field('air_pollution')
    variable: str = Field('CO')
    aoi: dict = Field(...)
    start_date: date
    end_date: date
    aggregation: str = Field('mean')

@app.get('/')
def frontend():
    return FileResponse(FRONTEND_DIR / 'index.html')

@app.get('/api/health')
def health():
    return {'status': 'ok'}

@app.post('/api/analyze')
def analyze(request: AnalysisRequest):
    if request.module != 'air_pollution' or request.variable != 'CO':
        raise HTTPException(status_code=400, detail='Only Air Pollution → CO is currently available.')
    if request.end_date <= request.start_date:
        raise HTTPException(status_code=400, detail='End date must be after start date.')
    if request.aoi.get('type') not in {'Polygon', 'MultiPolygon'}:
        raise HTTPException(status_code=400, detail='AOI must be a GeoJSON Polygon or MultiPolygon.')
    try:
        return analyze_co(request.model_dump())
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'GEE processing failed: {exc}') from exc

@app.post('/api/export/geotiff')
def export_geotiff(request: AnalysisRequest):
    try:
        image, _ = build_co_image(request.model_dump())
        url = image.getDownloadURL({'region': request.aoi, 'scale': 1113.2, 'crs': 'EPSG:4326', 'format': 'GEO_TIFF', 'maxPixels': 1e8})
        return {'success': True, 'download_url': url, 'filename': f'CO_{request.start_date}_{request.end_date}.tif'}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'GeoTIFF export failed: {exc}') from exc

@app.post('/api/report/pdf')
def report_pdf(request: AnalysisRequest):
    try:
        result = analyze_co(request.model_dump())
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42)
        styles = getSampleStyleSheet()
        story = [Paragraph('WebGIS Air Pollution — Analysis Report', styles['Title']), Spacer(1, 12)]
        rows = [
            ['Module', result['module']], ['Variable', result['variable']],
            ['Dataset', result['dataset']], ['Period', f"{result['start_date']} → {result['end_date']}"],
            ['Aggregation', result['aggregation'].title()], ['Statistic', f"{result['value']:.6e} {result['unit']}"],
            ['Images', str(result['image_count'])],
        ]
        table = Table(rows, colWidths=[110, 350])
        table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(0,-1),colors.whitesmoke),('VALIGN',(0,0),(-1,-1),'TOP'),('FONTNAME',(0,0),(-1,-1),'Helvetica'),('PADDING',(0,0),(-1,-1),7)]))
        story += [table, Spacer(1, 14), Paragraph('Interpretation note: CO is satellite column number density, not a direct ground-level concentration or ISPU value.', styles['BodyText'])]
        doc.build(story)
        buffer.seek(0)
        return StreamingResponse(buffer, media_type='application/pdf', headers={'Content-Disposition': f"attachment; filename=CO_report_{request.start_date}_{request.end_date}.pdf"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'PDF report generation failed: {exc}') from exc

@app.post('/api/upload/geotiff')
def upload_geotiff(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(('.tif', '.tiff')):
        raise HTTPException(status_code=400, detail='Please upload a GeoTIFF file (.tif or .tiff).')
    data = file.file.read()
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail='GeoTIFF is too large. Maximum size is 100 MB.')
    file_id = uuid.uuid4().hex
    tif_path = UPLOAD_DIR / f'{file_id}.tif'
    tif_path.write_bytes(data)
    try:
        with rasterio.open(tif_path) as src:
            if src.crs is None:
                raise HTTPException(status_code=400, detail='GeoTIFF has no CRS/georeferencing information.')
            bounds = [src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top]
            width, height, count = src.width, src.height, src.count
            dtype = src.dtypes[0]
            nodata = src.nodata
            preview = src.read(out_shape=(min(3, count), min(800, height), min(800, width)))
            if preview.shape[0] == 1:
                arr = preview[0]
            else:
                arr = preview.transpose(1, 2, 0)
            import numpy as np
            arr = np.asarray(arr, dtype='float32')
            finite = arr[np.isfinite(arr)]
            lo, hi = (float(np.percentile(finite, 2)), float(np.percentile(finite, 98))) if finite.size else (0.0, 1.0)
            if hi <= lo: hi = lo + 1.0
            arr = np.clip((arr - lo) / (hi - lo) * 255, 0, 255).astype('uint8')
            if arr.ndim == 2:
                img = Image.fromarray(arr, 'L')
            else:
                if arr.shape[2] == 2: arr = arr[:, :, :1]
                if arr.shape[2] > 3: arr = arr[:, :, :3]
                img = Image.fromarray(arr)
            preview_path = UPLOAD_DIR / f'{file_id}.png'
            img.save(preview_path, 'PNG')
        return {'success': True, 'id': file_id, 'filename': file.filename, 'crs': str(src.crs), 'bounds': bounds, 'width': width, 'height': height, 'bands': count, 'dtype': dtype, 'nodata': nodata, 'preview_url': f'/api/upload/geotiff/{file_id}/preview'}
    except HTTPException:
        tif_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tif_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f'Could not read GeoTIFF: {exc}') from exc

@app.get('/api/upload/geotiff/{file_id}/preview')
def geotiff_preview(file_id: str):
    path = UPLOAD_DIR / f'{file_id}.png'
    if not path.is_file():
        raise HTTPException(status_code=404, detail='GeoTIFF preview not found.')
    return FileResponse(path, media_type='image/png')

@app.get('/api/upload/geotiff/{file_id}/download')
def geotiff_download(file_id: str):
    path = UPLOAD_DIR / f'{file_id}.tif'
    if not path.is_file():
        raise HTTPException(status_code=404, detail='Uploaded GeoTIFF not found.')
    return FileResponse(path, media_type='image/tiff', filename=f'uploaded_{file_id}.tif')
