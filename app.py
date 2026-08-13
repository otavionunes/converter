"""
EWAAD Converter — async .doc to .docx via LibreOffice UNO listener
POST /convert    → {"job_id": "..."} immediately (202)
GET  /result/<id> → 202 pending, 200 + bytes done, 422 error

Uses multiprocessing.Process for conversion (no GIL blocking).
UNO listener is the fast path (~2-5s). No soffice fallback (avoids OOM).
"""
import os
import subprocess
import tempfile
import shutil
import logging
import multiprocessing
import uuid
import time
import json

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

# Must use spawn context to avoid fork issues with LibreOffice
_mp_ctx = multiprocessing.get_context('fork')

app = Flask(__name__)
CORS(app)
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB
PYTHON3 = '/usr/bin/python3'
CONVERT_UNO = '/app/convert_uno.py'

# Shared job state via Manager dict
_manager = _mp_ctx.Manager()
_jobs = _manager.dict()


def _convert_process(job_id, input_path, tmp_dir, filename, jobs_dict):
    """Runs in a separate process — no GIL, won't block Flask."""
    output_path = os.path.splitext(input_path)[0] + '.docx'
    try:
        result = subprocess.run(
            [PYTHON3, CONVERT_UNO, input_path, output_path],
            capture_output=True, timeout=55
        )
        stderr = result.stderr.decode('utf-8', errors='replace')
        stdout = result.stdout.decode('utf-8', errors='replace')

        if result.returncode != 0 or not os.path.exists(output_path):
            raise RuntimeError(f"UNO failed (rc={result.returncode}): {stderr[:300]}")

        with open(output_path, 'rb') as f:
            docx_bytes = f.read()

        if len(docx_bytes) < 100 or docx_bytes[:2] != b'PK':
            raise RuntimeError("Output is not a valid .docx")

        jobs_dict[job_id] = {
            'status': 'done',
            'result_bytes': docx_bytes,
            'docx_name': os.path.splitext(filename)[0] + '.docx',
            'error': None,
            'created_at': jobs_dict[job_id]['created_at'],
        }
    except Exception as e:
        jobs_dict[job_id] = {
            'status': 'error',
            'result_bytes': None,
            'docx_name': None,
            'error': str(e),
            'created_at': jobs_dict[job_id]['created_at'],
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _cleanup_old_jobs():
    cutoff = time.time() - 600
    stale = [k for k, v in _jobs.items() if v.get('created_at', 0) < cutoff]
    for k in stale:
        try:
            del _jobs[k]
        except Exception:
            pass


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
        'convert_uno': os.path.exists(CONVERT_UNO),
        'lo_listener_port_2002': lo_up,
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

    filename = request.headers.get('X-Filename', 'input.doc')
    if not filename.lower().endswith('.doc'):
        filename += '.doc'

    tmp_dir = tempfile.mkdtemp(prefix="ewaad_conv_")
    input_path = os.path.join(tmp_dir, filename)
    with open(input_path, 'wb') as f:
        f.write(doc_bytes)

    job_id = str(uuid.uuid4())
    _cleanup_old_jobs()
    _jobs[job_id] = {
        'status': 'pending',
        'result_bytes': None,
        'docx_name': os.path.splitext(filename)[0] + '.docx',
        'error': None,
        'created_at': time.time(),
    }

    p = _mp_ctx.Process(
        target=_convert_process,
        args=(job_id, input_path, tmp_dir, filename, _jobs),
        daemon=True
    )
    p.start()
    log.info("Started process pid=%d job=%s file=%s", p.pid, job_id, filename)
    return jsonify({"job_id": job_id}), 202


@app.route('/result/<job_id>', methods=['GET', 'OPTIONS'])
def result(job_id):
    if request.method == 'OPTIONS':
        return '', 204

    job = _jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    if job['status'] == 'pending':
        return jsonify({"status": "pending"}), 202
    if job['status'] == 'error':
        err = job['error']
        try:
            del _jobs[job_id]
        except Exception:
            pass
        return jsonify({"error": err}), 422

    docx_bytes = job['result_bytes']
    docx_name = job['docx_name']
    try:
        del _jobs[job_id]
    except Exception:
        pass

    return Response(
        docx_bytes,
        content_type='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{docx_name}"'}
    )


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
