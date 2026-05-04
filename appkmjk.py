import os
import json
from flask import Flask, render_template, jsonify, request, send_file, session, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime, timedelta
from dateutil.rrule import rrulestr
from sqlalchemy import text, func
from io import BytesIO
import io
import requests
import logging
import base64
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import smtplib, ssl, secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

# ═══════════════════════════════════════════════════════════════
# WEB PUSH — pywebpush + VAPID keys
# ═══════════════════════════════════════════════════════════════
try:
    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    _vapid_priv_env = os.environ.get('VAPID_PRIVATE_KEY', '')
    _vapid_pub_env  = os.environ.get('VAPID_PUBLIC_KEY',  '')

    if _vapid_priv_env and _vapid_pub_env:
        VAPID_PRIVATE_KEY = _vapid_priv_env.strip()
        VAPID_PUBLIC_KEY  = _vapid_pub_env.strip()
        print(f"[Push] Claus VAPID carregades des de l'entorn. "
              f"PUBLIC_KEY (20c): {VAPID_PUBLIC_KEY[:20]}…", flush=True)
    else:
        # Auto-genera claus si no estan definides a l'entorn
        _v = Vapid()
        _v.generate_keys()
        VAPID_PRIVATE_KEY = _v.private_pem().decode('utf-8')
        _pub_bytes        = _v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        VAPID_PUBLIC_KEY  = base64.urlsafe_b64encode(_pub_bytes).rstrip(b'=').decode('ascii')
        print(f"\n⚠️  VAPID keys auto-generades (no persistents). Afegeix a l'entorn:\n"
              f"  VAPID_PUBLIC_KEY={VAPID_PUBLIC_KEY}\n"
              f"  VAPID_PRIVATE_KEY={VAPID_PRIVATE_KEY}\n", flush=True)

    # Genera i mostra un parell de claus de referència vàlid a cada arrencada
    _ref = Vapid()
    _ref.generate_keys()
    _ref_pub = base64.urlsafe_b64encode(
        _ref.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    ).rstrip(b'=').decode('ascii')
    _ref_priv = _ref.private_pem().decode('utf-8')
    print(f"\n[Push] Claus de referència generades (còpia per a Render si cal):\n"
          f"  VAPID_PUBLIC_KEY={_ref_pub}\n"
          f"  VAPID_PRIVATE_KEY={_ref_priv}\n", flush=True)

    VAPID_SUBJECT    = os.environ.get('VAPID_SUBJECT', 'mailto:info.nexorasolutionsai@gmail.com')
    WEBPUSH_AVAILABLE = True
except ImportError:
    WEBPUSH_AVAILABLE = False
    VAPID_PUBLIC_KEY = VAPID_PRIVATE_KEY = VAPID_SUBJECT = None
    print("⚠️  pywebpush no disponible. Web Push desactivat. Executa: pip install pywebpush", flush=True)
# ═══════════════════════════════════════════════════════════════
# LOGGING — CONFIGURACIÓN INMEDIATA
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# META WHATSAPP API — CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════
META_AVAILABLE = True
REQUESTS_AVAILABLE = True

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.date import DateTrigger
    import pytz
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    print("⚠️  [Scheduler] APScheduler no instalado. pip install apscheduler para activarlo.")

META_PHONE_NUMBER_ID = os.environ.get('META_PHONE_NUMBER_ID', None)
META_ACCESS_TOKEN = os.environ.get('META_ACCESS_TOKEN', None)
META_BUSINESS_ACCOUNT_ID = os.environ.get('META_BUSINESS_ACCOUNT_ID', None)
META_WABA_ID             = os.environ.get('META_WABA_ID', None)

GMAIL_USER         = os.environ.get('GMAIL_USER')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')
META_API_VERSION = "v18.0"
META_API_URL = f"https://graph.facebook.com/{META_API_VERSION}/{{phone_id}}/messages"

# ═══════════════════════════════════════════════════════════════
# EMAIL — GMAIL SMTP
# ═══════════════════════════════════════════════════════════════

def send_email(to_email, subject, html_body):
    try:
        gmail_user     = os.environ.get('GMAIL_USER', '').strip().replace('\xa0', '').replace('\u00a0', '')
        gmail_password = os.environ.get('GMAIL_APP_PASSWORD', '').strip().replace('\xa0', '').replace('\u00a0', '')
        if not gmail_user or not gmail_password:
            logger.warning("GMAIL_USER o GMAIL_APP_PASSWORD no configurats")
            return False
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = gmail_user
        msg['To']      = to_email.strip()
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_password)
            server.send_message(msg)
        logger.info(f"Email enviat a {to_email}")
        return True
    except Exception as e:
        logger.error(f"Error email: {e}")
        return False

# ═══════════════════════════════════════════════════════════════
# USUARIOS Y CALENDARIOS — DATOS INICIALES
# ═══════════════════════════════════════════════════════════════

USUARIOS = [
    {'id': 1, 'nombre': 'Antonio', 'departamento': 'admin', 'email': 'antonio@rodonverges.com', 'rol': 'admin', 'sede': 'Mataró'},
    {'id': 3, 'nombre': 'Pau', 'departamento': 'admin', 'email': 'pau@rodonverges.com', 'rol': 'admin', 'sede': 'Vilassar'},
    {'id': 2, 'nombre': 'Myriam', 'departamento': 'laboral', 'email': 'myriam@rodonverges.com', 'rol': 'user', 'sede': 'Vilassar'},
    {'id': 4, 'nombre': 'Montse Martín', 'departamento': 'laboral', 'email': 'montse@rodonverges.com', 'rol': 'user', 'sede': 'Mataró'},
    {'id': 5, 'nombre': 'Anna Fabregà', 'departamento': 'fiscal', 'email': 'anna@rodonverges.com', 'rol': 'user', 'sede': 'Vilassar'},
]

CALENDARIOS = {
    'personales': [
        {'id': 1, 'usuario_id': 1, 'usuario': 'Antonio', 'nombre': 'Mi calendario personal'},
        {'id': 2, 'usuario_id': 2, 'usuario': 'Myriam', 'nombre': 'Mi calendario personal'},
        {'id': 4, 'usuario_id': 4, 'usuario': 'Montse Martín', 'nombre': 'Mi calendario personal'},
        {'id': 5, 'usuario_id': 5, 'usuario': 'Anna Fabregà', 'nombre': 'Mi calendario personal'},
    ],
    'departamentales': [
        {'id': 101, 'nombre': 'Calendario Laboral', 'tipo': 'laboral', 'departamento': 'laboral'},
        {'id': 102, 'nombre': 'Calendario Fiscal', 'tipo': 'fiscal', 'departamento': 'fiscal'},
        {'id': 103, 'nombre': 'Calendario Mercantil', 'tipo': 'mercantil', 'departamento': 'mercantil'},
    ]
}
# ═══════════════════════════════════════════════════════════════
# UTILS — GENERACIÓ AUTOMÀTICA DE CONTRASENYES
# ═══════════════════════════════════════════════════════════════

import re

def generar_password_username(username: str) -> str:
    """
    Genera una contrasenya automàtica a partir del username:
    - Elimina '_' i qualsevol símbol que no sigui lletra o número
    - Posa la primera lletra en majúscula
    - Afegeix '123!' al final
    Exemples:
      'antonio'  → 'Antonio123!'
      'anna_f'   → 'Annaf123!'
      'anna_m'   → 'Annam123!'
    """
    net = re.sub(r'[^a-zA-Z0-9]', '', username)  # elimina '_' i símbols
    if not net:
        return 'User123!'
    password = net[0].upper() + net[1:].lower() + '123!'
    return password
# ═══════════════════════════════════════════════════════════════
# WHATSAPP — FUNCIONES DE ENVÍO
# ═══════════════════════════════════════════════════════════════

def send_whatsapp_meta(to_phone: str, message: str = '',
                       message_type: str = "text",
                       use_template: bool = False,
                       nom: str = '', data: str = '', hora: str = '', seu: str = ''):
    """Envía un mensaje de WhatsApp via Meta Cloud API.

    Si use_template=True usa la plantilla aprovada 'nom_recordatori_cita' (ca)
    amb 4 variables: {{1}}=nom, {{2}}=data, {{3}}=hora, {{4}}=seu.
    Si use_template=False (per defecte) envia text lliure.
    """
    if not META_PHONE_NUMBER_ID or not META_ACCESS_TOKEN:
        return {'ok': False, 'error': 'Credenciales Meta no configuradas.', 'configured': False}
    phone = to_phone.strip()
    if not phone.startswith('+'): phone = '+34' + phone.lstrip('0')

    waba_id = META_WABA_ID or META_BUSINESS_ACCOUNT_ID or ''
    logger.info(f"[Meta API] phone_number_id={META_PHONE_NUMBER_ID} | waba_id={waba_id} | to={phone} | use_template={use_template}")

    if use_template:
        payload = {
            "messaging_product": "whatsapp",
            "to": phone.replace('+', ''),
            "type": "template",
            "template": {
                "name": "nom_recordatori_cita",
                "language": {"code": "ca"},
                "components": [{
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": nom},
                        {"type": "text", "text": data},
                        {"type": "text", "text": hora},
                        {"type": "text", "text": seu},
                    ]
                }]
            }
        }
        if waba_id:
            payload["waba_id"] = waba_id
    elif message_type == "text":
        payload = {"messaging_product": "whatsapp", "to": phone.replace('+', ''),
                   "type": "text", "text": {"preview_url": False, "body": message}}
    else:
        payload = {"messaging_product": "whatsapp", "to": phone.replace('+', ''),
                   "type": "template", "template": {"name": message_type, "language": {"code": "es_ES"}}}

    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}", "Content-Type": "application/json"}
    url = META_API_URL.format(phone_id=META_PHONE_NUMBER_ID)
    response = requests.post(url, json=payload, headers=headers, timeout=10)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        try:
            error_detail = response.json()
        except Exception:
            error_detail = response.text
        logger.error(f"❌ [Meta API] Error: {e} | Detall: {error_detail}")
        return {'ok': False, 'error': str(e), 'detail': error_detail}
    result = response.json()
    logger.info(f"✅ [Meta API] Missatge enviat a {phone}")
    return {'ok': True, 'message_id': result.get('messages', [{}])[0].get('id'), 'phone': phone}


def send_whatsapp_twilio(to_phone: str, nom: str, data: str, hora: str, seu: str) -> bool:
    """Adaptador: prepara les 4 variables de la plantilla i crida send_whatsapp_meta().
    Retorna True si l'enviament ha tingut èxit, False en cas d'error.
    """
    # Normalitzar telèfon: assegurar prefix internacional
    phone = to_phone.strip()
    if not phone.startswith('+'):
        phone = '+34' + phone.lstrip('0')

    # Formatar data: YYYY-MM-DD → "Dilluns 28/04/2026" per a la variable {{2}}
    DIES_CA = ['Dilluns','Dimarts','Dimecres','Dijous','Divendres','Dissabte','Diumenge']
    try:
        _d = datetime.strptime(data, '%Y-%m-%d')
        dia_setmana = DIES_CA[_d.weekday()]
        data_fmt    = _d.strftime('%d/%m/%Y')
    except Exception:
        dia_setmana = ''
        data_fmt    = data

    data_var = f"{dia_setmana} {data_fmt}".strip()

    result = send_whatsapp_meta(
        phone,
        use_template = True,
        nom  = nom,
        data = data_var,
        hora = hora,
        seu  = seu,
    )
    if result.get('ok'):
        logger.info(f"✅ [WA] Recordatori enviat a {phone}")
        return True
    else:
        logger.error(f"❌ [WA] Error enviant recordatori: {result.get('error')}")
        return False

# ═══════════════════════════════════════════════════════════════
# SCHEDULER — FUNCIONES
# ═══════════════════════════════════════════════════════════════

def send_whatsapp_job(to_phone: str, nom: str, data: str, hora: str, seu: str, job_id: str):
    """Envia un recordatori WhatsApp via plantilla aprovada i marca el job com a enviat a la BD."""
    with app.app_context():
        ok = send_whatsapp_twilio(to_phone, nom=nom, data=data, hora=hora, seu=seu)

        # Marcar sent=True a la BD
        try:
            job_rec = WaScheduledJob.query.filter_by(job_id=job_id).first()
            if job_rec:
                job_rec.sent = True
                db.session.commit()
        except Exception as _db_err:
            logger.error(f"[WaJob] Error marcant sent=True job {job_id}: {_db_err}")
            db.session.rollback()

        if ok:
            logger.info(f"✅ [Scheduler] Recordatori WA enviat a {to_phone} (job: {job_id})")
        else:
            logger.error(f"❌ [Scheduler] Error enviant recordatori WA a {to_phone} (job: {job_id})")

        # Notificar usuaris connectats
        socketio.emit(
            'notification_received',
            {
                'type':      'reminder',
                'title':     'Recordatori de cita',
                'message':   f'Recordatori enviat a {nom}',
                'timestamp': datetime.now().isoformat(),
            },
            broadcast=True
        )

def recover_pending_jobs():
    """Recupera i re-programa els jobs WA pendents (sent=False) després d'un restart.
    - send_at > ara  → re-afegeix a APScheduler amb DateTrigger
    - send_at <= ara → envia immediatament en thread separat
    """
    if not SCHEDULER_AVAILABLE or not scheduler:
        return
    with app.app_context():
        try:
            madrid   = pytz.timezone('Europe/Madrid')
            now_utc  = datetime.utcnow()
            pending  = WaScheduledJob.query.filter_by(sent=False).all()
            if not pending:
                logger.info("🔄 [Recover] Cap job WA pendent.")
                return

            recovered  = 0
            sent_now   = 0

            for job_rec in pending:
                send_at_naive = job_rec.send_at   # TIMESTAMP sense tz a la BD
                # Comparar en UTC (la BD guarda UTC per defecte amb datetime.utcnow)
                if send_at_naive > now_utc:
                    # Job futur: re-programar
                    send_at_tz = madrid.localize(send_at_naive) if send_at_naive.tzinfo is None else send_at_naive
                    try:
                        scheduler.add_job(
                            func         = send_whatsapp_job,
                            trigger      = DateTrigger(run_date=send_at_tz),
                            args         = [job_rec.phone, job_rec.nom, job_rec.data,
                                            job_rec.hora, job_rec.seu, job_rec.job_id],
                            id           = job_rec.job_id,
                            replace_existing = True,
                        )
                        recovered += 1
                        logger.info(f"🔄 [Recover] Re-programat: {job_rec.job_id} → {send_at_naive.isoformat()}")
                    except Exception as _sched_err:
                        logger.error(f"❌ [Recover] Error re-programant {job_rec.job_id}: {_sched_err}")
                else:
                    # Job passat no enviat: enviar ara en thread separat
                    def _send_missed(rec):
                        ok = send_whatsapp_twilio(rec.phone, nom=rec.nom, data=rec.data,
                                                  hora=rec.hora, seu=rec.seu)
                        with app.app_context():
                            try:
                                r = WaScheduledJob.query.filter_by(job_id=rec.job_id).first()
                                if r:
                                    r.sent = True
                                    db.session.commit()
                            except Exception as _e:
                                logger.error(f"[Recover] Error marcant sent job {rec.job_id}: {_e}")
                                db.session.rollback()
                        if ok:
                            logger.info(f"✅ [Recover] Enviat (retardat): {rec.job_id}")
                        else:
                            logger.error(f"❌ [Recover] Error enviant (retardat): {rec.job_id}")

                    threading.Thread(target=_send_missed, args=(job_rec,), daemon=True).start()
                    sent_now += 1

            logger.info(f"🔄 [Recover] {recovered} jobs re-programats, {sent_now} enviats immediatament.")

            # Recordatoris personals passats no enviats
            try:
                pending_past = PersonalReminder.query.filter(
                    PersonalReminder.is_sent == False,
                    PersonalReminder.remind_at <= datetime.utcnow()
                ).all()
                for r in pending_past:
                    send_push_notification(r.user_id, 'Recordatori de cita', r.message or 'Tens una cita pròximament')
                    r.is_sent = True
                if pending_past:
                    db.session.commit()
                    logger.info(f"🔄 [Recover] {len(pending_past)} recordatoris personals enviats en arrencada")
            except Exception as _re:
                logger.error(f"❌ [Recover] Error enviant recordatoris personals: {_re}")
                db.session.rollback()

        except Exception as _e:
            logger.error(f"❌ [Recover] Error en recover_pending_jobs: {_e}")


