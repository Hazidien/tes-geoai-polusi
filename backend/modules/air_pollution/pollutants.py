from datetime import date
from typing import Dict, Iterable

import ee

from backend.config import initialize_gee


POLLUTANTS = {
    'SO2': {
        'name': 'Sulfur Dioxide (SO2)',
        'dataset': 'COPERNICUS/S5P/NRTI/L3_SO2',
        'band': 'SO2_column_number_density',
        'unit': 'µg/m³',
        'native_unit': 'mol/m²',
        'scale': 1113.2,
        'molar_mass': 64.065,
        'mode': 'mass',
        'min': 0,
        'max': 100,
        'palette': ['000000', '0000ff', '800080', '00ffff', '00a000', 'ffff00', 'ff0000'],
    },
    'NO2': {
        'name': 'Nitrogen Dioxide (NO2)',
        'dataset': 'COPERNICUS/S5P/NRTI/L3_NO2',
        'band': 'tropospheric_NO2_column_number_density',
        'unit': 'µg/m³',
        'native_unit': 'mol/m²',
        'scale': 1113.2,
        'molar_mass': 46.0055,
        'mode': 'mass',
        'min': 0,
        'max': 100,
        'palette': ['000000', '0000ff', '800080', '00ffff', '00a000', 'ffff00', 'ff0000'],
    },
    'CO': {
        'name': 'Carbon Monoxide (CO)',
        'dataset': 'COPERNICUS/S5P/NRTI/L3_CO',
        'band': 'CO_column_number_density',
        'unit': 'µg/m³',
        'native_unit': 'mol/m²',
        'scale': 1113.2,
        'molar_mass': 28.01,
        'mode': 'mass',
        'min': 30000,
        'max': 40000,
        'palette': ['000000', '0000ff', '800080', '00ffff', '00a000', 'ffff00', 'ff0000'],
    },
    'CH4': {
        'name': 'Methane (CH4)',
        'dataset': 'COPERNICUS/S5P/OFFL/L3_CH4',
        'band': 'CH4_column_volume_mixing_ratio_dry_air',
        'unit': 'ppm',
        'native_unit': 'ppb',
        'scale': 1113.2,
        'molar_mass': None,
        'mode': 'ppm',
        'min': 1.8,
        'max': 1.9,
        'palette': ['000000', '0000ff', '800080', '00ffff', '00a000', 'ffff00', 'ff0000'],
    },
}


def get_config(variable: str) -> dict:
    try:
        return POLLUTANTS[variable.upper()]
    except KeyError as exc:
        raise ValueError(f'Unsupported air-pollution variable: {variable}') from exc


def _aoi(aoi: dict):
    return ee.Geometry(aoi)


def _collection(request: dict):
    initialize_gee()
    cfg = get_config(request['variable'])
    return (
        ee.ImageCollection(cfg['dataset'])
        .filterBounds(_aoi(request['aoi']))
        .filterDate(request['start_date'], request['end_date'])
        .select(cfg['band'])
    )


def _reducer(name: str):
    reducers = {
        'mean': ee.Reducer.mean(),
        'median': ee.Reducer.median(),
        'min': ee.Reducer.min(),
        'max': ee.Reducer.max(),
    }
    try:
        return reducers[name]
    except KeyError as exc:
        raise ValueError(f'Invalid spatial aggregation method: {name}') from exc


def _convert(image, variable: str):
    cfg = get_config(variable)
    if cfg['mode'] == 'mass':
        # Reference training formula: mol/m² -> µg/m³ using a 10 km atmospheric column.
        factor = cfg['molar_mass'] * 1e6 / 10000.0
        return image.multiply(factor)
    return image.divide(1000.0)


def _period_bounds(start: date, end: date, interval: str) -> Iterable[tuple[date, date]]:
    if interval == 'day':
        cursor = start
        while cursor < end:
            nxt = date.fromordinal(cursor.toordinal() + 1)
            yield cursor, min(nxt, end)
            cursor = nxt
        return
    if interval != 'month':
        raise ValueError('Interval must be day or month.')
    cursor = start
    while cursor < end:
        if cursor.month == 12:
            nxt = date(cursor.year + 1, 1, 1)
        else:
            nxt = date(cursor.year, cursor.month + 1, 1)
        yield cursor, min(nxt, end)
        cursor = nxt


def _format_date(value) -> str:
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def build_image(request: dict):
    cfg = get_config(request['variable'])
    collection = _collection(request)
    count = collection.size().getInfo()
    if not count:
        raise ValueError(f'No {cfg["name"]} imagery is available for the selected AOI and date range.')
    return _convert(collection.mean().clip(_aoi(request['aoi'])), request['variable']), count


def analyze_pollutant(request: dict):
    cfg = get_config(request['variable'])
    image, count = build_image(request)
    stats = image.reduceRegion(
        reducer=_reducer(request.get('aggregation', 'mean')),
        geometry=_aoi(request['aoi']),
        scale=cfg['scale'],
        maxPixels=1e8,
    ).getInfo()
    value = stats.get(cfg['band'])
    if value is None:
        raise ValueError('No valid pixels were found inside the selected AOI.')
    vis = {'min': cfg['min'], 'max': cfg['max'], 'palette': cfg['palette']}
    map_id = image.getMapId(vis)
    return {
        'success': True,
        'module': 'air_pollution',
        'variable': request['variable'],
        'name': cfg['name'],
        'dataset': cfg['dataset'],
        'band': cfg['band'],
        'unit': cfg['unit'],
        'native_unit': cfg['native_unit'],
        'scale': cfg['scale'],
        'aggregation': request.get('aggregation', 'mean'),
        'value': float(value),
        'image_count': int(count),
        'start_date': _format_date(request['start_date']),
        'end_date': _format_date(request['end_date']),
        'map': {'tile_url': map_id['tile_fetcher'].url_format, 'vis': vis},
        'interpretation': {'label': 'Relative', 'description': 'Relative satellite-derived value within the selected AOI and period.'},
        'note': f'{cfg["name"]} is derived from Sentinel-5P atmospheric observations. The reported {cfg["unit"]} value follows the reference conversion method and should not be treated as a ground-station measurement or ISPU value.',
    }


def build_timeseries(request: dict):
    cfg = get_config(request['variable'])
    initialize_gee()
    start = date.fromisoformat(request['start_date']) if isinstance(request['start_date'], str) else request['start_date']
    end = date.fromisoformat(request['end_date']) if isinstance(request['end_date'], str) else request['end_date']
    aoi = _aoi(request['aoi'])
    interval = request.get('interval', 'month')
    reducer = _reducer(request.get('aggregation', 'mean'))
    output = []
    for period_start, period_end in _period_bounds(start, end, interval):
        coll = (
            ee.ImageCollection(cfg['dataset'])
            .filterBounds(aoi)
            .filterDate(_format_date(period_start), _format_date(period_end))
            .select(cfg['band'])
        )
        count = coll.size().getInfo()
        if not count:
            continue
        image = _convert(coll.mean(), request['variable'])
        stats = image.reduceRegion(reducer=reducer, geometry=aoi, scale=cfg['scale'], maxPixels=1e8).getInfo()
        value = stats.get(cfg['band'])
        if value is not None:
            output.append({'date': _format_date(period_start), 'value': float(value), 'image_count': int(count)})
    return output


def download_image(request: dict):
    cfg = get_config(request['variable'])
    image, _ = build_image(request)
    return image.getDownloadURL({
        'region': request['aoi'],
        'scale': cfg['scale'],
        'crs': 'EPSG:4326',
        'format': 'GEO_TIFF',
        'maxPixels': 1e8,
    })
