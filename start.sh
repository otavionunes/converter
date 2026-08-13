#!/bin/bash
# Simple start: just gunicorn. Conversions use soffice sequentially via background thread.
PORT=${PORT:-8080}
exec gunicorn \
    --bind "0.0.0.0:$PORT" \
    --worker-class gevent \
    --workers 1 \
    --worker-connections 10 \
    --timeout 300 \
    app:app
