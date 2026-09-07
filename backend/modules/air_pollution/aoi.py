from io import BytesIO
import zipfile

import shapefile
from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_FEATURES = 5000


def _safe_zip_members(archive):
    members = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace('\\', '/')
        if name.startswith('/') or '..' in name.split('/'):
            raise ValueError('Invalid ZIP path.')
        members[name.lower().split('/')[-1]] = info
    return members


def shapefile_zip_to_geojson(filename, content):
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError('Shapefile ZIP is too large. Maximum size is 20 MB.')

    try:
        archive = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError('The uploaded file is not a valid ZIP archive.') from exc

    with archive:
        members = _safe_zip_members(archive)
        required = ['.shp', '.shx', '.dbf']
        missing = [suffix for suffix in required if not any(name.endswith(suffix) for name in members)]
        if missing:
            raise ValueError(f'Shapefile ZIP is missing required file(s): {", ".join(missing)}')

        shp_name = next(name for name in members if name.endswith('.shp'))
        base = shp_name[:-4]
        shx_name = base + '.shx'
        dbf_name = base + '.dbf'
        prj_name = base + '.prj'

        if shx_name not in members or dbf_name not in members:
            stem = shp_name.rsplit('/', 1)[-1][:-4]
            shx_name = next(name for name in members if name.rsplit('/', 1)[-1].lower() == f'{stem}.shx')
            dbf_name = next(name for name in members if name.rsplit('/', 1)[-1].lower() == f'{stem}.dbf')

        if prj_name not in members:
            stem = shp_name.rsplit('/', 1)[-1][:-4]
            prj_name = next((name for name in members if name.rsplit('/', 1)[-1].lower() == f'{stem}.prj'), None)
        if not prj_name:
            raise ValueError('The shapefile must include a .prj file so its CRS can be interpreted safely.')

        reader = shapefile.Reader(
            shp=BytesIO(archive.read(shp_name)),
            shx=BytesIO(archive.read(shx_name)),
            dbf=BytesIO(archive.read(dbf_name)),
        )
        shapes = reader.shapes()
        if not shapes:
            raise ValueError('The shapefile contains no features.')
        if len(shapes) > MAX_FEATURES:
            raise ValueError(f'Too many features. Maximum supported is {MAX_FEATURES}.')

        geometries = []
        for shp in shapes:
            if shp.shapeType not in (5, 15, 25):
                raise ValueError('Only Polygon or MultiPolygon shapefiles are supported as AOI.')
            geom = shape(shp.__geo_interface__)
            if not geom.is_empty:
                geometries.append(geom)

        if not geometries:
            raise ValueError('The shapefile contains no usable polygon geometry.')

        source_crs = CRS.from_wkt(archive.read(prj_name).decode('utf-8-sig'))
        target_crs = CRS.from_epsg(4326)
        transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
        reprojected = [transform(transformer.transform, geom) for geom in geometries]
        merged = unary_union(reprojected)
        if merged.is_empty:
            raise ValueError('The shapefile geometry could not be converted to a usable AOI.')
        if not merged.is_valid:
            merged = merged.buffer(0)
        if merged.is_empty or merged.geom_type not in ('Polygon', 'MultiPolygon'):
            raise ValueError('The uploaded geometry must resolve to Polygon or MultiPolygon.')

        return {
            'success': True,
            'filename': filename,
            'feature_count': len(geometries),
            'geometry': {
                'type': merged.geom_type,
                'coordinates': list(merged.coords) if merged.geom_type == 'Polygon' else [list(poly.coords) for poly in merged.geoms],
            } if merged.geom_type == 'Polygon' else {
                'type': 'MultiPolygon',
                'coordinates': [[[list(coord) for coord in ring.coords] for ring in polygon.geoms] for polygon in merged.geoms],
            },
            'crs': 'EPSG:4326',
            'note': 'The uploaded shapefile is processed temporarily as an AOI and is not stored as a permanent Earth Engine asset.',
        }
