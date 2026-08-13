#!/bin/bash
# unoserver needs PYTHONPATH to find LibreOffice's 'uno' module
export PYTHONPATH=/usr/lib/libreoffice/program:${PYTHONPATH:-}

echo "Starting unoserver daemon (port 2003)..."
unoserver --daemon --port 2003 --host 127.0.0.1 &
UNOSERVER_PID=$!

# Wait for port 2003 to open (LibreOffice cold start ~30-60s)
for i in $(seq 1 40); do
    sleep 2
    if ! kill -0 $UNOSERVER_PID 2>/dev/null; then
        echo "unoserver exited — will use soffice fallback"
        break
    fi
    if nc -z 127.0.0.1 2003 2>/dev/null; then
        echo "unoserver ready (${i}x2s elapsed)"
        break
    fi
    echo "  waiting for unoserver... ($i/40)"
done

# Start gunicorn Flask app
PORT=${PORT:-8080}
exec gunicorn \
    --bind "0.0.0.0:$PORT" \
    --worker-class gevent \
    --workers 1 \
    --worker-connections 10 \
    --timeout 120 \
    app:app
