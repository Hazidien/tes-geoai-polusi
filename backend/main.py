from datetime import date
from pathlib import Path
import io
import tempfile
import uuid
import urllib.request
import hashlib
import json

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import rasterio
from rasterio.warp import transform_bounds
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib import colors
from reportlab.lib.units import mm

from backend.aoi_upload import shapefile_zip_to_geojson
from backend.modules.air_pollution.pollutants import get_config, analyze_pollutant, build_timeseries, download_image, build_image

app=FastAPI(title='WebGIS Remote Sensing',version='0.8.0')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
ROOT=Path(__file__).resolve().parent.parent
FRONTEND_DIR=ROOT/'frontend'
UPLOAD_DIR=Path(tempfile.gettempdir())/'webgis_uploads'
UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
app.mount('/css',StaticFiles(directory=FRONTEND_DIR/'css'),name='css')
app.mount('/js',StaticFiles(directory=FRONTEND_DIR/'js'),name='js')

ANALYSIS_CACHE={}

class AnalysisRequest(BaseModel):
    module:str=Field('air_pollution')
    variable:str=Field('CO')
    aoi:dict=Field(...)
    start_date:date
    end_date:date
    aggregation:str=Field('mean')
    interval:str=Field('month')

def payload(request): return request.model_dump(mode='json')

def cache_key(data): return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def validate_request(request):
    if request.module!='air_pollution': raise HTTPException(400,'Unsupported module. This WebGIS currently provides Air Pollution only.')
    if request.variable not in {'SO2','NO2','CO','CH4'}: raise HTTPException(400,'Unsupported air-pollution variable. Choose SO2, NO2, CO, or CH4.')
    if request.end_date<request.start_date: raise HTTPException(400,'End date must be on or after start date.')
    if (request.end_date-request.start_date).days>=366: raise HTTPException(400,'Maximum analysis period is 365 days.')
    if request.aoi.get('type') not in {'Polygon','MultiPolygon'}: raise HTTPException(400,'AOI must be a GeoJSON Polygon or MultiPolygon.')
    if request.aggregation not in {'mean','median','min','max'}: raise HTTPException(400,'Invalid spatial aggregation method.')
    if request.interval not in {'day','month'}: raise HTTPException(400,'Invalid time series interval.')

def error_response(prefix,exc):
    if isinstance(exc,(ValueError,RuntimeError)): raise HTTPException(400,str(exc)) from exc
    raise HTTPException(500,f'{prefix}: {exc}') from exc

@app.get('/')
def frontend(): return FileResponse(FRONTEND_DIR/'index.html',headers={'Cache-Control':'no-store'})

@app.get('/api/health')
def health(): return {'status':'ok','application':'WebGIS Air Pollution','version':'0.8.0','variables':['SO2','NO2','CO','CH4']}

@app.get('/api/gee-status')
def gee_status():
    try:
        from backend.config import initialize_gee
        initialize_gee();return {'ok':True,'message':'Google Earth Engine is ready.'}
    except Exception as exc: return {'ok':False,'message':str(exc)}

@app.post('/api/analyze')
def analyze(request:AnalysisRequest):
    validate_request(request);data=payload(request);key=cache_key(data)
    try:
        result=analyze_pollutant(data);ANALYSIS_CACHE[key]={'request':data,'result':result};return result
    except Exception as exc: error_response('GEE processing failed',exc)

@app.post('/api/chart')
def chart(request:AnalysisRequest):
    validate_request(request);data=payload(request);key=cache_key(data)
    try:
        entry=ANALYSIS_CACHE.setdefault(key,{'request':data})
        series=entry.get('series')
        if series is None:
            series=build_timeseries(data);entry['series']=series
        return {'success':True,'variable':request.variable,'unit':get_config(request.variable)['unit'],'interval':request.interval,'aggregation':request.aggregation,'series':series}
    except Exception as exc: error_response('Time series processing failed',exc)

@app.post('/api/export/geotiff')
def export_geotiff(request:AnalysisRequest):
    validate_request(request)
    try:
        url=download_image(payload(request))
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'WebGIS-Air-Pollution/0.8.0'}),timeout=180) as response: data=response.read()
        if not data: raise ValueError('Earth Engine returned an empty GeoTIFF.')
        filename=f'{request.variable}_{request.start_date}_{request.end_date}.tif'
        return StreamingResponse(io.BytesIO(data),media_type='image/tiff',headers={'Content-Disposition':f'attachment; filename="{filename}"','Content-Length':str(len(data)),'Cache-Control':'no-store'})
    except Exception as exc: error_response('GeoTIFF download failed',exc)

