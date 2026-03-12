import os
import json
import sqlite3
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
from datetime import datetime, timedelta
import requests
import logging
import uuid
import sys
import threading
from functools import wraps

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
print("🚀 INICIANDO SERVIDOR CON MENSAJERÍA 100% FUNCIONAL")
print("="*80 + "\n")

# ═══════════════════════════════════════════════════════════════
# FLASK APP Y SOCKETIO
# ═══════════════════════════════════════════════════════════════

app = Flask(__name__, template_folder='templates', static_folder='templates')
app.config['SECRET_KEY'] = 'dev-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

logger.info("✅ Flask app creada")
logger.info("✅ SocketIO inicializado")

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE BASE DE DATOS
# ═══════════════════════════════════════════════════════════════

DB_FILE = 'gestionpro.db'

def init_db():
    """Inicializar base de datos con todas las tablas necesarias"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Tabla de mensajes PRIVADOS
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            sender_id INTEGER NOT NULL,
            sender_username TEXT,
            recipient_id INTEGER NOT NULL,
            text TEXT,
            timestamp TEXT,
            read BOOLEAN DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de mensajes GENERALES
    c.execute('''
        CREATE TABLE IF NOT EXISTS general_messages (
            id TEXT PRIMARY KEY,
            sender_id INTEGER NOT NULL,
            sender_username TEXT,
            text TEXT,
            timestamp TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de citas
    c.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            assigned_to INTEGER NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            time_end TEXT NOT NULL,
            client TEXT NOT NULL,
            service TEXT,
            notes TEXT,
            private BOOLEAN DEFAULT 0,
            client_phone TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de recordatorios personales
    c.execute('''
        CREATE TABLE IF NOT EXISTS personal_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reminder_timing TEXT NOT NULL,
            scheduled_for TEXT NOT NULL,
            fired BOOLEAN DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(appointment_id) REFERENCES appointments(id)
        )
    ''')
    
    # Tabla de recordatorios WhatsApp
    c.execute('''
        CREATE TABLE IF NOT EXISTS whatsapp_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL,
            recipient_phone TEXT NOT NULL,
            message TEXT,
            reminder_timing TEXT NOT NULL,
            scheduled_for TEXT NOT NULL,
            fired BOOLEAN DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(appointment_id) REFERENCES appointments(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("✅ Base de datos inicializada (6 tablas)")

# Inicializar BD al arrancar
init_db()

# ═══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ═══════════════════════════════════════════════════════════════

connected_users = {}
sid_to_userid = {}
message_ids_seen = set()
reminder_timers = {}

logger.info("✅ Estructuras de datos inicializadas")

# ═══════════════════════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════════════════════

def get_db():
    """Obtener conexión a BD"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def log_rooms_status():
    """Loguear estado actual de salas"""
    logger.debug(f"📊 ESTADO DE SALAS: {len(connected_users)} usuarios")
    for sid, user_data in list(connected_users.items()):
        uid = user_data.get('user_id')
        logger.debug(f"   - {user_data.get('username')} (UID={uid})")

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET - CONEXIÓN
# ═══════════════════════════════════════════════════════════════

@socketio.on('connect')
def handle_connect():
    """Cliente conectado"""
    sid = request.sid
    logger.info(f"🔌 [CONNECT] {sid[:8]}")
    emit('connection_response', {'data': 'Conectado'})

@socketio.on('disconnect')
def handle_disconnect():
    """Cliente desconectado"""
    sid = request.sid
    user_data = connected_users.pop(sid, None)
    user_id = sid_to_userid.pop(sid, None)
    
    if user_data:
        logger.info(f"❌ [DISCONNECT] {user_data.get('username')} (UID={user_id})")

@socketio.on('user_login')
def handle_user_login(data):
    """Usuario hace login"""
    sid = request.sid
    username = data.get('username', f'User_{sid[:6]}')
    user_id = data.get('userId')
    
    logger.info(f"👤 [LOGIN] {username} (UID={user_id})")
    
    try:
        user_id = int(user_id)
        if user_id <= 0:
            raise ValueError("user_id debe ser > 0")
    except (TypeError, ValueError) as e:
        logger.error(f"❌ [LOGIN] User ID inválido: {user_id}")
        emit('login_ack', {'ok': False, 'error': f'Invalid user_id'})
        return
    
    # Limpiar sesiones anteriores del mismo usuario
    old_sids = [s for s, u in sid_to_userid.items() if u == user_id and s != sid]
    for old_sid in old_sids:
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
    
    # Unirse a la sala
    join_room(room, sid=sid)
    
    logger.info(f"✅ [LOGIN] {username} en sala '{room}'")
    log_rooms_status()
    
    emit('login_ack', {
        'ok': True,
        'room': room,
        'user_id': user_id,
        'timestamp': datetime.now().isoformat()
    })

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET - MENSAJERÍA PRIVADA
# ═══════════════════════════════════════════════════════════════

