#!/bin/bash
set -e

# Start unoserver daemon (keeps LibreOffice warm — converts in ~1-2s instead of ~60s)
# Listens on localhost:2003 (UNO protocol)
echo "Starting unoserver daemon..."
unoserver --daemon --port 2003 --host 127.0.0.1 &
UNOSERVER_PID=$!

# Wait for unoserver to be ready (LibreOffice cold start)
echo "Waiting for unoserver to initialize..."
for i in $(seq 1 30); do
    sleep 2
    if unoconvert --connection "socket,host=127.0.0.1,port=2003,tcpNoDelay=1" /dev/null /dev/null 2>/dev/null; then
        break
    fi
    # Check if process still running
    if ! kill -0 $UNOSERVER_PID 2>/dev/null; then
        echo "unoserver died during startup!"
        break
    fi
    echo "  waiting... ($i/30)"
done
echo "unoserver ready."

# Start gunicorn Flask app
PORT=${PORT:-8080}
exec gunicorn \
    --bind "0.0.0.0:$PORT" \
    --worker-class gevent \
    --workers 1 \
    --worker-connections 10 \
    --timeout 120 \
    app:app
