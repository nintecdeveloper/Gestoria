import os
import json
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
from datetime import datetime
import requests
import logging
import uuid
import sys

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE LOGGING
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

print("\n" + "="*80)
print("🚀 INICIANDO SERVIDOR CON LOGGING DETALLADO")
print("="*80 + "\n")

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN META WHATSAPP
# ═══════════════════════════════════════════════════════════════

META_PHONE_NUMBER_ID = os.environ.get('META_PHONE_NUMBER_ID', None)
META_ACCESS_TOKEN = os.environ.get('META_ACCESS_TOKEN', None)
META_BUSINESS_ACCOUNT_ID = os.environ.get('META_BUSINESS_ACCOUNT_ID', None)
META_API_VERSION = "v18.0"

SCHEDULER_AVAILABLE = False
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    SCHEDULER_AVAILABLE = True
except ImportError:
    logger.warning("⚠️  APScheduler no disponible")

# ═══════════════════════════════════════════════════════════════
# FLASK APP Y SOCKETIO
# ═══════════════════════════════════════════════════════════════

app = Flask(__name__, template_folder='.', static_folder='.')
app.config['SECRET_KEY'] = 'dev-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

logger.info("✅ Flask app creada")
logger.info("✅ SocketIO inicializado")

# ═══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ═══════════════════════════════════════════════════════════════

connected_users = {}
sid_to_userid = {}
message_storage = {}
message_ids_seen = set()

logger.info("✅ Estructuras de datos inicializadas")

# ═══════════════════════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════════════════════

def make_conv_key(user_a, user_b):
    """Crear clave canónica: sorted user IDs"""
    return "-".join(map(str, sorted([int(user_a), int(user_b)])))

def log_rooms_status():
    """Loguear estado actual de salas"""
    logger.debug(f"📊 ESTADO DE SALAS:")
    logger.debug(f"   Usuarios conectados: {len(connected_users)}")
    for sid, user_data in list(connected_users.items()):
        uid = user_data.get('user_id')
        room = user_data.get('room')
        user_rooms = list(rooms(sid=sid))
        logger.debug(f"   SID {sid[:8]}: UID={uid}, Room={room}, Salas reales={user_rooms}")

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET EVENTS
# ═══════════════════════════════════════════════════════════════

@socketio.on('connect')
def handle_connect():
    """Evento: cliente conectado"""
    sid = request.sid
    logger.info(f"🔌 [CONNECT] Socket conectado: {sid[:8]}")
    emit('connection_response', {'data': 'Conectado'})

@socketio.on('disconnect')
def handle_disconnect():
    """Evento: cliente desconectado"""
    sid = request.sid
    user_data = connected_users.pop(sid, None)
    user_id = sid_to_userid.pop(sid, None)
    
    if user_data:
        logger.info(f"❌ [DISCONNECT] {user_data.get('username')} (UID={user_id}) desconectado")
    else:
        logger.debug(f"❌ [DISCONNECT] SID sin usuario: {sid[:8]}")

@socketio.on('user_login')
def handle_user_login(data):
    """Evento: usuario hace login y se une a su sala"""
    sid = request.sid
    username = data.get('username', f'User_{sid[:6]}')
    user_id = data.get('userId')
    
    logger.info(f"👤 [LOGIN] {username} (UID={user_id}) - SID={sid[:8]}")
    
    # Validar user_id
    try:
        user_id = int(user_id)
        if user_id <= 0:
            raise ValueError("user_id debe ser > 0")
    except (TypeError, ValueError) as e:
        logger.error(f"❌ [LOGIN] User ID inválido: {user_id}")
        emit('login_ack', {'ok': False, 'error': f'Invalid user_id: {user_id}'})
        return
    
    # Limpiar sesiones anteriores
    old_sids = [s for s, u in sid_to_userid.items() if u == user_id]
    for old_sid in old_sids:
        if old_sid != sid:
            logger.info(f"   Limpiando sesión anterior: {old_sid[:8]}")
            try:
                leave_room(f"user_{user_id}", sid=old_sid)
            except:
                pass
            connected_users.pop(old_sid, None)
            sid_to_userid.pop(old_sid, None)
    
    # Registrar usuario
    room = f"user_{user_id}"
    connected_users[sid] = {
        'username': username,
        'user_id': user_id,
        'connected_at': datetime.now().isoformat(),
        'room': room
    }
    sid_to_userid[sid] = user_id
    
    # CRUCIAL: Unirse a la sala
    logger.info(f"   Uniendo a sala: {room}")
    join_room(room, sid=sid)
    
    # Verificar que está realmente en la sala
    user_rooms = list(rooms(sid=sid))
    logger.debug(f"   Salas actuales: {user_rooms}")
    
    if room not in user_rooms:
        logger.error(f"❌ [LOGIN] Socket NO está en sala {room} después de join_room()")
        emit('login_ack', {'ok': False, 'error': 'Failed to join room'})
        return
    
    logger.info(f"✅ [LOGIN] {username} en sala '{room}'")
    
    # Log estado general
    log_rooms_status()
    
    # Enviar confirmación
    emit('login_ack', {
        'ok': True,
        'room': room,
        'user_id': user_id,
        'sid': sid,
        'timestamp': datetime.now().isoformat()
    })
    logger.debug(f"   login_ack enviado")

