import os
import json
from flask import Flask, render_template, jsonify, request, send_from_directory
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
app = Flask(__name__, template_folder='.', static_folder='static')
app.config['ENV'] = os.environ.get('FLASK_ENV', 'production')
app.config['DEBUG'] = False if app.config['ENV'] == 'production' else True
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

# Configurar SocketIO
# async_mode threading es compatible con Python 3.14 sin dependencias externas
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    async_mode='threading',
    logger=False,
    engineio_logger=False,
    max_http_buffer_size=20 * 1024 * 1024,  # 20MB para adjuntos
)

# Almacenar usuarios conectados en tiempo real
connected_users = {}
active_chats = {}

# ═══════════════════════════════════════════════════════════════
# RUTAS PRINCIPALES
# ═══════════════════════════════════════════════════════════════

@app.route('/')
@app.route('/app')
@app.route('/index')
@app.route('/gestionpro')
def home():
    """Servir la aplicación"""
    # Busca index3.html en el mismo directorio que app.py
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(base_dir, 'index3.html')

# ═══════════════════════════════════════════════════════════════
# ALMACENAMIENTO EN MEMORIA — MENSAJERÍA
# Los mensajes persisten mientras el servidor esté activo.
# ═══════════════════════════════════════════════════════════════

# Chat general: historial compartido
general_chat_messages = []
general_chat_counter  = 100

# Mensajes privados: { "uid_a-uid_b": [{id, fromId, toId, text, time, attachments}] }
private_messages = {}

# Mapeo sid → userId para gestionar desconexiones
sid_to_userid = {}


def _conv_key(a, b):
    """Clave única y ordenada para una conversación entre dos usuarios."""
    return "-".join(str(x) for x in sorted([int(a), int(b)]))

def _now_time():
    return datetime.now().strftime("%H:%M")

def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


# ═══════════════════════════════════════════════════════════════
# WEBSOCKET EVENTS — MENSAJERÍA EN TIEMPO REAL
# ═══════════════════════════════════════════════════════════════

@socketio.on('connect')
def handle_connect(auth=None):
    logger.info(f"🔗 [Socket] Nueva conexión: {request.sid}")
    emit('connect_ack', {'sid': request.sid})


@socketio.on('disconnect')
def handle_disconnect():
    uid = sid_to_userid.pop(request.sid, None)
    connected_users.pop(request.sid, None)
    if uid:
        leave_room(f"user_{uid}")
        leave_room("general")
        logger.info(f"❌ [Socket] uid={uid} desconectado")


@socketio.on('authenticate')
def handle_authenticate(data):
    """
    El cliente envía su userId real (numérico) justo al conectar.
    Esto mete al usuario en:
      - sala personal "user_{userId}"  → mensajes privados
      - sala "general"                 → chat grupal
    Y le devuelve el historial del chat general.
    """
    user_id  = data.get('userId')
    username = data.get('username', '')
    if not user_id:
        return

    sid_to_userid[request.sid] = user_id
    connected_users[request.sid] = {'userId': user_id, 'username': username}

    join_room(f"user_{user_id}")
    join_room("general")
    logger.info(f"✅ [Socket] Autenticado: userId={user_id} ({username})")

    # Enviar historial completo del chat general
    emit('gchat_history', {'messages': general_chat_messages})


@socketio.on('gchat_send')
def handle_gchat_send(data):
    """Guarda el mensaje y hace broadcast a TODOS en la sala general."""
    global general_chat_counter
    msg = {
        'id':          general_chat_counter,
        'userId':      data.get('userId'),
        'text':        data.get('text', ''),
        'time':        data.get('time', _now_time()),
        'date':        data.get('date', _today_str()),
        'attachments': data.get('attachments', []),
    }
    general_chat_counter += 1
    general_chat_messages.append(msg)
    logger.info(f"💬 [GChat] uid={msg['userId']}: {str(msg['text'])[:60]}")
    # room='general' incluye al propio emisor
    socketio.emit('gchat_message', msg, room='general')


@socketio.on('private_send')
def handle_private_send(data):
    """Guarda el mensaje privado y lo entrega a emisor y receptor."""
    import uuid as _uuid
    from_id = data.get('fromId')
    to_id   = data.get('toId')
    if not from_id or not to_id:
        return

    key = _conv_key(from_id, to_id)
    private_messages.setdefault(key, [])

    msg = {
        'id':          str(_uuid.uuid4()),
        'fromId':      int(from_id),
        'toId':        int(to_id),
        'text':        data.get('text', ''),
        'time':        data.get('time', _now_time()),
        'attachments': data.get('attachments', []),
    }
    private_messages[key].append(msg)
    logger.info(f"🔒 [Private] {from_id}→{to_id}: {str(msg['text'])[:60]}")

    # Entregar a la sala del emisor Y a la sala del receptor
    socketio.emit('private_message', msg, room=f"user_{from_id}")
    socketio.emit('private_message', msg, room=f"user_{to_id}")


@socketio.on('request_private_history')
def handle_private_history(data):
    """Devuelve el historial entre dos usuarios al solicitante."""
    a = data.get('userId')
    b = data.get('otherId')
    if not a or not b:
        return
    key  = _conv_key(a, b)
    msgs = private_messages.get(key, [])
    emit('private_history', {'otherId': int(b), 'messages': msgs})

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
        "send_at":     "2025-06-15T10:00:00",   ← fecha/hora de Madrid
        "job_id":      "wa_evento_42"            ← ID único (para evitar duplicados)
    }

    Respuesta OK:    { "ok": true,  "job_id": "wa_evento_42", "scheduled_for": "..." }
    Respuesta error: { "ok": false, "error": "motivo" }
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
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(base_dir, 'index3.html'), 200

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
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True,
        use_reloader=False,
    )