web: gunicorn flask_api_server:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2
worker: celery -A celery_worker worker --loglevel=info
beat: celery -A celery_worker beat --loglevel=info
