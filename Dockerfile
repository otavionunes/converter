FROM python:3.11-slim-bookworm

# Install LibreOffice and required shared libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-core \
    libreoffice-common \
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
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify LibreOffice install works at build time
RUN soffice --headless --version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8080

CMD ["/app/start.sh"]