@socketio.on('send_message')
def handle_send_message(data):
    """Enviar mensaje privado"""
    sid = request.sid
    sender_id = data.get('sender_id')
    sender_username = data.get('sender_username', '?')
    recipient_id = data.get('recipient_id')
    text = (data.get('message') or '').strip()
    message_id = data.get('message_id') or f"msg_{uuid.uuid4().hex[:12]}"
    
    ts = datetime.now().isoformat()
    
    logger.info(f"💬 [SEND_MESSAGE] {sender_username} → UID{recipient_id}")
    
    # Validación
    try:
        sender_id = int(sender_id)
        recipient_id = int(recipient_id)
    except (TypeError, ValueError):
        logger.error(f"❌ [SEND_MESSAGE] IDs inválidos")
        emit('message_ack', {'message_id': message_id, 'status': 'error'})
        return
    
    if sid not in sid_to_userid:
        logger.error(f"❌ [SEND_MESSAGE] SID no autenticado")
        emit('message_ack', {'message_id': message_id, 'status': 'error'})
        return
    
    if sid_to_userid[sid] != sender_id:
        logger.error(f"❌ [SEND_MESSAGE] Sender mismatch")
        emit('message_ack', {'message_id': message_id, 'status': 'error'})
        return
    
    if not text:
        logger.warning(f"⚠️ [SEND_MESSAGE] Texto vacío")
        return
    
    if message_id in message_ids_seen:
        logger.warning(f"⚠️ [SEND_MESSAGE] Duplicado: {message_id}")
        return
    
    message_ids_seen.add(message_id)
    
    # Crear mensaje
    msg = {
        'id': message_id,
        'sender_id': sender_id,
        'sender_username': sender_username,
        'recipient_id': recipient_id,
        'text': text,
        'timestamp': ts,
        'read': False
    }
    
    # Guardar en BD
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT INTO messages (id, sender_id, sender_username, recipient_id, text, timestamp, read)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (message_id, sender_id, sender_username, recipient_id, text, ts, 0))
        conn.commit()
        conn.close()
        logger.debug(f"   ✓ Guardado en BD")
    except Exception as e:
        logger.error(f"   ❌ Error BD: {e}")
    
    # Enviar ACK
    emit('message_ack', {
        'message_id': message_id,
        'status': 'ok',
        'timestamp': ts
    })
    
    # Enviar al receptor
    recipient_room = f"user_{recipient_id}"
    logger.info(f"   📤 Enviando a {recipient_room}")
    emit('receive_message', msg, room=recipient_room, include_self=False)

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET - CHAT GENERAL
# ═══════════════════════════════════════════════════════════════

@socketio.on('send_general_message')
def handle_general_message(data):
    """Enviar mensaje a chat general"""
    sid = request.sid
    sender_id = data.get('sender_id')
    sender_username = data.get('sender_username', '?')
    text = (data.get('message') or '').strip()
    message_id = data.get('message_id') or f"msg_{uuid.uuid4().hex[:12]}"
    
    ts = datetime.now().isoformat()
    
    logger.info(f"📢 [GENERAL_MESSAGE] {sender_username}: {text[:50]}")
    
    # Validación
    if not text:
        logger.warning(f"⚠️ [GENERAL_MESSAGE] Texto vacío")
        return
    
    if message_id in message_ids_seen:
        logger.warning(f"⚠️ [GENERAL_MESSAGE] Duplicado")
        return
    
    message_ids_seen.add(message_id)
    
    # Crear mensaje
    msg = {
        'id': message_id,
        'sender_id': sender_id,
        'sender_username': sender_username,
        'text': text,
        'timestamp': ts
    }
    
    # Guardar en BD
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT INTO general_messages (id, sender_id, sender_username, text, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (message_id, sender_id, sender_username, text, ts))
        conn.commit()
        conn.close()
        logger.debug(f"   ✓ Guardado en BD")
    except Exception as e:
        logger.error(f"   ❌ Error BD: {e}")
    
    # Enviar ACK
    emit('message_ack', {
        'message_id': message_id,
        'status': 'ok',
        'timestamp': ts
    })
    
    # Broadcast a TODOS
    logger.info(f"   📤 Broadcast a todos")
    emit('receive_general_message', msg, broadcast=True, include_self=False)

