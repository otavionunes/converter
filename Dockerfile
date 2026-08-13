FROM debian:bookworm-slim

# Install LibreOffice (full, with Python UNO bridge), Python 3
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-core \
    libreoffice-common \
    libreoffice-script-provider-python \
    python3-uno \
    fonts-opensymbol \
    libglib2.0-0 \
    libcairo2 \
    libsm6 \
    libxinerama1 \
    libdbus-glib-1-2 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    netcat-openbsd \
    python3 \
    python3-pip \
    python3-venv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify LibreOffice at build time
RUN soffice --headless --version

# Test that python3-uno works
RUN python3 -c "import uno; print('uno OK')"

# Install Flask app in a venv
RUN python3 -m venv /app/venv --system-site-packages
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY convert_uno.py .
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8080

CMD ["/app/start.sh"]
