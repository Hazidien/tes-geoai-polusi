from datetime import date
from pathlib import Path
import io
import tempfile
import uuid
import urllib.request

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import rasterio
from rasterio.warp import transform_bounds
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib import colors
from reportlab.lib.units import mm

from backend.modules.air_pollution.co import analyze_co, build_co_image, build_co_timeseries

app=FastAPI(title='WebGIS Remote Sensing',version='0.4.1')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
ROOT=Path(__file__).resolve().parent.parent
FRONTEND_DIR=ROOT/'frontend'
UPLOAD_DIR=Path(tempfile.gettempdir())/'webgis_uploads'
UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
app.mount('/css',StaticFiles(directory=FRONTEND_DIR/'css'),name='css')
app.mount('/js',StaticFiles(directory=FRONTEND_DIR/'js'),name='js')

class AnalysisRequest(BaseModel):
    module:str=Field('air_pollution')
    variable:str=Field('CO')
    aoi:dict=Field(...)
    start_date:date
    end_date:date
    aggregation:str=Field('mean')
    interval:str=Field('month')

def payload(request): return request.model_dump(mode='json')

def validate_request(request):
    if request.module!='air_pollution' or request.variable!='CO': raise HTTPException(400,'Only Air Pollution → CO is currently available.')
    if request.end_date<=request.start_date: raise HTTPException(400,'End date must be after start date.')
    if (request.end_date-request.start_date).days>366: raise HTTPException(400,'Maximum analysis period is 366 days.')
    if request.aoi.get('type') not in {'Polygon','MultiPolygon'}: raise HTTPException(400,'AOI must be a GeoJSON Polygon or MultiPolygon.')
    if request.aggregation not in {'mean','median','min','max'}: raise HTTPException(400,'Invalid spatial aggregation method.')
    if request.interval not in {'day','month'}: raise HTTPException(400,'Invalid time series interval.')

@app.get('/')
def frontend(): return FileResponse(FRONTEND_DIR/'index.html')

@app.get('/api/health')
def health(): return {'status':'ok'}

@app.post('/api/analyze')
def analyze(request:AnalysisRequest):
    validate_request(request)
    try: return analyze_co(payload(request))
    except (ValueError,RuntimeError) as exc: raise HTTPException(400,str(exc)) from exc
    except Exception as exc: raise HTTPException(500,f'GEE processing failed: {exc}') from exc

@app.post('/api/chart')
def chart(request:AnalysisRequest):
    validate_request(request)
    try: return {'success':True,'variable':'CO','unit':'mol/m²','interval':request.interval,'aggregation':request.aggregation,'series':build_co_timeseries(payload(request))}
    except (ValueError,RuntimeError) as exc: raise HTTPException(400,str(exc)) from exc
    except Exception as exc: raise HTTPException(500,f'Time series processing failed: {exc}') from exc

@app.post('/api/export/geotiff')
def export_geotiff(request:AnalysisRequest):
    validate_request(request)
    try:
        image,_=build_co_image(payload(request))
        url=image.getDownloadURL({'region':request.aoi,'scale':1113.2,'crs':'EPSG:4326','format':'GEO_TIFF','maxPixels':1e8})
        return {'success':True,'download_url':url,'filename':f'CO_{request.start_date}_{request.end_date}.tif'}
    except Exception as exc: raise HTTPException(500,f'GeoTIFF export failed: {exc}') from exc

