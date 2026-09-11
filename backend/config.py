from pathlib import Path
import json
import os

import ee
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')

PROJECT_ID = os.getenv('GEE_PROJECT_ID', '').strip()
CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '').strip()


def _credential_path():
    if CREDENTIALS:
        return Path(CREDENTIALS).expanduser()
    candidates = [
        ROOT / '.secrets' / 'gee-service-account.json',
        ROOT / '.secrets' / 'service-account.json',
        ROOT / 'gee-service-account.json',
        ROOT / 'service-account.json',
    ]
    return next((path for path in candidates if path.is_file()), None)


def initialize_gee():
    """Initialize EE using credentials that already exist; never start OAuth."""
    if not PROJECT_ID:
        raise RuntimeError('GEE_PROJECT_ID is not configured in .env.')

    credential_path = _credential_path()
    try:
        if credential_path:
            if not credential_path.is_file():
                raise RuntimeError(f'GEE credential file was not found: {credential_path}')
            with credential_path.open('r', encoding='utf-8') as handle:
                service_account = json.load(handle).get('client_email')
            if not service_account:
                raise RuntimeError('The configured GEE service-account JSON has no client_email.')
            credentials = ee.ServiceAccountCredentials(service_account, str(credential_path))
            ee.Initialize(credentials=credentials, project=PROJECT_ID)
        else:
            # Reuse credentials already stored by the existing EE/ADC setup.
            credentials = ee.data.get_persistent_credentials()
            if credentials is None:
                raise RuntimeError(
                    'Existing Earth Engine credentials were not found. Restore the existing '
                    'credential in .secrets/ or configure GOOGLE_APPLICATION_CREDENTIALS. '
                    'No new Earth Engine verification is started by this application.'
                )
            ee.Initialize(credentials=credentials, project=PROJECT_ID)

        # Force one lightweight server request here so failures are reported at
        # initialization time instead of later as the misleading "client library
        # not initialized" message.
        ee.Number(1).getInfo()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f'Google Earth Engine initialization failed: {exc}') from exc
