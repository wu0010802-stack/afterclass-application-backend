
from flask import Flask, send_from_directory, request
from config import Config
from flask_cors import CORS
from database import init_db

from routes.main import main_bp
from routes.admin import admin_bp
import os

app = Flask(__name__)
app.config.from_object(Config)

# Enable CORS for all domains on all routes
CORS(app, resources={r"/*": {"origins": "*"}})

# Register Blueprints
app.register_blueprint(main_bp)
app.register_blueprint(admin_bp)

# Initialize Database
init_db()

@app.route('/favicon.ico')
def favicon():
    try:
        return send_from_directory(os.path.join(app.root_path, 'static'),
                                   'favicon.ico', mimetype='image/vnd.microsoft.icon')
    except Exception:
        return '', 204

# Route for xlsx library (backward compatibility or update html)
@app.route('/xlsx.full.min.js')
def xlsx_lib():
    try:
        return send_from_directory(os.path.join(app.root_path, 'static', 'js'), 'lib_xlsx.full.min.js')
    except Exception:
        return '', 204

if __name__ == '__main__':
    print(f"Flask Server running at http://localhost:{Config.PORT}/")
    app.run(host='0.0.0.0', port=Config.PORT, debug=True)
