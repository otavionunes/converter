"""
EWAAD Converter — .doc to .docx microservice (Docker version)
Fast path: python3 convert_uno.py via running LibreOffice UNO listener (~2-5s).
Fallback: soffice --headless cold-start (~60s, may hit CF router timeout).
"""
import os
import subprocess
import tempfile
import shutil
import logging

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB

SOFFICE_PATH = '/usr/bin/soffice'
# Use system python3 (has python3-uno) not venv python
PYTHON3 = '/usr/bin/python3'
CONVERT_UNO = '/app/convert_uno.py'

log.info("soffice: %s", SOFFICE_PATH)
log.info("python3: %s, convert_uno: %s", PYTHON3, CONVERT_UNO)


def _convert_via_uno(input_path, output_path):
    """Fast: connect to running LO listener via UNO (~2-5s)."""
    cmd = [PYTHON3, CONVERT_UNO, input_path, output_path]
    return subprocess.run(cmd, capture_output=True, timeout=55)


def _convert_via_soffice(input_path, outdir):
    """Fallback: cold-start soffice (~60s)."""
    cmd = [
        SOFFICE_PATH, '--headless', '--norestore', '--nolockcheck',
        '--convert-to', 'docx', '--outdir', outdir, input_path,
    ]
    return subprocess.run(
        cmd, capture_output=True, timeout=170,
        cwd=outdir, env={**os.environ, 'HOME': outdir}
    )


@app.route('/debug', methods=['GET'])
def debug():
    import socket
    lo_port_open = False
    try:
        s = socket.create_connection(('localhost', 2002), timeout=1)
        s.close()
        lo_port_open = True
    except Exception:
        pass
    return jsonify({
        'soffice': os.path.exists(SOFFICE_PATH),
        'python3': os.path.exists(PYTHON3),
        'convert_uno': os.path.exists(CONVERT_UNO),
        'lo_listener_port_2002': lo_port_open,
        'PATH': os.environ.get('PATH', ''),
    }), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "soffice": os.path.exists(SOFFICE_PATH)}), 200


@app.route('/convert', methods=['OPTIONS', 'POST'])
def convert():
    if request.method == 'OPTIONS':
        return '', 204

    doc_bytes = request.get_data()
    if not doc_bytes:
        return jsonify({"error": "No file data received"}), 400
    if len(doc_bytes) > MAX_FILE_BYTES:
        return jsonify({"error": f"File too large ({len(doc_bytes)} bytes, max {MAX_FILE_BYTES})"}), 413

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
        use_uno = os.path.exists(CONVERT_UNO) and os.path.exists(PYTHON3)

        if use_uno:
            log.info("Converting %s via UNO listener", original_filename)
            try:
                result = _convert_via_uno(input_path, output_path)
                if result.returncode != 0 or not os.path.exists(output_path):
                    stderr = result.stderr.decode('utf-8', errors='replace')[:300]
                    log.warning("UNO failed (rc=%d): %s — falling back to soffice",
                                result.returncode, stderr)
                    use_uno = False
            except subprocess.TimeoutExpired:
                log.warning("UNO conversion timed out — falling back to soffice")
                use_uno = False

        if not use_uno:
            log.info("Converting %s via soffice (cold start)", original_filename)
            try:
                result = _convert_via_soffice(input_path, tmp_dir)
                if result.returncode != 0:
                    stderr = result.stderr.decode('utf-8', errors='replace')[:500]
                    log.error("soffice failed for %s: %s", original_filename, stderr)
                    return jsonify({"error": f"Conversion failed: {stderr}"}), 422
            except subprocess.TimeoutExpired:
                return jsonify({"error": "Conversion timed out"}), 422

        # Find output
        if not os.path.exists(output_path):
            docx_files = [f for f in os.listdir(tmp_dir) if f.endswith('.docx')]
            if not docx_files:
                return jsonify({"error": "LibreOffice produced no .docx output"}), 422
            output_path = os.path.join(tmp_dir, docx_files[0])

        with open(output_path, 'rb') as f:
            docx_bytes = f.read()

        if len(docx_bytes) < 100 or docx_bytes[:2] != b'PK':
            return jsonify({"error": "Converted output is not a valid .docx file"}), 422

        log.info("Converted %s: %d -> %d bytes", original_filename, len(doc_bytes), len(docx_bytes))
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