def pdf_chart(series):
    from reportlab.graphics.shapes import Drawing,String
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.charts.axes import XValueAxis,YValueAxis
    width,height=175*mm,55*mm
    d=Drawing(width,height)
    if not series:
        d.add(String(45,height/2,'No time-series data available.',fontSize=9))
        return d
    p=LinePlot();p.x=35;p.y=18;p.width=width-48;p.height=height-34
    p.data=[[(i,float(x['value'])) for i,x in enumerate(series)]]
    p.lines[0].strokeColor=colors.HexColor('#2d7ef7');p.lines[0].strokeWidth=1.8
    p.xValueAxis=XValueAxis();p.yValueAxis=YValueAxis()
    p.xValueAxis.valueMin=0;p.xValueAxis.valueMax=max(1,len(series)-1)
    vals=[float(x['value']) for x in series];lo,hi=min(vals),max(vals);pad=(hi-lo)*.08 or max(abs(lo)*.05,1e-8)
    p.yValueAxis.valueMin=lo-pad;p.yValueAxis.valueMax=hi+pad
    p.xValueAxis.labels.fontSize=7;p.yValueAxis.labels.fontSize=7
    d.add(p);d.add(String(35,height-9,'CO time series (mol/m²)',fontSize=8,fillColor=colors.HexColor('#334155')))
    return d

