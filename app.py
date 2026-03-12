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
print("🚀 INICIANDO SERVIDOR CON LOGGING DETALLADO")
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
    
    # Tabla de mensajes
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
    logger.info("✅ Base de datos inicializada")

# Inicializar BD al arrancar
init_db()

# ═══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ═══════════════════════════════════════════════════════════════

connected_users = {}
sid_to_userid = {}
message_ids_seen = set()
reminder_timers = {}  # Almacenar timers de recordatorios para limpiarlos

logger.info("✅ Estructuras de datos inicializadas")

# ═══════════════════════════════════════════════════════════════
# UTILIDADES DE BASE DE DATOS
# ═══════════════════════════════════════════════════════════════

def get_db():
    """Obtener conexión a BD"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

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
# WEBSOCKET EVENTS - CONEXIÓN
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

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET EVENTS - MENSAJERÍA
# ═══════════════════════════════════════════════════════════════

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
        'attachments': attachments,
        'read': False
    }
    
    # Persistir en BD
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT INTO messages (id, sender_id, sender_username, recipient_id, text, timestamp, read)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (message_id, sender_id, sender_username, recipient_id, text, ts, 0))
        conn.commit()
        conn.close()
        logger.debug(f"   ✓ Persistido en BD")
    except Exception as e:
        logger.error(f"   ❌ Error guardando en BD: {e}")
    
    # PASO 1: ACK al remitente
    logger.info(f"   1️⃣  ACK → remitente")
    emit('message_ack', {
        'message_id': message_id,
        'status': 'ok',
        'timestamp': ts
    })
    
    # PASO 2: Enviar al receptor
    recipient_room = f"user_{recipient_id}"
    logger.info(f"   2️⃣  receive_message → '{recipient_room}'")
    
    room_members = list(rooms(room=recipient_room))
    logger.debug(f"      Usuarios en {recipient_room}: {len(room_members)}")
    
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
    """Evento: notificar lectura de mensaje"""
    message_id = data.get('message_id')
    sender_id = data.get('sender_id')
    
    logger.debug(f"📖 [MESSAGE_READ] {message_id}")
    
    # Actualizar en BD
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE messages SET read = 1 WHERE id = ?', (message_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error actualizando lectura: {e}")
    
    emit('message_read_ack', {
        'message_id': message_id,
        'timestamp': datetime.now().isoformat()
    }, room=f"user_{sender_id}")

# ═══════════════════════════════════════════════════════════════
# REST ENDPOINTS - MENSAJERÍA
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def index():
    """Servir index3.html"""
    return render_template('index3.html')

@app.route('/api/messages/<int:user_a>/<int:user_b>')
def get_messages(user_a, user_b):
    """Obtener histórico de mensajes entre dos usuarios"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        key = make_conv_key(user_a, user_b)
        
        # Obtener mensajes ordenados por timestamp
        c.execute('''
            SELECT * FROM messages 
            WHERE (sender_id = ? AND recipient_id = ?) 
               OR (sender_id = ? AND recipient_id = ?)
            ORDER BY timestamp ASC
        ''', (user_a, user_b, user_b, user_a))
        
        rows = c.fetchall()
        messages = [dict(row) for row in rows]
        conn.close()
        
        logger.debug(f"📥 [API] get_messages({user_a}, {user_b}): {len(messages)} msgs")
        return jsonify({'ok': True, 'messages': messages})
    except Exception as e:
        logger.error(f"Error en get_messages: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# REST ENDPOINTS - CITAS
# ═══════════════════════════════════════════════════════════════

@app.route('/api/appointments', methods=['GET'])
def get_appointments():
    """Obtener todas las citas del usuario autenticado"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''
            SELECT * FROM appointments 
            ORDER BY date DESC, time ASC
        ''')
        
        rows = c.fetchall()
        appointments = [dict(row) for row in rows]
        conn.close()
        
        logger.debug(f"📅 [API] get_appointments: {len(appointments)} citas")
        return jsonify({'ok': True, 'appointments': appointments})
    except Exception as e:
        logger.error(f"Error en get_appointments: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/appointments', methods=['POST'])
def create_appointment():
    """Crear nueva cita"""
    try:
        data = request.json
        
        # Validaciones
        required = ['owner_id', 'assigned_to', 'date', 'time', 'time_end', 'client']
        for field in required:
            if field not in data:
                return jsonify({'ok': False, 'error': f'Campo faltante: {field}'}), 400
        
        owner_id = int(data['owner_id'])
        assigned_to = int(data['assigned_to'])
        date = data['date']
        time = data['time']
        time_end = data['time_end']
        client = data['client']
        service = data.get('service', '')
        notes = data.get('notes', '')
        private = data.get('private', False)
        client_phone = data.get('client_phone', '')
        
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO appointments 
            (owner_id, assigned_to, date, time, time_end, client, service, notes, private, client_phone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (owner_id, assigned_to, date, time, time_end, client, service, notes, private, client_phone))
        
        appointment_id = c.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"✅ [CITA] Nueva cita creada: ID={appointment_id}, cliente={client}, fecha={date}")
        
        # Notificar a usuarios conectados
        socketio.emit('appointment_created', {
            'id': appointment_id,
            'client': client,
            'date': date,
            'time': time
        }, broadcast=True)
        
        return jsonify({'ok': True, 'appointment_id': appointment_id}), 201
    
    except Exception as e:
        logger.error(f"Error creando cita: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/appointments/<int:appointment_id>', methods=['PUT'])
def update_appointment(appointment_id):
    """Actualizar cita existente"""
    try:
        data = request.json
        
        conn = get_db()
        c = conn.cursor()
        
        # Obtener cita actual
        c.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,))
        row = c.fetchone()
        
        if not row:
            conn.close()
            return jsonify({'ok': False, 'error': 'Cita no encontrada'}), 404
        
        # Actualizar campos
        date = data.get('date', row['date'])
        time = data.get('time', row['time'])
        time_end = data.get('time_end', row['time_end'])
        client = data.get('client', row['client'])
        service = data.get('service', row['service'])
        notes = data.get('notes', row['notes'])
        client_phone = data.get('client_phone', row['client_phone'])
        
        c.execute('''
            UPDATE appointments 
            SET date = ?, time = ?, time_end = ?, client = ?, service = ?, notes = ?, client_phone = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (date, time, time_end, client, service, notes, client_phone, appointment_id))
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ [CITA] Cita actualizada: ID={appointment_id}")
        
        socketio.emit('appointment_updated', {
            'id': appointment_id,
            'client': client,
            'date': date
        }, broadcast=True)
        
        return jsonify({'ok': True})
    
    except Exception as e:
        logger.error(f"Error actualizando cita: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/appointments/<int:appointment_id>', methods=['DELETE'])
def delete_appointment(appointment_id):
    """Eliminar cita"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Obtener cita para saber qué notificar
        c.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,))
        row = c.fetchone()
        
        if not row:
            conn.close()
            return jsonify({'ok': False, 'error': 'Cita no encontrada'}), 404
        
        # Eliminar recordatorios asociados
        c.execute('DELETE FROM personal_reminders WHERE appointment_id = ?', (appointment_id,))
        c.execute('DELETE FROM whatsapp_reminders WHERE appointment_id = ?', (appointment_id,))
        
        # Eliminar cita
        c.execute('DELETE FROM appointments WHERE id = ?', (appointment_id,))
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ [CITA] Cita eliminada: ID={appointment_id}")
        
        socketio.emit('appointment_deleted', {'id': appointment_id}, broadcast=True)
        
        return jsonify({'ok': True})
    
    except Exception as e:
        logger.error(f"Error eliminando cita: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# REST ENDPOINTS - RECORDATORIOS
# ═══════════════════════════════════════════════════════════════

def schedule_reminder_timer(appointment_id, user_id, reminder_timing, event_datetime):
    """Programar un recordatorio con timer en servidor"""
    
    timing_map = {
        'now': 0,
        '15m': 15 * 60,
        '30m': 30 * 60,
        '1h': 60 * 60,
        '2h': 2 * 60 * 60,
        '1d': 24 * 60 * 60,
        '1w': 7 * 24 * 60 * 60
    }
    
    delay_seconds = timing_map.get(reminder_timing, 0)
    event_time = datetime.fromisoformat(event_datetime)
    fire_at = event_time - timedelta(seconds=delay_seconds)
    now = datetime.now()
    time_until = (fire_at - now).total_seconds()
    
    logger.info(f"⏰ [RECORDATORIO] Programando para {appointment_id} en {time_until}s")
    
    def fire_reminder():
        try:
            conn = get_db()
            c = conn.cursor()
            
            # Actualizar como disparado
            c.execute('UPDATE personal_reminders SET fired = 1 WHERE appointment_id = ? AND user_id = ?',
                     (appointment_id, user_id))
            
            # Obtener datos de cita
            c.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,))
            apt = dict(c.fetchone())
            conn.close()
            
            # Emitir notificación a usuario
            user_room = f"user_{user_id}"
            socketio.emit('reminder_notification', {
                'type': 'personal',
                'appointment_id': appointment_id,
                'client': apt['client'],
                'date': apt['date'],
                'time': apt['time'],
                'service': apt['service'],
                'message': f"Recordatorio: Cita con {apt['client']} a las {apt['time']}"
            }, room=user_room)
            
            logger.info(f"✅ [RECORDATORIO] Disparado: cita {appointment_id}")
        
        except Exception as e:
            logger.error(f"Error disparando recordatorio: {e}")
    
    if time_until > 0:
        # Programar timer
        timer = threading.Timer(time_until, fire_reminder)
        timer.daemon = True
        timer.start()
        reminder_timers[f"{appointment_id}_{user_id}"] = timer
    else:
        # Ya pasó, disparar inmediatamente
        fire_reminder()

