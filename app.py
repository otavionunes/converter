"""
EWAAD Converter — async .doc to .docx via LibreOffice UNO listener
POST /convert    → {"job_id": "..."} immediately (202)
GET  /result/<id> → 202 pending, 200 + bytes done, 422 error

Job state stored as files in /tmp/ewaad_jobs/<id>/{status,output.docx,error}.
Conversion runs in subprocess — no GIL, /convert always returns in <1s.
"""
import os
import subprocess
import tempfile
import shutil
import logging
import uuid
import time

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB
PYTHON3 = '/usr/bin/python3'
CONVERT_UNO = '/app/convert_uno.py'
JOBS_DIR = '/tmp/ewaad_jobs'
os.makedirs(JOBS_DIR, exist_ok=True)


def _job_dir(job_id):
    return os.path.join(JOBS_DIR, job_id)


def _start_conversion(job_id, input_path, filename):
    """Launch conversion as detached subprocess — returns immediately."""
    jdir = _job_dir(job_id)
    output_path = os.path.join(jdir, 'output.docx')

    # Shell script that runs conversion and writes status file
    script = f"""#!/bin/bash
{PYTHON3} {CONVERT_UNO} '{input_path}' '{output_path}' > '{jdir}/stdout.txt' 2> '{jdir}/stderr.txt'
rc=$?
if [ $rc -eq 0 ] && [ -f '{output_path}' ]; then
    echo "done" > '{jdir}/status'
else
    cat '{jdir}/stderr.txt' > '{jdir}/error'
    echo "error" > '{jdir}/status'
fi
rm -f '{input_path}'
"""
    script_path = os.path.join(jdir, 'run.sh')
    with open(script_path, 'w') as f:
        f.write(script)
    os.chmod(script_path, 0o755)

    # Launch detached — does NOT block Flask
    subprocess.Popen(
        ['/bin/bash', script_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True
    )


def _cleanup_old_jobs():
    """Remove job dirs older than 10 minutes."""
    try:
        cutoff = time.time() - 600
        for jid in os.listdir(JOBS_DIR):
            jdir = os.path.join(JOBS_DIR, jid)
            if os.path.isdir(jdir) and os.path.getmtime(jdir) < cutoff:
                shutil.rmtree(jdir, ignore_errors=True)
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
    try:
        active = len(os.listdir(JOBS_DIR))
    except Exception:
        active = -1
    return jsonify({
        'convert_uno': os.path.exists(CONVERT_UNO),
        'lo_listener_port_2002': lo_up,
        'active_jobs': active,
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

    job_id = str(uuid.uuid4())
    jdir = _job_dir(job_id)
    os.makedirs(jdir, exist_ok=True)

    input_path = os.path.join(jdir, filename)
    with open(input_path, 'wb') as f:
        f.write(doc_bytes)

    with open(os.path.join(jdir, 'status'), 'w') as f:
        f.write('pending')
    with open(os.path.join(jdir, 'filename'), 'w') as f:
        f.write(filename)

    _cleanup_old_jobs()
    _start_conversion(job_id, input_path, filename)

    log.info("Queued job %s for %s", job_id, filename)
    return jsonify({"job_id": job_id}), 202


@app.route('/result/<job_id>', methods=['GET', 'OPTIONS'])
def result(job_id):
    if request.method == 'OPTIONS':
        return '', 204

    # Sanitize job_id
    if not job_id or '/' in job_id or '..' in job_id:
        return jsonify({"error": "Invalid job id"}), 400

    jdir = _job_dir(job_id)
    if not os.path.isdir(jdir):
        return jsonify({"error": "Job not found"}), 404

    status_file = os.path.join(jdir, 'status')
    if not os.path.exists(status_file):
        return jsonify({"status": "pending"}), 202

    with open(status_file) as f:
        status = f.read().strip()

    if status == 'pending':
        return jsonify({"status": "pending"}), 202

    if status == 'error':
        error_file = os.path.join(jdir, 'error')
        err = open(error_file).read()[:300] if os.path.exists(error_file) else "Unknown error"
        shutil.rmtree(jdir, ignore_errors=True)
        return jsonify({"error": err}), 422

    # done
    output_path = os.path.join(jdir, 'output.docx')
    if not os.path.exists(output_path):
        shutil.rmtree(jdir, ignore_errors=True)
        return jsonify({"error": "Output file missing"}), 422

    with open(output_path, 'rb') as f:
        docx_bytes = f.read()

    filename_file = os.path.join(jdir, 'filename')
    orig = open(filename_file).read().strip() if os.path.exists(filename_file) else 'output.doc'
    docx_name = os.path.splitext(orig)[0] + '.docx'

    shutil.rmtree(jdir, ignore_errors=True)

    return Response(
        docx_bytes,
        content_type='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{docx_name}"'}
    )


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
