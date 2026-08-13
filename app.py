"""
EWAAD Converter — async .doc to .docx microservice
POST /convert    → {"job_id": "..."} (immediately, starts conversion in background)
GET  /result/<id> → 202 while pending, 200 + docx bytes when ready, 422 on error
"""
import os
import subprocess
import tempfile
import shutil
import logging
import threading
import uuid
import time

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB
SOFFICE_PATH = '/usr/bin/soffice'
PYTHON3 = '/usr/bin/python3'
CONVERT_UNO = '/app/convert_uno.py'

# In-memory job store: job_id -> {status, result_bytes, error, tmp_dir, created_at}
_jobs = {}
_jobs_lock = threading.Lock()

# Cleanup jobs older than 10 minutes
def _cleanup_old_jobs():
    cutoff = time.time() - 600
    with _jobs_lock:
        old = [jid for jid, j in _jobs.items() if j.get('created_at', 0) < cutoff]
        for jid in old:
            tmp = _jobs[jid].get('tmp_dir')
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            del _jobs[jid]


def _run_conversion(job_id, input_path, output_path, tmp_dir, original_filename):
    """Background thread: convert file and store result in _jobs."""
    try:
        use_uno = os.path.exists(CONVERT_UNO) and os.path.exists(PYTHON3)
        success = False

        if use_uno:
            log.info("[%s] Converting %s via UNO", job_id, original_filename)
            try:
                result = subprocess.run(
                    [PYTHON3, CONVERT_UNO, input_path, output_path],
                    capture_output=True, timeout=90
                )
                if result.returncode == 0 and os.path.exists(output_path):
                    success = True
                else:
                    stderr = result.stderr.decode('utf-8', errors='replace')[:300]
                    log.warning("[%s] UNO failed (rc=%d): %s — trying soffice",
                                job_id, result.returncode, stderr)
            except subprocess.TimeoutExpired:
                log.warning("[%s] UNO timed out — trying soffice", job_id)

        if not success:
            log.info("[%s] Converting %s via soffice", job_id, original_filename)
            try:
                result = subprocess.run(
                    [SOFFICE_PATH, '--headless', '--norestore', '--nolockcheck',
                     '--convert-to', 'docx', '--outdir', tmp_dir, input_path],
                    capture_output=True, timeout=180,
                    cwd=tmp_dir, env={**os.environ, 'HOME': tmp_dir}
                )
                if result.returncode == 0:
                    docx_files = [f for f in os.listdir(tmp_dir) if f.endswith('.docx')]
                    if docx_files:
                        output_path = os.path.join(tmp_dir, docx_files[0])
                        success = True
                    else:
                        raise RuntimeError("soffice exited 0 but no .docx found")
                else:
                    raise RuntimeError(result.stderr.decode('utf-8', errors='replace')[:300])
            except subprocess.TimeoutExpired:
                raise RuntimeError("Conversion timed out (180s)")

        if not os.path.exists(output_path):
            docx_files = [f for f in os.listdir(tmp_dir) if f.endswith('.docx')]
            if docx_files:
                output_path = os.path.join(tmp_dir, docx_files[0])
            else:
                raise RuntimeError("No .docx output produced")

        with open(output_path, 'rb') as f:
            docx_bytes = f.read()

        if len(docx_bytes) < 100 or docx_bytes[:2] != b'PK':
            raise RuntimeError("Output is not a valid .docx file")

        log.info("[%s] Done: %s -> %d bytes", job_id, original_filename, len(docx_bytes))
        with _jobs_lock:
            _jobs[job_id]['status'] = 'done'
            _jobs[job_id]['result_bytes'] = docx_bytes
            _jobs[job_id]['docx_name'] = os.path.splitext(original_filename)[0] + '.docx'

    except Exception as e:
        log.error("[%s] Conversion failed: %s", job_id, e)
        with _jobs_lock:
            _jobs[job_id]['status'] = 'error'
            _jobs[job_id]['error'] = str(e)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]['tmp_dir'] = None


@app.route('/debug', methods=['GET'])
def debug():
    import socket
    lo_up = False
    try:
        s = socket.create_connection(('localhost', 2002), timeout=1)
        s.close()
        lo_up = True
    except Exception:
        pass
    return jsonify({
        'soffice': os.path.exists(SOFFICE_PATH),
        'python3': os.path.exists(PYTHON3),
        'convert_uno': os.path.exists(CONVERT_UNO),
        'lo_listener_port_2002': lo_up,
        'active_jobs': len(_jobs),
    }), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "soffice": os.path.exists(SOFFICE_PATH)}), 200


@app.route('/convert', methods=['OPTIONS', 'POST'])
def convert():
    """Accept file, start async conversion, return job_id immediately."""
    if request.method == 'OPTIONS':
        return '', 204

    doc_bytes = request.get_data()
    if not doc_bytes:
        return jsonify({"error": "No file data received"}), 400
    if len(doc_bytes) > MAX_FILE_BYTES:
        return jsonify({"error": f"File too large ({len(doc_bytes)} bytes)"}), 413

    is_ole2 = doc_bytes[:4] == b'\xd0\xcf\x11\xe0'
    is_wordml = doc_bytes[:5] == b'<?xml' and (
        b'WordDocument' in doc_bytes[:2000] or
        b'w:wordDocument' in doc_bytes[:2000] or
        b'mso-application' in doc_bytes[:2000] or
        b'w:document' in doc_bytes[:500]
    )
    if not (is_ole2 or is_wordml):
        return jsonify({"error": "File does not appear to be a .doc file"}), 400

    original_filename = request.headers.get('X-Filename', 'input.doc')
    if not original_filename.lower().endswith('.doc'):
        original_filename += '.doc'

    tmp_dir = tempfile.mkdtemp(prefix="ewaad_conv_")
    input_path = os.path.join(tmp_dir, original_filename)
    with open(input_path, 'wb') as f:
        f.write(doc_bytes)
    output_path = os.path.splitext(input_path)[0] + '.docx'

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _cleanup_old_jobs()
        _jobs[job_id] = {
            'status': 'pending',
            'result_bytes': None,
            'error': None,
            'tmp_dir': tmp_dir,
            'created_at': time.time(),
            'docx_name': os.path.splitext(original_filename)[0] + '.docx',
        }

    t = threading.Thread(
        target=_run_conversion,
        args=(job_id, input_path, output_path, tmp_dir, original_filename),
        daemon=True
    )
    t.start()

    log.info("Queued job %s for %s", job_id, original_filename)
    return jsonify({"job_id": job_id}), 202


@app.route('/result/<job_id>', methods=['GET', 'OPTIONS'])
def result(job_id):
    """Poll for conversion result."""
    if request.method == 'OPTIONS':
        return '', 204

    with _jobs_lock:
        job = _jobs.get(job_id)

    if job is None:
        return jsonify({"error": "Job not found"}), 404

    if job['status'] == 'pending':
        return jsonify({"status": "pending"}), 202

    if job['status'] == 'error':
        with _jobs_lock:
            _jobs.pop(job_id, None)
        return jsonify({"error": job['error']}), 422

    # done
    docx_bytes = job['result_bytes']
    docx_name = job['docx_name']
    with _jobs_lock:
        _jobs.pop(job_id, None)

    return Response(
        docx_bytes,
        content_type='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{docx_name}"'}
    )


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
