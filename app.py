"""
EWAAD Converter — async .doc to .docx (simple sequential queue)
POST /convert    → {"job_id": "..."} immediately
GET  /result/<id> → 202 pending, 200 + bytes done, 422 error
One conversion at a time (soffice is single-instance).
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
SOFFICE_PATH = '/usr/bin/soffice'

# Job store: job_id -> {status, result_bytes, error, created_at, docx_name}
_jobs = {}
_jobs_lock = threading.Lock()

# Single worker queue — ensures only one soffice runs at a time
_work_queue = queue.Queue()


def _worker():
    """Background thread: process one conversion at a time."""
    while True:
        job_id, input_path, tmp_dir, original_filename = _work_queue.get()
        output_path = os.path.splitext(input_path)[0] + '.docx'
        try:
            log.info("[%s] Converting %s via soffice", job_id, original_filename)
            result = subprocess.run(
                [SOFFICE_PATH, '--headless', '--norestore', '--nolockcheck',
                 '--convert-to', 'docx', '--outdir', tmp_dir, input_path],
                capture_output=True, timeout=180,
                cwd=tmp_dir, env={**os.environ, 'HOME': tmp_dir}
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode('utf-8', errors='replace')[:300])

            if not os.path.exists(output_path):
                docx_files = [f for f in os.listdir(tmp_dir) if f.endswith('.docx')]
                if not docx_files:
                    raise RuntimeError("No .docx output produced")
                output_path = os.path.join(tmp_dir, docx_files[0])

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
            log.error("[%s] Failed: %s", job_id, e)
            with _jobs_lock:
                _jobs[job_id]['status'] = 'error'
                _jobs[job_id]['error'] = str(e)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _work_queue.task_done()


# Start single worker thread
_worker_thread = threading.Thread(target=_worker, daemon=True)
_worker_thread.start()


def _cleanup_old_jobs():
    cutoff = time.time() - 600
    with _jobs_lock:
        old = [jid for jid, j in _jobs.items() if j.get('created_at', 0) < cutoff]
        for jid in old:
            del _jobs[jid]


@app.route('/debug', methods=['GET'])
def debug():
    return jsonify({
        'soffice': os.path.exists(SOFFICE_PATH),
        'queue_size': _work_queue.qsize(),
        'active_jobs': len(_jobs),
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
    log.info("Queued job %s for %s (queue depth: %d)", job_id, original_filename, _work_queue.qsize())
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