def create_seat_chats(user_id, user_name, user_sede):
    """Crea automáticamente los chats de sede cuando se añade un usuario."""
    try:
        logger.info(f"📱 [Chats Sede] Creando chats para {user_name} en {user_sede}")
        
        # Crear chat de sede si no existe
        seat_chat_id = f"seat_{user_sede.lower()}"
        if seat_chat_id not in message_storage:
            message_storage[seat_chat_id] = []
            logger.info(f"✅ [Chat Sede] Creado: {seat_chat_id}")
        
        # Crear chats individuales con otros usuarios de la misma sede
        same_sede_users = [u for u in USUARIOS if u.get('sede') == user_sede or u['departamento'] == 'admin']
        
        for other_user in same_sede_users:
            if other_user['id'] != user_id:
                conv_id = f"{user_name}_{other_user['nombre']}"
                if conv_id not in message_storage:
                    message_storage[conv_id] = []
                    logger.info(f"✅ [Chat Individual] Creado: {conv_id}")
                    
                # También crear en orden inverso
                conv_id_inv = f"{other_user['nombre']}_{user_name}"
                if conv_id_inv not in message_storage:
                    message_storage[conv_id_inv] = []
        
    except Exception as e:
        logger.error(f"❌ Error al crear chats de sede: {str(e)}")

# ═══════════════════════════════════════════════════════════════
# INICIALIZAR FLASK Y SOCKETIO
# ═══════════════════════════════════════════════════════════════

app = Flask(__name__, template_folder='templates')
app.config['ENV'] = os.environ.get('FLASK_ENV', 'production')
app.config['DEBUG'] = False if app.config['ENV'] == 'production' else True
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB màxim per request
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'

# ═══════════════════════════════════════════════════════════════
# SQLALCHEMY — CONFIGURACIÓ I MODEL EVENT
# ═══════════════════════════════════════════════════════════════
_db_url = os.environ.get('DATABASE_URL', '')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url if _db_url else 'sqlite:///events.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Event(db.Model):
    __tablename__ = 'events'
    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title         = db.Column(db.String(200), nullable=True)
    date          = db.Column(db.String(10))
    start_time    = db.Column(db.String(5))
    end_time      = db.Column(db.String(5),   nullable=True)
    client_name   = db.Column(db.String(200), nullable=True)
    client_phone  = db.Column(db.String(50),  nullable=True)
    assigned_to   = db.Column(db.Integer)
    created_by    = db.Column(db.Integer)
    calendar_type = db.Column(db.String(50),  nullable=True)
    sede          = db.Column(db.String(50),  nullable=True)
    department    = db.Column(db.String(50),  nullable=True)
    service_type  = db.Column(db.String(100), nullable=True)
    notes         = db.Column(db.String(1000),nullable=True)
    is_private    = db.Column(db.Boolean,     default=False)
    wa_reminder          = db.Column(db.String(500),  nullable=True)   # JSON string
    pr_reminder          = db.Column(db.String(1000), nullable=True)   # JSON string
    created_at           = db.Column(db.DateTime,     default=datetime.utcnow)
    # Recurrència
    recurrence_rule      = db.Column(db.String(500),  nullable=True)   # RRULE string, p.ex. FREQ=WEEKLY;BYDAY=MO
    recurrence_master_id = db.Column(db.Integer,      nullable=True)   # FK manual a l'event pare
    is_recurring_master  = db.Column(db.Boolean,      default=False)   # True si és el pare

    def to_dict(self):
        return {
            'id':                  self.id,
            'ownerId':             self.created_by,
            'assignedTo':          self.assigned_to,
            'date':                self.date,
            'time':                self.start_time,
            'timeEnd':             self.end_time,
            'client':              self.client_name or '',
            'service':             self.service_type or '',
            'notes':               self.notes or '',
            'private':             bool(self.is_private),
            'clientPhone':         self.client_phone,
            'calendarType':        self.calendar_type,
            'sede':                self.sede,
            'department':          self.department,
            'waReminder':          json.loads(self.wa_reminder) if self.wa_reminder else None,
            'prReminders':         json.loads(self.pr_reminder) if self.pr_reminder else [],
            'recurrenceRule':      self.recurrence_rule,
            'recurrenceMasterId':  self.recurrence_master_id,
            'isRecurringMaster':   bool(self.is_recurring_master) if self.is_recurring_master is not None else False,
        }

class PersonalReminder(db.Model):
    __tablename__ = 'personal_reminders'
    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    event_id   = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=True)
    user_id    = db.Column(db.Integer, nullable=False)
    remind_at  = db.Column(db.DateTime, nullable=False)
    message    = db.Column(db.String(500), nullable=True)
    is_sent    = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':        self.id,
            'eventId':   self.event_id,
            'userId':    self.user_id,
            'remindAt':  self.remind_at.isoformat() if self.remind_at else None,
            'message':   self.message,
            'isSent':    bool(self.is_sent),
            'createdAt': self.created_at.isoformat() if self.created_at else None,
        }

class Message(db.Model):
    """Missatges de xat persistits a PostgreSQL.
    Substitueix message_storage (dict en memòria) per funcionar correctament
    amb múltiples workers de Gunicorn a Render.
    """
    __tablename__ = 'messages'
    pk                 = db.Column(db.Integer, primary_key=True, autoincrement=True)
    msg_id             = db.Column(db.String(200), nullable=False, index=True)
    conv_id            = db.Column(db.String(300), nullable=False, index=True)
    sender_id          = db.Column(db.Integer,     nullable=True)
    sender_username    = db.Column(db.String(200), nullable=True)
    recipient_username = db.Column(db.String(200), nullable=True)
    text               = db.Column(db.Text,        nullable=True)
    msg_timestamp      = db.Column(db.String(50),  nullable=True)   # ISO string
    attachments_json   = db.Column(db.Text,        nullable=True)   # JSON
    sede_key           = db.Column(db.String(50),  nullable=True)
    sede               = db.Column(db.String(100), nullable=True)
    created_at         = db.Column(db.DateTime,    default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':                 self.msg_id,
            'sender_id':          self.sender_id,
            'sender_username':    self.sender_username,
            'recipient_username': self.recipient_username or '',
            'text':               self.text or '',
            'timestamp':          self.msg_timestamp,
            'attachments':        json.loads(self.attachments_json) if self.attachments_json else [],
            'sede_key':           self.sede_key,
            'sede':               self.sede,
        }

class LastRead(db.Model):
    """Guarda l'últim missatge llegit per cada usuari i conversa.
    Permet calcular unread counts persistents entre sessions i workers.
    """
    __tablename__ = 'last_read'
    id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(200), nullable=False)
    conv_id  = db.Column(db.String(300), nullable=False)
    last_pk  = db.Column(db.Integer,     nullable=False, default=0)
    __table_args__ = (
        db.UniqueConstraint('username', 'conv_id', name='uq_lastread_user_conv'),
    )

class PushSubscription(db.Model):
    """Subscripcions Web Push per usuari (un usuari pot tenir múltiples dispositius)."""
    __tablename__ = 'push_subscriptions'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    endpoint   = db.Column(db.Text, nullable=False, unique=True)
    p256dh     = db.Column(db.Text, nullable=False)
    auth       = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Service(db.Model):
    __tablename__ = 'services'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    color      = db.Column(db.String(20), default='#f0c080')
    active     = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':    self.id,
            'name':  self.name,
            'color': self.color,
        }

class WaScheduledJob(db.Model):
    """Persisteix els recordatoris WhatsApp programats per poder-los recuperar en restart."""
    __tablename__ = 'wa_scheduled_jobs'
    id         = db.Column(db.Integer, primary_key=True)
    job_id     = db.Column(db.String(100), unique=True, nullable=False)
    event_id   = db.Column(db.Integer, nullable=True)
    phone      = db.Column(db.String(20),  nullable=False)
    nom        = db.Column(db.String(200), nullable=False)
    data       = db.Column(db.String(20),  nullable=False)
    hora       = db.Column(db.String(10),  nullable=False)
    seu        = db.Column(db.String(100), nullable=False)
    send_at    = db.Column(db.DateTime,    nullable=False)
    sent       = db.Column(db.Boolean,     default=False)
    created_at = db.Column(db.DateTime,    default=datetime.utcnow)

class DeptPermission(db.Model):
    """Persisteix els permisos d'accés als calendaris departamentals (laboral/fiscal/mercantil)."""
    __tablename__ = 'dept_permissions'
    dept            = db.Column(db.String(50), primary_key=True)
    level           = db.Column(db.Integer, nullable=False, default=2)
    access_to_depts = db.Column(db.Text, nullable=False, default='[]')  # JSON array

class User(db.Model):
    __tablename__ = 'users'
    id                   = db.Column(db.Integer, primary_key=True)
    username             = db.Column(db.String(100), unique=True, nullable=False)
    password_hash        = db.Column(db.String(255), nullable=False)
    name                 = db.Column(db.String(200), nullable=False)
    email                = db.Column(db.String(200), unique=True, nullable=True)
    phone                = db.Column(db.String(50),  nullable=True)
    role                 = db.Column(db.String(50),  default='user')
    sede                 = db.Column(db.String(100), nullable=True)
    departamento         = db.Column(db.String(100), nullable=True)
    color                = db.Column(db.String(50),  nullable=True)
    active               = db.Column(db.Boolean,     default=True)
    email_verified       = db.Column(db.Boolean,     default=False)
    must_change_password = db.Column(db.Boolean,     default=True)
    reset_token          = db.Column(db.String(100), nullable=True)
    reset_token_expires  = db.Column(db.DateTime,    nullable=True)
    created_at           = db.Column(db.DateTime,    default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':                   self.id,
            'username':             self.username,
            'name':                 self.name,
            'email':                self.email or '',
            'phone':                self.phone or '',
            'role':                 self.role,
            'sede':                 self.sede or '',
            'departamento':         self.departamento or '',
            'color':                self.color or 'teal',
            'active':               bool(self.active),
            'email_verified':       bool(self.email_verified),
            'must_change_password': bool(self.must_change_password),
        }

# ═══════════════════════════════════════════════════════════════
# LOGIN REQUIRED — Decorador d'autenticació
# ═══════════════════════════════════════════════════════════════

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({'error': 'Autenticació requerida'}), 401
        return f(*args, **kwargs)
    return decorated

import uuid
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def private_conv_id(name_a: str, name_b: str) -> str:
    """Retorna un conv_id normalitzat per ordre alfabètic per a xats privats.
    Garanteix que private_A_B i private_B_A sempre produeixen el mateix ID.
    """
    a, b = (name_a or '').strip(), (name_b or '').strip()
    first, second = (a, b) if a.lower() <= b.lower() else (b, a)
    return f"private_{first}_{second}"

# ═══════════════════════════════════════════════════════════════
# SEED USUARIS — Migrar usuaris inicials del HTML a PostgreSQL
# ═══════════════════════════════════════════════════════════════

SEED_USERS = [
    {'id': 1,  'username': 'antonio',    'password': 'admin123',      'name': 'Antonio',           'role': 'admin',    'email': 'antonio@rodonverges.com',    'phone': '+34 93 000 00 01', 'sede': 'Mataró',   'departamento': None,          'color': 'teal'},
    {'id': 3,  'username': 'pau',         'password': 'pau123',        'name': 'Pau',               'role': 'admin',    'email': 'pau@rodonverges.com',        'phone': '+34 93 000 00 03', 'sede': 'Vilassar', 'departamento': None,          'color': 'orange'},
    {'id': 10, 'username': 'myriam',      'password': 'Myriam123',     'name': 'Myriam Recolons',   'role': 'empleado', 'email': 'myriam@rodonverges.com',     'phone': '+34 93 000 00 10', 'sede': 'Mataró',   'departamento': 'laboral',     'color': 'blue'},
    {'id': 11, 'username': 'anna_f',      'password': 'Anna123',       'name': 'Anna Fabregà',      'role': 'empleado', 'email': 'anna.f@rodonverges.com',     'phone': '+34 93 000 00 11', 'sede': 'Mataró',   'departamento': 'fiscal',      'color': 'purple'},
    {'id': 12, 'username': 'montse',      'password': 'Montse123',     'name': 'Montse Martín',     'role': 'empleado', 'email': 'montse@rodonverges.com',     'phone': '+34 93 000 00 12', 'sede': 'Mataró',   'departamento': 'mercantil',   'color': 'pink'},
    {'id': 20, 'username': 'cristina',    'password': 'Cristina123',   'name': 'Cristina Navas',    'role': 'empleado', 'email': 'cristina@rodonverges.com',   'phone': '+34 93 000 00 20', 'sede': 'Vilassar', 'departamento': 'fiscal',      'color': 'green'},
    {'id': 21, 'username': 'anna_l',      'password': 'Anna123',       'name': 'Anna Llinas',       'role': 'empleado', 'email': 'anna.l@rodonverges.com',     'phone': '+34 93 000 00 21', 'sede': 'Vilassar', 'departamento': 'laboral',     'color': 'cyan'},
    {'id': 22, 'username': 'anna_m',      'password': 'Anna123',       'name': 'Anna Maria Rodón',  'role': 'empleado', 'email': 'anna.m@rodonverges.com',     'phone': '+34 93 000 00 22', 'sede': 'Vilassar', 'departamento': 'mercantil',   'color': 'yellow'},
    {'id': 23, 'username': 'vanessa',     'password': 'Vanessa123',    'name': 'Vanessa Culebras',  'role': 'empleado', 'email': 'vanessa@rodonverges.com',    'phone': '+34 93 000 00 23', 'sede': 'Vilassar', 'departamento': 'laboral',     'color': 'red'},
    {'id': 24, 'username': 'montserrat',  'password': 'Montserrat123', 'name': 'Montserrat Mir',    'role': 'empleado', 'email': 'montserrat@rodonverges.com', 'phone': '+34 93 000 00 24', 'sede': 'Vilassar', 'departamento': 'fiscal',      'color': 'brown'},
]

def seed_users():
    """Migra els usuaris inicials a la taula users si està buida. S'executa una sola vegada."""
    if User.query.count() > 0:
        return
    for u in SEED_USERS:
        user = User(
            id=u['id'],
            username=u['username'],
            password_hash=generate_password_hash(u['password']),
            name=u['name'],
            role=u['role'],
            email=u['email'],
            phone=u['phone'],
            sede=u['sede'],
            departamento=u['departamento'],
            color=u['color'],
            active=True,
            email_verified=False,
            must_change_password=True,
        )
        db.session.add(user)
    db.session.commit()
    try:
        db.session.execute(db.text("SELECT setval('users_id_seq', (SELECT MAX(id) FROM users))"))
        db.session.commit()
    except Exception:
        pass
    logger.info(f"✅ [Seed] {len(SEED_USERS)} usuaris migrats a la BD amb must_change_password=True")

