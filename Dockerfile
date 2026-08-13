FROM debian:bookworm-slim

# Install LibreOffice (full with Python runtime), unoconv, Python 3, pip
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-core \
    libreoffice-common \
    libreoffice-script-provider-python \
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
    unoconv \
    python3 \
    python3-pip \
    python3-venv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify LibreOffice and unoconv at build time
RUN soffice --headless --version
RUN unoconv --version

# Install Flask app in a venv
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8080

CMD ["/app/start.sh"]
