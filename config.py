
import os

class Config:
    PORT = int(os.environ.get('PORT', 3000))
    DB_NAME = "afterschool"
    DB_USER = "yilunwu"
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    DATABASE_URL = os.environ.get('DATABASE_URL')
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-please-change')
