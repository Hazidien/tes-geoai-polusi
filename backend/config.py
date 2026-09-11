from pathlib import Path
import os

import ee
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')

PROJECT_ID = os.getenv('GEE_PROJECT_ID', '').strip()
CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '').strip()


def initialize_gee():
    """Initialize Earth Engine using a service account or existing ADC login.

    Service-account credentials remain the preferred deployment option. In
    GitHub Codespaces, an authenticated Google ADC session can also be used so
    the WebGIS does not fail merely because GOOGLE_APPLICATION_CREDENTIALS is
    unset.
    """
    if not PROJECT_ID:
        raise RuntimeError(
            'GEE_PROJECT_ID is not configured. Set it to a Google Cloud project '
            'that has Earth Engine enabled.'
        )

    try:
        if CREDENTIALS:
            credential_path = Path(CREDENTIALS).expanduser()
            if not credential_path.is_file():
                raise RuntimeError(
                    f'GEE credential file was not found at: {credential_path}'
                )
            credentials = ee.ServiceAccountCredentials(None, str(credential_path))
            ee.Initialize(credentials=credentials, project=PROJECT_ID)
        else:
            # Fall back to Application Default Credentials (ADC), which is
            # suitable for an authenticated Codespace/gcloud environment.
            ee.Initialize(project=PROJECT_ID)
    except RuntimeError:
        raise
    except Exception as exc:
        if CREDENTIALS:
            raise RuntimeError(
                f'Google Earth Engine authentication failed: {exc}'
            ) from exc
        raise RuntimeError(
            'Google Earth Engine authentication failed. No service-account '
            'file is configured and ADC is not authenticated. Set '
            'GOOGLE_APPLICATION_CREDENTIALS or authenticate Google ADC in '
            'the Codespace.'
        ) from exc
