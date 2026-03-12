import os
import json
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
import requests
import logging
import uuid

# ═══════════════════════════════════════════════════════════════
# META WHATSAPP API — IMPORTACIÓN CONDICIONAL
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

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN META WHATSAPP API
# ═══════════════════════════════════════════════════════════════
META_PHONE_NUMBER_ID = os.environ.get('META_PHONE_NUMBER_ID', None)
META_ACCESS_TOKEN = os.environ.get('META_ACCESS_TOKEN', None)
META_BUSINESS_ACCOUNT_ID = os.environ.get('META_BUSINESS_ACCOUNT_ID', None)
META_API_VERSION = "v18.0"
META_API_URL = f"https://graph.instagram.com/{META_API_VERSION}/{{phone_id}}/messages"

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ [Meta API] Error al enviar a {phone}: {str(e)}")
        return {
            'ok': False,
            'error': f'Error Meta API: {str(e)}'
        }
    except Exception as e:
        logger.error(f"❌ [Meta API] Error inesperado: {str(e)}")
        return {
            'ok': False,
            'error': str(e)
        }

# ═══════════════════════════════════════════════════════════════
# SCHEDULER — INICIALIZACIÓN
# ═══════════════════════════════════════════════════════════════
scheduler = None
if SCHEDULER_AVAILABLE:
    scheduler = BackgroundScheduler(timezone='Europe/Madrid')
    scheduler.start()
    logger.info("✅ [Scheduler] APScheduler iniciado correctamente.")

def send_whatsapp_job(to_phone: str, message: str):
    """Tarea ejecutada por el scheduler en el momento programado."""
    result = send_whatsapp_meta(to_phone, message)
    if result['ok']:
        logger.info(f"✅ [Scheduler/Meta] Recordatorio enviado a {to_phone}")
    else:
        logger.error(f"❌ [Scheduler/Meta] No se pudo enviar a {to_phone}: {result.get('error')}")

# ═══════════════════════════════════════════════════════════════
# INICIALIZAR FLASK Y SOCKETIO
# ═══════════════════════════════════════════════════════════════
app = Flask(__name__, template_folder='templates')
app.config['ENV'] = os.environ.get('FLASK_ENV', 'production')
app.config['DEBUG'] = False if app.config['ENV'] == 'production' else True
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    async_mode='threading'
)

# ═══════════════════════════════════════════════════════════════
# ESTADO GLOBAL — MENSAJERÍA
# ✅ MEJORADO: Tracking completo de usuarios y deduplicación
# ═══════════════════════════════════════════════════════════════
connected_users = {}   # sid → {username, user_id, connected_at, room}
sid_to_userid   = {}   # sid → user_id
message_storage = {}   # {"1-2": [msg]}
general_storage = []   # [msg]
message_ids_seen = set()  # Para deduplicación global

def make_conv_key(a, b):
    """Clave canónica — idéntica a convKey() del frontend."""
    return "-".join(sorted([str(int(a)), str(int(b))]))

# ═══════════════════════════════════════════════════════════════
# RUTAS PRINCIPALES
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def home():
    return render_template('index3.html')

@app.route('/app')
def dashboard():
    return render_template('index3.html')

@app.route('/index')
def index_alt():
    return render_template('index3.html')

@app.route('/gestionpro')
def gestionpro():
    return render_template('index3.html')

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET — CICLO DE VIDA
# ═══════════════════════════════════════════════════════════════

@socketio.on('connect')
def handle_connect(auth):
    """Nuevo cliente conectado vía socket."""
    logger.info(f"🔗 [WS] Nuevo socket: {request.sid}")
    emit('connect_ack', {'sid': request.sid, 'timestamp': datetime.now().isoformat()})

@socketio.on('disconnect')
def handle_disconnect():
    """Cliente desconectado."""
    sid = request.sid
    info = connected_users.pop(sid, None)
    user_id = sid_to_userid.pop(sid, None)
    
    if info:
        logger.info(f"❌ [WS] {info['username']} desconectado (sid={sid[:8]}, user_id={user_id})")
    else:
        logger.warning(f"⚠️  [WS] Socket desconectado sin registro previo: {sid[:8]}")

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET — REGISTRO (join room personal)
# ═══════════════════════════════════════════════════════════════

