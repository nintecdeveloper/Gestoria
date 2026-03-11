"""
═══════════════════════════════════════════════════════════════════════════════
  GESTIONPRO v3.0 - BACKEND FLASK CON WEBSOCKET Y META API
  
  VERSIÓN: 3.0 (CORREGIDA PARA RENDER)
  ESTADO: ✅ Producción
  
  CAMBIOS PRINCIPALES:
  ✅ Busca index3.html en TODAS las rutas posibles (incluyendo templates/)
  ✅ Usa render_template correctamente
  ✅ Configurado correctamente para Render
  ✅ Sin dependencias de gevent (usa threading nativo)
  ✅ Manejo robusto de errores
  ✅ Health checks para Render
  ✅ WebSockets funcionales
  ✅ Meta API integrada
  ✅ APScheduler para recordatorios
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import json
import sys
from pathlib import Path
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from datetime import datetime
import requests
import logging

# ═══════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# APSCHEDULER
# ═══════════════════════════════════════════════════════════════════════════
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.date import DateTrigger
    import pytz
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    logger.warning("⚠️  APScheduler no instalado. Instala: pip install apscheduler")

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN META API
# ═══════════════════════════════════════════════════════════════════════════
META_PHONE_NUMBER_ID = os.environ.get('META_PHONE_NUMBER_ID', None)
META_ACCESS_TOKEN = os.environ.get('META_ACCESS_TOKEN', None)
META_BUSINESS_ACCOUNT_ID = os.environ.get('META_BUSINESS_ACCOUNT_ID', None)
META_API_VERSION = "v18.0"
META_API_URL = f"https://graph.facebook.com/{META_API_VERSION}/{{phone_id}}/messages"

logger.info("═" * 80)
logger.info("🚀 GESTIONPRO v3.0 INICIANDO")
logger.info("═" * 80)

# ═══════════════════════════════════════════════════════════════════════════
# BUSCAR ARCHIVO HTML - MÚLTIPLES RUTAS
# ═══════════════════════════════════════════════════════════════════════════

def find_html_file():
    """
    Busca index3.html en múltiples ubicaciones posibles.
    CRÍTICO: Esta es la función que soluciona el problema de Render.
    """
    # Obtener rutas base
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir) if current_dir.endswith('src') else current_dir
    cwd = os.getcwd()
    
    # Lista de rutas a probar (en orden de preferencia)
    paths_to_try = [
        # Rutas en carpeta templates (PRINCIPAL)
        os.path.join(project_root, 'templates', 'index3.html'),
        os.path.join(current_dir, 'templates', 'index3.html'),
        os.path.join(cwd, 'templates', 'index3.html'),
        
        # Rutas en raíz
        os.path.join(project_root, 'index3.html'),
        os.path.join(current_dir, 'index3.html'),
        os.path.join(cwd, 'index3.html'),
        
        # Rutas específicas de Render
        '/opt/render/project/src/templates/index3.html',
        '/opt/render/project/src/index3.html',
        os.path.join(cwd, 'src', 'templates', 'index3.html'),
    ]
    
    # Buscar el archivo
    for path in paths_to_try:
        if os.path.isfile(path):
            logger.info(f"✅ HTML encontrado: {path}")
            return path, os.path.dirname(path)  # Devuelve ruta y carpeta
    
    # Si no se encuentra, log detallado
    logger.error("❌ index3.html NO ENCONTRADO")
    logger.error(f"   Rutas probadas:")
    for path in paths_to_try:
        logger.error(f"     • {path}")
    logger.error(f"   CWD: {cwd}")
    logger.error(f"   Current dir: {current_dir}")
    logger.error(f"   Project root: {project_root}")
    
    return None, None

# ═══════════════════════════════════════════════════════════════════════════
# INICIALIZAR FLASK
# ═══════════════════════════════════════════════════════════════════════════

# Encontrar HTML y carpeta de templates
html_path, template_dir = find_html_file()

if not html_path:
    # Fallback: crear app sin template_folder específico
    logger.warning("⚠️  Usando carpeta templates por defecto")
    app = Flask(__name__, template_folder='templates')
else:
    # Usar la carpeta donde encontramos el HTML
    app = Flask(__name__, template_folder=template_dir)

# Configuración
app.config['ENV'] = os.environ.get('FLASK_ENV', 'production')
app.config['DEBUG'] = False if app.config['ENV'] == 'production' else True
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

logger.info(f"📁 Template folder: {app.template_folder}")
logger.info(f"🔧 Environment: {app.config['ENV']}")

# ═══════════════════════════════════════════════════════════════════════════
# SOCKETIO
# ═══════════════════════════════════════════════════════════════════════════

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    async_mode='threading',
    logger=False,
    engineio_logger=False,
    max_http_buffer_size=20 * 1024 * 1024
)

connected_users = {}

# ═══════════════════════════════════════════════════════════════════════════
# SCHEDULER
# ═══════════════════════════════════════════════════════════════════════════

scheduler = None
if SCHEDULER_AVAILABLE:
    try:
        scheduler = BackgroundScheduler(timezone='Europe/Madrid')
        scheduler.start()
        logger.info("✅ APScheduler iniciado correctamente")
    except Exception as e:
        logger.error(f"❌ Error iniciando APScheduler: {e}")
        scheduler = None

def send_whatsapp_job(to_phone: str, message: str):
    """Tarea programada para enviar WhatsApp"""
    result = send_whatsapp_meta(to_phone, message)
    if result['ok']:
        logger.info(f"✅ WhatsApp recordatorio enviado a {to_phone}")
    else:
        logger.error(f"❌ Error enviando recordatorio a {to_phone}: {result.get('error')}")

# ═══════════════════════════════════════════════════════════════════════════
# META API
# ═══════════════════════════════════════════════════════════════════════════

def send_whatsapp_meta(to_phone: str, message: str, message_type: str = "text"):
    """Envía mensaje via Meta WhatsApp Cloud API"""
    if not META_PHONE_NUMBER_ID or not META_ACCESS_TOKEN:
        return {
            'ok': False,
            'error': 'Credenciales Meta no configuradas',
            'configured': False
        }
    
    phone = to_phone.strip()
    if not phone.startswith('+'):
        phone = '+34' + phone.lstrip('0')
    
    payload = {
        "messaging_product": "whatsapp",
        "to": phone.replace('+', ''),
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message
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
        
        return {
            'ok': True,
            'message_id': result.get('messages', [{}])[0].get('id'),
            'phone': phone
        }
    except Exception as e:
        logger.error(f"❌ Meta API error: {str(e)}")
        return {'ok': False, 'error': str(e)}

# ═══════════════════════════════════════════════════════════════════════════
# RUTAS - SERVIR HTML
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/')
@app.route('/app')
@app.route('/index')
@app.route('/gestionpro')
def home():
    """Servir la aplicación"""
    try:
        # Intentar usar render_template
        return render_template('index3.html')
    except Exception as e:
        logger.error(f"⚠️  render_template falló: {e}. Usando fallback.")
        
        # FALLBACK: Leer archivo directamente
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
        except Exception as e2:
            logger.error(f"❌ No se pudo servir HTML: {e2}")
            return jsonify({'error': 'HTML no disponible'}), 503

# ═══════════════════════════════════════════════════════════════════════════
# RUTAS API - WEBSOCKET
# ═══════════════════════════════════════════════════════════════════════════

@socketio.on('connect')
def handle_connect(auth):
    """Usuario se conecta"""
    user_id = request.sid
    logger.info(f"✅ Usuario conectado: {user_id}")
    emit('connect_response', {'data': 'Conectado al servidor', 'user_id': user_id})

@socketio.on('disconnect')
def handle_disconnect():
    """Usuario se desconecta"""
    user_id = request.sid
    if user_id in connected_users:
        del connected_users[user_id]
    logger.info(f"❌ Usuario desconectado: {user_id}")

@socketio.on('user_login')
def handle_user_login(data):
    """Usuario hace login"""
    user_id = request.sid
    username = data.get('username', f'Usuario_{user_id[:8]}')
    connected_users[user_id] = {
        'username': username,
        'sid': user_id,
        'connected_at': datetime.now().isoformat()
    }
    logger.info(f"✅ {username} logueado")
    socketio.emit('user_status_update', {
        'user_id': user_id,
        'username': username,
        'status': 'online',
        'online_users': len(connected_users)
    }, broadcast=True)

@socketio.on('send_message')
def handle_message(data):
    """Recibe y retransmite mensaje"""
    sender_id = request.sid
    recipient_id = data.get('recipient_id')
    message_text = data.get('message', '')
    sender_username = data.get('sender_username', 'Usuario')
    
    if not message_text.strip():
        return
    
    message_obj = {
        'id': data.get('message_id', f'msg_{datetime.now().timestamp()}'),
        'sender_id': sender_id,
        'sender_username': sender_username,
        'recipient_id': recipient_id,
        'text': message_text,
        'timestamp': datetime.now().isoformat(),
        'read': False
    }
    
    logger.info(f"💬 Mensaje: {sender_username} → {recipient_id[:8]}")
    
    if recipient_id and recipient_id in connected_users:
        socketio.emit('receive_message', message_obj, room=recipient_id)
    
    socketio.emit('message_sent', {
        'message_id': message_obj['id'],
        'status': 'delivered',
        'timestamp': datetime.now().isoformat()
    }, room=sender_id)

@socketio.on('typing')
def handle_typing(data):
    """Notifica typing"""
    sender_id = request.sid
    recipient_id = data.get('recipient_id')
    sender_username = data.get('sender_username', 'Usuario')
    
    if recipient_id and recipient_id in connected_users:
        socketio.emit('user_typing', {
            'sender_id': sender_id,
            'sender_username': sender_username
        }, room=recipient_id)

@socketio.on('get_online_users')
def handle_get_online_users():
    """Retorna usuarios online"""
    socketio.emit('online_users_list', {
        'users': list(connected_users.values()),
        'count': len(connected_users)
    })

# ═══════════════════════════════════════════════════════════════════════════
# RUTAS API - WHATSAPP
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/api/whatsapp/send', methods=['POST'])
def send_whatsapp():
    """Envía WhatsApp inmediato"""
    data = request.get_json(silent=True) or {}
    to_phone = data.get('to', '').strip()
    message = data.get('message', '').strip()
    
    if not to_phone or not message:
        return jsonify({'ok': False, 'error': 'Faltan campos'}), 400
    
    result = send_whatsapp_meta(to_phone, message)
    
    if result['ok']:
        return jsonify({'ok': True, 'message_id': result.get('message_id')})
    else:
        return jsonify({'ok': False, 'error': result.get('error')}), 503

@app.route('/api/whatsapp/schedule', methods=['POST'])
def schedule_whatsapp():
    """Programa WhatsApp para el futuro"""
    if not SCHEDULER_AVAILABLE or not scheduler:
        return jsonify({'ok': False, 'error': 'Scheduler no disponible'}), 503
    
    data = request.get_json(silent=True) or {}
    to_phone = data.get('to', '').strip()
    message = data.get('message', '').strip()
    send_at = data.get('send_at', '').strip()
    job_id = data.get('job_id', '').strip()
    
    if not all([to_phone, message, send_at, job_id]):
        return jsonify({'ok': False, 'error': 'Faltan campos'}), 400
    
    try:
        send_dt = datetime.fromisoformat(send_at)
        if send_dt.tzinfo is None:
            madrid = pytz.timezone('Europe/Madrid')
            send_dt = madrid.localize(send_dt)
    except ValueError:
        return jsonify({'ok': False, 'error': 'Formato inválido'}), 400
    
    now_tz = datetime.now(pytz.timezone('Europe/Madrid'))
    if send_dt <= now_tz:
        return jsonify({'ok': False, 'error': 'Fecha ya pasó'}), 400
    
    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    except:
        pass
    
    try:
        scheduler.add_job(
            func=send_whatsapp_job,
            trigger=DateTrigger(run_date=send_dt),
            args=[to_phone, message],
            id=job_id,
            replace_existing=True
        )
        logger.info(f"📅 WhatsApp programado: {send_dt} → {to_phone}")
        return jsonify({
            'ok': True,
            'job_id': job_id,
            'scheduled_for': send_dt.isoformat()
        })
    except Exception as e:
        logger.error(f"❌ Error programando: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/whatsapp/cancel/<job_id>', methods=['DELETE'])
def cancel_whatsapp(job_id):
    """Cancela WhatsApp programado"""
    if not SCHEDULER_AVAILABLE or not scheduler:
        return jsonify({'ok': False, 'error': 'Scheduler no disponible'}), 503
    
    try:
        job = scheduler.get_job(job_id)
        if job:
            scheduler.remove_job(job_id)
            logger.info(f"🗑️ Job cancelado: {job_id}")
            return jsonify({'ok': True})
        else:
            return jsonify({'ok': False, 'error': 'Job no encontrado'}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/whatsapp/status', methods=['GET'])
def whatsapp_status():
    """Status de Meta API y Scheduler"""
    meta_ok = bool(META_PHONE_NUMBER_ID and META_ACCESS_TOKEN)
    scheduler_ok = SCHEDULER_AVAILABLE and scheduler is not None
    
    reasons = []
    if not meta_ok:
        reasons.append("Meta no configurado")
    if not scheduler_ok:
        reasons.append("APScheduler no disponible")
    
    return jsonify({
        'meta_ready': meta_ok,
        'scheduler_ready': scheduler_ok,
        'fully_ready': meta_ok and scheduler_ok,
        'reason': ' · '.join(reasons) if reasons else 'Configurado'
    })

# ═══════════════════════════════════════════════════════════════════════════
# RUTAS API - STATUS Y HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/api/status')
def api_status():
    """Status general de la aplicación"""
    return jsonify({
        'status': 'ok',
        'app': 'GestióPro',
        'version': '3.0',
        'timestamp': datetime.now().isoformat(),
        'environment': app.config['ENV'],
        'meta_ready': bool(META_PHONE_NUMBER_ID and META_ACCESS_TOKEN),
        'scheduler_ready': SCHEDULER_AVAILABLE and scheduler is not None,
        'websocket_ready': True,
        'connected_users': len(connected_users),
        'html_loaded': html_path is not None
    })

@app.route('/api/health')
def api_health():
    """Health check para Render"""
    return jsonify({
        'status': 'healthy',
        'service': 'gestionpro',
        'timestamp': datetime.now().isoformat(),
        'html_found': html_path is not None
    }), 200

# ═══════════════════════════════════════════════════════════════════════════
# WEBHOOK META
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/api/whatsapp/webhook', methods=['GET'])
def whatsapp_webhook_verify():
    """Verificar webhook con Meta"""
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    verify_token = os.environ.get('WHATSAPP_WEBHOOK_TOKEN', 'your_verify_token')
    
    if token == verify_token:
        return challenge
    return 'Invalid token', 403

@app.route('/api/whatsapp/webhook', methods=['POST'])
def whatsapp_webhook_receive():
    """Recibir webhooks de Meta"""
    data = request.get_json()
    logger.info(f"📨 Webhook recibido: {json.dumps(data, indent=2)}")
    return jsonify({'status': 'ok'}), 200

# ═══════════════════════════════════════════════════════════════════════════
# MANEJO DE ERRORES
# ═══════════════════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(error):
    """404 - Servir HTML SPA"""
    try:
        return render_template('index3.html'), 200
    except:
        if html_path:
            try:
                with open(html_path, 'r', encoding='utf-8') as f:
                    return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
            except:
                pass
        return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(error):
    """500 - Error interno"""
    logger.error(f"❌ Error 500: {str(error)}")
    return jsonify({'error': 'Internal server error'}), 500

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("═" * 80)
    logger.info(f"🚀 Iniciando servidor en puerto {port}")
    logger.info("═" * 80)
    
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True,
        use_reloader=False
    )