def seed_services():
    """Insereix els serveis inicials si la taula és buida."""
    if Service.query.count() > 0:
        return
    serveis_inicials = [
        {'name': 'Assessorament Fiscal',   'color': '#f0c080'},
        {'name': 'Gestió Laboral',          'color': '#a8d8a8'},
        {'name': 'Assessorament Mercantil', 'color': '#a8c8f0'},
        {'name': 'Gestió Comptable',        'color': '#f0a8a8'},
        {'name': 'Assessorament Jurídic',   'color': '#d4a8f0'},
        {'name': 'Altres serveis',          'color': '#c0c0c0'},
    ]
    for s in serveis_inicials:
        db.session.add(Service(name=s['name'], color=s['color']))
    db.session.commit()
    logger.info(f"✅ [Seed] {len(serveis_inicials)} serveis inicials inserits")


def generate_reset_token(user) -> str:
    """Genera un token de reset i el guarda a l'usuari. Retorna el token."""
    token = secrets.token_urlsafe(32)
    user.reset_token         = token
    user.reset_token_expires = datetime.utcnow() + timedelta(hours=24)
    db.session.commit()
    return token

# ═══════════════════════════════════════════════════════════════
# BEFORE REQUEST — Protecció global de les rutes /api/*
# ═══════════════════════════════════════════════════════════════

EXEMPTED_PATHS = {
    '/api/auth/login',
    '/api/auth/logout',
    '/api/auth/me',
    '/api/auth/change-password',
    '/api/auth/forgot-password',
    '/api/auth/resend-verification',
    '/api/health',
    '/api/status',
    '/api/whatsapp/webhook',
    '/api/push/vapid-public-key',
}

@app.before_request
def check_auth():
    """Verifica autenticació per a totes les rutes /api/* excepte les exempcions."""
    if request.path.startswith('/api/') and request.path not in EXEMPTED_PATHS:
        if not session.get('user_id'):
            return jsonify({'error': 'Autenticació requerida'}), 401
    return None

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    async_mode='threading'
)

# Rate limiting — protecció contra brute force
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[],          # sense límit global; s'aplica per endpoint
    storage_uri="memory://",
)

# ═══════════════════════════════════════════════════════════════
# ALMACENAMIENTO GLOBAL — ESTRUCTURA CLARA
# ═══════════════════════════════════════════════════════════════

# Usuarios conectados en tiempo real
connected_users = {}  # {sid: {username, sid, sede, rol, connected_at}}
username_to_sid = {}  # {username: sid}
user_to_sede = {}     # {sid: sede}

# ═══════════════════════════════════════════════════════════════
# PERSISTÈNCIA — Guardar i carregar missatges en fitxer JSON
# ═══════════════════════════════════════════════════════════════
import threading

STORAGE_FILE = os.path.join(os.path.dirname(__file__), 'messages_data.json')
_storage_lock = threading.Lock()

def load_message_storage():
    """Carrega els missatges des del fitxer JSON."""
    default = {
        'general': [],
        'sede_mataro': [],
        'sede_vilassar': [],
    }
    try:
        if os.path.exists(STORAGE_FILE):
            with open(STORAGE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Assegurar que les claus base existeixen
            for key in ['general', 'sede_mataro', 'sede_vilassar']:
                if key not in data:
                    data[key] = []
            logger.info(f"✅ [Persistència] Missatges carregats: {sum(len(v) for v in data.values())} total")
            return data
    except Exception as e:
        logger.warning(f"⚠️ [Persistència] No s'han pogut carregar missatges: {e}")
    return default

def save_message_storage():
    """Guarda els missatges al fitxer JSON (thread-safe)."""
    try:
        with _storage_lock:
            with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
                json.dump(message_storage, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"⚠️ [Persistència] No s'han pogut guardar missatges: {e}")

# ALMACENAMIENTO DE MENSAJES — carregat des de fitxer
message_storage = load_message_storage()

# ═══════════════════════════════════════════════════════════════
# API AUTH — Autenticació amb sessions Flask
# ═══════════════════════════════════════════════════════════════

@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("5 per 2 minutes")
def auth_login():
    data     = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': 'Credencials incorrectes'}), 401

    user = User.query.filter_by(username=username, active=True).first()

    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Credencials incorrectes'}), 401

    if user.must_change_password:
        logger.info(f"[Login] {username} → must_change_password")
        return jsonify({'must_change_password': True, 'user_id': user.id}), 200

    session['user_id'] = user.id
    session.permanent = True
    logger.info(f"✅ [Login] {username} autenticat (id={user.id})")
    return jsonify({'ok': True, 'user': user.to_dict()})

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({'error': 'Massa intents. Torna a provar en 2 minuts.'}), 429

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'No autenticat'}), 401
    user = User.query.get(user_id)
    if not user or not user.active:
        session.clear()
        return jsonify({'error': 'No autenticat'}), 401
    return jsonify({'ok': True, 'user': user.to_dict()})

@app.route('/api/auth/change-password', methods=['POST'])
def auth_change_password():
    data             = request.get_json(silent=True) or {}
    user_id          = data.get('user_id')
    new_password     = data.get('new_password', '')
    confirm_password = data.get('confirm_password', '')

    if not user_id:
        return jsonify({'error': 'user_id requerit'}), 400
    if new_password != confirm_password:
        return jsonify({'error': 'Les contrasenyes no coincideixen'}), 400
    if len(new_password) < 8:
        return jsonify({'error': 'La contrasenya ha de tenir mínim 8 caràcters'}), 400

    # Comprovar autorització: admin pot canviar qualsevol, usuari només la seva
    session_user_id = session.get('user_id')
    if session_user_id:
        caller = User.query.get(session_user_id)
        if caller and caller.role != 'admin' and caller.id != int(user_id):
            return jsonify({'error': 'No autoritzat'}), 403

    user = User.query.get(int(user_id))
    if not user:
        return jsonify({'error': 'Usuari no trobat'}), 404

    user.password_hash        = generate_password_hash(new_password)
    user.must_change_password = False
    db.session.commit()

    # Si no hi havia sessió (flux must_change_password), iniciar-la ara
    if not session_user_id:
        session['user_id'] = user.id
        session.permanent  = True

    logger.info(f"✅ [ChangePassword] Contrasenya actualitzada per usuari id={user.id}")
    return jsonify({'ok': True, 'user': user.to_dict()})

@app.route('/api/auth/forgot-password', methods=['POST'])
def auth_forgot_password():
    data  = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    # Sempre retornem ok per no revelar si l'email existeix
    if email:
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if user:
            try:
                token     = generate_reset_token(user)
                base_url  = os.environ.get('APP_BASE_URL', request.host_url.rstrip('/'))
                link      = f"{base_url}/set-password?token={token}"
                html_body = (
                    "<html><body style='font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px;'>"
                    "<h2 style='color:#2c4a3e;'>Restablir contrasenya</h2>"
                    f"<p>Hola <strong>{user.name}</strong>,</p>"
                    "<p>Has demanat restablir la teva contrasenya. Fes clic al boto per continuar:</p>"
                    "<p style='margin:24px 0;'>"
                    f"<a href='{link}' style='background:#2c4a3e;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;display:inline-block;'>Restablir contrasenya</a>"
                    "</p>"
                    "<p style='color:#999;font-size:12px;'>Aquest link caduca en 24 hores. Si no ho has demanat, ignora aquest correu.</p>"
                    "</body></html>"
                )
                send_email(user.email, "Restablir contrasenya - Rodonverges Associats", html_body)
            except Exception as e:
                logger.error(f"❌ [ForgotPassword] Error: {e}")
    return jsonify({'ok': True})

@app.route('/api/auth/resend-verification', methods=['POST'])
def auth_resend_verification():
    data    = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'user_id requerit'}), 400
    user = User.query.get(int(user_id))
    if not user or not user.email:
        return jsonify({'ok': True})  # silent
    try:
        token     = generate_reset_token(user)
        base_url  = os.environ.get('APP_BASE_URL', request.host_url.rstrip('/'))
        link      = f"{base_url}/set-password?token={token}"
        html_body = (
            "<html><body style='font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px;'>"
            "<h2 style='color:#2c4a3e;'>Configura el teu acces</h2>"
            f"<p>Hola <strong>{user.name}</strong>,</p>"
            "<p>Fes clic al boto per establir la teva contrasenya:</p>"
            "<p style='margin:24px 0;'>"
            f"<a href='{link}' style='background:#2c4a3e;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;display:inline-block;'>Establir contrasenya</a>"
            "</p>"
            "<p style='color:#999;font-size:12px;'>Aquest link caduca en 24 hores.</p>"
            "</body></html>"
        )
        send_email(user.email, "Configura el teu acces - Rodonverges Associats", html_body)
    except Exception as e:
        logger.error(f"❌ [ResendVerification] Error: {e}")
    return jsonify({'ok': True})

@app.route('/set-password', methods=['GET'])
def set_password_page():
    token = request.args.get('token', '').strip()
    if not token:
        return "<h2>Link invàlid o caducat.</h2>", 400
    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        return "<h2>Link invàlid o caducat.</h2>", 400
    html = f"""<!doctype html>
<html lang="ca">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Establir contrasenya · Rodonvergés Associats</title>
  <style>
    body{{font-family:'DM Sans',Arial,sans-serif;background:#f2f1ee;min-height:100vh;display:flex;align-items:center;justify-content:center;}}
    .card{{background:#fff;border-radius:12px;padding:40px;max-width:400px;width:100%;box-shadow:0 4px 20px rgba(0,0,0,.1);}}
    h2{{color:#2c4a3e;margin-bottom:8px;font-size:22px;}}
    p{{color:#555;margin-bottom:24px;font-size:14px;}}
    label{{display:block;font-size:13px;color:#333;margin-bottom:4px;}}
    input{{width:100%;padding:10px 12px;border:1px solid #d4d2cc;border-radius:6px;font-size:14px;margin-bottom:16px;box-sizing:border-box;}}
    button{{width:100%;padding:12px;background:#2c4a3e;color:#fff;border:none;border-radius:6px;font-size:15px;cursor:pointer;}}
    button:hover{{background:#1a3028;}}
    .err{{color:#b94a48;font-size:13px;margin-bottom:12px;display:none;}}
    .ok{{color:#4a7a5a;font-size:14px;margin-top:16px;display:none;text-align:center;}}
  </style>
</head>
<body>
  <div class="card">
    <h2>Establir contrasenya</h2>
    <p>Hola <strong>{user.name}</strong>, crea la teva contrasenya per accedir.</p>
    <div class="err" id="err"></div>
    <label>Nova contrasenya *</label>
    <input type="password" id="p1" placeholder="Mínim 8 caràcters" autocomplete="new-password"/>
    <label>Confirmar contrasenya *</label>
    <input type="password" id="p2" placeholder="Repeteix la contrasenya" autocomplete="new-password"/>
    <button onclick="submit()">Guardar contrasenya</button>
    <div class="ok" id="ok">✅ Contrasenya guardada. Ja pots <a href="/">iniciar sessió</a>.</div>
  </div>
  <script>
    async function submit(){{
      const p1=document.getElementById('p1').value;
      const p2=document.getElementById('p2').value;
      const err=document.getElementById('err');
      err.style.display='none';
      if(p1.length<8){{err.textContent='La contrasenya ha de tenir mínim 8 caràcters.';err.style.display='block';return;}}
      if(p1!==p2){{err.textContent='Les contrasenyes no coincideixen.';err.style.display='block';return;}}
      const res=await fetch('/set-password',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{token:'{token}',new_password:p1}})}});
      const data=await res.json();
      if(data.ok){{document.querySelector('button').style.display='none';document.getElementById('ok').style.display='block';}}
      else{{err.textContent=data.error||'Error desconegut.';err.style.display='block';}}
    }}
    document.getElementById('p2').addEventListener('keydown',e=>{{if(e.key==='Enter')submit();}});
  </script>
</body>
</html>"""
    return html

@app.route('/set-password', methods=['POST'])
def set_password_submit():
    data     = request.get_json(silent=True) or {}
    token    = data.get('token', '').strip()
    new_pass = data.get('new_password', '')
    if not token:
        return jsonify({'ok': False, 'error': 'Token invàlid'}), 400
    if len(new_pass) < 8:
        return jsonify({'ok': False, 'error': 'La contrasenya ha de tenir mínim 8 caràcters'}), 400
    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        return jsonify({'ok': False, 'error': 'Link invàlid o caducat'}), 400
    user.password_hash        = generate_password_hash(new_pass)
    user.email_verified       = True
    user.must_change_password = False
    user.reset_token          = None
    user.reset_token_expires  = None
    db.session.commit()
    logger.info(f"✅ [SetPassword] Contrasenya establerta per {user.username}")
    return jsonify({'ok': True})

# ═══════════════════════════════════════════════════════════════
# RUTAS PRINCIPALES
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def home():
    """Ruta principal"""
    return render_template('index3.html')

@app.route('/app')
def dashboard():
    """Ruta alternativa del dashboard"""
    return render_template('index3.html')

@app.route('/index')
def index_alt():
    """Ruta alternativa - index"""
    return render_template('index3.html')

@app.route('/gestionpro')
def gestionpro():
    """Ruta de la aplicación GestióPro"""
    return render_template('index3.html')

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET EVENTS — MENSAJERÍA EN TIEMPO REAL
# ═══════════════════════════════════════════════════════════════

