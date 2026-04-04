"""
Google Calendar Service — CRUD d'events al Google Calendar.

Mapeig de camps:
  title           → summary
  date+start_time → start.dateTime  (Europe/Madrid)
  date+end_time   → end.dateTime    (Europe/Madrid)
  notes           → description (+ client_name / client_phone)
  id intern       → extendedProperties.private.gestor_id
"""

import logging
from google_auth import get_calendar_service, GOOGLE_CALENDAR_ID

logger = logging.getLogger(__name__)

TIMEZONE = 'Europe/Madrid'


def _build_gcal_body(event):
    """
    Construeix el body per a la Google Calendar API a partir d'un objecte Event (SQLAlchemy).
    """
    # Construir description amb info del client
    parts = []
    if event.client_name:
        parts.append(f"Client: {event.client_name}")
    if event.client_phone:
        parts.append(f"Telèfon: {event.client_phone}")
    if event.notes:
        parts.append(event.notes)
    description = '\n'.join(parts) if parts else ''

    # start / end en format ISO amb timezone
    start_dt = f"{event.date}T{event.start_time}:00"
    if event.end_time:
        end_dt = f"{event.date}T{event.end_time}:00"
    else:
        # Si no hi ha hora final, posar 1h per defecte
        end_dt = f"{event.date}T{event.start_time}:00"

    body = {
        'summary': event.title or event.service_type or 'Cita',
        'description': description,
        'start': {
            'dateTime': start_dt,
            'timeZone': TIMEZONE,
        },
        'end': {
            'dateTime': end_dt,
            'timeZone': TIMEZONE,
        },
        'extendedProperties': {
            'private': {
                'gestor_id': str(event.id),
            }
        },
    }

    # Si no hi ha end_time, fer l'event d'1 hora
    if not event.end_time:
        # Calcular +1h
        h, m = map(int, event.start_time.split(':'))
        h_end = h + 1
        if h_end >= 24:
            h_end = 23
            m = 59
        body['end']['dateTime'] = f"{event.date}T{h_end:02d}:{m:02d}:00"

    return body


def crear_event(event):
    """
    Crea un event al Google Calendar.
    Retorna el google_calendar_event_id o None si falla.
    """
    service = get_calendar_service()
    if not service:
        return None

    try:
        body = _build_gcal_body(event)
        gcal_event = service.events().insert(
            calendarId=GOOGLE_CALENDAR_ID,
            body=body,
        ).execute()

        gcal_id = gcal_event.get('id')
        logger.info(f"✅ [Google Calendar] Event creat: {gcal_id} (gestor_id={event.id})")
        return gcal_id
    except Exception as e:
        logger.error(f"❌ [Google Calendar] Error creant event (gestor_id={event.id}): {e}")
        return None


def actualitzar_event(event):
    """
    Actualitza un event existent al Google Calendar.
    Requereix que event.google_calendar_event_id estigui definit.
    Retorna True si ha anat bé, False si ha fallat.
    """
    if not event.google_calendar_event_id:
        logger.warning(f"⚠️  [Google Calendar] Event {event.id} no té google_calendar_event_id, no es pot actualitzar")
        return False

    service = get_calendar_service()
    if not service:
        return False

    try:
        body = _build_gcal_body(event)
        service.events().update(
            calendarId=GOOGLE_CALENDAR_ID,
            eventId=event.google_calendar_event_id,
            body=body,
        ).execute()

        logger.info(f"✅ [Google Calendar] Event actualitzat: {event.google_calendar_event_id}")
        return True
    except Exception as e:
        logger.error(f"❌ [Google Calendar] Error actualitzant event {event.google_calendar_event_id}: {e}")
        return False


def eliminar_event(event):
    """
    Elimina un event del Google Calendar.
    Retorna True si ha anat bé, False si ha fallat.
    """
    if not event.google_calendar_event_id:
        return True  # Res a eliminar

    service = get_calendar_service()
    if not service:
        return False

    try:
        service.events().delete(
            calendarId=GOOGLE_CALENDAR_ID,
            eventId=event.google_calendar_event_id,
        ).execute()

        logger.info(f"✅ [Google Calendar] Event eliminat: {event.google_calendar_event_id}")
        return True
    except Exception as e:
        logger.error(f"❌ [Google Calendar] Error eliminant event {event.google_calendar_event_id}: {e}")
        return False