@socketio.on('user_login')
def handle_user_login(data):
    """
    Registra un usuario en la room personal.
    ✅ CORREGIDO: Validación estricta y ACK inmediato
    """
    sid     = request.sid
    username = data.get('username', f'User_{sid[:6]}')
    user_id  = data.get('userId')
    
    # Validar user_id
    try:
        user_id = int(user_id)
        if user_id <= 0:
            raise ValueError("user_id debe ser > 0")
    except (TypeError, ValueError) as e:
        logger.error(f"❌ [WS] user_login recibido con user_id inválido: {user_id} ({e})")
        emit('login_ack', {'ok': False, 'error': 'Invalid user_id'})
        return
    
    # Registrar usuario
    room = f"user_{user_id}"
    
    # Limpiar cualquier registro anterior del mismo user_id
    old_sids = [s for s, u in sid_to_userid.items() if u == user_id]
    for old_sid in old_sids:
        if old_sid != sid:
            logger.info(f"🔄 [WS] Limpiando SID antiguo: {old_sid[:8]} para user_id={user_id}")
            try:
                leave_room(f"user_{user_id}", sid=old_sid)
            except:
                pass
            connected_users.pop(old_sid, None)
            sid_to_userid.pop(old_sid, None)
    
    # Registrar nuevo/actual
    connected_users[sid] = {
        'username': username,
        'user_id':  user_id,
        'connected_at': datetime.now().isoformat(),
        'room': room
    }
    sid_to_userid[sid] = user_id
    
    # Unir a la room personal
    join_room(room)
    logger.info(f"✅ [WS] {username} (id={user_id}) → room '{room}' (sid={sid[:8]})")
    
    # ACK inmediato
    emit('login_ack', {
        'ok': True, 
        'room': room, 
        'user_id': user_id,
        'sid': sid,
        'timestamp': datetime.now().isoformat()
    })

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET — MENSAJE PRIVADO
# ✅ CORREGIDO: ENVÍA CONFIRMACIÓN AL REMITENTE
# ═══════════════════════════════════════════════════════════════

@socketio.on('send_message')
def handle_send_message(data):
    """
    Recibe un mensaje privado, lo guarda, lo deduplica, y lo retransmite.
    ✅ CORREGIDO: El remitente TAMBIÉN recibe confirmación de entrega
    """
    sender_id        = data.get('sender_id')
    sender_username  = data.get('sender_username', '?')
    recipient_id     = data.get('recipient_id')
    text             = (data.get('message') or '').strip()
    message_id       = data.get('message_id') or f"msg_{uuid.uuid4().hex[:12]}"
    attachments      = data.get('attachments') or []
    
    ts = datetime.now().isoformat()
    
    # VALIDACIONES ESTRICTAS
    try:
        sender_id    = int(sender_id)
        recipient_id = int(recipient_id)
    except (TypeError, ValueError):
        logger.error(f"❌ [MSG] IDs inválidos: sender={sender_id}, recipient={recipient_id}")
        emit('message_ack', {
            'message_id': message_id, 
            'status': 'error', 
            'reason': 'invalid_ids',
            'timestamp': ts
        })
        return
    
    # Validar que sender está registrado
    sid = request.sid
    if sid not in sid_to_userid or sid_to_userid[sid] != sender_id:
        logger.error(f"❌ [MSG] Sender no autenticado: SID={sid[:8]}, claimed={sender_id}, actual={sid_to_userid.get(sid)}")
        emit('message_ack', {
            'message_id': message_id,
            'status': 'error',
            'reason': 'not_authenticated',
            'timestamp': ts
        })
        return
    
    if not text and not attachments:
        logger.warning(f"⚠️  [MSG] Mensaje vacío: {message_id}")
        return
    
    # DEDUPLICACIÓN
    if message_id in message_ids_seen:
        logger.warning(f"⚠️  [MSG] DUPLICADO detectado: {message_id}")
        emit('message_ack', {
            'message_id': message_id,
            'status': 'ok',
            'timestamp': ts,
            'duplicated': True
        })
        return
    
    message_ids_seen.add(message_id)
    
    # Crear mensaje
    msg = {
        'id':              message_id,
        'sender_id':       sender_id,
        'sender_username': sender_username,
        'recipient_id':    recipient_id,
        'text':            text,
        'timestamp':       ts,
        'attachments':     attachments
    }
    
    # Persistir en memoria
    key = make_conv_key(sender_id, recipient_id)
    if key not in message_storage:
        message_storage[key] = []
    message_storage[key].append(msg)
    logger.info(f"💬 [MSG] {sender_username}(id={sender_id}) → id{recipient_id} (conv={key}): '{text[:40]}'")
    
    # ✅ ACK al remitente (confirmación de recepción en servidor)
    emit('message_ack', {
        'message_id': message_id,
        'status': 'ok',
        'timestamp': ts,
        'stored_at': key
    })
    
    # ✅ CORREGIDO: AHORA ENVIAMOS AL RECEPTOR
    emit('receive_message', msg, room=f"user_{recipient_id}", include_self=False)
    
    # ✅ NUEVO: TAMBIÉN ENVIAMOS AL REMITENTE (para sincronización)
    # Esto permite que el remitente vea el mensaje confirmado en todas sus pestañas
    emit('message_delivered', {
        'message_id': message_id,
        'recipient_id': recipient_id,
        'timestamp': ts,
        'delivered_to_recipient': True
    }, room=f"user_{sender_id}")
    
    logger.debug(f"📤 [EMIT] Mensaje {message_id} entregado a receptor {recipient_id}")

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET — NOTIFICACIÓN DE LECTURA
# ═══════════════════════════════════════════════════════════════

