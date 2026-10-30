"""Production entry point: gunicorn wsgi:app"""
from gridglass import create_app

app = create_app()
