#!/bin/bash
# Use sync worker with threads — gevent blocks on subprocess.run()
PORT=${PORT:-8080}
exec gunicorn \
    --bind "0.0.0.0:$PORT" \
    --worker-class sync \
    --workers 1 \
    --threads 4 \
    --timeout 300 \
    app:app
