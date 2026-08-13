"""
EWAAD Converter — .doc to .docx microservice (Docker version)
Uses unoserver daemon for fast conversions (~1-2s) instead of cold LibreOffice start (~60s).
Accepts a .doc file via POST /convert, returns .docx bytes.
Internal service — no auth required.
"""
import os
import subprocess
import tempfile
import shutil
import logging
import glob as _glob

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB

UNOSERVER_CONNECTION = "socket,host=127.0.0.1,port=2003,tcpNoDelay=1"
SOFFICE_PATH = '/usr/bin/soffice'

# Find unoconvert — installed under LibreOffice Python's scripts dir
def _find_unoconvert():
    candidates = (
        _glob.glob('/usr/lib/libreoffice/program/unoconvert') +
        _glob.glob('/usr/local/lib/python*/dist-packages/bin/unoconvert') +
        [shutil.which('unoconvert') or '']
    )
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None

def _find_lo_python():
    candidates = (
        _glob.glob('/usr/lib/libreoffice/program/python3*') +
        _glob.glob('/usr/lib/libreoffice/program/python')
    )
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None

UNOCONVERT = _find_unoconvert()
LO_PYTHON = _find_lo_python()
log.info("unoconvert: %s, LO_PYTHON: %s", UNOCONVERT, LO_PYTHON)


def _convert_via_unoserver(input_path, output_path):
    """Convert using unoconvert (fast — reuses running LibreOffice daemon)."""
    # Run as: lo_python unoconvert --connection ... input output
    cmd = []
    if LO_PYTHON:
        cmd = [LO_PYTHON, UNOCONVERT]
    else:
        cmd = [UNOCONVERT]
    cmd += [
        '--connection', UNOSERVER_CONNECTION,
        '--convert-to', 'docx',
        input_path,
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=55)
    return result


def _convert_via_soffice(input_path, outdir):
    """Fallback: convert using soffice directly (slow cold start)."""
    cmd = [
        SOFFICE_PATH, '--headless', '--norestore', '--nolockcheck',
        '--convert-to', 'docx',
        '--outdir', outdir,
        input_path,
    ]
    result = subprocess.run(
        cmd, capture_output=True, timeout=170,
        cwd=outdir, env={**os.environ, 'HOME': outdir}
    )
    return result


@app.route('/debug', methods=['GET'])
def debug():
    return jsonify({
        'unoconvert': UNOCONVERT,
        'unoconvert_exists': bool(UNOCONVERT and os.path.exists(UNOCONVERT)),
        'lo_python': LO_PYTHON,
        'lo_python_exists': bool(LO_PYTHON and os.path.exists(LO_PYTHON)),
        'soffice_path': SOFFICE_PATH,
        'soffice_exists': os.path.exists(SOFFICE_PATH),
        'unoserver_connection': UNOSERVER_CONNECTION,
        'PATH': os.environ.get('PATH', ''),
    }), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "unoconvert": bool(UNOCONVERT and os.path.exists(UNOCONVERT)),
    }), 200


@app.route('/convert', methods=['OPTIONS', 'POST'])
def convert():
    """
    POST /convert
    Body: raw .doc bytes (Content-Type: application/octet-stream)
    Header: X-Filename: original filename (optional)
    Returns: raw .docx bytes (Content-Type: application/octet-stream)
    """
    if request.method == 'OPTIONS':
        return '', 204

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

        output_path = os.path.splitext(input_path)[0] + '.docx'

        # Try unoserver first (fast), fall back to soffice (slow)
        use_uno = bool(UNOCONVERT and os.path.exists(UNOCONVERT))
        if use_uno:
            log.info("Converting %s via unoserver", original_filename)
            try:
                result = _convert_via_unoserver(input_path, output_path)
                if result.returncode != 0:
                    stderr = result.stderr.decode('utf-8', errors='replace')[:500]
                    stdout = result.stdout.decode('utf-8', errors='replace')[:200]
                    log.warning("unoconvert failed (rc=%d): %s %s — falling back to soffice",
                                result.returncode, stderr, stdout)
                    use_uno = False
            except subprocess.TimeoutExpired:
                log.warning("unoconvert timed out — falling back to soffice")
                use_uno = False

        if not use_uno:
            log.info("Converting %s via soffice (fallback)", original_filename)
            try:
                result = _convert_via_soffice(input_path, tmp_dir)
                if result.returncode != 0:
                    stderr = result.stderr.decode('utf-8', errors='replace')[:500]
                    log.error("soffice failed for %s: %s", original_filename, stderr)
                    return jsonify({"error": f"Conversion failed: {stderr}"}), 422
                # soffice writes to outdir, not output_path directly
                docx_files = [f for f in os.listdir(tmp_dir) if f.endswith('.docx')]
                if docx_files:
                    output_path = os.path.join(tmp_dir, docx_files[0])
            except subprocess.TimeoutExpired:
                return jsonify({"error": "Conversion timed out"}), 422

        if not os.path.exists(output_path):
            # check tmp_dir for any .docx
            docx_files = [f for f in os.listdir(tmp_dir) if f.endswith('.docx')]
            if not docx_files:
                return jsonify({"error": "LibreOffice produced no .docx output"}), 422
            output_path = os.path.join(tmp_dir, docx_files[0])

        with open(output_path, 'rb') as f:
            docx_bytes = f.read()

        if len(docx_bytes) < 100 or docx_bytes[:2] != b'PK':
            return jsonify({"error": "Converted output is not a valid .docx file"}), 422

        log.info("Converted %s: %d bytes -> %d bytes", original_filename, len(doc_bytes), len(docx_bytes))
        docx_name = os.path.splitext(original_filename)[0] + '.docx'
        return Response(
            docx_bytes,
            content_type='application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{docx_name}"'}
        )

    except Exception as e:
        log.exception("Unexpected error converting %s", original_filename)
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