@socketio.on('message_read')
def handle_message_read(data):
    """
    Notifica que un mensaje fue leído.
    Nuevo: permite sincronización de lectura entre usuarios.
    """
    reader_id = data.get('reader_id')
    message_id = data.get('message_id')
    sender_id = data.get('sender_id')
    
    sid = request.sid
    if sid not in sid_to_userid or sid_to_userid[sid] != reader_id:
        return
    
    # Notificar al remitente que su mensaje fue leído
    emit('message_read_ack', {
        'message_id': message_id,
        'read_by': reader_id,
        'timestamp': datetime.now().isoformat()
    }, room=f"user_{sender_id}")
    
    logger.debug(f"📖 [READ] Usuario {reader_id} leyó mensaje {message_id}")

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET — CHAT GENERAL
# ═══════════════════════════════════════════════════════════════

@socketio.on('send_general_message')
def handle_general_message(data):
    """Mensaje en el chat general."""
    sid             = request.sid
    sender_id       = data.get('sender_id') or sid_to_userid.get(sid, 0)
    sender_username = data.get('sender_username', '')
    text            = (data.get('message') or '').strip()
    message_id      = data.get('message_id') or f"gchat_{uuid.uuid4().hex[:12]}"

    try:
        sender_id = int(sender_id)
    except (TypeError, ValueError):
        sender_id = 0
    
    # Deduplicación
    if any(m['id'] == message_id for m in general_storage):
        logger.warning(f"⚠️  [GCHAT] DUPLICADO: {message_id}")
        emit('message_ack', {'message_id': message_id, 'status': 'ok', 'duplicated': True})
        return

    if not text:
        return

    ts = datetime.now().isoformat()
    msg = {
        'id':              message_id,
        'sender_id':       sender_id,
        'sender_username': sender_username,
        'text':            text,
        'timestamp':       ts
    }
    general_storage.append(msg)
    logger.info(f"💬 [GCHAT] {sender_username}: '{text[:40]}'")
    
    emit('message_ack', {'message_id': message_id, 'status': 'ok', 'timestamp': ts})
    emit('receive_general_message', msg, broadcast=True, include_self=False)

# ═══════════════════════════════════════════════════════════════
# REST API — HISTÓRICO DE CONVERSACIÓN PRIVADA
# ═══════════════════════════════════════════════════════════════

