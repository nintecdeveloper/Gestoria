import os
import json
import threading
from flask import Flask, render_template, jsonify, request, send_file, redirect, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from io import BytesIO
import io
import requests
import logging
import base64
import pandas as pd
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
META_API_VERSION = "v18.0"
META_API_URL = f"https://graph.facebook.com/{META_API_VERSION}/{{phone_id}}/messages"

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

CATALAN_DAYS = {
    0: 'Dilluns', 1: 'Dimarts', 2: 'Dimecres', 3: 'Dijous',
    4: 'Divendres', 5: 'Dissabte', 6: 'Diumenge'
}

def format_date_catalan(date_str: str) -> str:
    """Formata una data YYYY-MM-DD en català: 'Dijous 05/03/2026'."""
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    day_name = CATALAN_DAYS[dt.weekday()]
    return f"{day_name} {dt.strftime('%d/%m/%Y')}"

def send_whatsapp_meta(to_phone: str, message: str, message_type: str = "text",
                       template_params: list = None):
    """Envía un mensaje de WhatsApp via Meta Cloud API."""
    logger.info(f"📞 [Meta API] Iniciant enviament: to_phone={to_phone}, type={message_type}, params={template_params}")

    if not META_PHONE_NUMBER_ID or not META_ACCESS_TOKEN:
        logger.error(f"❌ [Meta API] Credencials no configurades: PHONE_ID={'SET' if META_PHONE_NUMBER_ID else 'MISSING'}, TOKEN={'SET' if META_ACCESS_TOKEN else 'MISSING'}")
        return {
            'ok': False,
            'error': 'Credenciales Meta no configuradas en variables de entorno.',
            'configured': False
        }

    phone = to_phone.strip()
    if not phone.startswith('+'):
        phone = '+34' + phone.lstrip('0')

    if message_type == "text":
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message
            }
        }
    else:
        template_data = {
            "name": message_type,
            "language": {
                "code": "ca"
            }
        }
        if template_params:
            template_data["components"] = [{
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in template_params]
            }]
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": template_data
        }

    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    url = META_API_URL.format(phone_id=META_PHONE_NUMBER_ID)

    logger.info(f"📞 [Meta API] URL: {url}")
    logger.info(f"📞 [Meta API] Payload: {json.dumps(payload, ensure_ascii=False)}")
    logger.info(f"📞 [Meta API] Phone formatted: {phone} → API to: {phone.replace('+', '')}")

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        logger.info(f"📞 [Meta API] Response status: {response.status_code}")
        logger.info(f"📞 [Meta API] Response body: {response.text}")
        response.raise_for_status()

        result = response.json()
        msg_id = result.get('messages', [{}])[0].get('id')
        logger.info(f"✅ [Meta API] Missatge enviat a {phone} · ID: {msg_id}")

        return {
            'ok': True,
            'message_id': msg_id,
            'phone': phone
        }
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ [Meta API] HTTP Error {response.status_code}: {response.text}")
        return {
            'ok': False,
            'error': f"HTTP {response.status_code}: {response.text}"
        }
    except Exception as e:
        logger.error(f"❌ [Meta API] Error: {str(e)}")
        return {
            'ok': False,
            'error': str(e)
        }

# ═══════════════════════════════════════════════════════════════
# SCHEDULER — FUNCIONES
# ═══════════════════════════════════════════════════════════════

