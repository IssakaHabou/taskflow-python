"""Point d'entrée WSGI : uWSGI (PythonClusters) ou Gunicorn (gunicorn wsgi:application)."""
from app import app as application

app = application
