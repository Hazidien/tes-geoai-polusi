import ee
from datetime import date, timedelta
from backend.config import initialize_gee

DATASET='COPERNICUS/S5P/NRTI/L3_CO'
BAND='CO_column_number_density'
UNIT='mol/m²'
SCALE=1113.2


def _period_bounds(start,end,interval):
    s=date.fromisoformat(start) if isinstance(start,str) else start
    e=date.fromisoformat(end) if isinstance(end,str) else end
    current=s
    while current<=e:
        if interval=='day':
            nxt=current+timedelta(days=1)
        else:
            nxt=date(current.year+1,1,1) if current.month==12 else date(current.year,current.month+1,1)
        yield current,min(e+timedelta(days=1),nxt)
        current=nxt


def _collection(request):
    initialize_gee()
    aoi=ee.Geometry(request['aoi'])
    end_obj=date.fromisoformat(request['end_date']) if isinstance(request['end_date'],str) else request['end_date']
    return (ee.ImageCollection(DATASET).filterBounds(aoi).filterDate(request['start_date'],(end_obj+timedelta(days=1)).isoformat()).select(BAND))


def _reducer(name):
    reducers={'mean':ee.Reducer.mean(),'median':ee.Reducer.median(),'min':ee.Reducer.min(),'max':ee.Reducer.max()}
    if name not in reducers: raise ValueError('Invalid spatial aggregation method.')
    return reducers[name]


def build_co_image(request):
    aoi=ee.Geometry(request['aoi'])
    collection=_collection(request)
    image_count=collection.size().getInfo()
    if not image_count: raise ValueError('No Sentinel-5P CO imagery was found for this AOI and date range.')
    return collection.mean().clip(aoi),image_count


def analyze_co(request):
    image,image_count=build_co_image(request)
    aoi=ee.Geometry(request['aoi'])
    stats=image.reduceRegion(reducer=_reducer(request['aggregation']),geometry=aoi,scale=SCALE,bestEffort=True,maxPixels=1e8).getInfo()
    value=stats.get(BAND) or stats.get(f"{BAND}_{request['aggregation']}")
    if value is None:
        nums=[v for v in stats.values() if isinstance(v,(int,float))]
        value=nums[0] if nums else None
    if value is None: raise RuntimeError('GEE returned no valid CO pixels for the selected AOI and date range. Try a larger AOI or a different period.')
    map_info=image.getMapId({'min':0,'max':0.05,'palette':['001219','005f73','0a9396','94d2bd','e9d8a6','ee9b00','ca6702','bb3e03','ae2012']})
    return {'success':True,'module':'air_pollution','variable':'CO','dataset':DATASET,'band':BAND,'start_date':request['start_date'],'end_date':request['end_date'],'aggregation':request['aggregation'],'value':float(value),'mean':float(value) if request['aggregation']=='mean' else None,'image_count':int(image_count),'unit':UNIT,'map':{'tile_url':map_info['tile_fetcher'].url_format},'interpretation':{'label':'Relative'},'note':'CO column number density; not a ground-level concentration or ISPU value.'}


def build_co_timeseries(request):
    aoi=ee.Geometry(request['aoi'])
    collection=_collection(request)
    reducer=_reducer(request['aggregation'])
    series=[]
    for period_start,period_end in _period_bounds(request['start_date'],request['end_date'],request.get('interval','month')):
        period=collection.filterDate(period_start.isoformat(),period_end.isoformat())
        count=period.size().getInfo()
        if not count: continue
        image=period.mean()
        stats=image.reduceRegion(reducer=reducer,geometry=aoi,scale=SCALE,bestEffort=True,maxPixels=1e8).getInfo()
        value=stats.get(BAND) or stats.get(f"{BAND}_{request['aggregation']}")
        if value is not None: series.append({'date':period_start.isoformat(),'value':float(value),'image_count':int(count)})
    return series
