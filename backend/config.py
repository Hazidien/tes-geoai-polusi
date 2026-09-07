import os
from pathlib import Path

import ee
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')

PROJECT_ID = os.getenv('GEE_PROJECT_ID', '').strip()


def initialize_gee():
    """Initialize Earth Engine with the user's local/Codespaces credentials.

    Authentication is intentionally not performed inside the API process.
    Run `earthengine authenticate` once in the development environment, then
    initialize against the registered Google Cloud project.
    """
    if not PROJECT_ID:
        raise RuntimeError('GEE_PROJECT_ID is not configured. Set GEE_PROJECT_ID=tes-geoai in .env.')

    try:
        ee.Initialize(project=PROJECT_ID)
    except Exception as exc:
        raise RuntimeError(
            'Google Earth Engine authentication/initialization failed. '
            'Run `earthengine authenticate` in the development environment, '
            f'then retry. Original error: {exc}'
        ) from exc
