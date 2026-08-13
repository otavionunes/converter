"""
EWAAD Converter — .doc to .docx microservice (Docker version)
Accepts a .doc file via POST /convert, returns .docx bytes.
Internal service — no auth required.
"""
import os
import subprocess
import tempfile
import shutil
import logging
import glob

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB

# In Docker, LibreOffice is installed to the standard system path
SOFFICE_PATH = '/usr/bin/soffice'
LIBREOFFICE_AVAILABLE = os.path.exists(SOFFICE_PATH)

if LIBREOFFICE_AVAILABLE:
    log.info("LibreOffice available at: %s", SOFFICE_PATH)
else:
    log.warning("LibreOffice NOT found at %s", SOFFICE_PATH)


@app.route('/debug', methods=['GET'])
def debug():
    """Debug endpoint — shows soffice location and PATH info."""
    results = {
        'soffice_path': SOFFICE_PATH,
        'soffice_exists': os.path.exists(SOFFICE_PATH),
        'which_soffice': shutil.which('soffice'),
        'which_libreoffice': shutil.which('libreoffice'),
        'PATH': os.environ.get('PATH', ''),
    }
    # Also glob for any soffice binaries
    for pattern in ['/usr/bin/soffice', '/usr/lib/libreoffice/program/soffice']:
        results[f'glob_{pattern}'] = os.path.exists(pattern)
    return jsonify(results), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "libreoffice": LIBREOFFICE_AVAILABLE
    }), 200


@app.route('/convert', methods=['POST'])
def convert():
    """
    POST /convert
    Body: raw .doc bytes (Content-Type: application/octet-stream)
    Header: X-Filename: original filename (optional)
    Returns: raw .docx bytes (Content-Type: application/octet-stream)
    """
    if not LIBREOFFICE_AVAILABLE:
        return jsonify({"error": "LibreOffice not available on this instance"}), 503

    doc_bytes = request.get_data()
    if not doc_bytes:
        return jsonify({"error": "No file data received"}), 400
    if len(doc_bytes) > MAX_FILE_BYTES:
        return jsonify({"error": f"File too large ({len(doc_bytes)} bytes, max {MAX_FILE_BYTES})"}), 413

    # Verify it's a .doc file (OLE2 binary or XML-based WordML)
    is_ole2 = doc_bytes[:4] == b'\xd0\xcf\x11\xe0'
    is_wordml = doc_bytes[:5] == b'<?xml' and (
        b'WordDocument' in doc_bytes[:2000] or
        b'w:wordDocument' in doc_bytes[:2000] or
        b'mso-application' in doc_bytes[:2000] or
        b'w:document' in doc_bytes[:500]
    )
    if not (is_ole2 or is_wordml):
        return jsonify({"error": "File does not appear to be a .doc (OLE2 or WordML) format"}), 400

    original_filename = request.headers.get('X-Filename', 'input.doc')
    if not original_filename.lower().endswith('.doc'):
        original_filename += '.doc'

    tmp_dir = tempfile.mkdtemp(prefix="ewaad_conv_")
    try:
        input_path = os.path.join(tmp_dir, original_filename)
        with open(input_path, 'wb') as f:
            f.write(doc_bytes)

        cmd = [
            SOFFICE_PATH, '--headless', '--norestore', '--nolockcheck',
            '--convert-to', 'docx',
            '--outdir', tmp_dir,
            input_path
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=180,
            cwd=tmp_dir,
            env={**os.environ, 'HOME': tmp_dir}
        )

        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', errors='replace')[:500]
            log.error("LibreOffice failed for %s: %s", original_filename, stderr)
            return jsonify({"error": f"Conversion failed: {stderr}"}), 422

        expected_output = os.path.splitext(input_path)[0] + '.docx'
        if not os.path.exists(expected_output):
            docx_files = [f for f in os.listdir(tmp_dir) if f.endswith('.docx')]
            if not docx_files:
                return jsonify({"error": "LibreOffice produced no .docx output"}), 422
            expected_output = os.path.join(tmp_dir, docx_files[0])

        with open(expected_output, 'rb') as f:
            docx_bytes = f.read()

        if len(docx_bytes) < 100 or docx_bytes[:2] != b'PK':
            return jsonify({"error": "Converted output is not a valid .docx file"}), 422

        log.info("Converted %s: %d bytes -> %d bytes", original_filename, len(doc_bytes), len(docx_bytes))
        return Response(
            docx_bytes,
            content_type='application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{os.path.splitext(original_filename)[0]}.docx"'}
        )

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Conversion timed out (180s limit)"}), 422
    except Exception as e:
        log.exception("Unexpected error converting %s", original_filename)
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