@app.post('/api/upload/aoi')
def upload_aoi(file:UploadFile=File(...)):
    if not file.filename or not file.filename.lower().endswith(('.zip','.shp','.geojson','.json')): raise HTTPException(400,'Upload a Shapefile ZIP (.zip) or GeoJSON (.geojson/.json).')
    try:
        raw=file.file.read()
        if file.filename.lower().endswith(('.geojson','.json')):
            data=json.loads(raw.decode('utf-8'))
            if data.get('type')=='FeatureCollection':
                polygons=[f.get('geometry') for f in data.get('features',[]) if f.get('geometry',{}).get('type') in {'Polygon','MultiPolygon'}]
                if not polygons: raise ValueError('GeoJSON contains no Polygon or MultiPolygon features.')
                if len(polygons)==1: geometry=polygons[0]
                else:
                    coords=[]
                    for geom in polygons: coords.extend(geom.get('coordinates',[]) if geom.get('type')=='MultiPolygon' else [geom.get('coordinates',[])])
                    geometry={'type':'MultiPolygon','coordinates':coords}
            elif data.get('type')=='Feature': geometry=data.get('geometry')
            else: geometry=data
            if geometry.get('type') not in {'Polygon','MultiPolygon'}: raise ValueError('AOI must be Polygon or MultiPolygon.')
            return {'success':True,'filename':file.filename,'geometry':geometry,'feature_count':1,'source':'GeoJSON'}
        if file.filename.lower().endswith('.shp'): raise ValueError('Please ZIP the complete Shapefile set (.shp, .shx, .dbf and preferably .prj) before uploading.')
        result=shapefile_zip_to_geojson(raw)
        return {'success':True,'filename':file.filename,'geometry':result['geometry'],'feature_count':result['feature_count'],'source_epsg':result['source_epsg'],'source':'Shapefile'}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(400,f'AOI upload failed: {exc}') from exc

def pdf_chart(series,variable,unit):
    from reportlab.graphics.shapes import Drawing,String
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.charts.axes import XValueAxis,YValueAxis
    width,height=175*mm,55*mm;d=Drawing(width,height)
    if not series: d.add(String(45,height/2,'No time-series data available.',fontSize=9));return d
    p=LinePlot();p.x=35;p.y=18;p.width=width-48;p.height=height-34;p.data=[[(i,float(x['value'])) for i,x in enumerate(series)]]
    p.lines[0].strokeColor=colors.HexColor('#2d7ef7');p.lines[0].strokeWidth=1.8;p.xValueAxis=XValueAxis();p.yValueAxis=YValueAxis();p.xValueAxis.valueMin=0;p.xValueAxis.valueMax=max(1,len(series)-1)
    vals=[float(x['value']) for x in series];lo,hi=min(vals),max(vals);pad=(hi-lo)*.08 or max(abs(lo)*.05,1e-8);p.yValueAxis.valueMin=lo-pad;p.yValueAxis.valueMax=hi+pad;p.xValueAxis.labels.fontSize=7;p.yValueAxis.labels.fontSize=7
    d.add(p);d.add(String(35,height-9,f'{variable} time series ({unit})',fontSize=8,fillColor=colors.HexColor('#334155')));return d

def fallback_preview(request,result,cfg):
    path=UPLOAD_DIR/f'{uuid.uuid4().hex}_fallback.png';img=Image.new('RGB',(1200,700),'white');draw=ImageDraw.Draw(img);draw.rectangle((40,40,1160,660),outline='#334155',width=3)
    draw.text((65,65),f'{cfg["name"]} — Sentinel-5P',fill='#0f2742');draw.text((65,95),f'Result: {result["value"]:.6e} {cfg["unit"]}',fill='#334155');draw.text((65,125),'AOI outline / analysis preview',fill='#64748b')
    def rings(geometry):
        if geometry['type']=='Polygon': return geometry.get('coordinates',[])[:1]
        return [ring for poly in geometry.get('coordinates',[]) for ring in poly[:1]]
    pts=[(x,y) for ring in rings(request['aoi']) for x,y in ring]
    if pts:
        xs=[p[0] for p in pts];ys=[p[1] for p in pts];xmin,xmax=min(xs),max(xs);ymin,ymax=min(ys),max(ys);dx=xmax-xmin or 1;dy=ymax-ymin or 1;mapped=[(100+(x-xmin)/dx*1000,600-(y-ymin)/dy*500) for x,y in pts];draw.polygon(mapped,outline='#dc2626',width=5)
    img.save(path,'PNG');return path

