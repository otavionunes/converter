#!/bin/bash
# Start LibreOffice UNO listener (single process, warm for ~2-5s conversions)
echo "Starting LibreOffice UNO listener on port 2002..."
soffice --headless --norestore --nolockcheck \
    --accept="socket,host=localhost,port=2002,tcpNoDelay=1;urp;StarOffice.ServiceManager" &
LO_PID=$!

# Wait up to 80s for port 2002
for i in $(seq 1 40); do
    sleep 2
    if nc -z localhost 2002 2>/dev/null; then
        echo "LibreOffice UNO listener ready (${i}x2s)"
        break
    fi
    if ! kill -0 $LO_PID 2>/dev/null; then
        echo "WARNING: LibreOffice listener exited during startup"
        break
    fi
    echo "  waiting... ($i/40)"
done

# Start gunicorn with sync+threads (gevent blocks Python threads with subprocess)
PORT=${PORT:-8080}
exec gunicorn \
    --bind "0.0.0.0:$PORT" \
    --worker-class gthread \
    --workers 1 \
    --threads 4 \
    --timeout 300 \
    app:app
