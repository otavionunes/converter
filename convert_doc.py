#!/usr/bin/env python3
"""
convert_doc.py — Convert .doc to .docx.
- WordML/Word2003 XML: uses convert_wordml.py (Python-only, fast ~1s)
- OLE2 binary .doc: uses soffice --headless (slow ~60s)
"""
import sys
import os
import subprocess
import glob


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def convert_wordml(input_path, output_path):
    """Convert WordML XML .doc via Python (fast, no LibreOffice)."""
    wordml_script = os.path.join(SCRIPT_DIR, 'convert_wordml.py')
    result = subprocess.run(
        [sys.executable, wordml_script, input_path, output_path],
        capture_output=True, timeout=30
    )
    print(result.stderr.decode('utf-8', errors='replace'), file=sys.stderr)
    if result.returncode != 0 or not os.path.exists(output_path):
        raise RuntimeError(f"WordML conversion failed (rc={result.returncode})")


def convert_ole2(input_path, output_dir):
    """Convert OLE2 binary .doc via soffice --headless."""
    soffice = '/usr/bin/soffice'
    profile_dir = os.path.join(output_dir, 'lo_profile')
    os.makedirs(profile_dir, exist_ok=True)

    env = {
        'HOME': output_dir,
        'PATH': '/usr/bin:/usr/local/bin:/bin',
        'TMPDIR': output_dir,
    }
    result = subprocess.run(
        [soffice,
         f'-env:UserInstallation=file://{profile_dir}',
         '--headless', '--norestore', '--nolockcheck', '--nocrashreport',
         '--convert-to', 'docx', '--outdir', output_dir, input_path],
        capture_output=True, timeout=150, cwd=output_dir, env=env
    )
    print(result.stdout.decode('utf-8', errors='replace'), file=sys.stderr)
    print(result.stderr.decode('utf-8', errors='replace'), file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"soffice failed rc={result.returncode}: {result.stderr.decode()[:200]}")

    base = os.path.splitext(os.path.basename(input_path))[0]
    expected = os.path.join(output_dir, base + '.docx')
    if os.path.exists(expected):
        os.rename(expected, os.path.join(output_dir, 'output.docx'))
        return
    docx_files = glob.glob(os.path.join(output_dir, '*.docx'))
    if docx_files:
        os.rename(docx_files[0], os.path.join(output_dir, 'output.docx'))
        return
    raise RuntimeError("soffice produced no .docx output")


def convert(input_path, output_dir):
    with open(input_path, 'rb') as f:
        header = f.read(8)

    is_ole2 = header[:4] == b'\xd0\xcf\x11\xe0'
    is_wordml = header[:5] == b'<?xml'

    if not (is_ole2 or is_wordml):
        print(f"ERROR: unrecognized .doc format: {header[:8].hex()}", file=sys.stderr)
        sys.exit(2)

    output_path = os.path.join(output_dir, 'output.docx')

    if is_wordml:
        print(f"Converting WordML: {os.path.basename(input_path)}", file=sys.stderr)
        convert_wordml(input_path, output_path)
    else:
        print(f"Converting OLE2 via soffice: {os.path.basename(input_path)}", file=sys.stderr)
        convert_ole2(input_path, output_dir)

    size = os.path.getsize(output_path)
    print(f"Done: {os.path.basename(input_path)} -> output.docx ({size:,} bytes)", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: convert_doc.py <input.doc> <output_dir>", file=sys.stderr)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
