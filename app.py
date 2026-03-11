"""
═══════════════════════════════════════════════════════════════════════════════
  GESTIONPRO v3.0 - VERSIÓN ULTRA-SIMPLE Y ROBUSTA
  
  GARANTIZADO: HTML se muestra completamente visible
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import json
import sys
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_file
from flask_socketio import SocketIO, emit
from datetime import datetime
import requests
import logging

# ═══════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
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

# ═══════════════════════════════════════════════════════════════════════════
# META API CONFIG
# ═══════════════════════════════════════════════════════════════════════════
META_PHONE_NUMBER_ID = os.environ.get('META_PHONE_NUMBER_ID', None)
META_ACCESS_TOKEN = os.environ.get('META_ACCESS_TOKEN', None)
META_API_VERSION = "v18.0"
META_API_URL = f"https://graph.facebook.com/{META_API_VERSION}/{{phone_id}}/messages"

# ═══════════════════════════════════════════════════════════════════════════
# CREAR APP FLASK CON TEMPLATE FOLDER
# ═══════════════════════════════════════════════════════════════════════════

logger.info("═" * 80)
logger.info("🚀 GESTIONPRO v3.0 INICIANDO")
logger.info("═" * 80)

# Asegurarse de que la carpeta templates existe y tiene el HTML
base_dir = Path(__file__).parent.absolute()
templates_dir = base_dir / 'templates'
html_file = templates_dir / 'index3.html'

logger.info(f"📁 Base dir: {base_dir}")
logger.info(f"📁 Templates dir: {templates_dir}")
logger.info(f"📄 HTML file: {html_file}")
logger.info(f"✓ HTML existe: {html_file.exists()}")

# Crear app
app = Flask(__name__, template_folder=str(templates_dir))
app.config['ENV'] = os.environ.get('FLASK_ENV', 'production')
app.config['DEBUG'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-production')

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
    engineio_logger=False
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
        logger.info("✅ APScheduler listo")
    except Exception as e:
        logger.error(f"❌ APScheduler: {e}")

# ═══════════════════════════════════════════════════════════════════════════
# FUNCIONES AUXILIARES
# ═══════════════════════════════════════════════════════════════════════════

def send_whatsapp_meta(to_phone: str, message: str):
    """Envía WhatsApp via Meta API"""
    if not META_PHONE_NUMBER_ID or not META_ACCESS_TOKEN:
        return {'ok': False, 'error': 'Meta no configurado', 'configured': False}
    
    phone = to_phone.strip()
    if not phone.startswith('+'):
        phone = '+34' + phone.lstrip('0')
    
    payload = {
        "messaging_product": "whatsapp",
        "to": phone.replace('+', ''),
        "type": "text",
        "text": {"preview_url": False, "body": message}
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
        return {'ok': True, 'message_id': result.get('messages', [{}])[0].get('id')}
    except Exception as e:
        logger.error(f"Meta API error: {e}")
        return {'ok': False, 'error': str(e)}

def send_whatsapp_job(to_phone: str, message: str):
    """Tarea programada"""
    result = send_whatsapp_meta(to_phone, message)
    if result['ok']:
        logger.info(f"✅ WhatsApp enviado a {to_phone}")

# ═══════════════════════════════════════════════════════════════════════════
# RUTAS - SERVIR HTML
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/')
@app.route('/app')
@app.route('/index')
@app.route('/gestionpro')
def home():
    """Servir index3.html"""
    try:
        logger.info("📄 Sirviendo index3.html con render_template")
        return render_template('index3.html')
    except Exception as e:
        logger.error(f"❌ render_template error: {e}")
        try:
            with open(html_file, 'r', encoding='utf-8') as f:
                content = f.read()
            logger.info("📄 HTML servido con lectura directa")
            return content, 200, {'Content-Type': 'text/html; charset=utf-8'}
        except Exception as e2:
            logger.error(f"❌ Error crítico: {e2}")
            return jsonify({'error': 'HTML no disponible', 'details': str(e2)}), 503

# ═══════════════════════════════════════════════════════════════════════════
# WEBSOCKET EVENTS
# ═══════════════════════════════════════════════════════════════════════════

@socketio.on('connect')
def handle_connect(auth):
    user_id = request.sid
    logger.info(f"✅ Usuario conectado: {user_id}")
    emit('connect_response', {'user_id': user_id, 'data': 'Conectado'})

@socketio.on('disconnect')
def handle_disconnect():
    user_id = request.sid
    if user_id in connected_users:
        del connected_users[user_id]
    logger.info(f"❌ Usuario desconectado: {user_id}")

@socketio.on('user_login')
def handle_user_login(data):
    user_id = request.sid
    username = data.get('username', f'User_{user_id[:8]}')
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
    
    if recipient_id and recipient_id in connected_users:
        socketio.emit('receive_message', message_obj, room=recipient_id)
    
    socketio.emit('message_sent', {'message_id': message_obj['id'], 'status': 'delivered'}, room=sender_id)

@socketio.on('typing')
def handle_typing(data):
    sender_id = request.sid
    recipient_id = data.get('recipient_id')
    if recipient_id and recipient_id in connected_users:
        socketio.emit('user_typing', {
            'sender_id': sender_id,
            'sender_username': data.get('sender_username', 'Usuario')
        }, room=recipient_id)

@socketio.on('get_online_users')
def handle_get_online_users():
    socketio.emit('online_users_list', {
        'users': list(connected_users.values()),
        'count': len(connected_users)
    })

# ═══════════════════════════════════════════════════════════════════════════
# API - WHATSAPP
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/api/whatsapp/send', methods=['POST'])
def send_whatsapp():
    data = request.get_json(silent=True) or {}
    to_phone = data.get('to', '').strip()
    message = data.get('message', '').strip()
    
    if not to_phone or not message:
        return jsonify({'ok': False, 'error': 'Faltan campos'}), 400
    
    result = send_whatsapp_meta(to_phone, message)
    if result['ok']:
        return jsonify({'ok': True, 'message_id': result.get('message_id')})
    return jsonify({'ok': False, 'error': result.get('error')}), 503

@app.route('/api/whatsapp/schedule', methods=['POST'])
def schedule_whatsapp():
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
    except:
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
        return jsonify({'ok': True, 'job_id': job_id, 'scheduled_for': send_dt.isoformat()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/whatsapp/cancel/<job_id>', methods=['DELETE'])
def cancel_whatsapp(job_id):
    if not SCHEDULER_AVAILABLE or not scheduler:
        return jsonify({'ok': False, 'error': 'Scheduler no disponible'}), 503
    
    try:
        job = scheduler.get_job(job_id)
        if job:
            scheduler.remove_job(job_id)
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': 'Job no encontrado'}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/whatsapp/status', methods=['GET'])
def whatsapp_status():
    meta_ok = bool(META_PHONE_NUMBER_ID and META_ACCESS_TOKEN)
    scheduler_ok = SCHEDULER_AVAILABLE and scheduler is not None
    return jsonify({
        'meta_ready': meta_ok,
        'scheduler_ready': scheduler_ok,
        'fully_ready': meta_ok and scheduler_ok,
        'reason': 'OK' if (meta_ok and scheduler_ok) else 'Parcialmente configurado'
    })

# ═══════════════════════════════════════════════════════════════════════════
# API - STATUS Y HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/api/status')
def api_status():
    return jsonify({
        'status': 'ok',
        'app': 'GestióPro',
        'version': '3.0',
        'timestamp': datetime.now().isoformat(),
        'html_found': html_file.exists(),
        'websocket_ready': True,
        'connected_users': len(connected_users)
    })

@app.route('/api/health')
def api_health():
    return jsonify({
        'status': 'healthy',
        'service': 'gestionpro',
        'timestamp': datetime.now().isoformat(),
        'html_found': html_file.exists()
    }), 200

# ═══════════════════════════════════════════════════════════════════════════
# WEBHOOK META
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/api/whatsapp/webhook', methods=['GET'])
def whatsapp_webhook_verify():
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    verify_token = os.environ.get('WHATSAPP_WEBHOOK_TOKEN', 'your_verify_token')
    if token == verify_token:
        return challenge
    return 'Invalid token', 403

@app.route('/api/whatsapp/webhook', methods=['POST'])
def whatsapp_webhook_receive():
    data = request.get_json()
    logger.info(f"📨 Webhook recibido: {json.dumps(data, indent=2)}")
    return jsonify({'status': 'ok'}), 200

# ═══════════════════════════════════════════════════════════════════════════
# ERROR HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(error):
    """404 - Servir HTML SPA"""
    try:
        return render_template('index3.html'), 200
    except:
        if html_file.exists():
            try:
                with open(html_file, 'r', encoding='utf-8') as f:
                    return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
            except:
                pass
        return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(error):
    logger.error(f"❌ Error 500: {str(error)}")
    return jsonify({'error': 'Internal server error', 'details': str(error)}), 500

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("═" * 80)
    logger.info(f"✅ GESTIONPRO LISTO")
    logger.info(f"   Port: {port}")
    logger.info(f"   HTML: {'ENCONTRADO' if html_file.exists() else 'NO ENCONTRADO'}")
    logger.info(f"   Path: {html_file}")
    logger.info("═" * 80)
    
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True,
        use_reloader=False
    )