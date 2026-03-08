import os
from flask import Flask, render_template, jsonify, request
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
# TWILIO — IMPORTACIÓN CONDICIONAL
# El bloque try/except permite que la app funcione aunque Twilio
# no esté instalado todavía. Cuando lo tengas todo listo, instala:
#   pip install twilio
# y el import se activará automáticamente.
# ═══════════════════════════════════════════════════════════════
try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    print("⚠️  [WhatsApp] Twilio no instalado. pip install twilio para activarlo.")

# ═══════════════════════════════════════════════════════════════
# APSCHEDULER — IMPORTACIÓN CONDICIONAL
# Programa el envío de WhatsApp desde el servidor, independiente
# de si el navegador está abierto o cerrado.
# Instala con: pip install apscheduler
# Añade también "apscheduler" a requirements.txt
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
# CONFIGURACIÓN TWILIO
# ─────────────────────────────────────────────────────────────
# PASOS PARA ACTIVAR (cuando tengas las credenciales):
#
#   1. Crea cuenta gratuita en https://www.twilio.com
#   2. En el Dashboard de Twilio copia:
#        · Account SID  → TWILIO_ACCOUNT_SID
#        · Auth Token   → TWILIO_AUTH_TOKEN
#   3. Activa WhatsApp Sandbox:
#        · Messaging → Try it out → Send a WhatsApp message
#        · El número sandbox es: whatsapp:+14155238886
#        · Guárdalo en TWILIO_WHATSAPP_FROM (formato: whatsapp:+14155238886)
#   4. En Render, ve a tu servicio → Environment → Add Environment Variable
#        · TWILIO_ACCOUNT_SID   = ACxxxxxxxxxxxxxxxxxxxx
#        · TWILIO_AUTH_TOKEN    = tu_auth_token
#        · TWILIO_WHATSAPP_FROM = whatsapp:+14155238886   ← sandbox
#   5. Instala la librería: pip install twilio
#      y añade "twilio" a requirements.txt
#
# Para producción (número propio de empresa):
#   · Solicita un número WhatsApp Business en Twilio
#   · Cambia TWILIO_WHATSAPP_FROM al nuevo número
#   · No se necesita ningún otro cambio en el código
# ─────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID  = os.environ.get('TWILIO_ACCOUNT_SID',  None)
TWILIO_AUTH_TOKEN   = os.environ.get('TWILIO_AUTH_TOKEN',   None)
TWILIO_WHATSAPP_FROM = os.environ.get('TWILIO_WHATSAPP_FROM', None)
# Ejemplo producción: 'whatsapp:+34XXXXXXXXX'
# Ejemplo sandbox:    'whatsapp:+14155238886'

def get_twilio_client():
    """Devuelve cliente Twilio si las credenciales están configuradas."""
    if not TWILIO_AVAILABLE:
        return None, "Twilio no instalado. Ejecuta: pip install twilio"
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return None, "Credenciales Twilio no configuradas en variables de entorno."
    if not TWILIO_WHATSAPP_FROM:
        return None, "TWILIO_WHATSAPP_FROM no configurado en variables de entorno."
    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        return client, None
    except Exception as e:
        return None, f"Error al inicializar Twilio: {str(e)}"

# ═══════════════════════════════════════════════════════════════
# SCHEDULER — INICIALIZACIÓN
# Se arranca un scheduler en background que ejecuta los trabajos
# de envío de WhatsApp en el momento programado, sin necesidad
# de que el navegador esté abierto.
# ═══════════════════════════════════════════════════════════════
scheduler = None
if SCHEDULER_AVAILABLE:
    scheduler = BackgroundScheduler(timezone='Europe/Madrid')
    scheduler.start()
    print("✅ [Scheduler] APScheduler iniciado correctamente.")

def send_whatsapp_job(to_phone: str, message: str):
    """
    Tarea ejecutada por el scheduler en el momento programado.
    Envía el WhatsApp via Twilio directamente desde el servidor.
    Esta función corre en background, sin intervención del usuario.
    """
    client, err = get_twilio_client()
    if err:
        print(f"❌ [Scheduler/WA] No se puede enviar a {to_phone}: {err}")
        return
    try:
        # Normalizar número al formato whatsapp:+XXXXXXXXXXX
        phone = to_phone.strip()
        if not phone.startswith('whatsapp:'):
            if not phone.startswith('+'):
                phone = '+34' + phone.lstrip('0')
            phone = 'whatsapp:' + phone

        msg = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=phone,
            body=message
        )
        print(f"✅ [Scheduler/WA] Enviado a {phone} · SID: {msg.sid}")
    except Exception as e:
        print(f"❌ [Scheduler/WA] Error al enviar a {to_phone}: {str(e)}")

# ═══════════════════════════════════════════════════════════════
# INICIALIZAR FLASK
# ═══════════════════════════════════════════════════════════════
app = Flask(__name__, template_folder='templates')
app.config['ENV'] = os.environ.get('FLASK_ENV', 'production')
app.config['DEBUG'] = False if app.config['ENV'] == 'production' else True

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
# API WHATSAPP — ENVÍO AUTOMÁTICO VÍA TWILIO
# ═══════════════════════════════════════════════════════════════