@app.route('/api/reminders/personal', methods=['POST'])
def create_personal_reminder():
    """Crear recordatorio personal para cita"""
    try:
        data = request.json
        
        appointment_id = int(data['appointment_id'])
        user_id = int(data['user_id'])
        reminder_timing = data['reminder_timing']  # 'now', '15m', '30m', '1h', '2h', '1d', '1w'
        
        conn = get_db()
        c = conn.cursor()
        
        # Obtener cita para calcular scheduled_for
        c.execute('SELECT date, time FROM appointments WHERE id = ?', (appointment_id,))
        apt = c.fetchone()
        
        if not apt:
            conn.close()
            return jsonify({'ok': False, 'error': 'Cita no encontrada'}), 404
        
        event_datetime = f"{apt['date']}T{apt['time']}:00"
        
        timing_map = {
            'now': 0,
            '15m': 15 * 60,
            '30m': 30 * 60,
            '1h': 60 * 60,
            '2h': 2 * 60 * 60,
            '1d': 24 * 60 * 60,
            '1w': 7 * 24 * 60 * 60
        }
        
        delay_seconds = timing_map.get(reminder_timing, 0)
        event_time = datetime.fromisoformat(event_datetime)
        scheduled_for = (event_time - timedelta(seconds=delay_seconds)).isoformat()
        
        # Insertar en BD
        c.execute('''
            INSERT INTO personal_reminders (appointment_id, user_id, reminder_timing, scheduled_for)
            VALUES (?, ?, ?, ?)
        ''', (appointment_id, user_id, reminder_timing, scheduled_for))
        
        reminder_id = c.lastrowid
        conn.commit()
        conn.close()
        
        # Programar timer en servidor
        schedule_reminder_timer(appointment_id, user_id, reminder_timing, event_datetime)
        
        logger.info(f"✅ [RECORDATORIO PERSONAL] Creado: cita {appointment_id}, usuario {user_id}, timing {reminder_timing}")
        
        return jsonify({'ok': True, 'reminder_id': reminder_id}), 201
    
    except Exception as e:
        logger.error(f"Error creando recordatorio personal: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/reminders/whatsapp', methods=['POST'])
def create_whatsapp_reminder():
    """Crear recordatorio WhatsApp para cita"""
    try:
        data = request.json
        
        appointment_id = int(data['appointment_id'])
        recipient_phone = data['recipient_phone']
        reminder_timing = data['reminder_timing']
        
        conn = get_db()
        c = conn.cursor()
        
        # Obtener cita
        c.execute('SELECT date, time, client, service FROM appointments WHERE id = ?', (appointment_id,))
        apt = c.fetchone()
        
        if not apt:
            conn.close()
            return jsonify({'ok': False, 'error': 'Cita no encontrada'}), 404
        
        event_datetime = f"{apt['date']}T{apt['time']}:00"
        
        timing_map = {
            'now': 0,
            '1h': 60 * 60,
            '1d': 24 * 60 * 60,
            '1w': 7 * 24 * 60 * 60
        }
        
        delay_seconds = timing_map.get(reminder_timing, 0)
        event_time = datetime.fromisoformat(event_datetime)
        scheduled_for = (event_time - timedelta(seconds=delay_seconds)).isoformat()
        
        # Construir mensaje
        message = f"Hola {apt['client']}, le recordamos su cita en Rodonvergés Associats el {apt['date']} a las {apt['time']}"
        if apt['service']:
            message += f" ({apt['service']})"
        message += ". ¡Le esperamos!"
        
        # Insertar en BD
        c.execute('''
            INSERT INTO whatsapp_reminders (appointment_id, recipient_phone, message, reminder_timing, scheduled_for)
            VALUES (?, ?, ?, ?, ?)
        ''', (appointment_id, recipient_phone, message, reminder_timing, scheduled_for))
        
        reminder_id = c.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"✅ [RECORDATORIO WA] Creado: cita {appointment_id}, teléfono {recipient_phone}, timing {reminder_timing}")
        
        return jsonify({'ok': True, 'reminder_id': reminder_id}), 201
    
    except Exception as e:
        logger.error(f"Error creando recordatorio WhatsApp: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# REST ENDPOINTS - SALUD
# ═══════════════════════════════════════════════════════════════

@app.route('/api/health')
def health():
    """Health check"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) as msg_count FROM messages')
        msg_count = c.fetchone()['msg_count']
        
        c.execute('SELECT COUNT(*) as apt_count FROM appointments')
        apt_count = c.fetchone()['apt_count']
        
        c.execute('SELECT COUNT(*) as rem_count FROM personal_reminders WHERE fired = 0')
        rem_count = c.fetchone()['rem_count']
        
        conn.close()
        
        return jsonify({
            'status': 'ok',
            'connected_users': len(connected_users),
            'messages': msg_count,
            'appointments': apt_count,
            'pending_reminders': rem_count
        })
    except Exception as e:
        logger.error(f"Error en health check: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500

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
    logger.info("🚀 INICIANDO SERVIDOR CON SOPORTE COMPLETO")
    logger.info(f"HOST: {host}")
    logger.info(f"PORT: {port}")
    logger.info(f"DEBUG: True")
    logger.info(f"LOGGING: Detallado (DEBUG)")
    logger.info(f"DATABASE: {DB_FILE}")
    logger.info(f"SOCKETIO: Habilitado")
    logger.info("="*80 + "\n")
    
    socketio.run(
        app,
        host=host,
        port=port,
        debug=True,
        allow_unsafe_werkzeug=True,
        log_output=True
    )