@app.route('/api/messages/<int:uid_a>/<int:uid_b>', methods=['GET'])
def get_conversation(uid_a, uid_b):
    """
    Devuelve histórico de conversación entre dos usuarios.
    ✅ Con logging detallado.
    """
    key  = make_conv_key(uid_a, uid_b)
    msgs = message_storage.get(key, [])
    logger.info(f"📥 [API] GET /api/messages/{uid_a}/{uid_b} → key='{key}', msgs={len(msgs)}")
    return jsonify({
        'ok': True,
        'conv_key': key,
        'messages': msgs,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/messages/general', methods=['GET'])
def get_general_history():
    """Devuelve histórico del chat general."""
    return jsonify({
        'ok': True,
        'messages': general_storage,
        'timestamp': datetime.now().isoformat()
    })

# ═══════════════════════════════════════════════════════════════
# DEBUG API — Estado del servidor
# ═══════════════════════════════════════════════════════════════

@app.route('/api/debug/status', methods=['GET'])
def debug_status():
    """DEBUG: Estado actual del servidor."""
    return jsonify({
        'connected_users': {sid: {
            'username': info['username'],
            'user_id': info['user_id'],
            'room': info['room']
        } for sid, info in connected_users.items()},
        'message_storage_keys': list(message_storage.keys()),
        'general_chat_messages': len(general_storage),
        'seen_message_ids': len(message_ids_seen),
        'timestamp': datetime.now().isoformat()
    })

# ═══════════════════════════════════════════════════════════════
# API WHATSAPP — ENVÍO AUTOMÁTICO VÍA META
# ═══════════════════════════════════════════════════════════════

@app.route('/api/whatsapp/send', methods=['POST'])
def send_whatsapp():
    """Envía un WhatsApp directamente."""
    data = request.get_json(silent=True) or {}
    to_phone = data.get('to', '').strip()
    message  = data.get('message', '').strip()

    if not to_phone or not message:
        return jsonify({'ok': False, 'error': 'Faltan campos: to, message'}), 400

    result = send_whatsapp_meta(to_phone, message)
    
    return jsonify(result), 200 if result.get('ok') else (
        jsonify(result), 503 if not result.get('configured') else 500
    )

@app.route('/api/whatsapp/schedule', methods=['POST'])
def schedule_whatsapp():
    """Programa el envío de un WhatsApp en una fecha/hora futura."""
    if not SCHEDULER_AVAILABLE or not scheduler:
        return jsonify({
            'ok': False,
            'error': 'APScheduler no disponible. pip install apscheduler',
            'configured': False
        }), 503

    data = request.get_json(silent=True) or {}
    to_phone = data.get('to', '').strip()
    message  = data.get('message', '').strip()
    send_at  = data.get('send_at', '').strip()
    job_id   = data.get('job_id', '').strip()

    if not to_phone or not message or not send_at or not job_id:
        return jsonify({'ok': False, 'error': 'Faltan campos: to, message, send_at, job_id'}), 400

    try:
        send_dt = datetime.fromisoformat(send_at)
        if send_dt.tzinfo is None:
            madrid = pytz.timezone('Europe/Madrid')
            send_dt = madrid.localize(send_dt)
    except ValueError:
        return jsonify({'ok': False, 'error': f'Formato de send_at inválido: {send_at}'}), 400

    now_tz = datetime.now(pytz.timezone('Europe/Madrid'))
    if send_dt <= now_tz:
        return jsonify({'ok': False, 'error': 'La fecha de envío ya ha pasado'}), 400

    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    except Exception:
        pass

    try:
        scheduler.add_job(
            func=send_whatsapp_job,
            trigger=DateTrigger(run_date=send_dt),
            args=[to_phone, message],
            id=job_id,
            replace_existing=True
        )
        logger.info(f"📅 [Scheduler] WA programado para {send_dt.isoformat()} → {to_phone}")
        return jsonify({
            'ok': True,
            'job_id': job_id,
            'scheduled_for': send_dt.isoformat()
        })
    except Exception as e:
        logger.error(f"❌ [Scheduler] Error: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/whatsapp/cancel/<job_id>', methods=['DELETE'])
def cancel_whatsapp(job_id):
    """Cancela un recordatorio de WhatsApp programado."""
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
    """Comprueba si Meta API y el Scheduler están listos."""
    meta_ok = bool(META_PHONE_NUMBER_ID and META_ACCESS_TOKEN)
    scheduler_ok = SCHEDULER_AVAILABLE and scheduler is not None

    reasons = []
    if not meta_ok:
        reasons.append("Meta no configurada")
    if not SCHEDULER_AVAILABLE:
        reasons.append("APScheduler no instalado")
    elif not scheduler_ok:
        reasons.append("Scheduler no inicializado")

    return jsonify({
        'meta_ready':      meta_ok,
        'scheduler_ready': scheduler_ok,
        'fully_ready':     meta_ok and scheduler_ok,
        'reason':          ' · '.join(reasons) if reasons else 'Todo OK'
    })

# ═══════════════════════════════════════════════════════════════
# WEBHOOK PARA RECIBIR MENSAJES DE META (Opcional)
# ═══════════════════════════════════════════════════════════════

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
    logger.info(f"📨 [Webhook] Mensaje recibido de Meta: {json.dumps(data, indent=2)}")
    return jsonify({'status': 'ok'}), 200

# ═══════════════════════════════════════════════════════════════
# RUTAS API — ESTADO Y HEALTH CHECK
# ═══════════════════════════════════════════════════════════════

@app.route('/api/status')
def api_status():
    """Endpoint para verificar estado de la API"""
    return jsonify({
        'status': 'ok',
        'app': 'GestióPro',
        'version': '3.2_FIXED',
        'timestamp': datetime.now().isoformat(),
        'environment': app.config['ENV'],
        'meta_ready': bool(META_PHONE_NUMBER_ID and META_ACCESS_TOKEN),
        'scheduler_ready': SCHEDULER_AVAILABLE and scheduler is not None,
        'websocket_ready': True,
        'connected_users': len(connected_users),
        'total_conversations': len(message_storage)
    })

@app.route('/api/health')
def api_health():
    """Endpoint de health check para Render"""
    return jsonify({
        'status': 'healthy',
        'service': 'gestionpro-v3.2_FIXED',
        'timestamp': datetime.now().isoformat()
    }), 200

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
# CONFIGURACIÓN DE PUERTO Y HOST
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