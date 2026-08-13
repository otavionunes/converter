#!/bin/bash
# Note: no set -e — unoconvert probe exits non-zero until ready, which is expected

# Start unoserver daemon (keeps LibreOffice warm — converts in ~1-2s instead of ~60s)
# Listens on localhost:2003 (UNO protocol)
echo "Starting unoserver daemon..."
unoserver --daemon --port 2003 --host 127.0.0.1 &
UNOSERVER_PID=$!

# Wait for unoserver to be ready (LibreOffice cold start ~30-60s)
echo "Waiting for unoserver to initialize..."
READY=0
for i in $(seq 1 40); do
    sleep 2
    # Check if process still running
    if ! kill -0 $UNOSERVER_PID 2>/dev/null; then
        echo "unoserver process not found — continuing anyway"
        break
    fi
    # Try a no-op connection test (nc to port 2003)
    if nc -z 127.0.0.1 2003 2>/dev/null; then
        READY=1
        break
    fi
    echo "  waiting for port 2003... ($i/40)"
done
if [ $READY -eq 1 ]; then
    echo "unoserver ready on port 2003."
else
    echo "unoserver may not be ready yet — starting gunicorn anyway."
fi

# Start gunicorn Flask app
PORT=${PORT:-8080}
exec gunicorn \
    --bind "0.0.0.0:$PORT" \
    --worker-class gevent \
    --workers 1 \
    --worker-connections 10 \
    --timeout 120 \
    app:app