@socketio.on('connect')
def handle_connect(auth):
    """Usuario se conecta al socket"""
    user_id = request.sid
    logger.info(f"🔗 [Socket] Usuario conectado: {user_id}")
    emit('connect_response', {
        'data': 'Conectado al servidor',
        'user_id': user_id
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Usuario se desconecta del socket"""
    user_id = request.sid
    if user_id in connected_users:
        username = connected_users[user_id].get('username', 'Usuario')
        del connected_users[user_id]
        # NO esborrem username_to_sid aquí: si el socket es reconnecta
        # i envia user_login de nou, s'actualitzarà sol.
        # Esborrar-lo provoca que missatges enviats durant la reconnexió es perdin.
        if user_id in user_to_sede:
            del user_to_sede[user_id]
        logger.info(f"❌ [Socket] {username} desconectado (SID: {user_id})")
    else:
        logger.info(f"❌ [Socket] Usuario desconectado: {user_id}")

@socketio.on('user_login')
def handle_user_login(data):
    """Registra un usuario como conectado"""
    user_id = request.sid
    username = data.get('username', f'User_{user_id[:8]}')
    sede = data.get('sede', 'Desconocida')
    user_role = data.get('role', 'user')
    
    connected_users[user_id] = {
        'username': username,
        'sid': user_id,
        'sede': sede,
        'rol': user_role,
        'connected_at': datetime.now().isoformat()
    }
    username_to_sid[username] = user_id
    user_to_sede[user_id] = sede
    
    logger.info(f"✅ [Chat] {username} conectado (SID: {user_id}, Sede: {sede})")
    
    # ═══════════════════════════════════════════════════════════════
    # ENVIAR HISTÓRICOS AL CONECTAR
    # ═══════════════════════════════════════════════════════════════
    
    # 1. HISTÓRICO GENERAL — Para todos los usuarios
    if message_storage['general']:
        socketio.emit('load_general_history', {
            'messages': message_storage['general'][-50:]
        }, room=user_id)
        logger.info(f"📨 [Histórico] Enviados {len(message_storage['general'][-50:])} mensajes generales a {username}")
    
    # 2. HISTÓRICO DE SEDE — Solo para usuarios de esa sede + admins
    if user_role == 'admin' or sede == 'Mataró':
        if message_storage['sede_mataro']:
            socketio.emit('load_sede_history', {
                'messages': message_storage['sede_mataro'][-50:],
                'sede_key': 'mataro'
            }, room=user_id)
            logger.info(f"📨 [Histórico Mataró] Enviados {len(message_storage['sede_mataro'][-50:])} mensajes a {username}")
    
    if user_role == 'admin' or sede == 'Vilassar':
        if message_storage['sede_vilassar']:
            socketio.emit('load_sede_history', {
                'messages': message_storage['sede_vilassar'][-50:],
                'sede_key': 'vilassar'
            }, room=user_id)
            logger.info(f"📨 [Histórico Vilassar] Enviados {len(message_storage['sede_vilassar'][-50:])} mensajes a {username}")
    
    # Notificar a todos que hay un nuevo usuario online
    socketio.emit('user_status_update', {
        'user_id': user_id,
        'username': username,
        'sede': sede,
        'status': 'online',
        'online_users': len(connected_users)
    }, broadcast=True)
    
    logger.info(f"✅ [Históricos] Completados para {username}")
    
    # Entregar missatges privats pendents (enviats mentre estava offline)
    pending_keys = [k for k in message_storage if k.startswith('private_') and f'_{username}' in k]
    pending_count = 0
    for key in pending_keys:
        for pending_msg in message_storage[key]:
            if pending_msg.get('recipient_username') == username:
                socketio.emit('receive_message', pending_msg, room=user_id)
                pending_count += 1
    if pending_count > 0:
        logger.info(f"📬 [Pendientes] Entregats {pending_count} missatges pendents a {username}")

# ═══════════════════════════════════════════════════════════════
# CHAT GENERAL — Disponible para todos
# ═══════════════════════════════════════════════════════════════

@socketio.on('send_general_message')
def handle_general_message(data):
    """Envía un mensaje al chat general"""
    sender_id = request.sid
    sender_username = data.get('sender_username', 'Usuario')
    sender_user_id = data.get('sender_user_id', None)
    message_text = data.get('message', '').strip()
    message_id = data.get('message_id', f'msg_{int(datetime.now().timestamp() * 1000)}')
    attachments = data.get('attachments', [])
    
    # Validación
    if not message_text and not attachments:
        logger.warning(f"⚠️ [Chat General] Mensaje vacío de {sender_username}")
        return
    
    if not sender_user_id:
        logger.error(f"❌ [Chat General] Sin sender_user_id de {sender_username}")
        return
    
    # Crear objeto de mensaje
    message_obj = {
        'id': message_id,
        'sender_id': sender_user_id,
        'sender_username': sender_username,
        'text': message_text,
        'timestamp': datetime.now().isoformat(),
        'attachments': attachments
    }
    
    # Almacenar en servidor
    message_storage['general'].append(message_obj)
    save_message_storage()
    logger.info(f"💬 [Chat General] {sender_username}: {message_text[:50] if message_text else '(adjuntos)'}")
    logger.info(f"✅ [Almacenado] Mensaje {message_id}. Total: {len(message_storage['general'])}")
    
    # FIX: Excluir remitente para evitar duplicado
    socketio.emit('receive_general_message', message_obj, broadcast=True, skip_sid=sender_id)
    logger.info(f"📤 [Broadcast] Mensaje {message_id} enviado a TODOS excepto remitente")
    
    # Notificación
    socketio.emit('general_message_notification', {
        'from': sender_username,
        'message': message_text[:50] + '...' if len(message_text) > 50 else message_text,
        'timestamp': datetime.now().isoformat()
    }, broadcast=True, skip_sid=sender_id)

# ═══════════════════════════════════════════════════════════════
# CHAT DE SEDE — Solo para usuarios de esa sede + admins
# ═══════════════════════════════════════════════════════════════

@socketio.on('send_sede_message')
def handle_sede_message(data):
    """Envía un mensaje al chat de sede"""
    sender_id = request.sid
    sender_username = data.get('sender_username', 'Usuario')
    sender_user_id = data.get('sender_user_id', None)
    message_text = data.get('message', '').strip()
    message_id = data.get('message_id', f'msg_{int(datetime.now().timestamp() * 1000)}')
    sede = data.get('sede', '')
    sede_key = data.get('sede_key', '')
    attachments = data.get('attachments', [])
    
    # Validación
    if not message_text and not attachments:
        logger.warning(f"⚠️ [Chat Sede] Mensaje vacío de {sender_username}")
        return
    
    if not sender_user_id or not sede_key:
        logger.error(f"❌ [Chat Sede] Datos incompletos de {sender_username}")
        return
    
    # Crear objeto de mensaje
    message_obj = {
        'id': message_id,
        'sender_id': sender_user_id,
        'sender_username': sender_username,
        'text': message_text,
        'timestamp': datetime.now().isoformat(),
        'attachments': attachments,
        'sede': sede,
        'sede_key': sede_key
    }
    
    # Almacenar en servidor
    storage_key = f'sede_{sede_key}'
    message_storage[storage_key].append(message_obj)
    save_message_storage()
    logger.info(f"💬 [Chat Sede {sede}] {sender_username}: {message_text[:50] if message_text else '(adjuntos)'}")
    logger.info(f"✅ [Almacenado] Mensaje {message_id} en {storage_key}. Total: {len(message_storage[storage_key])}")
    
    # Obtener usuarios de esta sede (+ admins)
    sede_user_sids = []
    for username, sid in username_to_sid.items():
        if sid in connected_users:
            user_sede = connected_users[sid].get('sede', '')
            user_rol = connected_users[sid].get('rol', 'user')
            if user_sede == sede or user_rol == 'admin':
                sede_user_sids.append(sid)
                logger.debug(f"  ✓ {username} ({sid}) en {sede}")
    
    # Enviar a usuarios de esta sede (excepto remitente)
    for sid in sede_user_sids:
        if sid != sender_id:
            socketio.emit('receive_sede_message', message_obj, room=sid)
    
    logger.info(f"📤 [Enviado] Mensaje {message_id} a {len(sede_user_sids)} usuarios de {sede}")
    
    # Notificación
    for sid in sede_user_sids:
        if sid != sender_id:
            socketio.emit('sede_message_notification', {
                'from': sender_username,
                'sede': sede,
                'message': message_text[:50] + '...' if len(message_text) > 50 else message_text,
                'timestamp': datetime.now().isoformat()
            }, room=sid)

# ═══════════════════════════════════════════════════════════════
# CHAT PRIVADO — Entre dos usuarios
# ═══════════════════════════════════════════════════════════════

@socketio.on('send_message')
def handle_private_message(data):
    """Envía un mensaje privado"""
    sender_id = request.sid
    sender_username = data.get('sender_username', 'Usuario')
    recipient_username = data.get('recipient_username', '')
    message_text = data.get('message', '').strip()
    message_id = data.get('message_id', f'msg_{int(datetime.now().timestamp() * 1000)}')
    attachments = data.get('attachments', [])
    conv_id = data.get('conv_id', f'{sender_username}_{recipient_username}')
    
    # Validación
    if not message_text and not attachments:
        logger.warning(f"⚠️ [Chat Privado] Mensaje vacío de {sender_username}")
        return
    
    # Obtenir l'ID numèric de l'usuari (no el socket SID)
    sender_user_id = data.get('sender_user_id') or data.get('userId') or sender_id

    # Crear objeto de mensaje
    message_obj = {
        'id': message_id,
        'sender_id': sender_user_id,   # ID numèric de l'usuari, no el socket SID
        'sender_username': sender_username,
        'recipient_username': recipient_username,
        'text': message_text,
        'timestamp': datetime.now().isoformat(),
        'attachments': attachments
    }
    
    # Almacenar en servidor con clave privada normalizada (ordre alfabètic)
    private_key = private_conv_id(sender_username, recipient_username)
    if private_key not in message_storage:
        message_storage[private_key] = []
    message_storage[private_key].append(message_obj)
    save_message_storage()
    
    logger.info(f"💬 [RT] {sender_username} → {recipient_username}: {message_text[:50] if message_text else '(adjuntos)'}")
    logger.info(f"🔍 [RT] username_to_sid keys: {list(username_to_sid.keys())}")
    logger.info(f"🔍 [RT] connected_users: {[v.get('username') for v in connected_users.values()]}")
    
    # Buscar receptor: primer per username_to_sid, després per connected_users (per si el SID ha canviat)
    recipient_sid = username_to_sid.get(recipient_username)
    logger.info(f"🔍 [RT] recipient_sid from username_to_sid: {recipient_sid}")
    
    # Si el SID guardat ja no és a connected_users, buscar per nom dins connected_users
    if not recipient_sid or recipient_sid not in connected_users:
        logger.info(f"🔍 [RT] SID obsolet o no trobat, cercant per nom...")
        for sid, info in connected_users.items():
            if info.get('username') == recipient_username:
                recipient_sid = sid
                username_to_sid[recipient_username] = sid  # Actualitzar
                logger.info(f"🔍 [RT] Trobat per fallback: {recipient_username} → {sid}")
                break
    
    if recipient_sid and recipient_sid in connected_users:
        # Receptor connectat: entregar immediatament
        socketio.emit('receive_message', message_obj, room=recipient_sid)
        logger.info(f"✅ [RT] Missatge entregat a {recipient_username} (SID: {recipient_sid})")
        print(f"[RT] SocketIO emit receive_message → sala {recipient_sid} ({recipient_username})")
        socketio.emit('message_notification', {
            'from': sender_username,
            'message': "📎 Archivo adjunto" if attachments else (message_text[:50] + '...' if len(message_text) > 50 else message_text),
            'timestamp': datetime.now().isoformat()
        }, room=recipient_sid)
    else:
        # Receptor offline: el missatge ja està guardat a message_storage
        logger.warning(f"⚠️ [RT] {recipient_username} no connectat — guardat a {private_key}")
        print(f"[RT] {recipient_username} OFFLINE — missatge guardat, no entregat en temps real")
    
    # Confirmar envío al remitente
    socketio.emit('message_sent', {
        'message_id': message_id,
        'status': 'sent',
        'timestamp': datetime.now().isoformat()
    }, room=sender_id)

# ═══════════════════════════════════════════════════════════════
# CHAT PRIVADO CON ADJUNTOS (Backward compatibility)
# ═══════════════════════════════════════════════════════════════

@socketio.on('send_message_with_attachment')
def handle_message_with_attachment(data):
    """Recibe un mensaje con adjunto y lo retransmite"""
    sender_id = request.sid
    sender_username = data.get('sender_username', 'Usuario')
    recipient_username = data.get('recipient_username', '')
    message_text = data.get('message', '')
    message_id = data.get('message_id', f'msg_{datetime.now().timestamp()}')
    conv_id = data.get('conv_id', f'{sender_username}_{recipient_username}')
    attachments = data.get('attachments', [])
    
    if not message_text.strip() and not attachments:
        logger.warning(f"⚠️ [Chat] Mensaje vacío de {sender_username}")
        return
    
    # Crear objeto de mensaje
    message_obj = {
        'id': message_id,
        'sender_id': sender_id,
        'sender_username': sender_username,
        'recipient_username': recipient_username,
        'text': message_text,
        'timestamp': datetime.now().isoformat(),
        'read': False,
        'attachments': attachments
    }
    
    # ALMACENAR MENSAJE EN SERVIDOR
    if conv_id not in message_storage:
        message_storage[conv_id] = []
    message_storage[conv_id].append(message_obj)
    save_message_storage()
    
    logger.info(f"💬 [Chat Privado] {sender_username} → {recipient_username}: {len(attachments)} archivo(s)")
    
    # BUSCAR EL SID DEL RECEPTOR POR USERNAME
    recipient_sid = username_to_sid.get(recipient_username)
    
    if recipient_sid and recipient_sid in connected_users:
        # ENVIAR MENSAJE AL DESTINATARIO
        socketio.emit('receive_message', message_obj, room=recipient_sid)
        logger.info(f"✅ [Mensaje Entregado] A {recipient_username} (SID: {recipient_sid})")
        
        # ENVIAR NOTIFICACIÓN AL DESTINATARIO
        socketio.emit('message_notification', {
            'from': sender_username,
            'message': "📎 Archivo adjunto" if len(attachments) > 0 else (message_text[:50] + '...' if len(message_text) > 50 else message_text),
            'timestamp': datetime.now().isoformat()
        }, room=recipient_sid)
    else:
        logger.warning(f"⚠️ [Mensaje No Entregado] {recipient_username} no conectado")
    
    # CONFIRMAR AL REMITENTE
    socketio.emit('message_sent', {
        'message_id': message_id,
        'status': 'sent',
        'timestamp': datetime.now().isoformat()
    }, room=sender_id)

# ═══════════════════════════════════════════════════════════════
# EVENTOS ADICIONALES
# ═══════════════════════════════════════════════════════════════

@socketio.on('typing')
def handle_typing(data):
    """Notifica que alguien está escribiendo"""
    sender_id = request.sid
    recipient_username = data.get('recipient_username', '')
    sender_username = data.get('sender_username', 'Usuario')
    
    recipient_sid = username_to_sid.get(recipient_username)
    if recipient_sid and recipient_sid in connected_users:
        socketio.emit('user_typing', {
            'sender_id': sender_id,
            'sender_username': sender_username
        }, room=recipient_sid)

@socketio.on('stop_typing')
def handle_stop_typing(data):
    """Notifica que dejó de escribir"""
    sender_id = request.sid
    recipient_username = data.get('recipient_username', '')
    
    recipient_sid = username_to_sid.get(recipient_username)
    if recipient_sid and recipient_sid in connected_users:
        socketio.emit('user_stop_typing', {
            'sender_id': sender_id
        }, room=recipient_sid)

@socketio.on('get_online_users')
def handle_get_online_users():
    """Retorna lista de usuarios online"""
    online_list = list(connected_users.values())
    socketio.emit('online_users_list', {
        'users': online_list,
        'count': len(online_list)
    })

@socketio.on('send_notification')
def handle_notification(data):
    """Envía una notificación a un usuario específico"""
    recipient_username = data.get('recipient_username', '')
    notification_type = data.get('type', 'info')
    message = data.get('message', '')
    title = data.get('title', '')
    
    recipient_sid = username_to_sid.get(recipient_username)
    if recipient_sid and recipient_sid in connected_users:
        socketio.emit('notification_received', {
            'type': notification_type,
            'title': title,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }, room=recipient_sid)
        logger.info(f"🔔 [Notification] Enviada a {recipient_username}: {title}")

@socketio.on('broadcast_notification')
def handle_broadcast_notification(data):
    """Envía una notificación a todos los usuarios"""
    notification_type = data.get('type', 'info')
    message = data.get('message', '')
    title = data.get('title', '')
    
    socketio.emit('notification_received', {
        'type': notification_type,
        'title': title,
        'message': message,
        'timestamp': datetime.now().isoformat()
    }, broadcast=True)
    logger.info(f"🔔 [Broadcast Notification] {title}")

# ═══════════════════════════════════════════════════════════════
# API REST — RECUPERAR MENSAJES Y ADJUNTOS
# ═══════════════════════════════════════════════════════════════
@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Puja un fitxer al servidor i retorna la URL"""
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'No file'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'ok': False, 'error': 'No filename'}), 400
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    blocked = {'exe','bat','sh','ps1','cmd','com','scr','pif','vbs','js'}
    if ext in blocked:
        return jsonify({'ok': False, 'error': 'Tipus de fitxer no permès'}), 400
    unique_name = f"{uuid.uuid4().hex}_{f.filename}"
    save_path = os.path.join(UPLOAD_FOLDER, unique_name)
    f.save(save_path)
    url = f"/api/uploads/{unique_name}"
    logger.info(f"📎 [Upload] Fitxer guardat: {unique_name} ({f.content_length or 0} bytes)")
    return jsonify({'ok': True, 'url': url, 'name': f.filename})

