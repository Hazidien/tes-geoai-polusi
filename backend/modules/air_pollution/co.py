import ee

from backend.config import initialize_gee

DATASET = 'COPERNICUS/S5P/NRTI/L3_CO'
BAND = 'CO_column_number_density'
UNIT = 'mol/m²'


def analyze_co(request):
    initialize_gee()

    aoi = ee.Geometry(request['aoi'])
    aggregation = request['aggregation']
    start_date = str(request['start_date'])
    end_date = str(request['end_date'])

    collection = (
        ee.ImageCollection(DATASET)
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .select(BAND)
    )

    image_count = collection.size().getInfo()
    if not image_count:
        raise ValueError('No Sentinel-5P CO imagery was found for this AOI and date range.')

    # Create one temporal mean composite for the selected period.
    # The selected aggregation is then a spatial statistic over the user's AOI.
    image = collection.mean().clip(aoi)

    reducers = {
        'mean': ee.Reducer.mean(),
        'median': ee.Reducer.median(),
        'min': ee.Reducer.min(),
        'max': ee.Reducer.max(),
    }

    stats = image.reduceRegion(
        reducer=reducers[aggregation],
        geometry=aoi,
        scale=1113.2,
        bestEffort=True,
        maxPixels=1e8,
    ).getInfo()

    value = stats.get(BAND)
    if value is None:
        raise RuntimeError('GEE returned no statistic for the selected AOI.')

    # Contextual thresholds from the spatial distribution inside the selected AOI.
    # These are relative classes for this analysis, not health standards or ISPU limits.
    percentile_stats = image.reduceRegion(
        reducer=ee.Reducer.percentile([25, 50, 75]),
        geometry=aoi,
        scale=1113.2,
        bestEffort=True,
        maxPixels=1e8,
    ).getInfo()

    p25 = percentile_stats.get(f'{BAND}_p25')
    p50 = percentile_stats.get(f'{BAND}_p50')
    p75 = percentile_stats.get(f'{BAND}_p75')

    if p25 is not None and p50 is not None and p75 is not None:
        if value < p25:
            level = 'Low'
        elif value < p50:
            level = 'Moderate'
        elif value < p75:
            level = 'High'
        else:
            level = 'Very High'
    else:
        level = 'Not classified'

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
        'start_date': start_date,
        'end_date': end_date,
        'aggregation': aggregation,
        'value': float(value),
        'image_count': int(image_count),
        'unit': UNIT,
        'classification': {
            'level': level,
            'method': 'Relative quartile classification within the selected AOI and period.',
            'thresholds': {
                'p25': p25,
                'p50': p50,
                'p75': p75,
            },
        },
        'map': {'tile_url': map_info['tile_fetcher'].url_format},
        'note': 'CO column number density; not a ground-level concentration or direct ISPU value.',
    }
