"""
EWAAD Converter — async .doc to .docx via LibreOffice UNO listener
POST /convert    → {"job_id": "..."} immediately (202)
GET  /result/<id> → 202 pending, 200 + bytes done, 422 error
Uses soffice --accept UNO listener (one warm process, ~2-5s per conversion).
No soffice fallback — avoids OOM from two concurrent LibreOffice processes.
"""
import os
import subprocess
import tempfile
import shutil
import logging
import threading
import queue
import uuid
import time

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB
SOFFICE = '/usr/bin/soffice'
PYTHON3 = '/usr/bin/python3'
CONVERT_UNO = '/app/convert_uno.py'

# Job store
_jobs = {}
_jobs_lock = threading.Lock()
_work_queue = queue.Queue()


def _cleanup_old_jobs():
    cutoff = time.time() - 600
    with _jobs_lock:
        stale = [k for k, v in _jobs.items() if v.get('created_at', 0) < cutoff]
        for k in stale:
            del _jobs[k]


def _worker():
    """Single background thread — one conversion at a time via UNO."""
    while True:
        job_id, input_path, tmp_dir, filename = _work_queue.get()
        output_path = os.path.splitext(input_path)[0] + '.docx'
        try:
            log.info("[%s] Converting %s via UNO", job_id, filename)
            result = subprocess.run(
                [PYTHON3, CONVERT_UNO, input_path, output_path],
                capture_output=True, timeout=55
            )
            stdout = result.stdout.decode('utf-8', errors='replace')
            stderr = result.stderr.decode('utf-8', errors='replace')
            log.info("[%s] UNO rc=%d stdout=%s stderr=%s", job_id, result.returncode, stdout[:200], stderr[:200])

            if result.returncode != 0 or not os.path.exists(output_path):
                raise RuntimeError(f"UNO conversion failed (rc={result.returncode}): {stderr[:300]}")

            with open(output_path, 'rb') as f:
                docx_bytes = f.read()

            if len(docx_bytes) < 100 or docx_bytes[:2] != b'PK':
                raise RuntimeError("Output is not a valid .docx file")

            log.info("[%s] Done: %s -> %d bytes", job_id, filename, len(docx_bytes))
            with _jobs_lock:
                _jobs[job_id]['status'] = 'done'
                _jobs[job_id]['result_bytes'] = docx_bytes
                _jobs[job_id]['docx_name'] = os.path.splitext(filename)[0] + '.docx'

        except Exception as e:
            log.error("[%s] Failed: %s", job_id, e)
            with _jobs_lock:
                _jobs[job_id]['status'] = 'error'
                _jobs[job_id]['error'] = str(e)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _work_queue.task_done()


_worker_thread = threading.Thread(target=_worker, daemon=True)
_worker_thread.start()


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
        'soffice': os.path.exists(SOFFICE),
        'convert_uno': os.path.exists(CONVERT_UNO),
        'lo_listener_port_2002': lo_up,
        'queue_size': _work_queue.qsize(),
        'active_jobs': len(_jobs),
    }), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200


@app.route('/convert', methods=['OPTIONS', 'POST'])
def convert():
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

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _cleanup_old_jobs()
        _jobs[job_id] = {
            'status': 'pending',
            'result_bytes': None,
            'error': None,
            'created_at': time.time(),
            'docx_name': os.path.splitext(original_filename)[0] + '.docx',
        }

    _work_queue.put((job_id, input_path, tmp_dir, original_filename))
    log.info("Queued job %s for %s (queue=%d)", job_id, original_filename, _work_queue.qsize())
    return jsonify({"job_id": job_id}), 202


@app.route('/result/<job_id>', methods=['GET', 'OPTIONS'])
def result(job_id):
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