@app.route('/api/uploads/<filename>', methods=['GET'])
def serve_upload(filename):
    """Serveix un fitxer pujat"""
    return send_file(os.path.join(UPLOAD_FOLDER, filename), as_attachment=True)
@app.route('/api/messages/<conv_id>', methods=['GET'])
def get_messages(conv_id):
    """Recupera missatges d'una conversa des de PostgreSQL.
    Suporta paginació via ?before_id=<msg_id> (carrega 50 missatges anteriors a aquell ID).
    Retorna has_more: true si hi ha missatges més antics.
    """
    if not conv_id:
        return jsonify({'ok': False, 'error': 'conv_id requerit', 'messages': [], 'has_more': False}), 400
    try:
        LIMIT = 50
        before_id = request.args.get('before_id', '').strip() or None

        # Normalitzar conv_id privat per ordre alfabètic
        norm_id = conv_id
        if conv_id.startswith('private_'):
            parts = conv_id.replace('private_', '', 1).split('_', 1)
            if len(parts) == 2:
                norm_id = private_conv_id(parts[0], parts[1])

        def _fetch(cid):
            q = Message.query.filter_by(conv_id=cid)
            if before_id:
                ref = Message.query.filter_by(msg_id=before_id).first()
                if ref:
                    q = q.filter(Message.pk < ref.pk)
            return list(reversed(q.order_by(Message.created_at.desc()).limit(LIMIT).all()))

        msgs = _fetch(norm_id)

        # Safety net: compatibilitat amb missatges antics guardats amb conv_id no normalitzat
        if not msgs and norm_id != conv_id:
            msgs = _fetch(conv_id)
            norm_id = conv_id if msgs else norm_id

        # Calcular has_more: hi ha missatges més antics que el primer de la pàgina actual?
        has_more = False
        if msgs:
            oldest_pk = msgs[0].pk
            has_more = Message.query.filter(
                Message.conv_id == norm_id,
                Message.pk < oldest_pk
            ).count() > 0

        return jsonify({
            'ok':       True,
            'conv_id':  norm_id,
            'messages': [m.to_dict() for m in msgs],
            'has_more': has_more,
        })
    except Exception as e:
        logger.error(f"[Messages GET] Error: {str(e)}")
        return jsonify({'ok': False, 'error': str(e), 'messages': [], 'has_more': False}), 500

@app.route('/api/messages/<conv_id>', methods=['POST'])
def send_message_api(conv_id):
    """Guarda un missatge a PostgreSQL via HTTP polling. Usat pel frontend en lloc de SocketIO."""
    try:
        data = request.get_json(force=True) or {}
        msg_id      = data.get('id') or f'msg_{int(datetime.now().timestamp() * 1000)}'
        sender      = data.get('sender_username', '')
        text        = data.get('text', '').strip()
        attachments = data.get('attachments', [])

        if not text and not attachments:
            return jsonify({'ok': False, 'error': 'Missatge buit'}), 400

        # Normalitzar conv_id privat per ordre alfabètic
        norm_conv_id = conv_id
        if conv_id.startswith('private_'):
            parts = conv_id.replace('private_', '', 1).split('_', 1)
            if len(parts) == 2:
                norm_conv_id = private_conv_id(parts[0], parts[1])

        # Deduplicacio: comprova si el msg_id ja existeix a la BD
        existing = Message.query.filter_by(msg_id=msg_id).first()
        if existing:
            return jsonify({'ok': True, 'message': existing.to_dict(), 'duplicate': True})

        sede_key = norm_conv_id.replace('sede_', '') if norm_conv_id.startswith('sede_') else None
        sede     = data.get('sede', '') if norm_conv_id.startswith('sede_') else None

        msg = Message(
            msg_id             = msg_id,
            conv_id            = norm_conv_id,
            sender_id          = data.get('sender_id'),
            sender_username    = sender,
            recipient_username = data.get('recipient_username', ''),
            text               = text,
            msg_timestamp      = data.get('timestamp', datetime.utcnow().isoformat()),
            attachments_json   = json.dumps(attachments) if attachments else None,
            sede_key           = sede_key,
            sede               = sede,
        )
        db.session.add(msg)
        db.session.commit()

        # ── Web Push: notifica destinataris SEMPRE (privat / seu / general) ──
        try:
            sender_id   = data.get('sender_id')
            sender_user = User.query.get(sender_id) if sender_id else None
            sender_name = sender_user.name if sender_user else (sender or 'Missatge nou')
            preview     = (text[:80] + '…') if len(text) > 80 else (text or '📎 Adjunt')

            logger.info(f"[Push] Trigger missatge: conv={norm_conv_id!r} sender={sender_name!r}")

            if norm_conv_id.startswith('private_'):
                # Conversa privada → notifica únicament el destinatari
                recipient_un = data.get('recipient_username', '').strip()
                if recipient_un:
                    recipient_user = User.query.filter(
                                        func.lower(User.username) == recipient_un.lower(),
                                        User.active == True
                                    ).first()
                    if recipient_user:
                        send_push_notification(
                            recipient_user.id,
                            title=sender_name,
                            body=preview,
                            url='/',
                            tag=f'msg-{norm_conv_id}',
                        )
                    else:
                        logger.warning(f"[Push] ⚠️  Destinatari no trobat: username={recipient_un!r}")

            elif norm_conv_id.startswith('sede_'):
                # Xat de seu → notifica tots els usuaris actius d'aquella seu (excepte remitent)
                sede_val = norm_conv_id.replace('sede_', '', 1)
                sede_users = User.query.filter(
                    User.sede == sede_val,
                    User.active == True,
                    User.id != sender_id,
                ).all()
                for u in sede_users:
                    send_push_notification(
                        u.id,
                        title=f'{sender_name} · {sede_val.capitalize()}',
                        body=preview,
                        url='/',
                        tag=f'msg-{norm_conv_id}',
                    )

            else:
                # Xat general → notifica tots els usuaris actius (excepte remitent)
                all_users = User.query.filter(
                    User.active == True,
                    User.id != sender_id,
                ).all()
                for u in all_users:
                    send_push_notification(
                        u.id,
                        title=f'{sender_name} · Chat General',
                        body=preview,
                        url='/',
                        tag='msg-general',
                    )

        except Exception as _push_err:
            logger.error(f"[Push] ❌ Error en trigger de missatge: {_push_err!r}")

        logger.info(f"[Polling POST] {sender}: \"{text[:40]}\" -> {norm_conv_id}")
        return jsonify({'ok': True, 'message': msg.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Polling POST] Error: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/messages/<conv_id>/read', methods=['POST'])
def mark_messages_read(conv_id):
    """Marca una conversa com a llegida per l'usuari indicat.
    Guarda a PostgreSQL l'últim pk de missatge llegit (persistent entre sessions i workers).
    """
    data = request.get_json(force=True) or {}
    username = (data.get('username') or '').strip()
    if not username:
        return jsonify({'ok': True})  # ignorar si no hi ha username

    # Normalitzar conv_id privat
    norm_id = conv_id
    if conv_id.startswith('private_'):
        parts = conv_id.replace('private_', '', 1).split('_', 1)
        if len(parts) == 2:
            norm_id = private_conv_id(parts[0], parts[1])

    try:
        from sqlalchemy import func as sqlfunc
        max_pk = db.session.query(sqlfunc.max(Message.pk)).filter_by(conv_id=norm_id).scalar() or 0

        lr = LastRead.query.filter_by(username=username, conv_id=norm_id).first()
        if lr:
            if max_pk > lr.last_pk:
                lr.last_pk = max_pk
        else:
            lr = LastRead(username=username, conv_id=norm_id, last_pk=max_pk)
            db.session.add(lr)
        db.session.commit()
        return jsonify({'ok': True, 'last_pk': max_pk})
    except Exception as e:
        db.session.rollback()
        logger.error(f"[LastRead] Error: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/messages/unread-count', methods=['GET'])
def get_total_unread_count():
    """Retorna el total de missatges no llegits per l'usuari de la sessió actual."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'unread': 0})
    user = User.query.get(user_id)
    if not user:
        return jsonify({'unread': 0})
    username = user.username
    try:
        from sqlalchemy import func as sqlfunc
        last_reads_rows = LastRead.query.filter_by(username=username).all()
        if not last_reads_rows:
            # Primera sessió: marcar tots els missatges actuals com a llegits → 0 no llegits
            conv_max_pks = db.session.query(
                Message.conv_id, sqlfunc.max(Message.pk)
            ).group_by(Message.conv_id).all()
            for conv_id, max_pk in conv_max_pks:
                if max_pk is None:
                    continue
                db.session.add(LastRead(username=username, conv_id=conv_id, last_pk=max_pk))
            db.session.commit()
            return jsonify({'unread': 0})
        last_reads = {lr.conv_id: lr.last_pk for lr in last_reads_rows}
        conv_ids = [row[0] for row in db.session.query(Message.conv_id).distinct().all()]
        total = 0
        for cid in conv_ids:
            last_pk = last_reads.get(cid)
            if last_pk is None:
                continue
            total += Message.query.filter(
                Message.conv_id == cid,
                Message.pk > last_pk,
                Message.sender_username != username
            ).count()
        return jsonify({'unread': total})
    except Exception as e:
        logger.error(f"[UnreadCount] Error: {str(e)}")
        return jsonify({'unread': 0})

@app.route('/api/unread-counts', methods=['GET'])
def get_unread_counts():
    """Retorna el recompte de missatges no llegits per conv_id per a l'usuari indicat.
    Si l'usuari no té cap registre LastRead (primera sessió amb el sistema),
    retorna needs_init=True i counts={} en lloc de comptar tots com a no llegits.
    """
    username = (request.args.get('username') or '').strip()
    if not username:
        return jsonify({'ok': False, 'counts': {}}), 400
    try:
        from sqlalchemy import func as sqlfunc
        last_reads_rows = LastRead.query.filter_by(username=username).all()

        # Primera sessió: cap registre LastRead → inicialitzar al frontend
        if not last_reads_rows:
            return jsonify({'ok': True, 'counts': {}, 'needs_init': True})

        last_reads = {lr.conv_id: lr.last_pk for lr in last_reads_rows}
        conv_ids = [
            row[0] for row in
            db.session.query(Message.conv_id).distinct().all()
        ]
        counts = {}
        for cid in conv_ids:
            last_pk = last_reads.get(cid, 0)
            unread = Message.query.filter(
                Message.conv_id == cid,
                Message.pk > last_pk,
                Message.sender_username != username
            ).count()
            if unread > 0:
                counts[cid] = unread
        return jsonify({'ok': True, 'counts': counts, 'needs_init': False})
    except Exception as e:
        logger.error(f"[UnreadCounts] Error: {str(e)}")
        return jsonify({'ok': False, 'counts': {}}), 500

@app.route('/api/messages/init-session', methods=['POST'])
def init_session_read():
    """Inicialitza LastRead per a l'usuari: marca tots els missatges existents
    com a llegits. S'usa la primera vegada que l'usuari entra amb el sistema nou
    per evitar que tots els missatges antics apareguin com a no llegits.
    """
    data = request.get_json(force=True) or {}
    username = (data.get('username') or '').strip()
    if not username:
        return jsonify({'ok': False, 'error': 'username requerit'}), 400
    try:
        from sqlalchemy import func as sqlfunc
        # Per cada conv_id existent, crear LastRead al max pk actual
        conv_max_pks = db.session.query(
            Message.conv_id,
            sqlfunc.max(Message.pk)
        ).group_by(Message.conv_id).all()

        initialized = 0
        for conv_id, max_pk in conv_max_pks:
            if max_pk is None:
                continue
            lr = LastRead.query.filter_by(username=username, conv_id=conv_id).first()
            if lr:
                lr.last_pk = max(lr.last_pk, max_pk)
            else:
                lr = LastRead(username=username, conv_id=conv_id, last_pk=max_pk)
                db.session.add(lr)
            initialized += 1
        db.session.commit()
        logger.info(f"[InitSession] {username}: {initialized} converses inicialitzades")
        return jsonify({'ok': True, 'initialized': initialized})
    except Exception as e:
        db.session.rollback()
        logger.error(f"[InitSession] Error: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/messages/attachment/<msg_id>/<filename>', methods=['GET'])
def get_message_attachment(msg_id, filename):
    """Descargar un archivo adjunto de un mensaje"""
    try:
        # Buscar el mensaje en el almacenamiento
        for conv_id, messages in message_storage.items():
            for msg in messages:
                if msg.get('id') == msg_id and msg.get('attachments'):
                    for att in msg['attachments']:
                        if att.get('name') == filename:
                            # El archivo está almacenado como base64
                            file_data = att.get('data', '')
                            if file_data.startswith('data:'):
                                # Extraer la parte base64
                                file_data = file_data.split(',')[1]
                            
                            binary_data = base64.b64decode(file_data)
                            
                            return send_file(
                                BytesIO(binary_data),
                                download_name=filename,
                                as_attachment=True
                            )
        
        logger.warning(f"⚠️ Archivo no encontrado: {msg_id}/{filename}")
        return jsonify({'ok': False, 'error': 'Archivo no encontrado'}), 404
    except Exception as e:
        logger.error(f"❌ Error al descargar adjunto: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500
# ═══════════════════════════════════════════════════════════════
# API USUARIS — Llistar i crear
# ═══════════════════════════════════════════════════════════════

@app.route('/api/usuarios', methods=['GET'])
def get_usuarios():
    """Retorna la llista d'usuaris (sense password_hash)"""
    try:
        users = User.query.order_by(User.id).all()
        return jsonify({'ok': True, 'usuarios': [u.to_dict() for u in users]})
    except Exception as e:
        logger.error(f"[Usuarios GET] Error: {str(e)}")
        return jsonify({'ok': False, 'error': str(e), 'usuarios': []}), 500

@app.route('/api/usuarios', methods=['POST'])
def crear_usuario():
    """Crea un nou usuari a PostgreSQL amb contrasenya generada automàticament."""
    data         = request.get_json(silent=True) or {}
    username     = data.get('username', '').strip()
    nombre       = data.get('nombre', '').strip()
    email        = data.get('email', '').strip().replace('\xa0', '').replace('\u200b', '')
    departamento = data.get('departamento', '').strip()
    rol          = data.get('rol', 'empleado').strip()
    sede         = data.get('sede', '').strip()
    color        = data.get('color', 'teal').strip()
    phone        = data.get('phone', '').strip()

    password_raw = data.get('password', '').strip()

    if not username or not nombre or not departamento or not sede:
        return jsonify({'ok': False, 'error': 'Falten camps obligatoris: username, nombre, departamento, sede'}), 400
    if not email:
        return jsonify({'ok': False, 'error': 'El camp email és obligatori'}), 400
    if not password_raw:
        return jsonify({'ok': False, 'error': 'La contrasenya es obligatoria'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'ok': False, 'error': f"El username '{username}' ja existeix"}), 409

    if email and User.query.filter_by(email=email).first():
        return jsonify({'ok': False, 'error': f"L'email '{email}' ja existeix"}), 409

    user = User(
        username=username,
        password_hash=generate_password_hash(password_raw),
        name=nombre,
        email=email or None,
        phone=phone or None,
        role=rol,
        departamento=departamento,
        sede=sede,
        color=color,
        active=True,
        email_verified=False,
        must_change_password=True,
    )
    db.session.add(user)
    db.session.commit()
    logger.info(f"✅ [Usuari] Creat: {nombre} (username: {username})")
    create_seat_chats(user.id, nombre, sede)
    return jsonify({'ok': True, 'usuario': user.to_dict()}), 201

@app.route('/api/usuarios/<int:user_id>', methods=['PUT'])
def actualitzar_usuario(user_id):
    """Actualitza les dades d'un usuari existent (sense canviar contrasenya)."""
    user = User.query.get(user_id)
    if not user:
        return jsonify({'ok': False, 'error': 'Usuari no trobat'}), 404
    data = request.get_json(silent=True) or {}
    if 'nombre' in data:
        user.name = (data.get('nombre') or '').strip()
    if 'email' in data:
        new_email = (data.get('email') or '').strip().replace('\xa0', '').replace('\u200b', '')
        existing = User.query.filter(User.email == new_email, User.id != user_id).first()
        if existing:
            return jsonify({'ok': False, 'error': f"L'email '{new_email}' ja existeix"}), 409
        user.email = new_email or None
    if 'phone' in data:
        user.phone = (data.get('phone') or '').strip() or None
    if 'rol' in data:
        user.role = (data.get('rol') or '').strip()
    if 'role' in data:
        user.role = (data.get('role') or '').strip()
    if 'departamento' in data:
        user.departamento = (data.get('departamento') or '').strip() or None
    if 'sede' in data:
        user.sede = (data.get('sede') or '').strip()
    if 'color' in data:
        user.color = (data.get('color') or '').strip()
    if 'active' in data:
        user.active = bool(data['active'])
    db.session.commit()
    logger.info(f"✅ [Usuari] Actualitzat: id={user_id}")
    return jsonify({'ok': True, 'usuario': user.to_dict()})

@app.route('/api/users/admins', methods=['GET'])
def get_admin_users():
    """Retorna tots els usuaris amb role='admin' i active=True."""
    if not session.get('user_id'):
        return jsonify({'ok': False, 'error': 'Autenticació requerida'}), 401
    admins = User.query.filter_by(role='admin', active=True).order_by(User.sede, User.name).all()
    return jsonify({'ok': True, 'admins': [
        {'id': u.id, 'username': u.username, 'name': u.name, 'sede': u.sede or ''}
        for u in admins
    ]})

# ═══════════════════════════════════════════════════════════════
# API DEPT PERMISSIONS
# ═══════════════════════════════════════════════════════════════

DEPT_NAMES = ['laboral', 'fiscal', 'mercantil']

@app.route('/api/dept-permissions', methods=['GET'])
def get_dept_permissions():
    """Retorna els permisos departamentals. Qualsevol usuari autenticat pot llegir-los."""
    if not session.get('user_id'):
        return jsonify({'ok': False, 'error': 'Autenticació requerida'}), 401
    result = {}
    for dept in DEPT_NAMES:
        row = DeptPermission.query.get(dept)
        if row:
            try:
                access = json.loads(row.access_to_depts) if row.access_to_depts else []
            except Exception:
                access = []
            result[dept] = {'level': row.level, 'accessToDepts': access}
        else:
            result[dept] = {'level': 2, 'accessToDepts': []}
    return jsonify({'ok': True, 'permissions': result})

@app.route('/api/dept-permissions', methods=['POST'])
def save_dept_permissions():
    """Desa els permisos departamentals. Només admins."""
    if not session.get('user_id'):
        return jsonify({'ok': False, 'error': 'Autenticació requerida'}), 401
    user = User.query.get(session['user_id'])
    if not user or user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Accés restringit a administradors'}), 403
    data = request.get_json(silent=True) or {}
    permissions = data.get('permissions', {})
    try:
        for dept in DEPT_NAMES:
            perm = permissions.get(dept, {})
            level  = int(perm.get('level', 2))
            access = json.dumps(perm.get('accessToDepts', []))
            row = DeptPermission.query.get(dept)
            if row:
                row.level           = level
                row.access_to_depts = access
            else:
                db.session.add(DeptPermission(dept=dept, level=level, access_to_depts=access))
        db.session.commit()
        logger.info(f"✅ [DeptPerms] Permisos desats per {user.username}")
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ [DeptPerms] Error desant permisos: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# API WHATSAPP — ENVÍO AUTOMÁTICO
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# API CLIENTS — Importació des d'Excel/CSV a PostgreSQL
# ═══════════════════════════════════════════════════════════════

try:
    import psycopg2
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    logger.warning("⚠️ psycopg2 no disponible. Importació de clients desactivada.")

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    """Connecta a PostgreSQL via DATABASE_URL"""
    return psycopg2.connect(DATABASE_URL)

def clean_phone(phone):
    """Neteja telèfons: elimina parèntesis, espais, guions"""
    if not phone:
        return ''
    return re.sub(r'[^\d+]', '', str(phone))

@app.route('/api/clients', methods=['GET'])
def get_clients():
    """Retorna tots els clients de PostgreSQL"""
    if not PSYCOPG2_AVAILABLE:
        return jsonify({'ok': False, 'error': 'psycopg2 no disponible', 'clients': []}), 500
    if not DATABASE_URL:
        return jsonify({'ok': True, 'clients': []})
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nombre, telefono, email, direccion, ciudad, cif, notas
            FROM clients
            ORDER BY nombre ASC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        clients = [
            {
                'id': r[0],
                'name': r[1] or '',
                'phone': r[2] or '',
                'email': r[3] or '',
                'address': r[4] or '',
                'city': r[5] or '',
                'cif': r[6] or '',
                'notes': r[7] or '',
            }
            for r in rows
        ]
        return jsonify({'ok': True, 'clients': clients})
    except Exception as e:
        logger.error(f"❌ [Clients] Error: {str(e)}")
        return jsonify({'ok': False, 'error': str(e), 'clients': []}), 500

@app.route('/api/clients', methods=['POST'])
def create_client():
    """Crea un nou client a PostgreSQL."""
    if not PSYCOPG2_AVAILABLE:
        return jsonify({'ok': False, 'error': 'psycopg2 no disponible'}), 500
    if not DATABASE_URL:
        return jsonify({'ok': False, 'error': 'Base de dades no configurada'}), 500
    data   = request.get_json(silent=True) or {}
    name   = (data.get('name') or '').strip()
    phone  = clean_phone(data.get('phone') or '')
    email  = (data.get('email') or '').strip()
    cif    = (data.get('cif') or '').strip()
    city   = (data.get('city') or data.get('ciutat') or '').strip()
    notes  = (data.get('notes') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'El nom és obligatori'}), 400
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO clients (nombre, telefono, email, cif, ciudad, notas, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
        """, (name, phone or None, email or None, cif or None, city or None, notes or None))
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"✅ [Clients] Creat client id={new_id} nom='{name}'")
        return jsonify({'ok': True, 'client': {
            'id': new_id, 'name': name, 'phone': phone,
            'email': email, 'cif': cif, 'city': city, 'notes': notes, 'address': ''
        }}), 201
    except Exception as e:
        logger.error(f"❌ [Clients] Error creant client: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clients/<int:client_id>', methods=['PUT'])
def update_client(client_id):
    """Edita un client existent a PostgreSQL."""
    if not PSYCOPG2_AVAILABLE:
        return jsonify({'ok': False, 'error': 'psycopg2 no disponible'}), 500
    if not DATABASE_URL:
        return jsonify({'ok': False, 'error': 'Base de dades no configurada'}), 500
    data   = request.get_json(silent=True) or {}
    name   = (data.get('name') or '').strip()
    phone  = clean_phone(data.get('phone') or '')
    email  = (data.get('email') or '').strip()
    cif    = (data.get('cif') or '').strip()
    city   = (data.get('city') or data.get('ciutat') or '').strip()
    notes  = (data.get('notes') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'El nom és obligatori'}), 400
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            UPDATE clients
            SET nombre=%s, telefono=%s, email=%s, cif=%s, ciudad=%s, notas=%s
            WHERE id=%s
        """, (name, phone or None, email or None, cif or None, city or None, notes or None, client_id))
        if cur.rowcount == 0:
            conn.rollback(); cur.close(); conn.close()
            return jsonify({'ok': False, 'error': 'Client no trobat'}), 404
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"✅ [Clients] Editat client id={client_id}")
        return jsonify({'ok': True, 'client': {
            'id': client_id, 'name': name, 'phone': phone,
            'email': email, 'cif': cif, 'city': city, 'notes': notes, 'address': ''
        }})
    except Exception as e:
        logger.error(f"❌ [Clients] Error editant client: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clients/<int:client_id>', methods=['DELETE'])
def delete_client(client_id):
    """Elimina un client de PostgreSQL."""
    if not PSYCOPG2_AVAILABLE:
        return jsonify({'ok': False, 'error': 'psycopg2 no disponible'}), 500
    if not DATABASE_URL:
        return jsonify({'ok': False, 'error': 'Base de dades no configurada'}), 500
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("DELETE FROM clients WHERE id=%s", (client_id,))
        if cur.rowcount == 0:
            conn.rollback(); cur.close(); conn.close()
            return jsonify({'ok': False, 'error': 'Client no trobat'}), 404
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"✅ [Clients] Eliminat client id={client_id}")
        return jsonify({'ok': True})
    except Exception as e:
        logger.error(f"❌ [Clients] Error eliminant client: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clients/import', methods=['POST'])
def import_clients_db():
    """Importa clients des d'Excel o CSV a PostgreSQL. Només admins."""

    # Seguretat: només admins (verificació via sessió, no via capçalera forjable)
    _uid = session.get('user_id')
    _u   = User.query.get(_uid) if _uid else None
    if not _u or _u.role != 'admin':
        return jsonify({'ok': False, 'error': 'No autoritzat'}), 403

    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'Cap fitxer rebut.'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'ok': False, 'error': 'Nom de fitxer buit.'}), 400

    filename = f.filename.lower()
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(f.read()), dtype=str)
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(f.read()), dtype=str)
        else:
            return jsonify({'ok': False, 'error': 'Format no suportat. Usa CSV o Excel.'}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Error llegint fitxer: {str(e)}'}), 400

    # Normalitzar noms de columnes
    df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]

    def find_col(options):
        for opt in options:
            if opt in df.columns:
                return opt
        return None

    inserted = 0
    skipped = 0
    errors = []
    if not PSYCOPG2_AVAILABLE:
        return jsonify({'ok': False, 'error': 'psycopg2 no instal·lat al servidor.'}), 500
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        for idx, row in df.iterrows():
            try:
                nombre_col   = find_col(['nombre', 'nom', 'name'])
                telefono_col = find_col(['número_de_teléfono', 'numero_de_telefono', 'telefono', 'telèfon', 'phone', 'tel', 'móvil', 'movil', 'teléfono_1', 'telefono_1', 'telèfon_1', 'teléfono 1', 'telefono 1'])
                email_col    = find_col(['email', 'correu', 'mail'])
                dir_col      = find_col(['dirección', 'direccion', 'address', 'adreça'])
                ciudad_col   = find_col(['ciudad', 'ciutat', 'city'])
                cif_col      = find_col(['cif', 'nif'])
                notas_col    = find_col(['notas', 'notes', 'comentaris'])

                nombre   = str(row[nombre_col]).strip()   if nombre_col   and pd.notna(row[nombre_col])   else ''
                telefono = clean_phone(row[telefono_col]) if telefono_col and pd.notna(row[telefono_col]) else ''
                email    = str(row[email_col]).strip()    if email_col    and pd.notna(row[email_col])    else ''
                direccion= str(row[dir_col]).strip()      if dir_col      and pd.notna(row[dir_col])      else ''
                ciudad   = str(row[ciudad_col]).strip()   if ciudad_col   and pd.notna(row[ciudad_col])   else ''
                cif      = str(row[cif_col]).strip()      if cif_col      and pd.notna(row[cif_col])      else ''
                notas    = str(row[notas_col]).strip()    if notas_col    and pd.notna(row[notas_col])    else ''

                if not nombre:
                    skipped += 1
                    continue

                cur.execute("""
                    INSERT INTO clients (nombre, telefono, email, direccion, ciudad, cif, notas, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (telefono) DO NOTHING
                """, (nombre, telefono or None, email, direccion, ciudad, cif, notas))

                if cur.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1

            except Exception as row_err:
                errors.append(f'Fila {idx + 2}: {str(row_err)}')
                skipped += 1

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        return jsonify({'ok': False, 'error': f'Error de base de dades: {str(e)}'}), 500

    logger.info(f"📥 [Import Clients] {inserted} inserits, {skipped} omesos")
    return jsonify({
        'ok': True,
        'inserted': inserted,
        'skipped': skipped,
        'errors': errors[:10]
    })
