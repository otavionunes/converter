#!/bin/bash
# Start LibreOffice in listener/daemon mode (accepts UNO connections on port 2002)
echo "Starting LibreOffice UNO listener on port 2002..."
soffice --headless --norestore --nolockcheck \
    --accept="socket,host=localhost,port=2002,tcpNoDelay=1;urp;StarOffice.ServiceManager" &
LO_PID=$!

# Wait for port 2002 to open
for i in $(seq 1 40); do
    sleep 2
    if nc -z localhost 2002 2>/dev/null; then
        echo "LibreOffice listener ready on port 2002 (${i}x2s elapsed)"
        break
    fi
    if ! kill -0 $LO_PID 2>/dev/null; then
        echo "LibreOffice listener exited unexpectedly — conversions will cold-start"
        break
    fi
    echo "  waiting... ($i/40)"
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
