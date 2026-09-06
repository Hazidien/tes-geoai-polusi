import ee
from backend.config import initialize_gee

DATASET = 'COPERNICUS/S5P/NRTI/L3_CO'
BAND = 'CO_column_number_density'
UNIT = 'mol/m²'


def analyze_co(request):
    initialize_gee()
    aoi = ee.Geometry(request['aoi'])
    reducers = {
        'mean': ee.Reducer.mean(),
        'median': ee.Reducer.median(),
        'min': ee.Reducer.min(),
        'max': ee.Reducer.max(),
    }
    collection = (ee.ImageCollection(DATASET)
        .filterBounds(aoi)
        .filterDate(request['start_date'], request['end_date'])
        .select(BAND))
    image_count = collection.size().getInfo()
    if not image_count:
        raise ValueError('No Sentinel-5P CO imagery was found for this AOI and date range.')
    image = collection.mean().clip(aoi)
    stats = image.reduceRegion(
        reducer=reducers[request['aggregation']],
        geometry=aoi,
        scale=1113.2,
        bestEffort=True,
        maxPixels=1e8,
    ).getInfo()
    key = f'{BAND}_{request["aggregation"]}'
    value = stats.get(key)
    if value is None:
        raise RuntimeError('GEE returned no statistic for the selected AOI.')
    map_info = image.getMapId({
        'min': 0,
        'max': 0.05,
        'palette': ['black', 'blue', 'cyan', 'yellow', 'red'],
    })
    return {
        'success': True,
        'module': 'air_pollution',
        'variable': 'CO',
        'dataset': DATASET,
        'band': BAND,
        'start_date': request['start_date'],
        'end_date': request['end_date'],
        'aggregation': request['aggregation'],
        'value': float(value),
        'mean': float(value) if request['aggregation'] == 'mean' else None,
        'image_count': int(image_count),
        'unit': UNIT,
        'map': {'tile_url': map_info['tile_fetcher'].url_format},
        'note': 'CO column number density; not a ground-level concentration.',
    }