def get_map_preview(data,result,cfg):
    image,_=build_image(data)
    visual=image.visualize(min=cfg['min'],max=cfg['max'],palette=cfg['palette'])
    try:
        import ee
        boundary=ee.Image().byte().paint(ee.Geometry(data['aoi']),1,3).visualize(min=0,max=1,palette=['FFFFFF'])
        visual=visual.blend(boundary)
    except Exception: pass
    thumb=visual.getThumbURL({'region':data['aoi'],'dimensions':1000,'format':'png'})
    with urllib.request.urlopen(urllib.request.Request(thumb,headers={'User-Agent':'WebGIS-Air-Pollution/0.8.0'}),timeout=90) as response: raw=response.read()
    if not raw.startswith(b'\x89PNG'): raise ValueError('Earth Engine returned an invalid map preview.')
    path=UPLOAD_DIR/f'{uuid.uuid4().hex}_map.png';path.write_bytes(raw)
    try:
        with Image.open(path) as im:
            rgba=im.convert('RGBA');pixels=list(rgba.getdata());nonzero=sum(1 for p in pixels if p[3]>0 and (p[0]+p[1]+p[2])>8)
            if nonzero<max(100,rgba.width*rgba.height//1000): raise ValueError('Earth Engine map preview was empty.')
    except Exception:
        path.unlink(missing_ok=True);raise
    return path

@app.post('/api/report/pdf')
def report_pdf(request:AnalysisRequest):
    validate_request(request);data=payload(request);key=cache_key(data);map_path=None
    try:
        entry=ANALYSIS_CACHE.setdefault(key,{'request':data})
        result=entry.get('result') or analyze_pollutant(data);entry['result']=result
        series=entry.get('series')
        if series is None: series=build_timeseries(data);entry['series']=series
        cfg=get_config(request.variable)
        try: map_path=get_map_preview(data,result,cfg)
        except Exception: map_path=fallback_preview(request,result,cfg)
        buffer=io.BytesIO();doc=SimpleDocTemplate(buffer,pagesize=A4,rightMargin=15*mm,leftMargin=15*mm,topMargin=14*mm,bottomMargin=14*mm)
        styles=getSampleStyleSheet();styles.add(ParagraphStyle(name='SmallNote',parent=styles['BodyText'],fontSize=8.5,leading=12,textColor=colors.HexColor('#475569')));styles.add(ParagraphStyle(name='SectionTitle',parent=styles['Heading2'],fontSize=13,leading=16,textColor=colors.HexColor('#0f2742'),spaceBefore=8,spaceAfter=6))
        story=[Paragraph('WebGIS Air Pollution Analysis',styles['Title']),Paragraph(cfg['name']+' — Sentinel-5P',styles['Heading2']),Paragraph('Developed by <b>Hazidien Ramadhan Utomo</b>',styles['SmallNote']),Spacer(1,7),Paragraph('This report presents the spatial and temporal analysis of the selected Sentinel-5P pollutant over the user-selected Area of Interest (AOI).',styles['BodyText']),Spacer(1,8),RLImage(str(map_path),width=175*mm,height=112*mm),Paragraph('Sentinel-5P analysis map with the selected pollutant gradient and AOI boundary.',styles['SmallNote']),Spacer(1,7),Paragraph('Analysis Parameters',styles['SectionTitle'])]
        rows=[['Module','Air Pollution'],['Variable',cfg['name']],['Dataset',cfg['dataset']],['Band',cfg['band']],['Period',f"{result['start_date']} → {result['end_date']}"],['Spatial aggregation',result['aggregation'].title()],['Time-series interval',request.interval.title()],['Images',str(result['image_count'])],['Statistic',f"{result['value']:.6e} {result['unit']}"]]
        table=Table(rows,colWidths=[48*mm,125*mm]);table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.HexColor('#cbd5e1')),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#f1f5f9')),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),6),('FONTNAME',(0,0),(0,-1),'Helvetica-Bold')]))
        story += [table,Spacer(1,9),Paragraph('Time Series',styles['SectionTitle']),pdf_chart(series,request.variable,cfg['unit']),Spacer(1,7),Paragraph('Reference-aligned method',styles['SectionTitle']),Paragraph('Sentinel-5P ImageCollection → AOI/date filtering → pollutant band selection → temporal mean → AOI clipping → reference unit conversion → spatial aggregation at 1113.2 m → selected time-series interval → GeoTIFF export.',styles['SmallNote']),Spacer(1,5),Paragraph('<b>Important:</b> Satellite atmospheric observations are not direct ground-station measurements and should not be interpreted as ISPU values.',styles['SmallNote'])]
        doc.build(story);buffer.seek(0);filename=f'{request.variable}_report_{request.start_date}_{request.end_date}.pdf';return StreamingResponse(buffer,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="{filename}"','Content-Length':str(buffer.getbuffer().nbytes),'Cache-Control':'no-store'})
    except Exception as exc: error_response('PDF report generation failed',exc)
    finally:
        if map_path: Path(map_path).unlink(missing_ok=True)

@app.post('/api/upload/geotiff')
def upload_geotiff(file:UploadFile=File(...)):
    if not file.filename or not file.filename.lower().endswith(('.tif','.tiff')): raise HTTPException(400,'Please upload a GeoTIFF file (.tif or .tiff)')
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
        preview_path=UPLOAD_DIR/f'{file_id}.png';img.save(preview_path,'PNG');return {'success':True,'id':file_id,'filename':file.filename,'crs':crs,'bounds':bounds,'width':width,'height':height,'bands':count,'dtype':dtype,'nodata':nodata,'preview_url':f'/api/upload/geotiff/{file_id}/preview'}
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
