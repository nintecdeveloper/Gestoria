import os
import json
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
import requests
import logging

# ═══════════════════════════════════════════════════════════════
# META WHATSAPP API — IMPORTACIÓN CONDICIONAL
# Ahora usamos Meta Cloud API en lugar de Twilio
# ═══════════════════════════════════════════════════════════════
META_AVAILABLE = True
REQUESTS_AVAILABLE = True

# ═══════════════════════════════════════════════════════════════
# APSCHEDULER — IMPORTACIÓN CONDICIONAL
# Programa el envío de WhatsApp desde el servidor, independiente
# de si el navegador está abierto o cerrado.
# ═══════════════════════════════════════════════════════════════
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
# ─────────────────────────────────────────────────────────────
# PASOS PARA ACTIVAR (cuando tengas las credenciales de Meta):
#
#   1. Ve a https://developers.facebook.com/
#   2. Crea un proyecto y selecciona "WhatsApp"
#   3. En la sección "Getting Started", obtén:
#        · Phone Number ID (de tu número de negocio)
#        · Access Token (con permisos whatsapp_business_messaging)
#        · Business Account ID
#   4. En Render, ve a tu servicio → Environment → Add Environment Variable
#        · META_PHONE_NUMBER_ID = 1234567890123456789
#        · META_ACCESS_TOKEN = EAAxxxxxxxxxxxxxxxxxxxxxxxx
#        · META_BUSINESS_ACCOUNT_ID = xxxxxxxxxx
#   5. El código está adaptado para usar estas variables
#
# ─────────────────────────────────────────────────────────────
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
    """
    Envía un mensaje de WhatsApp via Meta Cloud API.
    
    Args:
        to_phone: Número de teléfono destino (ej: +34612345678)
        message: Contenido del mensaje
        message_type: Tipo de mensaje ('text', 'template', etc.)
    
    Returns:
        dict: {'ok': True/False, 'message_id': '...', 'error': '...'}
    """
    if not META_PHONE_NUMBER_ID or not META_ACCESS_TOKEN:
        return {
            'ok': False,
            'error': 'Credenciales Meta no configuradas en variables de entorno.',
            'configured': False
        }
    
    # Normalizar número
    phone = to_phone.strip()
    if not phone.startswith('+'):
        phone = '+34' + phone.lstrip('0')
    
    # Preparar payload según tipo de mensaje
    if message_type == "text":
        payload = {
            "messaging_product": "whatsapp",
            "to": phone.replace('+', ''),  # Meta API requiere sin el +
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
    """
    Tarea ejecutada por el scheduler en el momento programado.
    Envía el WhatsApp via Meta Cloud API directamente desde el servidor.
    """
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

# Configurar SocketIO con soporte para Render
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    async_mode='threading'
)

# ═══════════════════════════════════════════════════════════════
# ESTADO GLOBAL — MENSAJERÍA
# CLAVE DE CONV: misma lógica que el frontend:
#   [a, b].sort().join("-")  →  ej: "1-2" para Antonio↔Myriam
# ═══════════════════════════════════════════════════════════════
connected_users = {}   # sid → {username, user_id, connected_at}
sid_to_userid   = {}   # sid → user_id (int)
# conv_key "MIN_ID-MAX_ID" → lista de mensajes
message_storage = {}   # {"1-2": [{id, sender_id, sender_username, recipient_id, text, timestamp, attachments}]}
general_storage = []   # [{id, sender_id, sender_username, text, timestamp}]

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
    logger.info(f"🔗 [WS] Nuevo socket: {request.sid}")
    emit('connect_ack', {'sid': request.sid})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    info = connected_users.pop(sid, None)
    sid_to_userid.pop(sid, None)
    if info:
        logger.info(f"❌ [WS] {info['username']} desconectado (sid={sid[:8]})")

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET — REGISTRO (join room personal)
# ═══════════════════════════════════════════════════════════════

@socketio.on('user_login')
def handle_user_login(data):
    sid     = request.sid
    username = data.get('username', f'User_{sid[:6]}')
    user_id  = data.get('userId')
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        user_id = 0

    connected_users[sid] = {
        'username': username,
        'user_id':  user_id,
        'connected_at': datetime.now().isoformat()
    }
    sid_to_userid[sid] = user_id

    # Unir a la room personal "user_<id>" — el emit de mensajes
    # privados apunta a esta room, sin necesidad de conocer el SID.
    room = f"user_{user_id}"
    join_room(room)
    logger.info(f"✅ [WS] {username} (id={user_id}) → room '{room}' (sid={sid[:8]})")

    # ACK al cliente
    emit('login_ack', {'ok': True, 'room': room, 'user_id': user_id})

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET — MENSAJE PRIVADO
# ═══════════════════════════════════════════════════════════════

@socketio.on('send_message')
def handle_send_message(data):
    sender_id        = data.get('sender_id')
    sender_username  = data.get('sender_username', '')
    recipient_id     = data.get('recipient_id')
    text             = (data.get('message') or '').strip()
    message_id       = data.get('message_id') or f"msg_{datetime.now().timestamp()}"
    attachments      = data.get('attachments') or []

    # Convertir IDs a int
    try:
        sender_id    = int(sender_id)
        recipient_id = int(recipient_id)
    except (TypeError, ValueError):
        emit('message_ack', {'message_id': message_id, 'status': 'error', 'reason': 'invalid_ids'})
        return

    if not text and not attachments:
        return

    ts = datetime.now().isoformat()
    msg = {
        'id':              message_id,
        'sender_id':       sender_id,
        'sender_username': sender_username,
        'recipient_id':    recipient_id,
        'text':            text,
        'timestamp':       ts,
        'attachments':     attachments
    }

    # Persistir con la misma clave que convKey() del frontend
    key = make_conv_key(sender_id, recipient_id)
    if key not in message_storage:
        message_storage[key] = []
    message_storage[key].append(msg)
    logger.info(f"💬 [MSG PRIVADO] {sender_username}→id{recipient_id} (conv={key}): '{text[:40]}'")

    # Entregar al receptor via su room personal
    # NOTA: emit() sin socketio. usa el contexto del handler actual (correcto para threading)
    emit('receive_message', msg, room=f"user_{recipient_id}", include_self=False)

    # ACK al remitente
    emit('message_ack', {'message_id': message_id, 'status': 'ok', 'timestamp': ts})

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET — CHAT GENERAL
# ═══════════════════════════════════════════════════════════════

