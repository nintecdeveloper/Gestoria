import os
import json
from flask import Flask, render_template, jsonify, request, send_file
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
META_API_URL = f"https://graph.instagram.com/{META_API_VERSION}/{{phone_id}}/messages"

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

def send_whatsapp_meta(to_phone: str, message: str, message_type: str = "text"):
    """Envía un mensaje de WhatsApp via Meta Cloud API."""
    if not META_PHONE_NUMBER_ID or not META_ACCESS_TOKEN:
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
            "to": phone.replace('+', ''),
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message
            }
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": phone.replace('+', ''),
            "type": "template",
            "template": {
                "name": message_type,
                "language": {
                    "code": "es_ES"
                }
            }
        }
    
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    url = META_API_URL.format(phone_id=META_PHONE_NUMBER_ID)
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"✅ [Meta API] Mensaje enviado a {phone} · ID: {result.get('messages', [{}])[0].get('id')}")
        
        return {
            'ok': True,
            'message_id': result.get('messages', [{}])[0].get('id'),
            'phone': phone
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

def send_whatsapp_job(to_phone: str, message: str):
    """Trabajo del scheduler para enviar WhatsApp"""
    result = send_whatsapp_meta(to_phone, message)
    if result['ok']:
        logger.info(f"✅ [Scheduler/Meta] Recordatorio enviado a {to_phone}")
    else:
        logger.error(f"❌ [Scheduler/Meta] Error: {result.get('error')}")
    
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
            'waReminder':   json.loads(self.wa_reminder) if self.wa_reminder else None,
            'prReminders':  json.loads(self.pr_reminder) if self.pr_reminder else [],
        }

import uuid
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
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
    
    # Crear objeto de mensaje
    message_obj = {
        'id': message_id,
        'sender_id': sender_id,
        'sender_username': sender_username,
        'recipient_username': recipient_username,
        'text': message_text,
        'timestamp': datetime.now().isoformat(),
        'attachments': attachments
    }
    
    # Almacenar en servidor con clave privada normalizada
    private_key = f'private_{sender_username}_{recipient_username}'
    if private_key not in message_storage:
        message_storage[private_key] = []
    message_storage[private_key].append(message_obj)
    save_message_storage()
    
    logger.info(f"💬 [Chat Privado] {sender_username} → {recipient_username}: {message_text[:50] if message_text else '(adjuntos)'}")
    
    # Buscar receptor: primer per username_to_sid, després per connected_users (per si el SID ha canviat)
    recipient_sid = username_to_sid.get(recipient_username)
    
    # Si el SID guardat ja no és a connected_users, buscar per nom dins connected_users
    if not recipient_sid or recipient_sid not in connected_users:
        for sid, info in connected_users.items():
            if info.get('username') == recipient_username:
                recipient_sid = sid
                username_to_sid[recipient_username] = sid  # Actualitzar
                break
    
    if recipient_sid and recipient_sid in connected_users:
        # Receptor connectat: entregar immediatament
        socketio.emit('receive_message', message_obj, room=recipient_sid)
        logger.info(f"✅ [Mensaje Entregado] A {recipient_username} (SID: {recipient_sid})")
        socketio.emit('message_notification', {
            'from': sender_username,
            'message': "📎 Archivo adjunto" if attachments else (message_text[:50] + '...' if len(message_text) > 50 else message_text),
            'timestamp': datetime.now().isoformat()
        }, room=recipient_sid)
    else:
        # Receptor offline: el missatge ja està guardat a message_storage
        # S'entregarà quan es connecti via la lògica de pendents
        logger.info(f"📬 [Mensaje Guardado] {recipient_username} offline — guardat a {private_key}")
    
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
    """Recupera el histórico de mensajes de una conversación"""
    if not conv_id:
        return jsonify({'ok': False, 'error': 'conv_id requerido', 'messages': []}), 400
    
    # Búsqueda bidireccional para privados
    messages = message_storage.get(conv_id)
    resolved_id = conv_id
    
    if messages is None and conv_id.startswith('private_'):
        parts = conv_id.replace('private_', '').split('_', 1)
        if len(parts) == 2:
            alt_id = f"private_{parts[1]}_{parts[0]}"
            messages = message_storage.get(alt_id)
            resolved_id = alt_id if messages is not None else conv_id
    
    if messages is None:
        return jsonify({'ok': True, 'conv_id': conv_id, 'messages': []})
    
    logger.info(f"📥 [Mensajes] Recuperando {len(messages)} mensajes de {resolved_id}")
    return jsonify({'ok': True, 'conv_id': resolved_id, 'messages': messages})