@socketio.on('send_message')
def handle_send_message(data):
    """Evento: recibir y retransmitir mensaje privado"""
    sid = request.sid
    sender_id = data.get('sender_id')
    sender_username = data.get('sender_username', '?')
    recipient_id = data.get('recipient_id')
    text = (data.get('message') or '').strip()
    message_id = data.get('message_id') or f"msg_{uuid.uuid4().hex[:12]}"
    attachments = data.get('attachments') or []
    
    ts = datetime.now().isoformat()
    
    logger.info(f"💬 [SEND_MESSAGE] {sender_id} → {recipient_id}")
    logger.debug(f"   Message ID: {message_id}")
    logger.debug(f"   SID: {sid[:8]}")
    logger.debug(f"   Texto: '{text[:40]}'")
    
    # VALIDACIÓN 1: IDs válidos
    try:
        sender_id = int(sender_id)
        recipient_id = int(recipient_id)
    except (TypeError, ValueError):
        logger.error(f"❌ [SEND_MESSAGE] IDs inválidos")
        emit('message_ack', {
            'message_id': message_id,
            'status': 'error',
            'reason': 'invalid_ids'
        })
        return
    
    # VALIDACIÓN 2: Autenticación
    if sid not in sid_to_userid:
        logger.error(f"❌ [SEND_MESSAGE] SID no autenticado: {sid[:8]}")
        emit('message_ack', {
            'message_id': message_id,
            'status': 'error',
            'reason': 'not_authenticated'
        })
        return
    
    auth_user_id = sid_to_userid[sid]
    if auth_user_id != sender_id:
        logger.error(f"❌ [SEND_MESSAGE] Sender mismatch: auth={auth_user_id}, claimed={sender_id}")
        emit('message_ack', {
            'message_id': message_id,
            'status': 'error',
            'reason': 'sender_mismatch'
        })
        return
    
    logger.debug(f"   ✓ Autenticación validada")
    
    # VALIDACIÓN 3: Contenido
    if not text and not attachments:
        logger.warning(f"⚠️  [SEND_MESSAGE] Mensaje vacío")
        return
    
    # VALIDACIÓN 4: Deduplicación
    if message_id in message_ids_seen:
        logger.warning(f"⚠️  [SEND_MESSAGE] Duplicado: {message_id}")
        emit('message_ack', {
            'message_id': message_id,
            'status': 'ok',
            'duplicated': True
        })
        return
    
    message_ids_seen.add(message_id)
    logger.debug(f"   ✓ Deduplicación OK")
    
    # Crear mensaje
    msg = {
        'id': message_id,
        'sender_id': sender_id,
        'sender_username': sender_username,
        'recipient_id': recipient_id,
        'text': text,
        'timestamp': ts,
        'attachments': attachments
    }
    
    # Persistir
    key = make_conv_key(sender_id, recipient_id)
    if key not in message_storage:
        message_storage[key] = []
    message_storage[key].append(msg)
    logger.debug(f"   ✓ Persistido (key={key}, total={len(message_storage[key])})")
    
    # PASO 1: ACK al remitente
    logger.info(f"   1️⃣  ACK → remitente")
    emit('message_ack', {
        'message_id': message_id,
        'status': 'ok',
        'timestamp': ts,
        'stored_at': key
    })
    
    # PASO 2: Enviar al receptor
    recipient_room = f"user_{recipient_id}"
    logger.info(f"   2️⃣  receive_message → '{recipient_room}'")
    
    room_members = list(rooms(room=recipient_room))
    logger.debug(f"      Usuarios en {recipient_room}: {len(room_members)}")
    for member_sid in room_members:
        member_user = connected_users.get(member_sid, {})
        logger.debug(f"         {member_sid[:8]}: {member_user.get('username')}")
    
    if not room_members:
        logger.warning(f"⚠️  ATENCIÓN: Sala '{recipient_room}' está VACÍA")
        logger.warning(f"   Usuario {recipient_id} NO está en su sala")
    
    emit('receive_message', msg, room=recipient_room, include_self=False)
    logger.debug(f"      ✓ Emitido")
    
    # PASO 3: Confirmación al remitente
    sender_room = f"user_{sender_id}"
    logger.info(f"   3️⃣  message_delivered → '{sender_room}'")
    emit('message_delivered', {
        'message_id': message_id,
        'recipient_id': recipient_id,
        'timestamp': ts,
        'delivered_to_recipient': True
    }, room=sender_room)
    logger.debug(f"      ✓ Emitido")
    
    logger.info(f"✅ [SEND_MESSAGE] Completado: {message_id}")

