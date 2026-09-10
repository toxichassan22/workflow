FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Keep the project root importable during Python startup so sitecustomize.py
# is loaded before gunicorn imports app:app.
ENV PYTHONPATH=/app

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD exec gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 8 --timeout 300 --graceful-timeout 30 app:app