@app.route('/api/whatsapp/send', methods=['POST'])
def send_whatsapp():
    """Envía un mensaje de WhatsApp via la plantilla 'nom_recordatori_cita'.
    Sempre usa use_template=True amb les 4 variables: client, date, time, sede.
    """
    data = request.get_json(silent=True) or {}
    logger.info(f"[WA /send] Rebut: {data}")

    to_phone = data.get('to', '').strip()
    if not to_phone:
        return jsonify({'ok': False, 'error': 'Falta el campo "to"'}), 400

    nom  = data.get('client', '') or ''
    date = data.get('date',   '') or ''
    hora = data.get('time',   '') or ''
    seu  = data.get('sede',   '') or ''

    # Formatar data: YYYY-MM-DD → "Dilluns 28/04/2026"
    DIES_CA = ['Dilluns','Dimarts','Dimecres','Dijous','Divendres','Dissabte','Diumenge']
    try:
        _d = datetime.strptime(date, '%Y-%m-%d')
        data_var = f"{DIES_CA[_d.weekday()]} {_d.strftime('%d/%m/%Y')}"
    except Exception:
        data_var = date

    result = send_whatsapp_meta(
        to_phone,
        use_template=True,
        nom=nom,
        data=data_var,
        hora=hora,
        seu=seu,
    )
    logger.info(f"[WA /send] Resultat: {result}")
    return jsonify(result)

