from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

import shapefile
from pyproj import Transformer


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    root = target.resolve()
    for member in zf.infolist():
        name = Path(member.filename)
        if name.is_absolute() or '..' in name.parts:
            raise ValueError('Unsafe path in Shapefile ZIP.')
        destination = (target / name).resolve()
        if root != destination and root not in destination.parents:
            raise ValueError('Unsafe path in Shapefile ZIP.')
    zf.extractall(target)


def _find(path: Path, suffix: str) -> Path | None:
    matches = list(path.rglob(f'*.{suffix}')) + list(path.rglob(f'*.{suffix.upper()}'))
    return matches[0] if matches else None


def _transform_geometry(geometry, source_epsg: int):
    if source_epsg == 4326:
        return geometry
    transformer = Transformer.from_crs(source_epsg, 4326, always_xy=True)

    def ring(coords):
        return [[*transformer.transform(x, y)] for x, y in coords]

    if geometry['type'] == 'Polygon':
        return {'type': 'Polygon', 'coordinates': [ring(r) for r in geometry['coordinates']]}
    if geometry['type'] == 'MultiPolygon':
        return {'type': 'MultiPolygon', 'coordinates': [[[p for p in ring(r)] for r in poly] for poly in geometry['coordinates']]}
    return geometry


def shapefile_zip_to_geojson(data: bytes) -> dict:
    if len(data) > 100 * 1024 * 1024:
        raise ValueError('Shapefile ZIP is too large. Maximum size is 100 MB.')
    with tempfile.TemporaryDirectory(prefix='webgis_shp_') as temp:
        folder = Path(temp)
        zip_path = folder / 'upload.zip'
        zip_path.write_bytes(data)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                _safe_extract(zf, folder / 'files')
        except zipfile.BadZipFile as exc:
            raise ValueError('Please upload a valid Shapefile ZIP.') from exc
        shp = _find(folder / 'files', 'shp')
        dbf = _find(folder / 'files', 'dbf')
        shx = _find(folder / 'files', 'shx')
        if not shp or not dbf or not shx:
            raise ValueError('Shapefile ZIP must contain .shp, .shx and .dbf files.')
        prj = _find(folder / 'files', 'prj')
        source_epsg = 4326
        if prj:
            text = prj.read_text(encoding='utf-8', errors='ignore')
            import re
            match = re.search(r'AUTHORITY\s*\[\s*"EPSG"\s*,\s*"(\d+)"\s*\]', text, re.I)
            if match:
                source_epsg = int(match.group(1))
            elif 'WGS_1984' in text or 'GCS_WGS_1984' in text:
                source_epsg = 4326
        reader = shapefile.Reader(str(shp))
        fields = [f[0] for f in reader.fields[1:]]
        features = []
        for shape_record in reader.iterShapeRecords():
            geom = shape_record.shape.__geo_interface__
            if geom['type'] not in {'Polygon', 'MultiPolygon'}:
                continue
            geom = _transform_geometry(geom, source_epsg)
            properties = dict(zip(fields, list(shape_record.record)))
            features.append({'type': 'Feature', 'properties': properties, 'geometry': geom})
        if not features:
            raise ValueError('The Shapefile contains no Polygon or MultiPolygon features.')
        geometry_types = {f['geometry']['type'] for f in features}
        if geometry_types == {'Polygon'}:
            merged = {'type': 'MultiPolygon', 'coordinates': [f['geometry']['coordinates'] for f in features]}
        elif geometry_types == {'MultiPolygon'}:
            merged = {'type': 'MultiPolygon', 'coordinates': [poly for f in features for poly in f['geometry']['coordinates']]}
        else:
            merged = {'type': 'MultiPolygon', 'coordinates': [f['geometry']['coordinates'] for f in features]}
        return {'type': 'FeatureCollection', 'features': features, 'geometry': merged, 'feature_count': len(features), 'source_epsg': source_epsg}
