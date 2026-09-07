import ee

from backend.config import initialize_gee

POLLUTANTS = {
    'CO': {
        'name': 'Carbon Monoxide (CO)', 'dataset': 'COPERNICUS/S5P/NRTI/L3_CO',
        'band': 'CO_column_number_density', 'unit': 'mol/m²', 'scale': 1113.2,
        'viz_min': 0, 'viz_max': 0.05, 'palette': ['black', 'blue', 'cyan', 'yellow', 'red'],
    },
    'NO2': {
        'name': 'Nitrogen Dioxide (NO₂)', 'dataset': 'COPERNICUS/S5P/NRTI/L3_NO2',
        'band': 'tropospheric_NO2_column_number_density', 'unit': 'mol/m²', 'scale': 1113.2,
        'viz_min': 0, 'viz_max': 0.0002, 'palette': ['black', 'blue', 'cyan', 'yellow', 'red'],
    },
    'SO2': {
        'name': 'Sulfur Dioxide (SO₂)', 'dataset': 'COPERNICUS/S5P/OFFL/L3_SO2',
        'band': 'SO2_column_number_density', 'unit': 'mol/m²', 'scale': 1113.2,
        'viz_min': 0, 'viz_max': 0.0005, 'palette': ['black', 'blue', 'cyan', 'yellow', 'red'],
    },
}


def _classify(value, image, aoi, band, scale):
    percentile_stats = image.reduceRegion(
        reducer=ee.Reducer.percentile([33, 66]), geometry=aoi, scale=scale,
        bestEffort=True, maxPixels=1e8,
    ).getInfo()
    p33 = percentile_stats.get(f'{band}_p33')
    p66 = percentile_stats.get(f'{band}_p66')
    if p33 is None or p66 is None:
        return 'Not classified', p33, p66
    if value <= p33:
        return 'Good', p33, p66
    if value <= p66:
        return 'Moderate', p33, p66
    return 'High', p33, p66


def _time_series(collection, aoi, band, scale, start_date, end_date):
    start = ee.Date(start_date)
    end = ee.Date(end_date)
    n_months = end.difference(start, 'month').ceil().max(1)

    def make_month(index):
        index = ee.Number(index)
        period_start = start.advance(index, 'month')
        period_end = period_start.advance(1, 'month')
        subset = collection.filterDate(period_start, period_end)
        image = subset.mean()
        value = image.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=aoi, scale=scale,
            bestEffort=True, maxPixels=1e8,
        ).get(band)
        return ee.Feature(None, {
            'date': period_start.format('YYYY-MM-dd'),
            'value': value,
            'image_count': subset.size(),
        })

    features = ee.FeatureCollection(ee.List.sequence(0, n_months.subtract(1)).map(make_month))
    return features.filter(ee.Filter.notNull(['value'])).getInfo().get('features', [])


def analyze_pollutant(request):
    initialize_gee()
    variable = request['variable']
    if variable not in POLLUTANTS:
        raise ValueError(f'Unsupported pollutant: {variable}')

    config = POLLUTANTS[variable]
    aoi = ee.Geometry(request['aoi'])
    aggregation = request['aggregation']
    start_date = str(request['start_date'])
    end_date = str(request['end_date'])

    collection = (
        ee.ImageCollection(config['dataset'])
        .filterBounds(aoi).filterDate(start_date, end_date).select(config['band'])
    )
    image_count = collection.size().getInfo()
    if not image_count:
        raise ValueError(f'No Sentinel-5P {variable} imagery was found for this AOI and date range.')

    image = collection.mean().clip(aoi)
    reducers = {
        'mean': ee.Reducer.mean(), 'median': ee.Reducer.median(),
        'min': ee.Reducer.min(), 'max': ee.Reducer.max(),
    }
    stats = image.reduceRegion(
        reducer=reducers[aggregation], geometry=aoi, scale=config['scale'],
        bestEffort=True, maxPixels=1e8,
    ).getInfo()
    value = stats.get(config['band'])
    if value is None:
        raise RuntimeError(f'GEE returned no {variable} statistic for the selected AOI.')

    level, p33, p66 = _classify(float(value), image, aoi, config['band'], config['scale'])
    time_series = _time_series(collection, aoi, config['band'], config['scale'], start_date, end_date)
    map_info = image.getMapId({
        'min': config['viz_min'], 'max': config['viz_max'], 'palette': config['palette'],
    })

    geotiff_url = None
    try:
        geotiff_url = image.getDownloadURL({
            'name': f'{variable}_{start_date}_{end_date}',
            'region': aoi.getInfo()['coordinates'],
            'scale': config['scale'],
            'crs': 'EPSG:4326',
            'format': 'GEO_TIFF',
        })
    except Exception:
        pass

    return {
        'success': True, 'module': 'air_pollution', 'variable': variable,
        'name': config['name'], 'dataset': config['dataset'], 'band': config['band'],
        'start_date': start_date, 'end_date': end_date, 'aggregation': aggregation,
        'value': float(value), 'image_count': int(image_count), 'unit': config['unit'],
        'classification': {
            'level': level,
            'method': 'Relative tertile classification within the selected AOI and analysis period.',
            'thresholds': {'p33': p33, 'p66': p66},
        },
        'time_series': [
            {'date': f['properties']['date'], 'value': float(f['properties']['value']),
             'image_count': int(f['properties']['image_count'])}
            for f in time_series if f.get('properties', {}).get('value') is not None
        ],
        'map': {'tile_url': map_info['tile_fetcher'].url_format},
        'downloads': {'geotiff_url': geotiff_url},
        'note': (
            f"{variable} is represented as Sentinel-5P column number density ({config['unit']}). "
            'The Good/Moderate/High classes are relative to the selected AOI and period; '
            'they are not direct ISPU or ground-level health-standard classifications.'
        ),
    }
