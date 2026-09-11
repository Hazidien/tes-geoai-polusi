from pathlib import Path
import json
import os

import ee
import google.auth
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
    for path in candidates:
        if path.is_file():
            return path
    return None


def initialize_gee():
    """Initialize Earth Engine from credentials that already exist.

    This function deliberately never calls ee.Authenticate() and therefore
    never starts a new interactive verification/login flow.
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
            # First reuse the Earth Engine persistent credential, which is what
            # ee.Authenticate() stores in ~/.config/earthengine/credentials.
            # If it is unavailable, fall back to normal Google ADC.
            try:
                ee.Initialize(credentials='persistent', project=PROJECT_ID)
            except Exception as persistent_error:
                credentials, _ = google.auth.default()
                if credentials is None:
                    raise persistent_error
                ee.Initialize(credentials=credentials, project=PROJECT_ID)

        # Force a tiny authenticated request so the API reports the real
        # credential/project problem here, not later during image processing.
        ee.Number(1).getInfo()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            'Earth Engine credentials are not available to this Codespace. '
            'The application will not start a new authentication flow. '
            f'Initialization detail: {exc}'
        ) from exc
