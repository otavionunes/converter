#!/bin/bash
# Start unoconv listener (persistent LibreOffice daemon)
echo "Starting unoconv listener..."
unoconv --listener &
LISTENER_PID=$!

# Wait for the listener to be ready
echo "Waiting for unoconv listener..."
for i in $(seq 1 40); do
    sleep 2
    if ! kill -0 $LISTENER_PID 2>/dev/null; then
        echo "unoconv listener exited — conversions will use cold-start soffice"
        break
    fi
    # Test with a trivial conversion attempt (will fail but connects to listener)
    if unoconv --connection "socket,host=localhost,port=2002,tcpNoDelay=1" -f docx -o /dev/null /dev/null 2>/dev/null; then
        echo "unoconv listener ready (${i}x2s elapsed)"
        break
    fi
    # Try nc as port check (unoconv listener uses port 2002)
    if nc -z 127.0.0.1 2002 2>/dev/null; then
        echo "unoconv listener ready on port 2002 (${i}x2s elapsed)"
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
