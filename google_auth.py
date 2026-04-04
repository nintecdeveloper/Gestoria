"""
Google Calendar OAuth2 — Inicialització del client.

Llegeix credencials des de variables d'entorn (configurades a Render):
  GOOGLE_CLIENT_ID
  GOOGLE_CLIENT_SECRET
  GOOGLE_REFRESH_TOKEN
  GOOGLE_CALENDAR_ID  (default: pau@rodonverges.com)
"""

import os
import logging
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
GOOGLE_REFRESH_TOKEN = os.environ.get('GOOGLE_REFRESH_TOKEN')
GOOGLE_CALENDAR_ID = os.environ.get('GOOGLE_CALENDAR_ID', 'pau@rodonverges.com')

SCOPES = ['https://www.googleapis.com/auth/calendar']
TOKEN_URI = 'https://oauth2.googleapis.com/token'


def _credentials_configured():
    """Retorna True si totes les credencials necessàries estan configurades."""
    return all([GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN])


def get_calendar_service():
    """
    Retorna un objecte service de Google Calendar API (v3).
    Retorna None si les credencials no estan configurades.
    """
    if not _credentials_configured():
        logger.warning("⚠️  [Google Calendar] Credencials no configurades — sincronització desactivada")
        return None

    try:
        creds = Credentials(
            token=None,
            refresh_token=GOOGLE_REFRESH_TOKEN,
            token_uri=TOKEN_URI,
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            scopes=SCOPES,
        )
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        return service
    except Exception as e:
        logger.error(f"❌ [Google Calendar] Error inicialitzant servei: {e}")
        return None
