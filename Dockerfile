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
    python3-pip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify LibreOffice install works at build time
RUN soffice --headless --version

# Install unoserver using LibreOffice's own Python (has the 'uno' module)
RUN /usr/lib/libreoffice/program/python -m pip install unoserver==3.3 --break-system-packages 2>/dev/null || \
    /usr/lib/libreoffice/program/python -m pip install unoserver==3.3

# Symlink unoserver/unoconvert into PATH from LibreOffice Python scripts
RUN ln -sf /usr/lib/libreoffice/program/unoserver /usr/local/bin/unoserver 2>/dev/null || true && \
    ln -sf /usr/lib/libreoffice/program/unoconvert /usr/local/bin/unoconvert 2>/dev/null || true && \
    find /usr -name "unoserver" -o -name "unoconvert" 2>/dev/null | head -10

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8080

CMD ["/app/start.sh"]

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8080

CMD ["/app/start.sh"]
