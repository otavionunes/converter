#!/bin/bash
# Note: no set -e — unoconvert probe exits non-zero until ready, which is expected

# Find unoserver — installed under LibreOffice Python
UNOSERVER_BIN=$(find /usr/lib/libreoffice /usr/local/bin -name "unoserver" 2>/dev/null | head -1)
LO_PYTHON=$(find /usr/lib/libreoffice/program -name "python3" -o -name "python" 2>/dev/null | head -1)

if [ -z "$UNOSERVER_BIN" ] || [ -z "$LO_PYTHON" ]; then
    echo "unoserver or LibreOffice Python not found — will use soffice fallback"
else
    echo "Starting unoserver daemon via $LO_PYTHON $UNOSERVER_BIN ..."
    $LO_PYTHON $UNOSERVER_BIN --daemon --port 2003 --host 127.0.0.1 &
    UNOSERVER_PID=$!

    # Wait for unoserver to be ready (LibreOffice cold start ~30-60s)
    echo "Waiting for unoserver on port 2003..."
    for i in $(seq 1 40); do
        sleep 2
        if ! kill -0 $UNOSERVER_PID 2>/dev/null; then
            echo "unoserver process exited — will use soffice fallback"
            break
        fi
        if nc -z 127.0.0.1 2003 2>/dev/null; then
            echo "unoserver ready on port 2003 (${i}x2s)"
            break
        fi
        echo "  waiting... ($i/40)"
    done
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