@app.route('/api/whatsapp/schedule', methods=['POST'])
def schedule_whatsapp():
    """Programa el envío de un WhatsApp en una fecha/hora futura.
    Desa el job a WaScheduledJob (sent=False) per poder recuperar-lo en restart.
    Camps nous: nom, data, hora, seu, event_id (a més dels clàssics to/send_at/job_id).
    """
    if not SCHEDULER_AVAILABLE or not scheduler:
        return jsonify({
            'ok': False,
            'error': 'APScheduler no disponible. pip install apscheduler',
            'configured': False
        }), 503

    payload  = request.get_json(silent=True) or {}
    to_phone = payload.get('to', '').strip()
    send_at  = payload.get('send_at', '').strip()
    job_id   = payload.get('job_id', '').strip()

    # Camps de la plantilla (obligatoris per al nou flux)
    nom      = (payload.get('nom')    or payload.get('client') or '').strip()
    data_cita= (payload.get('data')   or payload.get('date')   or '').strip()
    hora     = (payload.get('hora')   or payload.get('time')   or '').strip()
    seu      = (payload.get('seu')    or payload.get('sede')   or '').strip()
    event_id = payload.get('event_id') or None

    if not to_phone or not send_at or not job_id:
        return jsonify({'ok': False, 'error': 'Falten camps: to, send_at, job_id'}), 400
    if not nom or not data_cita or not hora or not seu:
        return jsonify({'ok': False, 'error': 'Falten camps de plantilla: nom, data, hora, seu'}), 400

    # Parsear la data d'enviament
    try:
        send_dt = datetime.fromisoformat(send_at)
        madrid  = pytz.timezone('Europe/Madrid')
        if send_dt.tzinfo is None:
            send_dt = madrid.localize(send_dt)
    except ValueError:
        return jsonify({'ok': False, 'error': f'Format de send_at invàlid: {send_at}'}), 400

    # Si la data ja ha passat, no programar
    now_tz = datetime.now(pytz.timezone('Europe/Madrid'))
    if send_dt <= now_tz:
        return jsonify({'ok': False, 'error': 'La data d\'enviament ja ha passat'}), 400

    # Desar (o actualitzar) el registre persistent a la BD
    try:
        send_at_utc = send_dt.astimezone(pytz.utc).replace(tzinfo=None)  # guardar UTC naive
        existing_rec = WaScheduledJob.query.filter_by(job_id=job_id).first()
        if existing_rec:
            existing_rec.phone   = to_phone
            existing_rec.nom     = nom
            existing_rec.data    = data_cita
            existing_rec.hora    = hora
            existing_rec.seu     = seu
            existing_rec.send_at = send_at_utc
            existing_rec.sent    = False
            if event_id:
                existing_rec.event_id = int(event_id)
        else:
            db.session.add(WaScheduledJob(
                job_id   = job_id,
                event_id = int(event_id) if event_id else None,
                phone    = to_phone,
                nom      = nom,
                data     = data_cita,
                hora     = hora,
                seu      = seu,
                send_at  = send_at_utc,
                sent     = False,
            ))
        db.session.commit()
    except Exception as _db_err:
        db.session.rollback()
        logger.error(f"❌ [Scheduler] Error desant WaScheduledJob {job_id}: {_db_err}")
        # Continuem igualment per programar el job en memòria

    # Eliminar job anterior amb el mateix ID si existeix
    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    except Exception:
        pass

    # Programar el job
    try:
        scheduler.add_job(
            func             = send_whatsapp_job,
            trigger          = DateTrigger(run_date=send_dt),
            args             = [to_phone, nom, data_cita, hora, seu, job_id],
            id               = job_id,
            replace_existing = True,
        )
        logger.info(f"📅 [Scheduler] WA programat per {send_dt.isoformat()} → {to_phone} (job: {job_id})")
        return jsonify({
            'ok':           True,
            'job_id':       job_id,
            'scheduled_for': send_dt.isoformat(),
        })
    except Exception as e:
        logger.error(f"❌ [Scheduler] Error programant job {job_id}: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/whatsapp/cancel/<job_id>', methods=['DELETE'])
def cancel_whatsapp(job_id):
    """Cancela un recordatorio de WhatsApp programado"""
    if not SCHEDULER_AVAILABLE or not scheduler:
        return jsonify({'ok': False, 'error': 'Scheduler no disponible'}), 503
    try:
        job = scheduler.get_job(job_id)
        if job:
            scheduler.remove_job(job_id)
            logger.info(f"🗑️  [Scheduler] Job cancelado: {job_id}")
            return jsonify({'ok': True})
        else:
            return jsonify({'ok': False, 'error': 'Job no encontrado'}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/whatsapp/status', methods=['GET'])
def whatsapp_status():
    """Comprova si Meta Cloud API i el Scheduler estan a punt."""
    meta_ok      = bool(META_ACCESS_TOKEN and META_PHONE_NUMBER_ID)
    scheduler_ok = SCHEDULER_AVAILABLE and scheduler is not None

    reasons = []
    if not meta_ok:
        reasons.append("Variables d'entorn Meta no configurades (META_ACCESS_TOKEN, META_PHONE_NUMBER_ID)")
    if not SCHEDULER_AVAILABLE:
        reasons.append("APScheduler no instal·lat (pip install apscheduler)")
    elif not scheduler_ok:
        reasons.append("Scheduler no inicialitzat")

    return jsonify({
        'meta_ready':      meta_ok,
        'scheduler_ready': scheduler_ok,
        'fully_ready':     meta_ok and scheduler_ok,
        'reason': ' · '.join(reasons) if reasons else 'Tot configurat correctament'
    })

@app.route('/api/whatsapp/webhook', methods=['GET'])
def whatsapp_webhook_verify():
    """Verifica el webhook con Meta"""
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    verify_token = os.environ.get('WHATSAPP_WEBHOOK_TOKEN', 'your_verify_token')
    
    if token == verify_token:
        return challenge
    return 'Invalid token', 403

@app.route('/api/whatsapp/webhook', methods=['POST'])
def whatsapp_webhook_receive():
    """Recibe mensajes entrantes de Meta"""
    data = request.get_json()
    logger.info(f"📨 [Webhook] Mensaje recibido: {json.dumps(data, indent=2)}")
    return jsonify({'status': 'ok'}), 200

# ═══════════════════════════════════════════════════════════════
# API LIMPIEZA DE MENSAJES (TESTING)
# ═══════════════════════════════════════════════════════════════

@app.route('/api/messages/clear', methods=['POST'])
def clear_messages():
    """Limpia los mensajes del servidor para testing"""
    data = request.get_json(silent=True) or {}
    chat_type = data.get('chat_type', 'all')
    
    if chat_type == 'all':
        for key in list(message_storage.keys()):
            if key not in ['general', 'sede_mataro', 'sede_vilassar']:
                del message_storage[key]
        message_storage['general'].clear()
        message_storage['sede_mataro'].clear()
        message_storage['sede_vilassar'].clear()
        save_message_storage()
        logger.info('🗑️  [Clear] Todos los mensajes eliminados')
    elif chat_type == 'general':
        message_storage['general'].clear()
        logger.info('🗑️  [Clear] Chat General eliminado')
    elif chat_type == 'mataro':
        message_storage['sede_mataro'].clear()
        logger.info('🗑️  [Clear] Chat Mataró eliminado')
    elif chat_type == 'vilassar':
        message_storage['sede_vilassar'].clear()
        logger.info('🗑️  [Clear] Chat Vilassar eliminado')
    else:
        return jsonify({'ok': False, 'error': f'chat_type desconocido: {chat_type}'}), 400
    
    return jsonify({'ok': True, 'cleared': chat_type})

# ═══════════════════════════════════════════════════════════════
# API ESTADO Y HEALTH CHECK
# ═══════════════════════════════════════════════════════════════

@app.route('/api/status')
def api_status():
    """Endpoint para verificar estado de la API"""
    return jsonify({
        'status': 'ok',
        'app': 'GestióPro',
        'version': '3.0',
        'timestamp': datetime.now().isoformat(),
        'environment': app.config['ENV'],
        'meta_ready': bool(META_ACCESS_TOKEN and META_PHONE_NUMBER_ID),
        'scheduler_ready': SCHEDULER_AVAILABLE and scheduler is not None,
        'websocket_ready': True,
        'connected_users': len(connected_users)
    })

@app.route('/api/health')
def api_health():
    """Endpoint de health check para Render"""
    return jsonify({
        'status': 'healthy',
        'service': 'gestionpro',
        'timestamp': datetime.now().isoformat()
    }), 200

# ═══════════════════════════════════════════════════════════════
# API ADMIN — Eines d'administració (només rol admin)
# ═══════════════════════════════════════════════════════════════

@app.route('/api/admin/reset-data', methods=['POST'])
def admin_reset_data():
    """Esborra tots els events, missatges i recordatoris personals de la BD.
    Només accessible per usuaris amb rol 'admin'.
    NO esborra: usuaris, clients ni serveis.
    """
    # Seguretat: només admins (verificació via sessió, no via capçalera forjable)
    _uid = session.get('user_id')
    _u   = User.query.get(_uid) if _uid else None
    if not _u or _u.role != 'admin':
        return jsonify({'ok': False, 'error': 'No autoritzat'}), 403

    try:
        deleted_events    = Event.query.delete()
        deleted_messages  = Message.query.delete()
        deleted_reminders = PersonalReminder.query.delete()
        db.session.commit()

        result = {
            'ok': True,
            'deleted': {
                'events':    deleted_events,
                'messages':  deleted_messages,
                'reminders': deleted_reminders,
            },
            'timestamp': datetime.utcnow().isoformat(),
        }
        logger.info(
            f"[RESET] BD neta per admin: "
            f"{deleted_events} events, "
            f"{deleted_messages} missatges, "
            f"{deleted_reminders} recordatoris"
        )
        return jsonify(result), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"[RESET] Error: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# API EVENTS — Persistència d'events de calendari a PostgreSQL
# ═══════════════════════════════════════════════════════════════

@app.route('/api/events', methods=['GET'])
def get_events():
    """Retorna tots els events.
    Les cites privades d'altri es retornen sense detalls (només data/hora/privat=true)
    per evitar exposar dades sensibles al navegador.
    """
    try:
        current_user_id = session.get('user_id')
        events = Event.query.order_by(Event.date.asc(), Event.start_time.asc()).all()
        result = []
        for e in events:
            if e.is_private and e.created_by != current_user_id:
                # Cita privada d'un altre usuari: retornar versió enmascarada
                result.append({
                    'id':         e.id,
                    'date':       e.date,
                    'time':       e.start_time or '',
                    'timeEnd':    e.end_time or '',
                    'private':    True,
                    'client':     '',
                    'service':    '',
                    'notes':      '',
                    'assignedTo': e.assigned_to,
                    'ownerId':    e.created_by,
                    'calendarType': e.calendar_type or '',
                })
            else:
                result.append(e.to_dict())
        return jsonify({'ok': True, 'events': result})
    except Exception as e:
        logger.error(f"❌ [Events GET] {str(e)}")
        return jsonify({'ok': False, 'error': str(e), 'events': []}), 500

@app.route('/api/events', methods=['POST'])
def create_event():
    """Crea un nou event (o sèrie recurrent) i el retorna amb l'id assignat per la BD."""
    try:
        data = request.get_json(force=True) or {}
        # client_id és informatiu (prové del frontend si el client existeix a la BD)
        # però NO es persiste a Event — el nom s'emmagatzema sempre com a text a client_name
        # data.get('client_id') s'ignora intencionadament

        rrule_str          = (data.get('recurrence_rule') or '').strip() or None
        is_master          = bool(rrule_str)

        ev = Event(
            date                 = data.get('date', ''),
            start_time           = data.get('time', ''),
            end_time             = data.get('timeEnd') or None,
            client_name          = data.get('client') or None,
            client_phone         = data.get('clientPhone') or None,
            assigned_to          = int(data.get('assignedTo', 0)),
            created_by           = int(data.get('ownerId', 0)),
            calendar_type        = data.get('calendarType') or None,
            sede                 = data.get('sede') or None,
            department           = data.get('department') or None,
            service_type         = data.get('service') or None,
            notes                = data.get('notes') or None,
            is_private           = bool(data.get('private', False)),
            wa_reminder          = json.dumps(data['waReminder']) if data.get('waReminder') else None,
            pr_reminder          = json.dumps(data['prReminders']) if data.get('prReminders') else None,
            recurrence_rule      = rrule_str,
            is_recurring_master  = is_master,
        )
        db.session.add(ev)
        db.session.flush()   # assigna ev.id sense tancar la transacció

        children_count = 0
        if rrule_str:
            try:
                import itertools
                # dtstart des de la data de l'event pare
                dtstart = datetime.strptime(ev.date, '%Y-%m-%d')

                # BUG 3 fix: si no hi ha COUNT ni UNTIL afegim UNTIL=1 any
                # per evitar que rrulestr generi una seqüència infinita
                effective_rule = rrule_str
                if 'COUNT' not in rrule_str and 'UNTIL' not in rrule_str:
                    until_date = dtstart + timedelta(weeks=52)
                    effective_rule = rrule_str + f';UNTIL={until_date.strftime("%Y%m%d")}'

                rule  = rrulestr(effective_rule, dtstart=dtstart, ignoretz=True)
                # BUG 1 fix: islice evita exhaurir un generador infinit
                dates = list(itertools.islice(rule, 365))
                # BUG 2 fix: no saltar cegament dates[0]; comparar per data
                for occ_dt in dates:
                    if occ_dt.strftime('%Y-%m-%d') == ev.date:
                        continue  # és el propi event pare, no crear fill
                    child = Event(
                        date                 = occ_dt.strftime('%Y-%m-%d'),
                        start_time           = ev.start_time,
                        end_time             = ev.end_time,
                        client_name          = ev.client_name,
                        client_phone         = ev.client_phone,
                        assigned_to          = ev.assigned_to,
                        created_by           = ev.created_by,
                        calendar_type        = ev.calendar_type,
                        sede                 = ev.sede,
                        department           = ev.department,
                        service_type         = ev.service_type,
                        notes                = ev.notes,
                        is_private           = ev.is_private,
                        recurrence_master_id = ev.id,
                        is_recurring_master  = False,
                    )
                    db.session.add(child)
                    children_count += 1
            except Exception as rrule_err:
                logger.warning(f"⚠️ [Events POST] Error generant recurrència: {rrule_err}")
                # Continuem: l'event pare es desa igualment

        db.session.commit()
        logger.info(f"✅ [Events POST] Event {ev.id} creat"
                    + (f" amb {children_count} fills recurrents" if children_count else ""))
        return jsonify({'ok': True, 'event': ev.to_dict(), 'children_count': children_count}), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ [Events POST] {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/events/<int:ev_id>', methods=['PUT'])
def update_event(ev_id):
    """Actualitza un event existent.
    Body param scope:
      'this' (default) → actualitza únicament aquest event.
      'all'            → actualitza aquest event + tots els fills de la sèrie.
    """
    try:
        ev = Event.query.get(ev_id)
        if not ev:
            return jsonify({'ok': False, 'error': 'Event no trobat'}), 404
        data  = request.get_json(force=True) or {}
        scope = data.get('scope', 'this')

        def _apply_fields(target, src):
            """Aplica els camps editables del payload src a l'objecte target."""
            target.start_time  = src.get('time',        target.start_time)
            target.end_time    = src.get('timeEnd')      if 'timeEnd'    in src else target.end_time
            target.client_name = src.get('client')    or target.client_name
            target.client_phone= src.get('clientPhone') if 'clientPhone' in src else target.client_phone
            target.assigned_to = int(src['assignedTo']) if 'assignedTo'  in src else target.assigned_to
            target.service_type= src.get('service')     if 'service'     in src else target.service_type
            target.notes       = src.get('notes')        if 'notes'       in src else target.notes
            target.is_private  = bool(src['private'])    if 'private'     in src else target.is_private
            target.wa_reminder = json.dumps(src['waReminder'])  if src.get('waReminder')  else (None if 'waReminder'  in src else target.wa_reminder)
            target.pr_reminder = json.dumps(src['prReminders']) if src.get('prReminders') else (None if 'prReminders' in src else target.pr_reminder)

        # Sempre actualitzem la data de l'event clicat (pot variar per a scope='this')
        ev.date = data.get('date', ev.date)
        _apply_fields(ev, data)

        if scope == 'all':
            # Determinar l'id del mestre
            master_id = ev.recurrence_master_id if ev.recurrence_master_id else ev_id
            # Actualitzar tots els fills (excepte el propi event ja actualitzat)
            siblings = Event.query.filter(
                Event.recurrence_master_id == master_id,
                Event.id != ev_id
            ).all()
            for sib in siblings:
                # Els fills mantenen la seva data — només es copien els camps de contingut
                _apply_fields(sib, data)
            # Si l'event clicat és un fill, actualitzar també el pare
            if ev.recurrence_master_id:
                master = Event.query.get(master_id)
                if master and master.id != ev_id:
                    _apply_fields(master, data)

        db.session.commit()
        return jsonify({'ok': True, 'event': ev.to_dict()})
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ [Events PUT {ev_id}] {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/events/<int:ev_id>', methods=['DELETE'])
def delete_event(ev_id):
    """Esborra un event.
    Query param scope:
      'this'      (default) → esborra únicament aquest event.
      'all'                 → esborra el pare + TOTS els fills.
      'following'           → esborra aquest event + tots els fills amb date >= data_clicada.
                              El pare i els fills anteriors es conserven.
    """
    try:
        ev = Event.query.get(ev_id)
        if not ev:
            return jsonify({'ok': False, 'error': 'Event no trobat'}), 404

        scope = request.args.get('scope', 'this')

        if scope == 'all':
            master_id = ev.recurrence_master_id if ev.recurrence_master_id else ev_id
            # Esborrar tots els fills
            Event.query.filter(Event.recurrence_master_id == master_id).delete()
            # Esborrar el mestre
            master = Event.query.get(master_id)
            if master:
                db.session.delete(master)

        elif scope == 'following':
            # Esborrar l'event clicat + tots els fills amb date >= data d'aquest event
            cutoff_date = ev.date   # string 'YYYY-MM-DD', ordre lexicogràfic correcte
            master_id   = ev.recurrence_master_id if ev.recurrence_master_id else ev_id
            # Fills a partir de la data de tall (inclou l'event clicat si és fill)
            Event.query.filter(
                Event.recurrence_master_id == master_id,
                Event.date >= cutoff_date
            ).delete()
            # Si l'event clicat és el pare (is_recurring_master), eliminar-lo també
            if ev.is_recurring_master:
                db.session.delete(ev)
            # Si l'event clicat és un fill, ja l'hem eliminat amb el filtre anterior

        else:  # scope == 'this'
            db.session.delete(ev)

        db.session.commit()
        return jsonify({'ok': True, 'deleted': ev_id, 'scope': scope})
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ [Events DELETE {ev_id}] {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# API REMINDERS — Recordatoris personals
# ═══════════════════════════════════════════════════════════════

@app.route('/api/reminders', methods=['GET'])
def get_reminders():
    """Retorna recordatoris pendents. Filtra per user_id i opcionalment event_id."""
    try:
        user_id  = request.args.get('user_id',  type=int)
        event_id = request.args.get('event_id', type=int)
        if not user_id:
            return jsonify({'ok': False, 'error': 'user_id requerit', 'reminders': []}), 400
        q = PersonalReminder.query.filter_by(user_id=user_id, is_sent=False)
        if event_id:
            q = q.filter_by(event_id=event_id)
        reminders = q.order_by(PersonalReminder.remind_at.asc()).all()
        return jsonify({'ok': True, 'reminders': [r.to_dict() for r in reminders]})
    except Exception as e:
        logger.error(f"❌ [Reminders GET] {str(e)}")
        return jsonify({'ok': False, 'error': str(e), 'reminders': []}), 500

@app.route('/api/reminders', methods=['POST'])
def create_reminder():
    """Crea un nou recordatori personal."""
    try:
        data = request.get_json(force=True) or {}
        remind_at_str = data.get('remindAt', '')
        try:
            remind_at = datetime.fromisoformat(remind_at_str.replace('Z', '+00:00')) if remind_at_str else datetime.utcnow()
        except Exception:
            remind_at = datetime.utcnow()
        r = PersonalReminder(
            event_id  = data.get('eventId') or None,
            user_id   = int(data.get('userId', 0)),
            remind_at = remind_at,
            message   = data.get('message') or None,
            is_sent   = False,
        )
        db.session.add(r)
        db.session.commit()
        return jsonify({'ok': True, 'reminder': r.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ [Reminders POST] {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/reminders/<int:rem_id>', methods=['DELETE'])
def delete_reminder(rem_id):
    """Esborra un recordatori per id."""
    try:
        r = PersonalReminder.query.get(rem_id)
        if not r:
            return jsonify({'ok': False, 'error': 'Recordatori no trobat'}), 404
        db.session.delete(r)
        db.session.commit()
        return jsonify({'ok': True, 'deleted': rem_id})
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ [Reminders DELETE {rem_id}] {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# SERVEIS — CRUD
# ═══════════════════════════════════════════════════════════════

@app.route('/api/services', methods=['GET'])
def get_services():
    services = Service.query.filter_by(active=True).order_by(Service.id).all()
    return jsonify({'ok': True, 'services': [s.to_dict() for s in services]})

@app.route('/api/services', methods=['POST'])
def create_service():
    caller = User.query.get(session.get('user_id'))
    logger.info(f"[Services POST] user_id={session.get('user_id')} role={caller.role if caller else 'N/A'}")
    if not caller or caller.role != 'admin':
        return jsonify({'ok': False, 'error': 'Sense permisos'}), 403
    data  = request.get_json(force=True) or {}
    name  = (data.get('name') or '').strip()
    color = (data.get('color') or '#f0c080').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'El nom és obligatori'}), 400
    s = Service(name=name, color=color)
    db.session.add(s)
    db.session.commit()
    return jsonify({'ok': True, 'service': s.to_dict()}), 201

@app.route('/api/services/<int:srv_id>', methods=['PUT'])
def update_service(srv_id):
    caller = User.query.get(session.get('user_id'))
    logger.info(f"[Services PUT] user_id={session.get('user_id')} role={caller.role if caller else 'N/A'}")
    if not caller or caller.role != 'admin':
        return jsonify({'ok': False, 'error': 'Sense permisos'}), 403
    s = Service.query.get(srv_id)
    if not s:
        return jsonify({'ok': False, 'error': 'Servei no trobat'}), 404
    data  = request.get_json(force=True) or {}
    name  = (data.get('name') or '').strip()
    color = (data.get('color') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'El nom és obligatori'}), 400
    s.name  = name
    if color:
        s.color = color
    db.session.commit()
    return jsonify({'ok': True, 'service': s.to_dict()})

@app.route('/api/services/<int:srv_id>', methods=['DELETE'])
def delete_service(srv_id):
    caller = User.query.get(session.get('user_id'))
    logger.info(f"[Services DELETE] user_id={session.get('user_id')} role={caller.role if caller else 'N/A'}")
    if not caller or caller.role != 'admin':
        return jsonify({'ok': False, 'error': 'Sense permisos'}), 403
    s = Service.query.get(srv_id)
    if not s:
        return jsonify({'ok': False, 'error': 'Servei no trobat'}), 404
    s.active = False
    db.session.commit()
    return jsonify({'ok': True, 'deleted': srv_id})

# ═══════════════════════════════════════════════════════════════
# MANEJO DE ERRORES
# ═══════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(error):
    """Manejar errores 404 - Servir la app"""
    return render_template('index3.html'), 200

@app.errorhandler(500)
def server_error(error):
    """Manejar errores 500"""
    logger.error(f"Error 500: {str(error)}")
    return jsonify({'error': 'Internal server error', 'details': str(error)}), 500

# ═══════════════════════════════════════════════════════════════
# WEB PUSH — Ruta per al Service Worker
# ═══════════════════════════════════════════════════════════════

@app.route('/sw.js')
def serve_sw():
    """Serveix el Service Worker des de l'arrel perquè tingui scope complet."""
    return send_from_directory('static', 'sw.js', mimetype='application/javascript',
                               max_age=0)

# ═══════════════════════════════════════════════════════════════
# WEB PUSH — Endpoints i funció d'enviament
# ═══════════════════════════════════════════════════════════════

def get_vapid_private_key():
    """Retorna la clau privada VAPID en format EC PEM (TraditionalOpenSSL) que pywebpush espera."""
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key, Encoding, PrivateFormat, NoEncryption
    )
    key_str = os.environ.get('VAPID_PRIVATE_KEY', VAPID_PRIVATE_KEY or '').strip()
    try:
        key = load_pem_private_key(key_str.encode(), password=None)
        return key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=NoEncryption()
        ).decode()
    except Exception as e:
        logger.error(f"[Push] Error carregant clau VAPID: {e}")
        return key_str


def send_push_notification(user_id, title, body, url='/', tag='ra-push'):
    """Envia una Web Push Notification a tots els dispositius d'un usuari."""
    if not WEBPUSH_AVAILABLE:
        logger.warning(f"[Push] ⚠️  WEBPUSH_AVAILABLE=False — pywebpush no instal·lat o error d'importació")
        return
    subs = PushSubscription.query.filter_by(user_id=user_id).all()
    logger.info(f"[Push] → user_id={user_id} | subs={len(subs)} | title='{title}'")
    if not subs:
        logger.warning(f"[Push] ⚠️  Cap subscripció trobada per user_id={user_id}")
        return
    payload = json.dumps({
        'title': title,
        'body':  body,
        'url':   url,
        'tag':   tag,
        'icon':  '/static/icon.png',
    })
    private_key = get_vapid_private_key()
    logger.info(f"[Push] VAPID public_key (primeres 20c): {(VAPID_PUBLIC_KEY or '')[:20]}…")
    expired = []
    for sub in subs:
        ep_short = sub.endpoint[-40:] if sub.endpoint else '?'
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {'p256dh': sub.p256dh, 'auth': sub.auth}
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={'sub': VAPID_SUBJECT},
                ttl=86400,
            )
            logger.info(f"[Push] ✅ Enviat correctament a ...{ep_short}")
        except WebPushException as exc:
            resp_status = exc.response.status_code if exc.response is not None else 'N/A'
            resp_body   = ''
            try:
                resp_body = exc.response.text[:200] if exc.response is not None else ''
            except Exception:
                pass
            logger.error(f"[Push] ❌ WebPushException user={user_id} ep=...{ep_short} "
                         f"HTTP={resp_status} body={resp_body!r} exc={exc}")
            if resp_status in (404, 410):
                expired.append(sub)
        except ValueError as exc:
            logger.error(f"[Push] ❌ Error de format de clau VAPID ep=...{ep_short}: {exc!r}")
            expired.append(sub)
        except Exception as exc:
            logger.error(f"[Push] ❌ Excepció inesperat user={user_id} ep=...{ep_short}: {exc!r}")
    for sub in expired:
        try:
            logger.info(f"[Push] 🗑️  Eliminant subscripció expirada user={user_id}")
            db.session.delete(sub)
            db.session.commit()
        except Exception:
            db.session.rollback()

@app.route('/api/push/test', methods=['POST'])
def push_test():
    """Envia una push de prova a l'usuari actual. Útil per debugar."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'No autenticat'}), 401
    logger.info(f"[Push/test] Enviant push de prova a user_id={user_id}")
    send_push_notification(
        user_id,
        title='🔔 Prova de notificació',
        body='Si veus això, el Web Push funciona correctament!',
        url='/',
        tag='push-test',
    )
    return jsonify({'ok': True, 'message': f'Push de prova enviat a user_id={user_id}'})

@app.route('/api/push/vapid-public-key', methods=['GET'])
def get_vapid_public_key():
    """Retorna la VAPID public key (text pla) per al frontend."""
    if not WEBPUSH_AVAILABLE or not VAPID_PUBLIC_KEY:
        return ('', 503)
    return (VAPID_PUBLIC_KEY, 200, {'Content-Type': 'text/plain; charset=utf-8'})

@app.route('/api/push/subscribe', methods=['POST'])
def push_subscribe():
    """Desa o actualitza la subscripció push de l'usuari actual.
    Accepta tant el format pla {endpoint, p256dh, auth} com el format natiu
    de subscription.toJSON() {endpoint, keys: {p256dh, auth}}.
    """
    if not WEBPUSH_AVAILABLE:
        return jsonify({'ok': False, 'error': 'Web Push no disponible'}), 503
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'No autenticat'}), 401
    data     = request.get_json(silent=True) or {}
    endpoint = (data.get('endpoint') or '').strip()
    # subscription.toJSON() posa les claus dins 'keys'; acceptem ambdós formats
    nested   = data.get('keys') or {}
    p256dh   = (nested.get('p256dh') or data.get('p256dh') or '').strip()
    auth     = (nested.get('auth')   or data.get('auth')   or '').strip()
    if not endpoint or not p256dh or not auth:
        return jsonify({'ok': False, 'error': 'Falten camps (endpoint, p256dh, auth)'}), 400
    existing = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if existing:
        existing.user_id = user_id
        existing.p256dh  = p256dh
        existing.auth    = auth
    else:
        db.session.add(PushSubscription(
            user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth
        ))
    db.session.commit()
    logger.info(f"[Push] Subscripció registrada per user_id={user_id}")
    return jsonify({'ok': True})

# ═══════════════════════════════════════════════════════════════
# CREAR TAULES A LA BD (si no existeixen)
# ═══════════════════════════════════════════════════════════════

with app.app_context():
    try:
        db.create_all()
        logger.info("✅ Taules de BD creades/verificades correctament")
        # ── Migracions addicients (ADD COLUMN IF NOT EXISTS és idempotent a PostgreSQL) ──
        migrations = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token VARCHAR(100)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires TIMESTAMP",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS recurrence_rule VARCHAR(500)",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS recurrence_master_id INTEGER",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS is_recurring_master BOOLEAN DEFAULT FALSE",
            "CREATE TABLE IF NOT EXISTS wa_scheduled_jobs (id SERIAL PRIMARY KEY, job_id VARCHAR(100) UNIQUE NOT NULL, event_id INTEGER, phone VARCHAR(20) NOT NULL, nom VARCHAR(200) NOT NULL, data VARCHAR(20) NOT NULL, hora VARCHAR(10) NOT NULL, seu VARCHAR(100) NOT NULL, send_at TIMESTAMP NOT NULL, sent BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS dept_permissions (dept VARCHAR(50) PRIMARY KEY, level INTEGER DEFAULT 2 NOT NULL, access_to_depts TEXT DEFAULT '[]' NOT NULL)",
            "CREATE TABLE IF NOT EXISTS services (id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL, color VARCHAR(20) DEFAULT '#f0c080', active BOOLEAN DEFAULT TRUE, created_at TIMESTAMP DEFAULT NOW())",
            "ALTER TABLE wa_scheduled_jobs ADD COLUMN IF NOT EXISTS nom VARCHAR(200)",
            "ALTER TABLE wa_scheduled_jobs ADD COLUMN IF NOT EXISTS data VARCHAR(20)",
            "ALTER TABLE wa_scheduled_jobs ADD COLUMN IF NOT EXISTS hora VARCHAR(10)",
            "ALTER TABLE wa_scheduled_jobs ADD COLUMN IF NOT EXISTS seu VARCHAR(100)",
        ]
        for sql in migrations:
            try:
                db.session.execute(text(sql))
            except Exception as mig_e:
                logger.warning(f"⚠️ Migració ignorada ({sql[:60]}…): {mig_e}")
                db.session.rollback()
        db.session.commit()
        seed_users()
        seed_services()
    except Exception as _e:
        logger.error(f"❌ Error creant taules o seed: {_e}")

# ═══════════════════════════════════════════════════════════════
# INICIALIZAR SCHEDULER (si está disponible)
# ═══════════════════════════════════════════════════════════════

def check_personal_reminders():
    """Comprova recordatoris personals pendents i envia push si és l'hora."""
    with app.app_context():
        try:
            now = datetime.utcnow()
            pending = PersonalReminder.query.filter(
                PersonalReminder.is_sent == False,
                PersonalReminder.remind_at <= now
            ).all()
            for r in pending:
                send_push_notification(r.user_id, 'Recordatori de cita', r.message or 'Tens una cita pròximament')
                r.is_sent = True
            if pending:
                db.session.commit()
                logger.info(f"[Reminders] {len(pending)} recordatoris enviats")
        except Exception as _e:
            logger.error(f"[Reminders] Error en check_personal_reminders: {_e}")
            db.session.rollback()


scheduler = None
if SCHEDULER_AVAILABLE:
    scheduler = BackgroundScheduler()
    scheduler.start()
    logger.info("✅ APScheduler iniciado")
    scheduler.add_job(
        check_personal_reminders,
        'interval',
        seconds=60,
        id='check_personal_reminders',
    )
    recover_pending_jobs()

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = '0.0.0.0'
    
    socketio.run(
        app,
        host=host,
        port=port,
        debug=app.config['DEBUG'],
        allow_unsafe_werkzeug=True
    )