@socketio.on('message_read')
def handle_message_read(data):
    """Notificar lectura de mensaje"""
    message_id = data.get('message_id')
    sender_id = data.get('sender_id')
    
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE messages SET read = 1 WHERE id = ?', (message_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error actualizando lectura: {e}")

# ═══════════════════════════════════════════════════════════════
# REST - MENSAJERÍA
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def index():
    """Servir index3.html"""
    return render_template('index3.html')

@app.route('/api/messages/<int:user_a>/<int:user_b>')
def get_messages(user_a, user_b):
    """Obtener mensajes privados entre dos usuarios"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''
            SELECT * FROM messages 
            WHERE (sender_id = ? AND recipient_id = ?) 
               OR (sender_id = ? AND recipient_id = ?)
            ORDER BY timestamp ASC
        ''', (user_a, user_b, user_b, user_a))
        
        rows = c.fetchall()
        messages = [dict(row) for row in rows]
        conn.close()
        
        logger.debug(f"📥 [API] get_messages({user_a},{user_b}): {len(messages)}")
        return jsonify({'ok': True, 'messages': messages})
    except Exception as e:
        logger.error(f"Error en get_messages: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/general-messages')
def get_general_messages():
    """Obtener mensajes del chat general"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''
            SELECT * FROM general_messages 
            ORDER BY timestamp ASC
        ''')
        
        rows = c.fetchall()
        messages = [dict(row) for row in rows]
        conn.close()
        
        logger.debug(f"📥 [API] get_general_messages: {len(messages)}")
        return jsonify({'ok': True, 'messages': messages})
    except Exception as e:
        logger.error(f"Error en get_general_messages: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# REST - CITAS
# ═══════════════════════════════════════════════════════════════

@app.route('/api/appointments', methods=['GET'])
def get_appointments():
    """Obtener citas"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM appointments ORDER BY date DESC, time ASC')
        rows = c.fetchall()
        appointments = [dict(row) for row in rows]
        conn.close()
        return jsonify({'ok': True, 'appointments': appointments})
    except Exception as e:
        logger.error(f"Error en get_appointments: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/appointments', methods=['POST'])
def create_appointment():
    """Crear cita"""
    try:
        data = request.json
        required = ['owner_id', 'assigned_to', 'date', 'time', 'time_end', 'client']
        for field in required:
            if field not in data:
                return jsonify({'ok': False, 'error': f'Campo faltante: {field}'}), 400
        
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT INTO appointments 
            (owner_id, assigned_to, date, time, time_end, client, service, notes, private, client_phone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (data['owner_id'], data['assigned_to'], data['date'], data['time'], data['time_end'],
              data['client'], data.get('service', ''), data.get('notes', ''), 
              data.get('private', False), data.get('client_phone', '')))
        
        appointment_id = c.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"✅ [CITA] Nueva: ID={appointment_id}")
        socketio.emit('appointment_created', {'id': appointment_id, 'client': data['client']}, broadcast=True)
        
        return jsonify({'ok': True, 'appointment_id': appointment_id}), 201
    except Exception as e:
        logger.error(f"Error creando cita: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/health')
def health():
    """Health check"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) as cnt FROM messages')
        msg_count = c.fetchone()['cnt']
        
        c.execute('SELECT COUNT(*) as cnt FROM general_messages')
        gen_msg_count = c.fetchone()['cnt']
        
        c.execute('SELECT COUNT(*) as cnt FROM appointments')
        apt_count = c.fetchone()['cnt']
        
        conn.close()
        
        return jsonify({
            'status': 'ok',
            'connected_users': len(connected_users),
            'private_messages': msg_count,
            'general_messages': gen_msg_count,
            'appointments': apt_count
        })
    except Exception as e:
        logger.error(f"Error en health check: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# MANEJO DE ERRORES
# ═══════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(error):
    return render_template('index3.html'), 200

@app.errorhandler(500)
def server_error(error):
    logger.error(f"❌ Error 500: {str(error)}")
    return jsonify({'error': 'Internal server error'}), 500

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = '0.0.0.0'
    
    logger.info("="*80)
    logger.info("🚀 SERVIDOR LISTO - MENSAJERÍA 100% FUNCIONAL")
    logger.info(f"HOST: {host}:{port}")
    logger.info(f"DB: {DB_FILE}")
    logger.info("="*80 + "\n")
    
    socketio.run(
        app,
        host=host,
        port=port,
        debug=True,
        allow_unsafe_werkzeug=True,
        log_output=True
    )