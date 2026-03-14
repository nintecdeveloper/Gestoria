import os
import json
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
import requests
import logging

# ═══════════════════════════════════════════════════════════════
# LOGGING — CONFIGURACIÓN INMEDIATA (ANTES DE CUALQUIER USO)
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
META_API_URL = f"https://graph.facebook.com/{META_API_VERSION}/{{phone_id}}/messages"
# ═══════════════════════════════════════════════════════════════
# USUARIOS Y CALENDARIOS — DATOS INICIALES
# ═══════════════════════════════════════════════════════════════

# Lista de usuarios (sin Sara)
USUARIOS = [
    {'id': 1, 'nombre': 'Antonio', 'departamento': 'admin', 'email': 'antonio@rodonverges.com', 'rol': 'admin', 'sede': 'Mataró'},
    {'id': 3, 'nombre': 'Pau', 'departamento': 'admin', 'email': 'pau@rodonverges.com', 'rol': 'admin', 'sede': 'Vilassar'},
    {'id': 2, 'nombre': 'Myriam', 'departamento': 'laboral', 'email': 'myriam@rodonverges.com', 'rol': 'user', 'sede': 'Vilassar'},
    {'id': 4, 'nombre': 'Montse Martín', 'departamento': 'laboral', 'email': 'montse@rodonverges.com', 'rol': 'user', 'sede': 'Mataró'},
    {'id': 5, 'nombre': 'Anna Fabregà', 'departamento': 'fiscal', 'email': 'anna@rodonverges.com', 'rol': 'user', 'sede': 'Vilassar'},
]

# Estructura de calendarios
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
def send_whatsapp_job(to_phone: str, message: str):

    # 1. Enviar WhatsApp
    result = send_whatsapp_meta(to_phone, message)

    if result['ok']:
        logger.info(f"✅ [Scheduler/Meta] Recordatorio enviado a {to_phone}")
    else:
        logger.error(f"❌ [Scheduler/Meta] No se pudo enviar a {to_phone}: {result.get('error')}")

    # 2. Enviar notificación al CRM (usuarios conectados)
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

# Almacenar usuarios conectados en tiempo real
connected_users = {}  # {sid: {username, sid, connected_at}}
username_to_sid = {}  # {username: sid} - MAPEO PARA ENCONTRAR USUARIOS
active_chats = {}
message_storage = {}  # {conv_id: [messages]} - ALMACENAR MENSAJES EN SERVIDOR

# ═══════════════════════════════════════════════════════════════
# RUTAS PRINCIPALES
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def home():
    """Ruta principal - Servir GestióPro"""
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
        # LIMPIAR MAPEO USERNAME-SID
        if username in username_to_sid:
            del username_to_sid[username]
        logger.info(f"❌ [Socket] {username} desconectado")
    else:
        logger.info(f"❌ [Socket] Usuario desconectado: {user_id}")

@socketio.on('user_login')
def handle_user_login(data):
    """Registra un usuario como conectado"""
    user_id = request.sid
    username = data.get('username', f'User_{user_id[:8]}')
    connected_users[user_id] = {
        'username': username,
        'sid': user_id,
        'connected_at': datetime.now().isoformat()
    }
    # MAPEAR USERNAME A SID PARA BÚSQUEDA RÁPIDA
    username_to_sid[username] = user_id
    logger.info(f"✅ [Chat] {username} conectado (SID: {user_id})")
    
    # Notificar a todos que hay un nuevo usuario online
    socketio.emit('user_status_update', {
        'user_id': user_id,
        'username': username,
        'status': 'online',
        'online_users': len(connected_users)
    }, broadcast=True)

@socketio.on('send_message')
def handle_message(data):
    """Recibe un mensaje privado y lo retransmite"""
    sender_id = request.sid
    sender_username = data.get('sender_username', 'Usuario')
    recipient_username = data.get('recipient_username', '')  # NOMBRE DE USUARIO, NO ID
    message_text = data.get('message', '')
    message_id = data.get('message_id', f'msg_{datetime.now().timestamp()}')
    conv_id = data.get('conv_id', f'{sender_username}_{recipient_username}')
    
    if not message_text.strip():
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
        'read': False
    }
    
    # ALMACENAR MENSAJE EN SERVIDOR
    if conv_id not in message_storage:
        message_storage[conv_id] = []
    message_storage[conv_id].append(message_obj)
    
    logger.info(f"💬 [Chat Privado] {sender_username} → {recipient_username}: {message_text[:50]}")
    
    # BUSCAR EL SID DEL RECEPTOR POR USERNAME
    recipient_sid = username_to_sid.get(recipient_username)
    
    if recipient_sid and recipient_sid in connected_users:
        # ENVIAR MENSAJE AL DESTINATARIO
        socketio.emit('receive_message', message_obj, room=recipient_sid)
        logger.info(f"✅ [Mensaje Entregado] A {recipient_username} (SID: {recipient_sid})")
        
        # ENVIAR NOTIFICACIÓN AL DESTINATARIO
        socketio.emit('message_notification', {
            'from': sender_username,
            'message': message_text[:50] + '...' if len(message_text) > 50 else message_text,
            'timestamp': datetime.now().isoformat()
        }, room=recipient_sid)
        logger.info(f"🔔 [Notificación Enviada] A {recipient_username}")
    else:
        logger.warning(f"⚠️ [Mensaje No Entregado] {recipient_username} no conectado")
    
    # CONFIRMAR AL REMITENTE
    socketio.emit('message_sent', {
        'message_id': message_id,
        'status': 'sent',
        'timestamp': datetime.now().isoformat()
    }, room=sender_id)

