FROM debian:bookworm-slim

# Install LibreOffice (full, with Python UNO bridge), Python 3
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-core \
    libreoffice-common \
    libreoffice-script-provider-python \
    libreoffice-java-common \
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
    default-jre-headless \
    python3 \
    python3-pip \
    python3-venv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify LibreOffice at build time
RUN soffice --headless --version

# Test that python3-uno works
RUN python3 -c "import uno; print('uno OK')"

# Test that soffice can actually convert a WordML file
RUN mkdir -p /tmp/lo_test && \
    echo '<?xml version="1.0" encoding="UTF-8"?><?mso-application progid="Word.Document"?><w:wordDocument xmlns:w="http://schemas.microsoft.com/office/word/2003/wordml"><w:body><w:p><w:r><w:t>test</w:t></w:r></w:p></w:body></w:wordDocument>' > /tmp/lo_test/test.doc && \
    soffice -env:UserInstallation=file:///tmp/lo_test/profile --headless --norestore --convert-to docx --outdir /tmp/lo_test /tmp/lo_test/test.doc && \
    ls -la /tmp/lo_test/test.docx && \
    echo "WordML conversion: OK" && \
    rm -rf /tmp/lo_test

# Install Flask app in a venv
RUN python3 -m venv /app/venv --system-site-packages
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY convert_doc.py .
COPY convert_uno.py .
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8080

CMD ["/app/start.sh"]
