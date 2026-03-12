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
socketio = SocketIO(app, cors_allowed_origins="*")

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
        emit('login_response', {'ok': False, 'error': 'ID inválido'})
        return
    
    # Registrar usuario
    users_online[sid] = {'user_id': user_id, 'username': username}
    join_room(f'user_{user_id}')
    
    print(f"✅ Login: {username} (ID={user_id})")
    emit('login_response', {'ok': True, 'user_id': user_id})

@socketio.on('send_msg')
def handle_send_msg(data):
    """Recibir mensaje privado"""
    sender_id = int(data.get('sender_id', 0))
    sender_username = data.get('sender_username', '?')
    recipient_id = int(data.get('recipient_id', 0))
    text = data.get('text', '').strip()
    
    if not text or sender_id <= 0 or recipient_id <= 0:
        print(f"❌ Mensaje inválido de {sender_id}")
        return
    
    ts = datetime.now().isoformat()
    
    print(f"💬 Mensaje: {sender_username} → User {recipient_id}: {text[:30]}")
    
    # Guardar en BD
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO messages (sender_id, sender_username, recipient_id, text, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (sender_id, sender_username, recipient_id, text, ts))
        conn.commit()
        conn.close()
        print(f"   ✓ Guardado en BD")
    except Exception as e:
        print(f"   ❌ Error BD: {e}")
        return
    
    # Crear objeto de mensaje
    msg = {
        'sender_id': sender_id,
        'sender_username': sender_username,
        'recipient_id': recipient_id,
        'text': text,
        'timestamp': ts
    }
    
    # ✅ ENVIAR AL RECEPTOR (sala user_X donde X es el ID del receptor)
    print(f"   📤 Enviando a sala: user_{recipient_id}")
    emit('new_msg', msg, room=f'user_{recipient_id}')
    
    # ✅ TAMBIÉN ENVIAR AL EMISOR para que vea su propio mensaje
    print(f"   📤 Enviando confirmación a sala: user_{sender_id}")
    emit('new_msg', msg, room=f'user_{sender_id}')
    
    print(f"✅ Mensaje entregado a ambos lados")

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
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Error BD: {e}")
        return
    
    # Broadcast a todos
    msg = {
        'sender_id': sender_id,
        'sender_username': sender_username,
        'text': text,
        'timestamp': ts
    }
    emit('new_general_msg', msg, broadcast=True)

# ═══════════════════════════════════════════════════════════════
# REST ROUTES
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

@app.route('/api/appointments', methods=['GET'])
def get_appointments():
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
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/appointments', methods=['POST'])
def create_appointment():
    try:
        data = request.json
        conn = sqlite3.connect(DB_FILE)
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
        
        socketio.emit('appointment_created', {'id': appointment_id}, broadcast=True)
        return jsonify({'ok': True, 'appointment_id': appointment_id}), 201
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    return render_template('index3.html'), 200

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("\n" + "="*80)
    print("🚀 SERVIDOR DE MENSAJERÍA INICIADO")
    print(f"🌐 http://localhost:{port}")
    print("="*80 + "\n")
    
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)