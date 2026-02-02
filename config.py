
import os

class Config:
    PORT = int(os.environ.get('PORT', 3000))
    DB_NAME = os.environ.get('PGDATABASE', 'afterschool')
    DB_USER = os.environ.get('PGUSER', 'yilunwu')
    DB_PASSWORD = os.environ.get('PGPASSWORD')
    DB_HOST = os.environ.get('PGHOST', 'localhost')
    DB_PORT = int(os.environ.get('PGPORT', 5432))
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    DATABASE_URL = os.environ.get('DATABASE_URL')
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-please-change')
