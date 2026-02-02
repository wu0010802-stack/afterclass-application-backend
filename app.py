
from flask import Flask, send_from_directory
from config import Config
from database import init_db
from routes.main import main_bp
from routes.admin import admin_bp
import os

app = Flask(__name__)
app.config.from_object(Config)

# Register Blueprints
app.register_blueprint(main_bp)
app.register_blueprint(admin_bp)

# Initialize Database
init_db()

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

# Route for xlsx library (backward compatibility or update html)
@app.route('/xlsx.full.min.js')
def xlsx_lib():
    return send_from_directory(os.path.join(app.root_path, 'static', 'js'), 'lib_xlsx.full.min.js')

if __name__ == '__main__':
    print(f"Flask Server running at http://localhost:{Config.PORT}/")
    app.run(host='0.0.0.0', port=Config.PORT, debug=True)
