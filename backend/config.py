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
        path = Path(CREDENTIALS).expanduser()
        return path if path.is_file() else None
    candidates = [
        ROOT / '.secrets' / 'gee-service-account.json',
        ROOT / '.secrets' / 'service-account.json',
        ROOT / 'gee-service-account.json',
        ROOT / 'service-account.json',
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def initialize_gee():
    """Initialize Earth Engine using credentials that already exist.

    No interactive authentication is performed here. A configured service
    account key is preferred; otherwise ee.Initialize() reuses the existing
    Earth Engine/Google credentials available in the Codespace.
    """
    if not PROJECT_ID:
        raise RuntimeError('GEE_PROJECT_ID is not configured in .env.')

    credential_path = _credential_path()
    try:
        if credential_path:
            with credential_path.open('r', encoding='utf-8') as handle:
                service_account = json.load(handle).get('client_email')
            if not service_account:
                raise RuntimeError('Configured service-account JSON has no client_email.')
            credentials = ee.ServiceAccountCredentials(service_account, str(credential_path))
            ee.Initialize(credentials=credentials, project=PROJECT_ID)
        else:
            # Reuse credentials already installed in this environment.
            # This does NOT call ee.Authenticate() and does not start a login flow.
            ee.Initialize(project=PROJECT_ID)

        # Force a tiny request so credential/project errors are reported now.
        ee.Number(1).getInfo()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            'Earth Engine is not initialized with the credentials already available '
            'to this Codespace. No new authentication flow was started. '
            f'Initialization detail: {exc}'
        ) from exc
