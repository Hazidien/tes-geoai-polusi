from pathlib import Path
import os

import ee
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')

PROJECT_ID = os.getenv('GEE_PROJECT_ID', '').strip()
CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '').strip()


def _credential_path():
    """Return an already-existing service-account JSON path, if available."""
    if CREDENTIALS:
        return Path(CREDENTIALS).expanduser()

    # Keep the existing authentication setup usable even when the credential
    # path was not exported in the Codespace shell. These paths are ignored by
    # Git and are only discovered locally; no new authentication flow is used.
    candidates = [
        ROOT / '.secrets' / 'gee-service-account.json',
        ROOT / '.secrets' / 'service-account.json',
        ROOT / 'gee-service-account.json',
        ROOT / 'service-account.json',
    ]
    for path in candidates:
        if path.is_file():
            return path

    secret_dir = ROOT / '.secrets'
    if secret_dir.is_dir():
        json_files = sorted(secret_dir.glob('*.json'))
        if len(json_files) == 1:
            return json_files[0]
    return None


def initialize_gee():
    """Initialize Earth Engine without starting a new interactive login."""
    if not PROJECT_ID:
        raise RuntimeError(
            'GEE_PROJECT_ID is not configured. Set it to a Google Cloud project '
            'that has Earth Engine enabled.'
        )

    credential_path = _credential_path()
    try:
        if credential_path:
            if not credential_path.is_file():
                raise RuntimeError(
                    f'GEE credential file was not found at: {credential_path}'
                )
            credentials = ee.ServiceAccountCredentials(None, str(credential_path))
            ee.Initialize(credentials=credentials, project=PROJECT_ID)
        else:
            # Reuse Application Default Credentials when the Codespace already
            # has them. This does not invoke ee.Authenticate() or open a login.
            ee.Initialize(project=PROJECT_ID)
    except RuntimeError:
        raise
    except Exception as exc:
        if credential_path:
            raise RuntimeError(
                f'Google Earth Engine authentication failed using {credential_path}: {exc}'
            ) from exc
        raise RuntimeError(
            'Google Earth Engine is not initialized. The existing service-account '
            'credential was not found and no Application Default Credentials are '
            'available. Restore the existing GEE credential in .secrets/ or set '
            'GOOGLE_APPLICATION_CREDENTIALS; this application does not start a new '
            'interactive Earth Engine verification flow.'
        ) from exc