@app.post('/api/report/pdf')
def report_pdf(request:AnalysisRequest):
    validate_request(request)
    map_path=None
    try:
        data=payload(request);result=analyze_co(data);series=build_co_timeseries(data);image,_=build_co_image(data)
        thumb=image.getThumbURL({'region':request.aoi,'dimensions':900,'format':'png','min':0,'max':0.05,'palette':['001219','005f73','0a9396','94d2bd','e9d8a6','ee9b00','ca6702','bb3e03','ae2012']})
        map_bytes=urllib.request.urlopen(thumb,timeout=30).read()
        map_path=UPLOAD_DIR/f'{uuid.uuid4().hex}_map.png';map_path.write_bytes(map_bytes)
        buffer=io.BytesIO();doc=SimpleDocTemplate(buffer,pagesize=A4,rightMargin=15*mm,leftMargin=15*mm,topMargin=14*mm,bottomMargin=14*mm)
        styles=getSampleStyleSheet();styles.add(ParagraphStyle(name='SmallNote',parent=styles['BodyText'],fontSize=8.5,leading=12,textColor=colors.HexColor('#475569')));styles.add(ParagraphStyle(name='SectionTitle',parent=styles['Heading2'],fontSize=13,leading=16,textColor=colors.HexColor('#0f2742'),spaceBefore=8,spaceAfter=6))
        story=[Paragraph('WebGIS Air Pollution Analysis',styles['Title']),Paragraph('Carbon Monoxide (CO) — Sentinel-5P',styles['Heading2']),Paragraph('Developed by <b>Hazidien Ramadhan Utomo</b>',styles['SmallNote']),Spacer(1,7),Paragraph('This report presents the spatial and temporal analysis of Carbon Monoxide (CO) based on Sentinel-5P data over the user-selected Area of Interest (AOI).',styles['BodyText']),Spacer(1,8),RLImage(str(map_path),width=175*mm,height=112*mm),Paragraph('Analysis map for the selected AOI. Colors represent relative CO values from Sentinel-5P imagery.',styles['SmallNote']),Spacer(1,7),Paragraph('Analysis Parameters',styles['SectionTitle'])]
        rows=[['Module',result['module']],['Variable','Carbon Monoxide (CO)'],['Dataset',result['dataset']],['Band',result['band']],['Period',f"{result['start_date']} → {result['end_date']}"],['Spatial aggregation',result['aggregation'].title()],['Time-series interval',request.interval.title()],['Images',str(result['image_count'])],['Statistic',f"{result['value']:.6e} {result['unit']}"]]
        table=Table(rows,colWidths=[48*mm,125*mm]);table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.HexColor('#cbd5e1')),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#f1f5f9')),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),6),('FONTNAME',(0,0),(0,-1),'Helvetica-Bold')]))
        story += [table,Spacer(1,9),Paragraph('Time Series',styles['SectionTitle']),pdf_chart(series),Spacer(1,7),Paragraph('Explanation',styles['SectionTitle']),Paragraph('The analysis uses the Sentinel-5P Carbon Monoxide collection with the <b>CO_column_number_density</b> band. Values are expressed as <b>column number density (mol/m²)</b>. The reference material describes the use of Sentinel-5P for CO analysis and the creation of a time-series chart based on the spatial mean over the study area.',styles['SmallNote']),Spacer(1,5),Paragraph('<b>Important:</b> These results represent satellite atmospheric column measurements, not direct ground-level air concentrations and not ISPU values.',styles['SmallNote']),Spacer(1,5),Paragraph('WebGIS purpose: to provide an interactive geospatial environment for exploring spatial patterns and temporal changes in CO over a selected AOI, while also supporting GeoTIFF export and PDF reporting.',styles['SmallNote'])]
        doc.build(story);buffer.seek(0)
        return StreamingResponse(buffer,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename=CO_report_{request.start_date}_{request.end_date}.pdf'})
    except Exception as exc: raise HTTPException(500,f'PDF report generation failed: {exc}') from exc
    finally:
        if map_path: map_path.unlink(missing_ok=True)

@app.post('/api/upload/geotiff')
def upload_geotiff(file:UploadFile=File(...)):
    if not file.filename or not file.filename.lower().endswith(('.tif','.tiff')): raise HTTPException(400,'Please upload a GeoTIFF file (.tif or .tiff).')
    data=file.file.read()
    if len(data)>100*1024*1024: raise HTTPException(400,'GeoTIFF is too large. Maximum size is 100 MB.')
    file_id=uuid.uuid4().hex;tif_path=UPLOAD_DIR/f'{file_id}.tif';tif_path.write_bytes(data)
    try:
        with rasterio.open(tif_path) as src:
            if src.crs is None: raise HTTPException(400,'GeoTIFF has no CRS/georeferencing information.')
            crs=str(src.crs);bounds=list(transform_bounds(src.crs,'EPSG:4326',src.bounds.left,src.bounds.bottom,src.bounds.right,src.bounds.top));width,height,count=src.width,src.height,src.count;dtype,nodata=src.dtypes[0],src.nodata;preview=src.read(out_shape=(min(3,count),min(800,height),min(800,width)))
        import numpy as np
        arr=preview[0] if preview.shape[0]==1 else preview.transpose(1,2,0);arr=np.asarray(arr,dtype='float32');finite=arr[np.isfinite(arr)];lo,hi=((float(np.percentile(finite,2)),float(np.percentile(finite,98))) if finite.size else (0.,1.));hi=hi if hi>lo else lo+1.;arr=np.clip((arr-lo)/(hi-lo)*255,0,255).astype('uint8')
        if arr.ndim==2: img=Image.fromarray(arr,'L')
        else:
            if arr.shape[2]==2: arr=arr[:,:,0];img=Image.fromarray(arr,'L')
            else: img=Image.fromarray(arr[:,:,:3])
        preview_path=UPLOAD_DIR/f'{file_id}.png';img.save(preview_path,'PNG')
        return {'success':True,'id':file_id,'filename':file.filename,'crs':crs,'bounds':bounds,'width':width,'height':height,'bands':count,'dtype':dtype,'nodata':nodata,'preview_url':f'/api/upload/geotiff/{file_id}/preview'}
    except HTTPException: tif_path.unlink(missing_ok=True);raise
    except Exception as exc: tif_path.unlink(missing_ok=True);raise HTTPException(400,f'Could not read GeoTIFF: {exc}') from exc

@app.get('/api/upload/geotiff/{file_id}/preview')
def geotiff_preview(file_id:str):
    path=UPLOAD_DIR/f'{file_id}.png'
    if not path.is_file(): raise HTTPException(404,'GeoTIFF preview not found.')
    return FileResponse(path,media_type='image/png')

@app.get('/api/upload/geotiff/{file_id}/download')
def geotiff_download(file_id:str):
    path=UPLOAD_DIR/f'{file_id}.tif'
    if not path.is_file(): raise HTTPException(404,'Uploaded GeoTIFF not found.')
    return FileResponse(path,media_type='image/tiff',filename=f'uploaded_{file_id}.tif')