@socketio.on('send_general_message')
def handle_general_message(data):
    sid             = request.sid
    sender_id       = data.get('sender_id') or sid_to_userid.get(sid, 0)
    sender_username = data.get('sender_username', '')
    text            = (data.get('message') or '').strip()
    message_id      = data.get('message_id') or f"gchat_{datetime.now().timestamp()}"

    try:
        sender_id = int(sender_id)
    except (TypeError, ValueError):
        sender_id = 0

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
    emit('receive_general_message', msg, broadcast=True)

# ═══════════════════════════════════════════════════════════════
# REST API — HISTÓRICO DE CONVERSACIÓN PRIVADA
#   GET /api/messages/<id_a>/<id_b>
#   Devuelve todos los mensajes entre los dos usuarios.
#   El frontend llama esto al hacer login para cargar el histórico.
# ═══════════════════════════════════════════════════════════════

@app.route('/api/messages/<int:uid_a>/<int:uid_b>', methods=['GET'])
def get_conversation(uid_a, uid_b):
    key  = make_conv_key(uid_a, uid_b)
    msgs = message_storage.get(key, [])
    logger.info(f"📥 [API] Histórico {key}: {len(msgs)} mensajes")
    return jsonify({'ok': True, 'conv_key': key, 'messages': msgs})

@app.route('/api/messages/general', methods=['GET'])
def get_general_history():
    return jsonify({'ok': True, 'messages': general_storage})

# ═══════════════════════════════════════════════════════════════
# API WHATSAPP — ENVÍO AUTOMÁTICO VÍA META
# ═══════════════════════════════════════════════════════════════

@app.route('/api/whatsapp/send', methods=['POST'])
def send_whatsapp():
    """
    Envía un mensaje de WhatsApp INMEDIATAMENTE via Meta Cloud API.
    Usado para el timing 'now' (envío al guardar la cita).

    Body JSON esperado:
    {
        "to":      "+34612345678",
        "message": "Hola, le recordamos su cita..."
    }

    Respuesta OK:    { "ok": true,  "message_id": "wamid..." }
    Respuesta error: { "ok": false, "error": "motivo" }
    """
    data = request.get_json(silent=True) or {}
    to_phone = data.get('to', '').strip()
    message  = data.get('message', '').strip()

    if not to_phone:
        return jsonify({'ok': False, 'error': 'Falta el campo "to" (teléfono destino)'}), 400
    if not message:
        return jsonify({'ok': False, 'error': 'Falta el campo "message"'}), 400

    result = send_whatsapp_meta(to_phone, message)
    
    if result['ok']:
        return jsonify({'ok': True, 'message_id': result.get('message_id')})
    else:
        return jsonify({
            'ok': False,
            'error': result.get('error'),
            'configured': result.get('configured', False)
        }), 503 if not result.get('configured') else 500


@app.route('/api/whatsapp/schedule', methods=['POST'])
def schedule_whatsapp():
    """
    Programa el envío de un WhatsApp en una fecha/hora futura.
    El servidor lo enviará automáticamente aunque el navegador esté cerrado.
    Usado para los timings '1h', '1d', '1w'.

    Body JSON esperado:
    {
        "to":          "+34612345678",
        "message":     "Hola, le recordamos su cita...",
        "send_at":     "2025-06-15T10:00:00",   ← fecha/hora de Madrid (IMPORTANTE)
        "job_id":      "wa_evento_42"            ← ID único (para evitar duplicados)
    }

    Respuesta OK:    { "ok": true,  "job_id": "wa_evento_42", "scheduled_for": "..." }
    Respuesta error: { "ok": false, "error": "motivo" }
    
    ✅ IMPORTANTE: El frontend debe enviar la fecha/hora EN HORA LOCAL DE MADRID
       convertida correctamente desde el navegador del usuario.
    """
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
    """
    Cancela un recordatorio de WhatsApp programado.
    Útil si se elimina o modifica una cita.

    Respuesta OK:    { "ok": true }
    Respuesta error: { "ok": false, "error": "motivo" }
    """
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
    """
    Comprueba si Meta API y el Scheduler están listos.
    
    Respuesta:
    {
        "meta_ready":      true/false,
        "scheduler_ready": true/false,
        "fully_ready":     true/false,
        "reason":          "..."
    }
    """
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
        'meta_ready':      meta_ok,
        'scheduler_ready': scheduler_ok,
        'fully_ready':     meta_ok and scheduler_ok,
        'reason':          ' · '.join(reasons) if reasons else 'Todo configurado correctamente'
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
    # Aquí puedes procesar mensajes entrantes si lo necesitas
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
# MANEJO DE ERRORES
# ═══════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(error):
    """Manejar errores 404 - Servir la app en lugar de error"""
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
    
    # Para Render: usar socketio.run en lugar de app.run
    socketio.run(
        app,
        host=host,
        port=port,
        debug=app.config['DEBUG'],
        allow_unsafe_werkzeug=True
    )