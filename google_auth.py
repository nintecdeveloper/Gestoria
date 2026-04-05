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

GOOGLE_CALENDAR_ID = os.environ.get('GOOGLE_CALENDAR_ID', 'pau@rodonverges.com')

SCOPES = ['https://www.googleapis.com/auth/calendar']
TOKEN_URI = 'https://oauth2.googleapis.com/token'


def get_calendar_service():
    """
    Retorna un objecte service de Google Calendar API (v3).
    Retorna None si les credencials no estan configurades.

    Llegeix GOOGLE_REFRESH_TOKEN dinàmicament de os.environ
    per detectar canvis fets pel flow OAuth web (/auth/google/callback).
    """
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    refresh_token = os.environ.get('GOOGLE_REFRESH_TOKEN')

    if not all([client_id, client_secret, refresh_token]):
        logger.warning("⚠️  [Google Calendar] Credencials no configurades — sincronització desactivada")
        return None

    try:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=TOKEN_URI,
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        return service
    except Exception as e:
        logger.error(f"❌ [Google Calendar] Error inicialitzant servei: {e}")
        return None