def send_whatsapp_job(to_phone: str, message: str, message_type: str = "text",
                      template_params: list = None, job_id: str = None):
    """Trabajo del scheduler para enviar WhatsApp.
    Paràmetre job_id opcional per marcar el registre com a sent=True a BD.
    """
    result = send_whatsapp_meta(to_phone, message, message_type=message_type,
                                template_params=template_params)
    if result['ok']:
        logger.info(f"✅ [Scheduler/Meta] Recordatorio enviado a {to_phone}")
    else:
        logger.error(f"❌ [Scheduler/Meta] Error: {result.get('error')}")

    # Marcar com a enviat a la BD (si tenim job_id i app context)
    if job_id:
        try:
            with app.app_context():
                rec = WaScheduledJob.query.filter_by(job_id=job_id).first()
                if rec:
                    rec.sent = True
                    db.session.commit()
                    logger.info(f"✅ [WaJob] Marcat sent=True per job_id={job_id}")
        except Exception as _e:
            logger.error(f"❌ [WaJob] Error marcant sent=True: {_e}")

    # Notificar a usuarios conectados
    socketio.emit(
        'notification_received',
        {
            'type': 'reminder',
            'title': 'Recordatori de cita',
            'message': message,
            'timestamp': datetime.now().isoformat()
        },
        broadcast=True
    )

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
    wa_reminder   = db.Column(db.String(500), nullable=True)   # JSON string
    pr_reminder   = db.Column(db.String(1000),nullable=True)   # JSON string
    google_calendar_event_id = db.Column(db.String(255), nullable=True)  # Google Calendar sync
    created_at    = db.Column(db.DateTime,    default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':           self.id,
            'ownerId':      self.created_by,
            'assignedTo':   self.assigned_to,
            'date':         self.date,
            'time':         self.start_time,
            'timeEnd':      self.end_time,
            'client':       self.client_name or '',
            'service':      self.service_type or '',
            'notes':        self.notes or '',
            'private':      bool(self.is_private),
            'clientPhone':  self.client_phone,
            'calendarType': self.calendar_type,
            'sede':         self.sede,
            'department':   self.department,
            'waReminders':  json.loads(self.wa_reminder) if self.wa_reminder else [],
            'prReminders':  json.loads(self.pr_reminder) if self.pr_reminder else [],
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

class WaScheduledJob(db.Model):
    """Persisteix els recordatoris WhatsApp programats a PostgreSQL.
    Permet recuperar-los si el servidor es reinicia (Render free tier dorm).
    """
    __tablename__ = 'wa_scheduled_jobs'
    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    job_id        = db.Column(db.String(100), unique=True, nullable=False, index=True)
    event_id      = db.Column(db.Integer, nullable=True)
    phone         = db.Column(db.String(20), nullable=False)
    template_vars = db.Column(db.JSON, nullable=False)  # {nom, data, hora, seu}
    send_at       = db.Column(db.DateTime(timezone=True), nullable=False)
    sent          = db.Column(db.Boolean, default=False, nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

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
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    async_mode='threading'
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
# RUTAS PRINCIPALES
# ═══════════════════════════════════════════════════════════════

@app.after_request
def add_no_cache_headers(response):
    """Evitar cache del navegador per assegurar que sempre carrega la versió més recent."""
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

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
    """Recupera missatges d'una conversa des de PostgreSQL."""
    if not conv_id:
        return jsonify({'ok': False, 'error': 'conv_id requerit', 'messages': []}), 400
    try:
        # Normalitzar conv_id privat per ordre alfabètic
        norm_id = conv_id
        if conv_id.startswith('private_'):
            parts = conv_id.replace('private_', '', 1).split('_', 1)
            if len(parts) == 2:
                norm_id = private_conv_id(parts[0], parts[1])

        msgs = (Message.query
                .filter_by(conv_id=norm_id)
                .order_by(Message.msg_timestamp.asc(), Message.created_at.asc())
                .all())

        # Safety net: si no hi ha missatges al conv_id normalitzat,
        # provar l'ordre invers per compatibilitat amb missatges antics
        if not msgs and norm_id != conv_id:
            msgs = (Message.query
                    .filter_by(conv_id=conv_id)
                    .order_by(Message.msg_timestamp.asc(), Message.created_at.asc())
                    .all())
            norm_id = conv_id if msgs else norm_id

        return jsonify({'ok': True, 'conv_id': norm_id, 'messages': [m.to_dict() for m in msgs]})
    except Exception as e:
        logger.error(f"[Messages GET] Error: {str(e)}")
        return jsonify({'ok': False, 'error': str(e), 'messages': []}), 500

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
        # Filtrar només conv_ids rellevants per a l'usuari:
        # - xats de grup (general, seus)
        # - xats privats on l'usuari és emissor o receptor
        from sqlalchemy import or_
        GROUP_CONVS = ['general', 'sede_mataro', 'sede_vilassar']
        conv_ids = [
            row[0] for row in
            db.session.query(Message.conv_id).filter(
                or_(
                    Message.conv_id.in_(GROUP_CONVS),
                    Message.sender_username == username,
                    Message.recipient_username == username
                )
            ).distinct().all()
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
    """Retorna la llista d'usuaris (sense contrasenya)"""
    return jsonify({'ok': True, 'usuarios': USUARIOS})

@app.route('/api/usuarios', methods=['POST'])
def crear_usuario():
    """
    Crea un nou usuari amb contrasenya generada automàticament.
    Body JSON esperat:
      {
        "username": "anna_m",       ← obligatori, per generar la contrasenya
        "nombre":   "Anna Martí",   ← obligatori
        "email":    "anna@...",     ← obligatori
        "departamento": "fiscal",   ← obligatori
        "rol":      "user",         ← opcional, default "user"
        "sede":     "Vilassar"      ← obligatori
      }
    Retorna el nou usuari + la contrasenya generada.
    """
    data = request.get_json(silent=True) or {}

    username     = data.get('username', '').strip()
    nombre       = data.get('nombre', '').strip()
    email        = data.get('email', '').strip()
    departamento = data.get('departamento', '').strip()
    rol          = data.get('rol', 'user').strip()
    sede         = data.get('sede', '').strip()

    # Validació camps obligatoris
    if not username or not nombre or not email or not departamento or not sede:
        return jsonify({
            'ok': False,
            'error': 'Falten camps obligatoris: username, nombre, email, departamento, sede'
        }), 400

    # Comprovar que el username no existeixi ja
    usernames_existents = [u.get('username', '').lower() for u in USUARIOS if 'username' in u]
    if username.lower() in usernames_existents:
        return jsonify({'ok': False, 'error': f"El username '{username}' ja existeix"}), 409

    # Generar contrasenya automàtica
    password = generar_password_username(username)

    # Generar nou ID (el màxim actual + 1)
    nou_id = max((u['id'] for u in USUARIOS), default=0) + 1

    nou_usuari = {
        'id':           nou_id,
        'username':     username,
        'nombre':       nombre,
        'email':        email,
        'departamento': departamento,
        'rol':          rol,
        'sede':         sede,
        'password':     password   # ← contrasenya generada automàticament
    }

    USUARIOS.append(nou_usuari)
    logger.info(f"✅ [Usuari] Creat: {nombre} (username: {username}, pass: {password})")

    # Crear chats de sede automàticament
    create_seat_chats(nou_id, nombre, sede)

    return jsonify({
        'ok':      True,
        'usuario': nou_usuari,
        'password_generada': password   # ← es mostra un sol cop, aquí
    }), 201
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

def ensure_clients_table():
    """Crea la taula clients si no existeix."""
    if not PSYCOPG2_AVAILABLE or not DATABASE_URL:
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(255) NOT NULL,
                telefono VARCHAR(50),
                email VARCHAR(255),
                direccion TEXT,
                ciudad VARCHAR(100),
                cif VARCHAR(20),
                notas TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # Assegurar índex UNIQUE en telefono (necessari per ON CONFLICT)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_telefono
            ON clients (telefono) WHERE telefono IS NOT NULL AND telefono != ''
        """)
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ [DB] Taula 'clients' verificada/creada correctament")
    except Exception as e:
        logger.error(f"❌ [DB] Error creant taula clients: {str(e)}")

# Crear taula al arrancar
ensure_clients_table()

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
    """Crea o actualitza un client individual a PostgreSQL."""
    logger.info(f"📥 [Clients POST] Petició rebuda")
    if not PSYCOPG2_AVAILABLE:
        logger.error("❌ [Clients POST] psycopg2 no disponible")
        return jsonify({'ok': False, 'error': 'psycopg2 no disponible'}), 500
    if not DATABASE_URL:
        logger.error("❌ [Clients POST] DATABASE_URL no configurada")
        return jsonify({'ok': False, 'error': 'DATABASE_URL no configurada'}), 500

    data = request.get_json(silent=True) or {}
    logger.info(f"📥 [Clients POST] Dades: name={data.get('name')}, phone={data.get('phone')}, id={data.get('id')}")
    nombre = (data.get('name') or '').strip()
    telefono = (data.get('phone') or '').strip()
    email = (data.get('email') or '').strip()
    direccion = (data.get('address') or '').strip()
    ciudad = (data.get('city') or '').strip()
    cif = (data.get('cif') or '').strip()
    notas = (data.get('notes') or '').strip()
    client_id = data.get('id')  # Si ve un ID, és una actualització

    if not nombre or not telefono:
        return jsonify({'ok': False, 'error': 'Nom i telèfon són obligatoris'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if client_id:
            # Actualització d'un client existent
            cur.execute("""
                UPDATE clients SET nombre=%s, telefono=%s, email=%s, direccion=%s,
                       ciudad=%s, cif=%s, notas=%s
                WHERE id=%s
                RETURNING id
            """, (nombre, telefono, email, direccion, ciudad, cif, notas, client_id))
            row = cur.fetchone()
            if not row:
                cur.close()
                conn.close()
                return jsonify({'ok': False, 'error': 'Client no trobat'}), 404
            result_id = row[0]
        else:
            # Nou client
            cur.execute("""
                INSERT INTO clients (nombre, telefono, email, direccion, ciudad, cif, notas, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (telefono) DO UPDATE SET nombre=EXCLUDED.nombre,
                    email=EXCLUDED.email, direccion=EXCLUDED.direccion,
                    ciudad=EXCLUDED.ciudad, cif=EXCLUDED.cif, notas=EXCLUDED.notas
                RETURNING id
            """, (nombre, telefono, email, direccion, ciudad, cif, notas))
            result_id = cur.fetchone()[0]

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"✅ [Clients] Client guardat: {nombre} (id={result_id})")
        return jsonify({'ok': True, 'id': result_id})

    except Exception as e:
        logger.error(f"❌ [Clients] Error creant client: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/clients/import', methods=['POST'])
def import_clients_db():
    """Importa clients des d'Excel o CSV a PostgreSQL. Només admins."""

    # Seguretat: només admins
    user_role = request.headers.get('X-User-Role', '')
    if user_role != 'admin':
        return jsonify({'ok': False, 'error': 'Accés denegat. Només administradors.'}), 403

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
    """Envía un mensaje de WhatsApp (texto o plantilla recordatori)"""
    data = request.get_json(silent=True) or {}
    to_phone = data.get('to', '').strip()
    use_template = data.get('use_template', False)
    logger.info(f"📤 [WA Send] Petició rebuda: to={to_phone}, use_template={use_template}, data={data}")

    if not to_phone:
        return jsonify({'ok': False, 'error': 'Falta el campo "to"'}), 400

    if use_template:
        client_name = data.get('client', '').strip()
        event_date = data.get('date', '').strip()
        event_time = data.get('time', '').strip()
        event_sede = data.get('sede', '').strip()
        if not all([client_name, event_date, event_time, event_sede]):
            return jsonify({'ok': False, 'error': 'Falten camps: client, date, time, sede'}), 400
        date_formatted = format_date_catalan(event_date)
        time_formatted = event_time if event_time.endswith('h') else event_time + 'h'
        template_params = [client_name, date_formatted, time_formatted, event_sede]
        result = send_whatsapp_meta(to_phone, '', message_type='nom_recordatori_cita',
                                    template_params=template_params)
    else:
        message = data.get('message', '').strip()
        if not message:
            return jsonify({'ok': False, 'error': 'Falta el campo "message"'}), 400
        result = send_whatsapp_meta(to_phone, message)

    return jsonify(result)

@app.route('/api/whatsapp/schedule', methods=['POST'])
def schedule_whatsapp():
    """Programa el envío de un WhatsApp en una fecha/hora futura"""
    if not SCHEDULER_AVAILABLE or not scheduler:
        return jsonify({
            'ok': False,
            'error': 'APScheduler no disponible. pip install apscheduler',
            'configured': False
        }), 503

    data = request.get_json(silent=True) or {}
    to_phone = data.get('to', '').strip()
    message = data.get('message', '').strip()
    send_at = data.get('send_at', '').strip()
    job_id = data.get('job_id', '').strip()
    use_template = data.get('use_template', False)

    if not to_phone or not send_at or not job_id:
        return jsonify({'ok': False, 'error': 'Faltan campos: to, send_at, job_id'}), 400

    if use_template:
        client_name = data.get('client', '').strip()
        event_date = data.get('date', '').strip()
        event_time = data.get('time', '').strip()
        event_sede = data.get('sede', '').strip()
        if not all([client_name, event_date, event_time, event_sede]):
            return jsonify({'ok': False, 'error': 'Falten camps: client, date, time, sede'}), 400
    elif not message:
        return jsonify({'ok': False, 'error': 'Falta el campo "message"'}), 400

    # Parsear la fecha de envío
    try:
        send_dt = datetime.fromisoformat(send_at)
        if send_dt.tzinfo is None:
            madrid = pytz.timezone('Europe/Madrid')
            send_dt = madrid.localize(send_dt)
    except ValueError:
        return jsonify({'ok': False, 'error': f'Formato de send_at inválido: {send_at}'}), 400

    # Si la fecha ya pasó, no programar
    now_tz = datetime.now(pytz.timezone('Europe/Madrid'))
    if send_dt <= now_tz:
        return jsonify({'ok': False, 'error': 'La fecha de envío ya ha pasado'}), 400

    # Eliminar job anterior con el mismo ID si existe (APScheduler + BD)
    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    except Exception:
        pass
    try:
        old_rec = WaScheduledJob.query.filter_by(job_id=job_id).first()
        if old_rec:
            db.session.delete(old_rec)
            db.session.commit()
    except Exception:
        pass

    # Preparar argumentos del job
    if use_template:
        date_formatted = format_date_catalan(event_date)
        time_formatted = event_time if event_time.endswith('h') else event_time + 'h'
        template_params = [client_name, date_formatted, time_formatted, event_sede]
        job_args = [to_phone, '', 'nom_recordatori_cita', template_params, job_id]
        tpl_vars = {'nom': client_name, 'data': date_formatted,
                    'hora': time_formatted, 'seu': event_sede}
    else:
        job_args = [to_phone, message, 'text', None, job_id]
        tpl_vars = {'missatge': message}

    # Desar a BD (persistència entre reinicis)
    event_id_val = data.get('event_id') or None
    try:
        rec = WaScheduledJob(
            job_id        = job_id,
            event_id      = int(event_id_val) if event_id_val else None,
            phone         = to_phone,
            template_vars = tpl_vars,
            send_at       = send_dt,
            sent          = False
        )
        db.session.add(rec)
        db.session.commit()
        logger.info(f"💾 [WaJob] Desat a BD: {job_id} → {send_dt.isoformat()}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ [WaJob] Error desant a BD: {e}")
        # Continuar igualment — el job s'afegirà a APScheduler

    # Programar el trabajo
    try:
        scheduler.add_job(
            func=send_whatsapp_job,
            trigger=DateTrigger(run_date=send_dt),
            args=job_args,
            id=job_id,
            replace_existing=True
        )
        logger.info(f"📅 [Scheduler] Meta WA programado para {send_dt.isoformat()} → {to_phone} (job: {job_id})")
        return jsonify({
            'ok': True,
            'job_id': job_id,
            'scheduled_for': send_dt.isoformat()
        })
    except Exception as e:
        logger.error(f"❌ [Scheduler] Error al programar job {job_id}: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/whatsapp/cancel/<job_id>', methods=['DELETE'])
def cancel_whatsapp(job_id):
    """Cancela un recordatorio de WhatsApp programado (APScheduler + BD)"""
    if not SCHEDULER_AVAILABLE or not scheduler:
        return jsonify({'ok': False, 'error': 'Scheduler no disponible'}), 503
    removed_scheduler = False
    removed_db = False
    try:
        job = scheduler.get_job(job_id)
        if job:
            scheduler.remove_job(job_id)
            removed_scheduler = True
            logger.info(f"🗑️  [Scheduler] Job cancelado: {job_id}")
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    # Esborrar de la BD
    try:
        rec = WaScheduledJob.query.filter_by(job_id=job_id).first()
        if rec:
            db.session.delete(rec)
            db.session.commit()
            removed_db = True
            logger.info(f"🗑️  [WaJob] Esborrat de BD: {job_id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ [WaJob] Error esborrant de BD: {e}")

    if removed_scheduler or removed_db:
        return jsonify({'ok': True})
    else:
        return jsonify({'ok': False, 'error': 'Job no encontrado'}), 404

@app.route('/api/whatsapp/test', methods=['GET'])
def whatsapp_test():
    """Endpoint de diagnòstic: envia un missatge de prova via Meta API.
    Ús: GET /api/whatsapp/test?to=34612345678
    Retorna tots els detalls de la crida per diagnosticar errors."""
    to_phone = request.args.get('to', '').strip()
    if not to_phone:
        return jsonify({
            'ok': False,
            'error': 'Afegeix ?to=34XXXXXXXXX al URL',
            'config': {
                'META_PHONE_NUMBER_ID': 'SET' if META_PHONE_NUMBER_ID else 'MISSING',
                'META_ACCESS_TOKEN': f"SET ({len(META_ACCESS_TOKEN)} chars)" if META_ACCESS_TOKEN else 'MISSING',
                'META_BUSINESS_ACCOUNT_ID': 'SET' if META_BUSINESS_ACCOUNT_ID else 'MISSING',
                'META_API_URL': META_API_URL.format(phone_id=META_PHONE_NUMBER_ID or 'MISSING'),
            }
        })
    # Enviar plantilla de prova
    result = send_whatsapp_meta(
        to_phone=to_phone,
        message='',
        message_type='nom_recordatori_cita',
        template_params=['Client Prova', 'Dimarts 15/04/2026', '10:00h', 'Mataró']
    )
    return jsonify({
        'result': result,
        'config': {
            'META_PHONE_NUMBER_ID': META_PHONE_NUMBER_ID[:4] + '...' if META_PHONE_NUMBER_ID else 'MISSING',
            'META_ACCESS_TOKEN': f"{META_ACCESS_TOKEN[:10]}...({len(META_ACCESS_TOKEN)} chars)" if META_ACCESS_TOKEN else 'MISSING',
            'META_API_URL': META_API_URL.format(phone_id=META_PHONE_NUMBER_ID or 'MISSING'),
        }
    })

@app.route('/api/whatsapp/status', methods=['GET'])
def whatsapp_status():
    """Comprueba si Meta API y el Scheduler están listos, incluyendo validación del token."""
    meta_configured = bool(META_PHONE_NUMBER_ID and META_ACCESS_TOKEN)
    scheduler_ok = SCHEDULER_AVAILABLE and scheduler is not None
    token_expired = False
    token_error = None

    # Si les credencials estan configurades, verificar que el token és vàlid
    # fent una crida GET lleugera a la Meta Graph API
    if meta_configured:
        try:
            import requests as req
            verify_url = f"https://graph.facebook.com/{META_API_VERSION}/{META_PHONE_NUMBER_ID}"
            verify_resp = req.get(verify_url, headers={
                "Authorization": f"Bearer {META_ACCESS_TOKEN}"
            }, params={"fields": "id"}, timeout=5)
            if verify_resp.status_code == 190 or (
                verify_resp.status_code == 401
            ):
                token_expired = True
                token_error = "Token Meta caducat o invàlid (HTTP 401)"
                logger.warning(f"⚠️ [WA Status] TOKEN CADUCAT — La crida a Meta API ha retornat HTTP {verify_resp.status_code}")
            elif verify_resp.status_code != 200:
                # Meta retorna 400 amb suberror 463/190 quan el token caduca
                resp_body = verify_resp.json() if verify_resp.headers.get('content-type', '').startswith('application/json') else {}
                error_data = resp_body.get('error', {})
                error_code = error_data.get('code', 0)
                error_subcode = error_data.get('error_subcode', 0)
                error_msg = error_data.get('message', '')
                if error_code == 190 or error_subcode in (463, 467):
                    token_expired = True
                    token_error = f"Token Meta caducat: {error_msg}"
                    logger.warning(f"⚠️ [WA Status] TOKEN CADUCAT — code={error_code} subcode={error_subcode} msg={error_msg}")
                else:
                    token_error = f"Meta API error (HTTP {verify_resp.status_code}): {error_msg or verify_resp.text[:200]}"
                    logger.warning(f"⚠️ [WA Status] Error verificant token: HTTP {verify_resp.status_code} — {error_msg or verify_resp.text[:200]}")
            else:
                logger.info(f"✅ [WA Status] Token Meta vàlid — phone_id verificat")
        except Exception as e:
            token_error = f"Error connectant amb Meta API: {str(e)}"
            logger.warning(f"⚠️ [WA Status] No s'ha pogut verificar el token: {str(e)}")

    meta_ok = meta_configured and not token_expired

    reasons = []
    if not meta_configured:
        reasons.append("Variables de entorno Meta no configuradas (META_PHONE_NUMBER_ID, META_ACCESS_TOKEN)")
    if token_expired:
        reasons.append(f"⚠️ TOKEN CADUCAT: {token_error}")
    elif token_error:
        reasons.append(f"Avís token: {token_error}")
    if not SCHEDULER_AVAILABLE:
        reasons.append("APScheduler no instalado (pip install apscheduler)")
    elif not scheduler_ok:
        reasons.append("Scheduler no inicializado")

    status = {
        'meta_ready': meta_ok,
        'token_expired': token_expired,
        'scheduler_ready': scheduler_ok,
        'fully_ready': meta_ok and scheduler_ok,
        'reason': ' · '.join(reasons) if reasons else 'Tot configurat correctament'
    }
    if token_error:
        status['token_error'] = token_error
    logger.info(f"📱 [WA Status] meta_ready={meta_ok} token_expired={token_expired} scheduler_ready={scheduler_ok} fully_ready={meta_ok and scheduler_ok}")
    return jsonify(status)

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
        'meta_ready': bool(META_PHONE_NUMBER_ID and META_ACCESS_TOKEN),
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
    user_role = request.headers.get('X-User-Role', '')
    if user_role != 'admin':
        return jsonify({'ok': False, 'error': 'Accés denegat. Nomes administradors.'}), 403

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
    """Retorna tots els events. El frontend s'encarrega del filtratge per permisos."""
    try:
        events = Event.query.order_by(Event.date.asc(), Event.start_time.asc()).all()
        return jsonify({'ok': True, 'events': [e.to_dict() for e in events]})
    except Exception as e:
        logger.error(f"❌ [Events GET] {str(e)}")
        return jsonify({'ok': False, 'error': str(e), 'events': []}), 500

@app.route('/api/events', methods=['POST'])
def create_event():
    """Crea un nou event i el retorna amb l'id assignat per la BD."""
    try:
        data = request.get_json(force=True) or {}
        logger.info(f"📅 [Events POST] waReminders={data.get('waReminders')}, prReminders={data.get('prReminders')}")
        ev = Event(
            date          = data.get('date', ''),
            start_time    = data.get('time', ''),
            end_time      = data.get('timeEnd') or None,
            client_name   = data.get('client') or None,
            client_phone  = data.get('clientPhone') or None,
            assigned_to   = int(data.get('assignedTo', 0)),
            created_by    = int(data.get('ownerId', 0)),
            calendar_type = data.get('calendarType') or None,
            sede          = data.get('sede') or None,
            department    = data.get('department') or None,
            service_type  = data.get('service') or None,
            notes         = data.get('notes') or None,
            is_private    = bool(data.get('private', False)),
            wa_reminder   = json.dumps(data['waReminders']) if data.get('waReminders') else None,
            pr_reminder   = json.dumps(data['prReminders']) if data.get('prReminders') else None,
        )
        db.session.add(ev)
        db.session.commit()

        # Sync asíncron a Google Calendar
        ev_id = ev.id
        def _sync_new():
            from calendar_sync import sync_event_to_calendar
            with app.app_context():
                event = Event.query.get(ev_id)
                if event:
                    sync_event_to_calendar(event, db.session)
        threading.Thread(target=_sync_new, daemon=True).start()

        return jsonify({'ok': True, 'event': ev.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ [Events POST] {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/events/<int:ev_id>', methods=['PUT'])
def update_event(ev_id):
    """Actualitza un event existent."""
    try:
        ev = Event.query.get(ev_id)
        if not ev:
            return jsonify({'ok': False, 'error': 'Event no trobat'}), 404
        data = request.get_json(force=True) or {}
        logger.info(f"📅 [Events PUT {ev_id}] waReminders={data.get('waReminders')}, prReminders={data.get('prReminders')}")
        ev.date          = data.get('date', ev.date)
        ev.start_time    = data.get('time', ev.start_time)
        ev.end_time      = data.get('timeEnd') if 'timeEnd' in data else ev.end_time
        ev.client_name   = data.get('client') or ev.client_name
        ev.client_phone  = data.get('clientPhone') if 'clientPhone' in data else ev.client_phone
        ev.assigned_to   = int(data['assignedTo']) if 'assignedTo' in data else ev.assigned_to
        ev.service_type  = data.get('service') if 'service' in data else ev.service_type
        ev.notes         = data.get('notes') if 'notes' in data else ev.notes
        ev.is_private    = bool(data['private']) if 'private' in data else ev.is_private
        ev.wa_reminder   = json.dumps(data['waReminders']) if data.get('waReminders') else (None if 'waReminders' in data else ev.wa_reminder)
        ev.pr_reminder   = json.dumps(data['prReminders']) if data.get('prReminders') else (None if 'prReminders' in data else ev.pr_reminder)
        db.session.commit()

        # Sync asíncron a Google Calendar
        def _sync_update():
            from calendar_sync import sync_event_to_calendar
            with app.app_context():
                event = Event.query.get(ev_id)
                if event:
                    sync_event_to_calendar(event, db.session)
        threading.Thread(target=_sync_update, daemon=True).start()

        return jsonify({'ok': True, 'event': ev.to_dict()})
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ [Events PUT {ev_id}] {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/events/<int:ev_id>', methods=['DELETE'])
def delete_event(ev_id):
    """Esborra un event."""
    try:
        ev = Event.query.get(ev_id)
        if not ev:
            return jsonify({'ok': False, 'error': 'Event no trobat'}), 404

        # Eliminar del Google Calendar abans d'esborrar de la BD
        gcal_id = ev.google_calendar_event_id
        db.session.delete(ev)
        db.session.commit()

        if gcal_id:
            def _sync_delete():
                from calendar_sync import delete_event_from_calendar
                from types import SimpleNamespace
                dummy = SimpleNamespace(google_calendar_event_id=gcal_id)
                delete_event_from_calendar(dummy)
            threading.Thread(target=_sync_delete, daemon=True).start()

        return jsonify({'ok': True, 'deleted': ev_id})
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ [Events DELETE {ev_id}] {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# GOOGLE CALENDAR — OAuth Web Flow (autorització externa)
# ═══════════════════════════════════════════════════════════════

GOOGLE_AUTH_TOKEN = os.environ.get('GOOGLE_AUTH_TOKEN')
RENDER_API_KEY = os.environ.get('RENDER_API_KEY')
RENDER_SERVICE_ID = os.environ.get('RENDER_SERVICE_ID')
GOOGLE_OAUTH_REDIRECT_URI = 'https://gestoriarodonverges.com/auth/google/callback'

@app.route('/auth/google')
def google_auth_start():
    """
    Redirigeix l'usuari a Google per autoritzar el Calendar.
    Protegit amb token secret a la URL: /auth/google?token=XXXX
    """
    logger.info(f"🔑 [Google Auth] Inici del flow OAuth")
    try:
        # Validar token secret
        token = request.args.get('token')
        logger.info(f"🔑 [Google Auth] GOOGLE_AUTH_TOKEN configurat: {'SÍ' if GOOGLE_AUTH_TOKEN else 'NO'}")
        logger.info(f"🔑 [Google Auth] Token URL present: {'SÍ' if token else 'NO'}")
        if not GOOGLE_AUTH_TOKEN or token != GOOGLE_AUTH_TOKEN:
            logger.warning(f"🔑 [Google Auth] Token invàlid o no configurat")
            return jsonify({'error': 'Accés denegat'}), 403

        client_id = os.environ.get('GOOGLE_CLIENT_ID')
        client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
        logger.info(f"🔑 [Google Auth] GOOGLE_CLIENT_ID: {'SET (' + client_id[:8] + '...)' if client_id else 'MISSING'}")
        logger.info(f"🔑 [Google Auth] GOOGLE_CLIENT_SECRET: {'SET (' + str(len(client_secret)) + ' chars)' if client_secret else 'MISSING'}")
        if not client_id or not client_secret:
            logger.error(f"❌ [Google Auth] Credencials Google NO configurades")
            return jsonify({'error': 'Credencials Google no configurades al servidor'}), 500

        logger.info(f"🔑 [Google Auth] Redirect URI: {GOOGLE_OAUTH_REDIRECT_URI}")

        try:
            from google_auth_oauthlib.flow import Flow
            logger.info(f"🔑 [Google Auth] google_auth_oauthlib importat correctament")
        except ImportError as ie:
            logger.error(f"❌ [Google Auth] No s'ha pogut importar google_auth_oauthlib: {ie}")
            return jsonify({'error': f'Mòdul google-auth-oauthlib no instal·lat: {ie}'}), 500

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [GOOGLE_OAUTH_REDIRECT_URI],
                }
            },
            scopes=['https://www.googleapis.com/auth/calendar'],
            redirect_uri=GOOGLE_OAUTH_REDIRECT_URI,
        )
        logger.info(f"🔑 [Google Auth] Flow creat correctament")

        authorization_url, state = flow.authorization_url(
            access_type='offline',
            prompt='consent',
            login_hint='pau@rodonverges.com',
        )
        logger.info(f"🔑 [Google Auth] URL d'autorització generada, state={state[:20]}...")

        # Guardar state a la sessió per validar al callback
        from flask import session
        session['google_oauth_state'] = state
        session['google_auth_token'] = token  # per re-validar al callback
        logger.info(f"🔑 [Google Auth] State guardat a la sessió. Redirigint a Google...")

        return redirect(authorization_url)

    except Exception as e:
        logger.error(f"❌ [Google Auth] Error inesperat: {type(e).__name__}: {str(e)}", exc_info=True)
        return jsonify({'error': f'Error intern: {type(e).__name__}: {str(e)}'}), 500

@app.route('/auth/google/callback')
def google_auth_callback():
    """
    Callback de Google OAuth. Rep el codi d'autorització,
    obté el refresh_token i el guarda a Render via API.
    """
    logger.info(f"🔑 [Google Callback] Callback rebut — URL: {request.url[:100]}...")
    try:
        from flask import session

        # Validar que ve d'un flow legítim
        stored_token = session.get('google_auth_token')
        logger.info(f"🔑 [Google Callback] Session token present: {'SÍ' if stored_token else 'NO'}")
        logger.info(f"🔑 [Google Callback] GOOGLE_AUTH_TOKEN configurat: {'SÍ' if GOOGLE_AUTH_TOKEN else 'NO'}")
        if not GOOGLE_AUTH_TOKEN or stored_token != GOOGLE_AUTH_TOKEN:
            logger.warning(f"🔑 [Google Callback] Token sessió invàlid — potser la sessió ha caducat")
            return jsonify({'error': 'Accés denegat — sessió caducada, torna a iniciar el flow'}), 403

        error = request.args.get('error')
        if error:
            logger.warning(f"🔑 [Google Callback] Google ha retornat error: {error}")
            return f"""
            <html><body style="font-family:sans-serif;text-align:center;margin-top:80px;">
            <h2 style="color:#e74c3c;">Autorització cancel·lada</h2>
            <p>Google ha retornat un error: <strong>{error}</strong></p>
            </body></html>
            """, 400

        client_id = os.environ.get('GOOGLE_CLIENT_ID')
        client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
        logger.info(f"🔑 [Google Callback] Credencials: client_id={'SET' if client_id else 'MISSING'}, client_secret={'SET' if client_secret else 'MISSING'}")

        try:
            from google_auth_oauthlib.flow import Flow
        except ImportError as ie:
            logger.error(f"❌ [Google Callback] ImportError google_auth_oauthlib: {ie}")
            return jsonify({'error': f'Mòdul no instal·lat: {ie}'}), 500

        state = session.get('google_oauth_state')
        logger.info(f"🔑 [Google Callback] OAuth state de sessió: {'SET' if state else 'MISSING'}")

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [GOOGLE_OAUTH_REDIRECT_URI],
                }
            },
            scopes=['https://www.googleapis.com/auth/calendar'],
            redirect_uri=GOOGLE_OAUTH_REDIRECT_URI,
            state=state,
        )

        # Obtenir tokens amb el codi d'autorització
        # IMPORTANT: request.url pot arribar amb http:// si hi ha proxy/Render davant
        auth_response_url = request.url
        if auth_response_url.startswith('http://') and GOOGLE_OAUTH_REDIRECT_URI.startswith('https://'):
            auth_response_url = auth_response_url.replace('http://', 'https://', 1)
            logger.info(f"🔑 [Google Callback] URL corregida http→https: {auth_response_url[:80]}...")

        logger.info(f"🔑 [Google Callback] Fent fetch_token...")
        flow.fetch_token(authorization_response=auth_response_url)
        creds = flow.credentials
        logger.info(f"🔑 [Google Callback] Token obtingut! refresh_token={'SÍ' if creds.refresh_token else 'NO'}")

        if not creds.refresh_token:
            logger.warning(f"🔑 [Google Callback] NO s'ha rebut refresh_token — cal revocar accés previ")
            return f"""
            <html><body style="font-family:sans-serif;text-align:center;margin-top:80px;">
            <h2 style="color:#e74c3c;">Error</h2>
            <p>No s'ha obtingut el refresh_token. Prova a revocar l'accés a
            <a href="https://myaccount.google.com/permissions">myaccount.google.com/permissions</a>
            i torna a autoritzar.</p>
            </body></html>
            """, 400

        # Guardar el refresh_token a Render via API
        logger.info(f"🔑 [Google Callback] Guardant refresh_token a Render...")
        render_ok = _save_refresh_token_to_render(creds.refresh_token)

        # Actualitzar la variable en memòria per ús immediat
        os.environ['GOOGLE_REFRESH_TOKEN'] = creds.refresh_token
        logger.info(f"🔑 [Google Callback] refresh_token guardat en memòria. Render API: {'OK' if render_ok else 'ERROR'}")

        if render_ok:
            status_msg = "El token s'ha guardat correctament a Render."
            color = "#2ecc71"
        else:
            status_msg = (
                "El token s'ha activat en memòria però <strong>no s'ha pogut guardar a Render</strong>. "
                "Afegeix-lo manualment: <br><code>GOOGLE_REFRESH_TOKEN=" + creds.refresh_token + "</code>"
            )
            color = "#f39c12"

        logger.info(f"✅ [Google Callback] Flow OAuth completat correctament!")
        return f"""
        <html>
        <body style="font-family:sans-serif;text-align:center;margin-top:80px;max-width:600px;margin-left:auto;margin-right:auto;">
            <div style="background:#f8f9fa;border-radius:12px;padding:40px;box-shadow:0 2px 10px rgba(0,0,0,0.1);">
                <h1 style="color:{color};">Autorització completada correctament</h1>
                <p style="font-size:18px;">El Google Calendar de <strong>pau@rodonverges.com</strong>
                ja està connectat amb la Gestoria.</p>
                <p style="color:#666;">{status_msg}</p>
                <hr style="margin:20px 0;border:none;border-top:1px solid #ddd;">
                <p style="color:#999;font-size:14px;">Pots tancar aquesta finestra.</p>
            </div>
        </body>
        </html>
        """

    except Exception as e:
        logger.error(f"❌ [Google Callback] Error inesperat: {type(e).__name__}: {str(e)}", exc_info=True)
        return jsonify({'error': f'Error intern al callback: {type(e).__name__}: {str(e)}'}), 500

def _save_refresh_token_to_render(refresh_token):
    """
    Guarda el GOOGLE_REFRESH_TOKEN a Render via la seva API.
    Retorna True si ha anat bé, False si ha fallat.
    """
    if not RENDER_API_KEY or not RENDER_SERVICE_ID:
        logger.warning("⚠️  [Google Auth] RENDER_API_KEY o RENDER_SERVICE_ID no configurats")
        return False

    try:
        url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars"

        # Primer, obtenir les env vars actuals per fer PUT
        headers = {
            'Authorization': f'Bearer {RENDER_API_KEY}',
            'Content-Type': 'application/json',
        }

        # Render API: PUT per actualitzar una env var específica
        put_url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars/GOOGLE_REFRESH_TOKEN"
        resp = requests.put(
            put_url,
            headers=headers,
            json={'value': refresh_token},
        )

        if resp.status_code in (200, 201):
            logger.info("✅ [Google Auth] GOOGLE_REFRESH_TOKEN guardat a Render")
            return True
        else:
            # Si no existeix, crear-la
            resp2 = requests.post(
                url,
                headers=headers,
                json=[{'key': 'GOOGLE_REFRESH_TOKEN', 'value': refresh_token}],
            )
            if resp2.status_code in (200, 201):
                logger.info("✅ [Google Auth] GOOGLE_REFRESH_TOKEN creat a Render")
                return True
            logger.error(f"❌ [Google Auth] Error guardant a Render: {resp.status_code} {resp.text} / {resp2.status_code} {resp2.text}")
            return False

    except Exception as e:
        logger.error(f"❌ [Google Auth] Error cridant Render API: {e}")
        return False

# ═══════════════════════════════════════════════════════════════
# GOOGLE CALENDAR — Sincronització massiva (one-time)
# ═══════════════════════════════════════════════════════════════

@app.route('/api/calendar/sync-all', methods=['POST'])
def calendar_sync_all():
    """Sincronitza tots els events futurs pendents al Google Calendar."""
    try:
        from calendar_sync import sync_all_future_events
        def _run():
            sync_all_future_events(app)
        threading.Thread(target=_run, daemon=True).start()
        return jsonify({'ok': True, 'message': 'Sincronització iniciada en segon pla'})
    except Exception as e:
        logger.error(f"❌ [Calendar Sync All] {str(e)}")
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
# MANEJO DE ERRORES
# ═══════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(error):
    """Manejar errores 404 - API retorna JSON, la resta serveix la app"""
    if request.path.startswith('/api/'):
        return jsonify({'ok': False, 'error': f'Ruta no trobada: {request.path}'}), 404
    return render_template('index3.html'), 200

@app.errorhandler(500)
def server_error(error):
    """Manejar errores 500"""
    logger.error(f"Error 500: {str(error)}")
    return jsonify({'error': 'Internal server error', 'details': str(error)}), 500

# ═══════════════════════════════════════════════════════════════
# CREAR TAULES A LA BD (si no existeixen)
# ═══════════════════════════════════════════════════════════════

with app.app_context():
    try:
        db.create_all()
        logger.info("✅ Taules de BD creades/verificades correctament")
        # Migracions: afegir columnes noves a taules existents
        # (db.create_all no afegeix columnes noves a taules ja existents)
        from sqlalchemy import inspect as sa_inspect, text
        insp = sa_inspect(db.engine)

        # Migració taula events: google_calendar_event_id
        if 'events' in insp.get_table_names():
            cols = [c['name'] for c in insp.get_columns('events')]
            if 'google_calendar_event_id' not in cols:
                db.session.execute(text('ALTER TABLE events ADD COLUMN google_calendar_event_id VARCHAR(255)'))
                db.session.commit()
                logger.info("✅ Migració: afegit camp google_calendar_event_id a events")

        # Migració taula event: wa_reminder, pr_reminder, client_phone
        if 'event' in insp.get_table_names():
            existing_cols = [c['name'] for c in insp.get_columns('event')]
            with db.engine.connect() as conn:
                if 'wa_reminder' not in existing_cols:
                    conn.execute(text('ALTER TABLE event ADD COLUMN wa_reminder VARCHAR(500)'))
                    conn.commit()
                    logger.info("✅ [DB] Columna wa_reminder afegida a event")
                if 'pr_reminder' not in existing_cols:
                    conn.execute(text('ALTER TABLE event ADD COLUMN pr_reminder VARCHAR(1000)'))
                    conn.commit()
                    logger.info("✅ [DB] Columna pr_reminder afegida a event")
                if 'client_phone' not in existing_cols:
                    conn.execute(text('ALTER TABLE event ADD COLUMN client_phone VARCHAR(50)'))
                    conn.commit()
                    logger.info("✅ [DB] Columna client_phone afegida a event")
            logger.info(f"✅ [DB] Columnes event verificades: {existing_cols}")
    except Exception as _e:
        logger.error(f"❌ Error creant taules: {_e}")

# ═══════════════════════════════════════════════════════════════
# INICIALIZAR SCHEDULER (si está disponible)
# ═══════════════════════════════════════════════════════════════

def recover_pending_jobs():
    """Recupera els recordatoris WhatsApp pendents de la BD i els re-programa.
    S'executa a l'arrancada per no perdre jobs si el servidor s'ha reiniciat.
    Jobs amb send_at en el futur → re-afegits a APScheduler.
    Jobs amb send_at ja passat → enviats immediatament.
    """
    if not SCHEDULER_AVAILABLE or not scheduler:
        return
    try:
        with app.app_context():
            import pytz as _pytz
            now_utc = datetime.utcnow().replace(tzinfo=_pytz.utc)
            pending = WaScheduledJob.query.filter_by(sent=False).all()
            logger.info(f"🔄 [Recover] {len(pending)} recordatoris pendents trobats a BD")
            for rec in pending:
                send_dt = rec.send_at
                # Assegurar timezone-aware
                if send_dt.tzinfo is None:
                    send_dt = send_dt.replace(tzinfo=_pytz.utc)

                tv = rec.template_vars or {}
                # Reconstruir job_args: [phone, message, message_type, template_params, job_id]
                if 'nom' in tv:
                    t_params = [tv.get('nom',''), tv.get('data',''),
                                tv.get('hora',''), tv.get('seu','')]
                    j_args = [rec.phone, '', 'nom_recordatori_cita', t_params, rec.job_id]
                else:
                    j_args = [rec.phone, tv.get('missatge',''), 'text', None, rec.job_id]

                if send_dt > now_utc:
                    # Futur → re-programar a APScheduler
                    try:
                        if not scheduler.get_job(rec.job_id):
                            scheduler.add_job(
                                func=send_whatsapp_job,
                                trigger=DateTrigger(run_date=send_dt),
                                args=j_args,
                                id=rec.job_id,
                                replace_existing=True
                            )
                            logger.info(f"⏰ [Recover] Re-programat: {rec.job_id} → {send_dt.isoformat()}")
                    except Exception as _e:
                        logger.error(f"❌ [Recover] Error re-programant {rec.job_id}: {_e}")
                else:
                    # Passat → enviar immediatament en background thread
                    logger.warning(f"⚡ [Recover] Job passat, enviant immediatament: {rec.job_id}")
                    import threading
                    threading.Thread(
                        target=send_whatsapp_job,
                        args=j_args,
                        daemon=True
                    ).start()
    except Exception as _e:
        logger.error(f"❌ [Recover] Error recuperant jobs: {_e}")


scheduler = None
if SCHEDULER_AVAILABLE:
    scheduler = BackgroundScheduler()
    scheduler.start()
    logger.info("✅ APScheduler iniciado")
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
