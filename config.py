import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-img2pdf'

    # PostgreSQL Configuration
    DB_HOST     = os.environ.get('DB_HOST')     or 'localhost'
    DB_PORT     = os.environ.get('DB_PORT')     or '5432'
    DB_NAME     = os.environ.get('DB_NAME')     or 'image_to_pdf'
    DB_USER     = os.environ.get('DB_USER')     or 'postgres'
    DB_PASSWORD = os.environ.get('DB_PASSWORD') or '12345'

    SQLALCHEMY_DATABASE_URI = (
        f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload Configuration
    UPLOAD_FOLDER     = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024          # 20 MB max
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif'}