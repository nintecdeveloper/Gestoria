import os
from flask import Flask, render_template, jsonify, request
from datetime import datetime

# Inicializar Flask con template_folder
app = Flask(__name__, template_folder='templates')

# Configuración para Render
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
# RUTAS API (para futuras integraciones)
# ═══════════════════════════════════════════════════════════════

@app.route('/api/status')
def api_status():
    """Endpoint para verificar estado de la API"""
    return jsonify({
        'status': 'ok',
        'app': 'GestióPro',
        'version': '1.0',
        'timestamp': datetime.now().isoformat(),
        'environment': app.config['ENV']
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
    # Obtener puerto de variables de entorno (Render proporciona PORT)
    port = int(os.environ.get('PORT', 5000))
    
    # En producción (Render), usar host 0.0.0.0
    host = '0.0.0.0'
    
    # Iniciar servidor
    app.run(
        host=host,
        port=port,
        debug=app.config['DEBUG'],
        use_reloader=False  # Desactivar reloader en Render
    )