@socketio.on('send_general_message')
def handle_general_message(data):
    """Recibe un mensaje del chat general y lo retransmite a todos"""
    sender_id = request.sid
    sender_username = data.get('sender_username', 'Usuario')
    message_text = data.get('message', '')
    message_id = data.get('message_id', f'msg_{datetime.now().timestamp()}')
    
    if not message_text.strip():
        return
    
    # Crear objeto de mensaje
    message_obj = {
        'id': message_id,
        'sender_id': sender_id,
        'sender_username': sender_username,
        'text': message_text,
        'timestamp': datetime.now().isoformat()
    }
    
    logger.info(f"💬 [Chat General] {sender_username}: {message_text[:50]}")
    
    # Retransmitir a todos los usuarios conectados
    socketio.emit('receive_general_message', message_obj, broadcast=True)
    
    # ENVIAR NOTIFICACIÓN A TODOS (excepto al remitente)
    socketio.emit('general_message_notification', {
        'from': sender_username,
        'message': message_text[:50] + '...' if len(message_text) > 50 else message_text,
        'timestamp': datetime.now().isoformat()
    }, broadcast=True, skip_sid=sender_id)
    logger.info(f"🔔 [Notificación Chat General Enviada] De {sender_username}")

@socketio.on('typing')
def handle_typing(data):
    """Notifica que alguien está escribiendo"""
    sender_id = request.sid
    recipient_username = data.get('recipient_username', '')
    sender_username = data.get('sender_username', 'Usuario')
    
    # BUSCAR RECEPTOR POR USERNAME
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
    
    # BUSCAR RECEPTOR POR USERNAME
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
    notification_type = data.get('type', 'info')  # info, warning, error, success
    message = data.get('message', '')
    title = data.get('title', '')
    
    # BUSCAR RECEPTOR POR USERNAME
    recipient_sid = username_to_sid.get(recipient_username)
    if recipient_sid and recipient_sid in connected_users:
        # ✅ CORRECCIÓN: Cambiar recipient_id por recipient_sid
        socketio.emit('notification_received', {
            'type': notification_type,
            'title': title,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }, room=recipient_sid)  # ← AQUÍ ESTÁ LA CORRECCIÓN
        logger.info(f"🔔 [Notification] Enviada a {recipient_sid[:8]}: {title}")

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
# API MENSAJERÍA — RECUPERAR HISTÓRICO
# ═══════════════════════════════════════════════════════════════

@app.route('/api/messages/<conv_id>', methods=['GET'])
def get_messages(conv_id):
    """
    Recupera el histórico de mensajes de una conversación.
    conv_id puede ser 'userA_userB' o 'userB_userA' (bidireccional).
    """
    if not conv_id:
        return jsonify({'ok': False, 'error': 'conv_id requerido', 'messages': []}), 400

    # Buscar en ambas direcciones (userA_userB o userB_userA)
    messages = message_storage.get(conv_id)
    resolved_id = conv_id
    if messages is None:
        parts = conv_id.split('_', 1)
        if len(parts) == 2:
            alt_id = f"{parts[1]}_{parts[0]}"
            messages = message_storage.get(alt_id)
            resolved_id = alt_id if messages is not None else conv_id

    if messages is None:
        return jsonify({'ok': True, 'conv_id': conv_id, 'messages': []})

    logger.info(f"📥 [Mensajes] Recuperando {len(messages)} mensajes de {resolved_id}")
    return jsonify({'ok': True, 'conv_id': resolved_id, 'messages': messages})


@app.route('/api/messages/<conv_id>/read', methods=['POST'])
def mark_messages_read(conv_id):
    """Marca todos los mensajes de una conversación como leídos."""
    messages = message_storage.get(conv_id, [])
    reader = request.get_json(silent=True, force=True) or {}
    reader_username = reader.get('username', '')
    for m in messages:
        if m.get('recipient_username') == reader_username:
            m['read'] = True
    return jsonify({'ok': True})

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
# API ADJUNTOS EN MENSAJERÍA
# ═══════════════════════════════════════════════════════════════

@app.route('/api/messages/attachment/<msg_id>/<filename>', methods=['GET'])
def get_message_attachment(msg_id, filename):
    """
    Descargar un archivo adjunto de un mensaje.
    Los archivos se almacenan en base64 en el servidor.
    """
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
                            
                            import base64
                            binary_data = base64.b64decode(file_data)
                            
                            from flask import send_file
                            from io import BytesIO
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
        'attachments': attachments  # ← AGREGAR ADJUNTOS
    }
    
    # ALMACENAR MENSAJE EN SERVIDOR
    if conv_id not in message_storage:
        message_storage[conv_id] = []
    message_storage[conv_id].append(message_obj)
    
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
# API CHATS AUTOMÁTICOS POR SEDE
# ═══════════════════════════════════════════════════════════════

def create_seat_chats(user_id, user_name, user_sede):
    """
    Crea automáticamente los chats de sede cuando se añade un usuario.
    - Chat de sede (todos los usuarios de la sede + admins)
    - Chats individuales con otros usuarios de la misma sede
    """
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