@socketio.on('message_read')
def handle_message_read(data):
    """Evento: notificar lectura"""
    message_id = data.get('message_id')
    sender_id = data.get('sender_id')
    logger.debug(f"📖 [MESSAGE_READ] {message_id}")
    emit('message_read_ack', {
        'message_id': message_id,
        'timestamp': datetime.now().isoformat()
    }, room=f"user_{sender_id}")

@socketio.on('send_general_message')
def handle_general_message(data):
    """Evento: mensaje general"""
    sender_id = data.get('sender_id')
    sender_username = data.get('sender_username', '?')
    text = (data.get('message') or '').strip()
    message_id = data.get('message_id') or f"msg_{uuid.uuid4().hex[:12]}"
    
    ts = datetime.now().isoformat()
    
    logger.debug(f"📢 [GENERAL] {sender_username}: {text[:40]}")
    
    if message_id in message_ids_seen:
        emit('message_ack', {'message_id': message_id, 'status': 'ok', 'duplicated': True})
        return
    
    message_ids_seen.add(message_id)
    
    if not text:
        return
    
    emit('message_ack', {'message_id': message_id, 'status': 'ok', 'timestamp': ts})
    
    msg = {
        'id': message_id,
        'sender_id': sender_id,
        'sender_username': sender_username,
        'text': text,
        'timestamp': ts
    }
    
    emit('receive_general_message', msg, broadcast=True)

# ═══════════════════════════════════════════════════════════════
# REST ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def index():
    """Servir index3.html"""
    return render_template('index3.html')

@app.route('/api/messages/<int:user_a>/<int:user_b>')
def get_messages(user_a, user_b):
    """Obtener histórico de mensajes"""
    key = make_conv_key(user_a, user_b)
    messages = message_storage.get(key, [])
    logger.debug(f"📥 [API] get_messages({user_a}, {user_b}): {len(messages)} msgs")
    return jsonify({'ok': True, 'messages': messages})

@app.route('/api/health')
def health():
    """Health check"""
    return jsonify({
        'status': 'ok',
        'connected_users': len(connected_users),
        'conversations': len(message_storage)
    })

@app.route('/api/debug/status')
def debug_status():
    """Estado de debugging"""
    log_rooms_status()
    
    return jsonify({
        'connected_users': {
            sid[:8]: {
                'username': data.get('username'),
                'user_id': data.get('user_id'),
                'room': data.get('room')
            }
            for sid, data in connected_users.items()
        },
        'conversations': {
            key: len(msgs)
            for key, msgs in message_storage.items()
        }
    })

# ═══════════════════════════════════════════════════════════════
# MANEJO DE ERRORES
# ═══════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(error):
    """Servir index3.html para rutas desconocidas"""
    return render_template('index3.html'), 200

@app.errorhandler(500)
def server_error(error):
    """Error 500"""
    logger.error(f"❌ Error 500: {str(error)}")
    return jsonify({'error': 'Internal server error'}), 500

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = '0.0.0.0'
    
    logger.info("="*80)
    logger.info("🚀 INICIANDO SERVIDOR")
    logger.info(f"HOST: {host}")
    logger.info(f"PORT: {port}")
    logger.info(f"DEBUG: True")
    logger.info(f"LOGGING: Detallado (DEBUG)")
    logger.info("="*80 + "\n")
    
    socketio.run(
        app,
        host=host,
        port=port,
        debug=True,
        allow_unsafe_werkzeug=True,
        log_output=True
    )