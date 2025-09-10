web: gunicorn flask_api_server:app --bind 0.0.0.0:$PORT
worker: celery -A celery_worker worker --loglevel=info
