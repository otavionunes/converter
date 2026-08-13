#!/bin/bash
# Simple start — conversion uses soffice --headless via detached subprocess
# No UNO listener needed (avoids complexity of shared connections)
PORT=${PORT:-8080}
exec gunicorn \
    --bind "0.0.0.0:$PORT" \
    --worker-class gthread \
    --workers 1 \
    --threads 4 \
    --timeout 300 \
    app:app
