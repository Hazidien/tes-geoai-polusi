from io import BytesIO
import zipfile

import shapefile
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
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
        members[name.lower()] = info
    return members


def _find_member(members, filename):
    target = filename.lower()
    if target in members:
        return target
    basename = target.rsplit('/', 1)[-1]
    matches = [name for name in members if name.rsplit('/', 1)[-1] == basename]
    return matches[0] if matches else None


def shapefile_zip_to_geojson(filename, content):
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError('Shapefile ZIP is too large. Maximum size is 20 MB.')

    try:
        archive = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError('The uploaded file is not a valid ZIP archive.') from exc

    with archive:
        members = _safe_zip_members(archive)
        shp_names = [name for name in members if name.endswith('.shp')]
        if not shp_names:
            raise ValueError('The ZIP does not contain a .shp file.')
        shp_name = shp_names[0]
        stem = shp_name[:-4]
        shx_name = _find_member(members, stem + '.shx')
        dbf_name = _find_member(members, stem + '.dbf')
        prj_name = _find_member(members, stem + '.prj')
        missing = [ext for ext, member in (('.shx', shx_name), ('.dbf', dbf_name), ('.prj', prj_name)) if not member]
        if missing:
            raise ValueError(f'Shapefile ZIP is missing required file(s): {", ".join(missing)}')

        reader = shapefile.Reader(
            shp=BytesIO(archive.read(members[shp_name])),
            shx=BytesIO(archive.read(members[shx_name])),
            dbf=BytesIO(archive.read(members[dbf_name])),
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

        try:
            source_crs = CRS.from_wkt(archive.read(members[prj_name]).decode('utf-8-sig'))
        except Exception as exc:
            raise ValueError('The .prj file could not be interpreted.') from exc

        transformer = Transformer.from_crs(source_crs, CRS.from_epsg(4326), always_xy=True)
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
            'geometry': mapping(merged),
            'crs': 'EPSG:4326',
            'note': 'The uploaded shapefile is processed temporarily as an AOI and is not stored as a permanent Earth Engine asset.',
        }
