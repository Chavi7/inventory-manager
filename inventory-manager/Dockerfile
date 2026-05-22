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

# Gunicorn serves the Flask app. One worker keeps SQLite access simple
# and is plenty for a single classroom.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", \
     "--timeout", "60", "app:app"]
