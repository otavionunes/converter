#!/usr/bin/env python3
"""
convert_doc.py — Convert a .doc to .docx using soffice --headless.
Usage: python3 convert_doc.py <input.doc> <output_dir>
Writes output.docx into output_dir.
"""
import sys
import os
import subprocess
import glob

def convert(input_path, output_dir):
    soffice = '/usr/bin/soffice'
    if not os.path.exists(soffice):
        print(f"ERROR: soffice not found at {soffice}", file=sys.stderr)
        sys.exit(1)

    # Ensure soffice has a writable HOME and user profile dir
    profile_dir = os.path.join(output_dir, 'lo_profile')
    os.makedirs(profile_dir, exist_ok=True)

    # For WordML XML files, ensure correct encoding declaration
    with open(input_path, 'rb') as fh:
        raw = fh.read(32)
    is_wordml = raw[:5] == b'<?xml'

    # If WordML and no encoding specified, ensure UTF-8 declaration
    actual_input = input_path
    if is_wordml:
        with open(input_path, 'rb') as fh:
            content = fh.read()
        # Ensure encoding="UTF-8" in XML declaration if missing
        if b'encoding=' not in content[:100]:
            content = content.replace(b'<?xml version="1.0"?>', b'<?xml version="1.0" encoding="UTF-8"?>', 1)
            fixed_path = input_path + '.fixed.doc'
            with open(fixed_path, 'wb') as fh:
                fh.write(content)
            actual_input = fixed_path

    env = {
        'HOME': output_dir,
        'PATH': '/usr/bin:/usr/local/bin:/bin',
        'TMPDIR': output_dir,
    }

    result = subprocess.run(
        [soffice,
         f'-env:UserInstallation=file://{profile_dir}',
         '--headless', '--norestore', '--nolockcheck', '--nocrashreport',
         '--convert-to', 'docx', '--outdir', output_dir, actual_input],
        capture_output=True,
        timeout=150,
        cwd=output_dir,
        env=env
    )

    print(result.stdout.decode('utf-8', errors='replace'), file=sys.stderr)
    print(result.stderr.decode('utf-8', errors='replace'), file=sys.stderr)

    if result.returncode != 0:
        print(f"soffice failed with rc={result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)

    # Find output file
    base = os.path.splitext(os.path.basename(input_path))[0]
    expected = os.path.join(output_dir, base + '.docx')
    if os.path.exists(expected):
        # Rename to output.docx
        os.rename(expected, os.path.join(output_dir, 'output.docx'))
        print(f"Done: {input_path} -> output.docx", file=sys.stderr)
        sys.exit(0)

    # Search for any .docx
    docx_files = glob.glob(os.path.join(output_dir, '*.docx'))
    if docx_files:
        os.rename(docx_files[0], os.path.join(output_dir, 'output.docx'))
        print(f"Done: {input_path} -> output.docx", file=sys.stderr)
        sys.exit(0)

    print("ERROR: no .docx output produced", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: convert_doc.py <input.doc> <output_dir>", file=sys.stderr)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
