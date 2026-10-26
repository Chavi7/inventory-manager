# Dragon Technologies Inventory Manager - Module 2
FROM python:3.12-slim

# Keep Python output unbuffered so logs show up in Portainer immediately.
ENV PYTHONUNBUFFERED=1

WORKDIR /srv/inventory

# Install dependencies first so Docker can cache this layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY app/ ./app/

# The SQLite database lives here; mount a volume at /data to persist it.
RUN mkdir -p /data
ENV INVENTORY_DB_PATH=/data/inventory.db

WORKDIR /srv/inventory/app
EXPOSE 5000

# Health check so Portainer can show "healthy" instead of just "running".
# Hits "/", which redirects to /setup before the first admin exists and then to
# the dashboard — both are 200 after the redirect, so it works at any stage.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=3).read()" || exit 1

# Gunicorn serves the Flask app. One worker keeps SQLite access simple
# and is plenty for a single classroom.
#
# --preload imports app:app in the master before forking, so a misconfigured
# secret (see _resolve_secret in app/app.py) exits the container instead of
# leaving a worker to die quietly while the container still looks "up".
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", \
     "--timeout", "60", "--preload", "app:app"]
