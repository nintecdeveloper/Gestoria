import os
import sqlite3
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, join_room
from datetime import datetime
import logging
import sys

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(level=logging.DEBUG, format='%(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# FLASK APP Y SOCKETIO
# ═══════════════════════════════════════════════════════════════
app = Flask(__name__, template_folder='templates', static_folder='templates')
app.config['SECRET_KEY'] = 'dev-secret-key'

# ⭐ IMPORTANTE: Configuración de SocketIO para que funcione en Render
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    ping_timeout=60,
    ping_interval=25,
    logger=True,
    engineio_logger=True
)

logger.info("✅ Flask app creada")
logger.info("✅ SocketIO inicializado")

# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════
DB_FILE = 'gestionpro.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Tabla simplificada de mensajes privados
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            sender_username TEXT,
            recipient_id INTEGER NOT NULL,
            text TEXT,
            timestamp TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de mensajes generales
    c.execute('''
        CREATE TABLE IF NOT EXISTS general_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de recordatorios personales
    c.execute('''
        CREATE TABLE IF NOT EXISTS personal_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reminder_timing TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(appointment_id) REFERENCES appointments(id)
        )
    ''')
    
    # Tabla de recordatorios WhatsApp
    c.execute('''
        CREATE TABLE IF NOT EXISTS whatsapp_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL,
            recipient_phone TEXT,
            reminder_timing TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(appointment_id) REFERENCES appointments(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada")

init_db()

# ═══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ═══════════════════════════════════════════════════════════════
users_online = {}  # socket_id -> {user_id, username}

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET EVENTS
# ═══════════════════════════════════════════════════════════════

@socketio.on('connect')
def handle_connect():
    print(f"🔌 Cliente conectado: {request.sid[:8]}")
    emit('connection_response', {'data': 'Conectado'})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in users_online:
        user = users_online.pop(sid)
        print(f"❌ Desconectado: {user.get('username')}")

@socketio.on('login')
def handle_login(data):
    """Usuario hace login"""
    sid = request.sid
    user_id = int(data.get('user_id', 0))
    username = data.get('username', f'Usuario {user_id}')
    
    if user_id <= 0:
        print(f"❌ Login inválido: ID={user_id}")
        emit('login_response', {'ok': False, 'error': 'ID inválido'})
        return
    
    # Registrar usuario
    users_online[sid] = {'user_id': user_id, 'username': username}
    join_room(f'user_{user_id}')
    
    print(f"✅ Login: {username} (ID={user_id}) - SID={sid[:8]}")
    emit('login_response', {'ok': True, 'user_id': user_id})

@socketio.on('send_msg')
def handle_send_msg(data):
    """Recibir mensaje privado"""
    sender_id = int(data.get('sender_id', 0))
    sender_username = data.get('sender_username', '?')
    recipient_id = int(data.get('recipient_id', 0))
    text = data.get('text', '').strip()
    
    print(f"\n{'='*60}")
    print(f"📨 MENSAJE RECIBIDO EN SERVIDOR")
    print(f"   De: {sender_username} (ID={sender_id})")
    print(f"   Para: ID={recipient_id}")
    print(f"   Texto: {text[:40]}...")
    print(f"   SID Emisor: {request.sid[:8]}")
    
    if not text or sender_id <= 0 or recipient_id <= 0:
        print(f"❌ Validación fallida")
        print(f"{'='*60}\n")
        return
    
    ts = datetime.now().isoformat()
    
    # Guardar en BD
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO messages (sender_id, sender_username, recipient_id, text, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (sender_id, sender_username, recipient_id, text, ts))
        
        # 🔑 Obtener el ID de la fila insertada
        message_id = c.lastrowid
        
        conn.commit()
        conn.close()
        print(f"   ✓ GUARDADO EN BASE DE DATOS (ID={message_id})")
    except Exception as e:
        print(f"   ❌ Error BD: {e}")
        print(f"{'='*60}\n")
        return
    
    # Crear objeto de mensaje con TODOS los campos requeridos
    msg = {
        'id': message_id,
        'sender_id': sender_id,
        'sender_username': sender_username,
        'recipient_id': recipient_id,
        'text': text,
        'timestamp': ts
    }
    
    # ENVIAR A AMBOS USUARIOS
    recipient_room = f'user_{recipient_id}'
    sender_room = f'user_{sender_id}'
    
    print(f"   📤 Emitiendo a sala: {recipient_room} (receptor)")
    emit('new_msg', msg, room=recipient_room)
    
    print(f"   📤 Emitiendo a sala: {sender_room} (emisor)")
    emit('new_msg', msg, room=sender_room)
    
    print(f"✅ MENSAJE ENTREGADO A AMBOS LADOS (ID={message_id})")
    print(f"{'='*60}\n")

@socketio.on('send_general')
def handle_send_general(data):
    """Mensaje al chat general"""
    sender_id = int(data.get('sender_id', 0))
    sender_username = data.get('sender_username', '?')
    text = data.get('text', '').strip()
    
    if not text or sender_id <= 0:
        return
    
    ts = datetime.now().isoformat()
    
    print(f"📢 Chat general: {sender_username}: {text[:30]}")
    
    # Guardar en BD
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO general_messages (sender_id, sender_username, text, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (sender_id, sender_username, text, ts))
        
        # 🔑 Obtener el ID de la fila insertada
        message_id = c.lastrowid
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Error BD: {e}")
        return
    
    # Broadcast a todos - con ID de BD
    msg = {
        'id': message_id,
        'sender_id': sender_id,
        'sender_username': sender_username,
        'text': text,
        'timestamp': ts
    }
    emit('new_general_msg', msg, broadcast=True)

# ═══════════════════════════════════════════════════════════════
# REST ROUTES - MENSAJES
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index3.html')

@app.route('/api/messages/<int:user_a>/<int:user_b>')
def get_messages(user_a, user_b):
    """Obtener mensajes entre dos usuarios"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute('''
            SELECT * FROM messages 
            WHERE (sender_id = ? AND recipient_id = ?) 
               OR (sender_id = ? AND recipient_id = ?)
            ORDER BY timestamp ASC
        ''', (user_a, user_b, user_b, user_a))
        
        rows = c.fetchall()
        messages = []
        for row in rows:
            messages.append({
                'id': row[0],
                'sender_id': row[1],
                'sender_username': row[2],
                'recipient_id': row[3],
                'text': row[4],
                'timestamp': row[5]
            })
        conn.close()
        
        return jsonify({'ok': True, 'messages': messages})
    except Exception as e:
        print(f"❌ Error get_messages: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/general-messages')
def get_general_messages():
    """Obtener mensajes del chat general"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute('SELECT * FROM general_messages ORDER BY timestamp ASC')
        
        rows = c.fetchall()
        messages = []
        for row in rows:
            messages.append({
                'id': row[0],
                'sender_id': row[1],
                'sender_username': row[2],
                'text': row[3],
                'timestamp': row[4]
            })
        conn.close()
        
        return jsonify({'ok': True, 'messages': messages})
    except Exception as e:
        print(f"❌ Error get_general_messages: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# REST ROUTES - CITAS (APPOINTMENTS)
# ═══════════════════════════════════════════════════════════════

@app.route('/api/appointments', methods=['GET'])
def get_appointments():
    """Obtener todas las citas"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('SELECT * FROM appointments ORDER BY date DESC, time ASC')
        rows = c.fetchall()
        appointments = []
        for row in rows:
            appointments.append({
                'id': row[0],
                'owner_id': row[1],
                'assigned_to': row[2],
                'date': row[3],
                'time': row[4],
                'time_end': row[5],
                'client': row[6],
                'service': row[7] or '',
                'notes': row[8] or '',
                'private': row[9],
                'client_phone': row[10] or ''
            })
        conn.close()
        return jsonify({'ok': True, 'appointments': appointments})
    except Exception as e:
        print(f"❌ Error get_appointments: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/appointments', methods=['POST'])
def create_appointment():
    """Crear una nueva cita"""
    try:
        data = request.json
        
        # Validación básica
        required_fields = ['owner_id', 'assigned_to', 'date', 'time', 'time_end', 'client']
        for field in required_fields:
            if field not in data or data[field] is None:
                return jsonify({'ok': False, 'error': f'Campo requerido: {field}'}), 400
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO appointments 
            (owner_id, assigned_to, date, time, time_end, client, service, notes, private, client_phone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['owner_id'], 
            data['assigned_to'], 
            data['date'], 
            data['time'], 
            data['time_end'],
            data['client'], 
            data.get('service', ''), 
            data.get('notes', ''), 
            data.get('private', False), 
            data.get('client_phone', '')
        ))
        
        appointment_id = c.lastrowid
        conn.commit()
        conn.close()
        
        print(f"✅ Cita creada: ID={appointment_id}, Cliente={data['client']}")
        socketio.emit('appointment_created', {'id': appointment_id}, broadcast=True)
        return jsonify({'ok': True, 'appointment_id': appointment_id}), 201
    except Exception as e:
        print(f"❌ Error create_appointment: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/appointments/<int:appointment_id>', methods=['PUT'])
def update_appointment(appointment_id):
    """Actualizar una cita existente"""
    try:
        data = request.json
        
        # Verificar que la cita existe
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,))
        existing = c.fetchone()
        
        if not existing:
            conn.close()
            return jsonify({'ok': False, 'error': 'Cita no encontrada'}), 404
        
        # Actualizar campos
        update_fields = {
            'date': data.get('date', existing[3]),
            'time': data.get('time', existing[4]),
            'time_end': data.get('time_end', existing[5]),
            'client': data.get('client', existing[6]),
            'service': data.get('service', existing[7]),
            'notes': data.get('notes', existing[8]),
            'private': data.get('private', existing[9]),
            'client_phone': data.get('client_phone', existing[10]),
            'assigned_to': data.get('assigned_to', existing[2])
        }
        
        c.execute('''
            UPDATE appointments 
            SET date = ?, time = ?, time_end = ?, client = ?, service = ?, 
                notes = ?, private = ?, client_phone = ?, assigned_to = ?
            WHERE id = ?
        ''', (
            update_fields['date'],
            update_fields['time'],
            update_fields['time_end'],
            update_fields['client'],
            update_fields['service'],
            update_fields['notes'],
            update_fields['private'],
            update_fields['client_phone'],
            update_fields['assigned_to'],
            appointment_id
        ))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Cita actualizada: ID={appointment_id}")
        socketio.emit('appointment_updated', {'id': appointment_id}, broadcast=True)
        return jsonify({'ok': True, 'appointment_id': appointment_id})
    except Exception as e:
        print(f"❌ Error update_appointment: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/appointments/<int:appointment_id>', methods=['DELETE'])
def delete_appointment(appointment_id):
    """Eliminar una cita"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Verificar que existe
        c.execute('SELECT * FROM appointments WHERE id = ?', (appointment_id,))
        existing = c.fetchone()
        
        if not existing:
            conn.close()
            return jsonify({'ok': False, 'error': 'Cita no encontrada'}), 404
        
        # Eliminar la cita
        c.execute('DELETE FROM appointments WHERE id = ?', (appointment_id,))
        
        # También eliminar recordatorios asociados
        c.execute('DELETE FROM personal_reminders WHERE appointment_id = ?', (appointment_id,))
        c.execute('DELETE FROM whatsapp_reminders WHERE appointment_id = ?', (appointment_id,))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Cita eliminada: ID={appointment_id}")
        socketio.emit('appointment_deleted', {'id': appointment_id}, broadcast=True)
        return jsonify({'ok': True})
    except Exception as e:
        print(f"❌ Error delete_appointment: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# REST ROUTES - RECORDATORIOS
# ═══════════════════════════════════════════════════════════════

@app.route('/api/reminders/personal', methods=['POST'])
def create_personal_reminder():
    """Crear un recordatorio personal"""
    try:
        data = request.json
        
        if not all(k in data for k in ['appointment_id', 'user_id', 'reminder_timing']):
            return jsonify({'ok': False, 'error': 'Campos requeridos faltantes'}), 400
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Verificar que la cita existe
        c.execute('SELECT * FROM appointments WHERE id = ?', (data['appointment_id'],))
        if not c.fetchone():
            conn.close()
            return jsonify({'ok': False, 'error': 'Cita no encontrada'}), 404
        
        # Insertar recordatorio
        c.execute('''
            INSERT INTO personal_reminders (appointment_id, user_id, reminder_timing)
            VALUES (?, ?, ?)
        ''', (data['appointment_id'], data['user_id'], data['reminder_timing']))
        
        reminder_id = c.lastrowid
        conn.commit()
        conn.close()
        
        print(f"✅ Recordatorio personal creado: ID={reminder_id}")
        return jsonify({'ok': True, 'reminder_id': reminder_id}), 201
    except Exception as e:
        print(f"❌ Error create_personal_reminder: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/reminders/whatsapp', methods=['POST'])
def create_whatsapp_reminder():
    """Crear un recordatorio por WhatsApp"""
    try:
        data = request.json
        
        if not all(k in data for k in ['appointment_id', 'recipient_phone', 'reminder_timing']):
            return jsonify({'ok': False, 'error': 'Campos requeridos faltantes'}), 400
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Verificar que la cita existe
        c.execute('SELECT * FROM appointments WHERE id = ?', (data['appointment_id'],))
        if not c.fetchone():
            conn.close()
            return jsonify({'ok': False, 'error': 'Cita no encontrada'}), 404
        
        # Insertar recordatorio
        c.execute('''
            INSERT INTO whatsapp_reminders (appointment_id, recipient_phone, reminder_timing)
            VALUES (?, ?, ?)
        ''', (data['appointment_id'], data['recipient_phone'], data['reminder_timing']))
        
        reminder_id = c.lastrowid
        conn.commit()
        conn.close()
        
        print(f"✅ Recordatorio WhatsApp creado: ID={reminder_id}")
        return jsonify({'ok': True, 'reminder_id': reminder_id}), 201
    except Exception as e:
        print(f"❌ Error create_whatsapp_reminder: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# ERROR HANDLERS
# ═══════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(e):
    return render_template('index3.html'), 200

@app.errorhandler(500)
def internal_error(e):
    print(f"❌ Error interno del servidor: {e}")
    return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500

# ═══════════════════════════════════════════════════════════════
# MAIN - COMPATIBLE CON RENDER
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Obtener puerto del ambiente (Render lo proporciona)
    port = int(os.environ.get('PORT', 5000))
    
    # Detectar si estamos en Render
    is_render = os.environ.get('RENDER') == 'true'
    
    print("\n" + "="*80)
    print("🚀 SERVIDOR DE MENSAJERÍA Y CITAS INICIADO")
    print(f"🌐 http://localhost:{port}")
    if is_render:
        print("☁️  Corriendo en RENDER")
    print("="*80 + "\n")
    
    # Ejecutar SocketIO
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True
    )