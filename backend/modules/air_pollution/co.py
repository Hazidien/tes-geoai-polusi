import ee
from datetime import date, timedelta
from backend.config import initialize_gee

DATASET = 'COPERNICUS/S5P/NRTI/L3_CO'
BAND = 'CO_column_number_density'
UNIT = 'mol/m²'
SCALE = 1113.2


def build_co_image(request):
    initialize_gee()
    aoi = ee.Geometry(request['aoi'])
    start = request['start_date']
    end = request['end_date']
    start_ee = start if isinstance(start, str) else start.isoformat()
    end_obj = date.fromisoformat(end) if isinstance(end, str) else end
    end_ee = (end_obj + timedelta(days=1)).isoformat()
    collection = (ee.ImageCollection(DATASET)
        .filterBounds(aoi)
        .filterDate(start_ee, end_ee)
        .select(BAND))
    image_count = collection.size().getInfo()
    if not image_count:
        raise ValueError('No Sentinel-5P CO imagery was found for this AOI and date range.')
    return collection.mean().clip(aoi), image_count


def analyze_co(request):
    image, image_count = build_co_image(request)
    aoi = ee.Geometry(request['aoi'])
    reducers = {'mean': ee.Reducer.mean(), 'median': ee.Reducer.median(), 'min': ee.Reducer.min(), 'max': ee.Reducer.max()}
    aggregation = request['aggregation']
    if aggregation not in reducers:
        raise ValueError('Invalid spatial aggregation method.')
    stats = image.reduceRegion(reducer=reducers[aggregation], geometry=aoi, scale=SCALE, bestEffort=True, maxPixels=1e8).getInfo()
    value = stats.get(BAND)
    if value is None:
        value = stats.get(f'{BAND}_{aggregation}')
    if value is None and stats:
        numeric_values = [v for v in stats.values() if isinstance(v, (int, float))]
        if numeric_values:
            value = numeric_values[0]
    if value is None:
        raise RuntimeError('GEE returned no valid CO pixels for the selected AOI and date range. Try a larger AOI or a different period.')
    map_info = image.getMapId({'min': 0, 'max': 0.05, 'palette': ['black', 'blue', 'cyan', 'yellow', 'red']})
    return {'success': True, 'module': 'air_pollution', 'variable': 'CO', 'dataset': DATASET, 'band': BAND, 'start_date': request['start_date'], 'end_date': request['end_date'], 'aggregation': aggregation, 'value': float(value), 'mean': float(value) if aggregation == 'mean' else None, 'image_count': int(image_count), 'unit': UNIT, 'map': {'tile_url': map_info['tile_fetcher'].url_format}, 'note': 'CO column number density; not a ground-level concentration.'}