@app.route('/api/whatsapp/send', methods=['POST'])
def send_whatsapp():
    """
    Envía un mensaje de WhatsApp INMEDIATAMENTE via Twilio.
    Usado para el timing 'now' (envío al guardar la cita).

    Body JSON esperado:
    {
        "to":      "+34612345678",
        "message": "Hola, le recordamos su cita..."
    }

    Respuesta OK:    { "ok": true,  "sid": "SMxxxx" }
    Respuesta error: { "ok": false, "error": "motivo" }
    """
    data = request.get_json(silent=True) or {}
    to_phone = data.get('to', '').strip()
    message  = data.get('message', '').strip()

    if not to_phone:
        return jsonify({'ok': False, 'error': 'Falta el campo "to" (teléfono destino)'}), 400
    if not message:
        return jsonify({'ok': False, 'error': 'Falta el campo "message"'}), 400

    # Normalizar número
    if not to_phone.startswith('whatsapp:'):
        if not to_phone.startswith('+'):
            to_phone = '+34' + to_phone.lstrip('0')
        to_phone = 'whatsapp:' + to_phone

    client, err = get_twilio_client()
    if err:
        print(f"⚠️  [WhatsApp] No se puede enviar: {err}")
        return jsonify({'ok': False, 'error': err, 'configured': False}), 503

    try:
        msg = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=to_phone,
            body=message
        )
        print(f"✅ [WhatsApp] Enviado a {to_phone} · SID: {msg.sid}")
        return jsonify({'ok': True, 'sid': msg.sid})
    except Exception as e:
        print(f"❌ [WhatsApp] Error al enviar a {to_phone}: {str(e)}")
        return jsonify({'ok': False, 'error': str(e)}), 500


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
        "send_at":     "2025-06-15T10:00:00",   ← fecha/hora UTC del envío
        "job_id":      "wa_evento_42"            ← ID único (para evitar duplicados)
    }

    Respuesta OK:    { "ok": true,  "job_id": "wa_evento_42", "scheduled_for": "..." }
    Respuesta error: { "ok": false, "error": "motivo" }
    """
    if not SCHEDULER_AVAILABLE or not scheduler:
        # Sin scheduler: el frontend gestionará el setTimeout como fallback
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
        # Si no tiene timezone, asumir Madrid
        if send_dt.tzinfo is None:
            madrid = pytz.timezone('Europe/Madrid')
            send_dt = madrid.localize(send_dt)
    except ValueError:
        return jsonify({'ok': False, 'error': f'Formato de send_at inválido: {send_at}'}), 400

    # Si la fecha ya pasó, no programar
    now_tz = datetime.now(pytz.timezone('Europe/Madrid'))
    if send_dt <= now_tz:
        return jsonify({'ok': False, 'error': 'La fecha de envío ya ha pasado'}), 400

    # Eliminar job anterior con el mismo ID si existe (evita duplicados al editar cita)
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
        print(f"📅 [Scheduler] WA programado para {send_dt.isoformat()} → {to_phone} (job: {job_id})")
        return jsonify({
            'ok': True,
            'job_id': job_id,
            'scheduled_for': send_dt.isoformat()
        })
    except Exception as e:
        print(f"❌ [Scheduler] Error al programar job {job_id}: {str(e)}")
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
            print(f"🗑️  [Scheduler] Job cancelado: {job_id}")
            return jsonify({'ok': True})
        else:
            return jsonify({'ok': False, 'error': 'Job no encontrado'}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/whatsapp/status', methods=['GET'])
def whatsapp_status():
    """
    Comprueba si Twilio y el Scheduler están listos.
    El frontend usa esto para saber si el envío es automático (servidor)
    o manual (wa.me fallback).

    Respuesta:
    {
        "twilio_ready":    true/false,
        "scheduler_ready": true/false,
        "fully_ready":     true/false,   ← true solo si ambos están OK
        "reason":          "..."
    }
    """
    twilio_ok = (
        TWILIO_AVAILABLE and
        bool(TWILIO_ACCOUNT_SID) and
        bool(TWILIO_AUTH_TOKEN) and
        bool(TWILIO_WHATSAPP_FROM)
    )
    scheduler_ok = SCHEDULER_AVAILABLE and scheduler is not None

    reasons = []
    if not TWILIO_AVAILABLE:
        reasons.append("Twilio no instalado (pip install twilio)")
    elif not twilio_ok:
        reasons.append("Variables de entorno Twilio no configuradas")
    if not SCHEDULER_AVAILABLE:
        reasons.append("APScheduler no instalado (pip install apscheduler)")

    return jsonify({
        'twilio_ready':    twilio_ok,
        'scheduler_ready': scheduler_ok,
        'fully_ready':     twilio_ok and scheduler_ok,
        'reason':          ' · '.join(reasons) if reasons else 'Todo configurado correctamente'
    })

# ═══════════════════════════════════════════════════════════════
# RUTAS API — ESTADO Y HEALTH CHECK
# ═══════════════════════════════════════════════════════════════

@app.route('/api/status')
def api_status():
    """Endpoint para verificar estado de la API"""
    return jsonify({
        'status': 'ok',
        'app': 'GestióPro',
        'version': '2.0',
        'timestamp': datetime.now().isoformat(),
        'environment': app.config['ENV'],
        'whatsapp_ready':  TWILIO_AVAILABLE and bool(TWILIO_ACCOUNT_SID) and bool(TWILIO_WHATSAPP_FROM),
        'scheduler_ready': SCHEDULER_AVAILABLE and scheduler is not None,
    })

@app.route('/api/health')
def api_health():
    """Endpoint de health check para Render"""
    return jsonify({'status': 'healthy', 'service': 'gestionpro'}), 200

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
    return jsonify({'error': 'Internal server error', 'details': str(error)}), 500

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE PUERTO Y HOST
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = '0.0.0.0'
    app.run(
        host=host,
        port=port,
        debug=app.config['DEBUG'],
        use_reloader=False
    )