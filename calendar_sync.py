"""
Google Calendar Sync — Lògica de sincronització entre Gestoria i Google Calendar.

Funcions:
  sync_event_to_calendar(event, db_session) — crea o actualitza segons google_calendar_event_id
  delete_event_from_calendar(event)         — elimina del Calendar
  sync_all_future_events(app)               — sincronització massiva d'events futurs (one-time)
"""

import logging
from datetime import date
from calendar_service import crear_event, actualitzar_event, eliminar_event

logger = logging.getLogger(__name__)


def sync_event_to_calendar(event, db_session):
    """
    Sincronitza un event individual al Google Calendar.
    - Si no té google_calendar_event_id → crea'l
    - Si ja en té → actualitza'l
    Desa el google_calendar_event_id a la BD.
    """
    try:
        if event.google_calendar_event_id:
            actualitzar_event(event)
        else:
            gcal_id = crear_event(event)
            if gcal_id:
                event.google_calendar_event_id = gcal_id
                db_session.commit()
    except Exception as e:
        logger.error(f"❌ [Calendar Sync] Error sincronitzant event {event.id}: {e}")


def delete_event_from_calendar(event):
    """
    Elimina un event del Google Calendar (si estava sincronitzat).
    """
    try:
        eliminar_event(event)
    except Exception as e:
        logger.error(f"❌ [Calendar Sync] Error eliminant event {event.id} del Calendar: {e}")


def sync_all_future_events(app):
    """
    Sincronitza tots els events futurs que encara no tenen google_calendar_event_id.
    Pensat per executar-se una vegada durant la migració inicial.
    Requereix el context de l'app Flask.
    """
    from app import Event, db

    with app.app_context():
        today = date.today().isoformat()
        events = Event.query.filter(
            Event.date >= today,
            Event.google_calendar_event_id.is_(None),
        ).order_by(Event.date.asc()).all()

        logger.info(f"📅 [Calendar Sync] Sincronitzant {len(events)} events futurs...")

        synced = 0
        for ev in events:
            gcal_id = crear_event(ev)
            if gcal_id:
                ev.google_calendar_event_id = gcal_id
                synced += 1

        db.session.commit()
        logger.info(f"✅ [Calendar Sync] Sincronitzats {synced}/{len(events)} events")
        return synced
