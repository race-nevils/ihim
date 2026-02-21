"""OAuth2 token management for Google Calendar API."""
import logging
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError, TransportError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

DATA_DIR = Path(__file__).parent.parent.parent / "data"
TOKEN_FILE = DATA_DIR / "google_token.json"
CREDS_FILE = DATA_DIR / "credentials.json"


def get_credentials() -> Optional[Credentials]:
    """Load or refresh Google OAuth2 credentials.

    Returns None if authentication is needed (no token or refresh failed).
    """
    if not TOKEN_FILE.exists():
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    except Exception as e:
        logger.warning(f"Failed to load token: {e}")
        return None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        except RefreshError as e:
            logger.error(f"Token refresh permanently failed (re-auth needed): {e}")
            return None
        except TransportError as e:
            logger.warning(f"Token refresh failed (network issue, transient): {e}")
            return None
        except Exception as e:
            logger.warning(f"Token refresh failed (unexpected): {e}")
            return None

    if creds and creds.valid:
        return creds

    return None


def start_auth_flow() -> Credentials:
    """Run interactive OAuth2 flow. Opens the system browser for consent.

    Requires credentials.json in IHIM/data/.
    Saves the resulting token to IHIM/data/google_token.json.

    Raises FileNotFoundError if credentials.json is missing.
    """
    if not CREDS_FILE.exists():
        raise FileNotFoundError(
            f"Place your Google OAuth2 credentials.json in {DATA_DIR}"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Google Calendar auth completed, token saved")
    return creds


def is_authenticated() -> bool:
    """Check if valid credentials exist."""
    return get_credentials() is not None


def revoke_auth() -> bool:
    """Delete stored token. Returns True if token existed."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        logger.info("Google Calendar token revoked")
        return True
    return False


def token_health() -> dict:
    """Read token state without triggering a refresh. For /status endpoint.

    Returns dict with token_exists, valid, expired, expiry, needs_auth.
    """
    if not TOKEN_FILE.exists():
        return {
            "token_exists": False,
            "valid": False,
            "expired": False,
            "expiry": None,
            "needs_auth": True,
        }

    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    except Exception:
        return {
            "token_exists": True,
            "valid": False,
            "expired": False,
            "expiry": None,
            "needs_auth": True,
        }

    expiry_str = creds.expiry.isoformat() if creds.expiry else None
    has_refresh = bool(creds.refresh_token)

    return {
        "token_exists": True,
        "valid": creds.valid,
        "expired": bool(creds.expired),
        "expiry": expiry_str,
        "has_refresh_token": has_refresh,
        "needs_auth": not creds.valid and not has_refresh,
    }