@app.route('/api/messages/<conv_id>/read', methods=['POST'])
def mark_messages_read(conv_id):
    """Marca todos los mensajes de una conversación como leídos"""
    messages = message_storage.get(conv_id, [])
    for m in messages:
        m['read'] = True
    return jsonify({'ok': True})

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
    """Envía un mensaje de WhatsApp"""
    data = request.get_json(silent=True) or {}
    to_phone = data.get('to', '').strip()
    message = data.get('message', '').strip()
    
    if not to_phone:
        return jsonify({'ok': False, 'error': 'Falta el campo "to"'}), 400
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

    if not to_phone or not message or not send_at or not job_id:
        return jsonify({'ok': False, 'error': 'Faltan campos: to, message, send_at, job_id'}), 400

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

    # Eliminar job anterior con el mismo ID si existe
    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    except Exception:
        pass

    # Programar el trabajo
    try:
        scheduler.add_job(
            func=send_whatsapp_job,
            trigger=DateTrigger(run_date=send_dt),
            args=[to_phone, message],
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
    """Comprueba si Meta API y el Scheduler están listos"""
    meta_ok = bool(META_PHONE_NUMBER_ID and META_ACCESS_TOKEN)
    scheduler_ok = SCHEDULER_AVAILABLE and scheduler is not None

    reasons = []
    if not meta_ok:
        reasons.append("Variables de entorno Meta no configuradas (META_PHONE_NUMBER_ID, META_ACCESS_TOKEN)")
    if not SCHEDULER_AVAILABLE:
        reasons.append("APScheduler no instalado (pip install apscheduler)")
    elif not scheduler_ok:
        reasons.append("Scheduler no inicializado")

    return jsonify({
        'meta_ready': meta_ok,
        'scheduler_ready': scheduler_ok,
        'fully_ready': meta_ok and scheduler_ok,
        'reason': ' · '.join(reasons) if reasons else 'Todo configurado correctamente'
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
            wa_reminder   = json.dumps(data['waReminder']) if data.get('waReminder') else None,
            pr_reminder   = json.dumps(data['prReminders']) if data.get('prReminders') else None,
        )
        db.session.add(ev)
        db.session.commit()
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
        ev.date          = data.get('date', ev.date)
        ev.start_time    = data.get('time', ev.start_time)
        ev.end_time      = data.get('timeEnd') if 'timeEnd' in data else ev.end_time
        ev.client_name   = data.get('client') or ev.client_name
        ev.client_phone  = data.get('clientPhone') if 'clientPhone' in data else ev.client_phone
        ev.assigned_to   = int(data['assignedTo']) if 'assignedTo' in data else ev.assigned_to
        ev.service_type  = data.get('service') if 'service' in data else ev.service_type
        ev.notes         = data.get('notes') if 'notes' in data else ev.notes
        ev.is_private    = bool(data['private']) if 'private' in data else ev.is_private
        ev.wa_reminder   = json.dumps(data['waReminder']) if data.get('waReminder') else (None if 'waReminder' in data else ev.wa_reminder)
        ev.pr_reminder   = json.dumps(data['prReminders']) if data.get('prReminders') else (None if 'prReminders' in data else ev.pr_reminder)
        db.session.commit()
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
        db.session.delete(ev)
        db.session.commit()
        return jsonify({'ok': True, 'deleted': ev_id})
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ [Events DELETE {ev_id}] {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

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
# CREAR TAULES A LA BD (si no existeixen)
# ═══════════════════════════════════════════════════════════════

with app.app_context():
    try:
        db.create_all()
        logger.info("✅ Taules de BD creades/verificades correctament")
    except Exception as _e:
        logger.error(f"❌ Error creant taules: {_e}")

# ═══════════════════════════════════════════════════════════════
# INICIALIZAR SCHEDULER (si está disponible)
# ═══════════════════════════════════════════════════════════════

scheduler = None
if SCHEDULER_AVAILABLE:
    scheduler = BackgroundScheduler()
    scheduler.start()
    logger.info("✅ APScheduler iniciado")

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
