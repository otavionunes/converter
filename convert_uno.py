#!/usr/bin/env python3
"""
convert_uno.py — Convert a .doc to .docx via a running LibreOffice UNO listener.
Usage: python3 convert_uno.py <input.doc> <output.docx>
Must be run with a Python that has the 'uno' module (LibreOffice's Python or
system python3 with python3-uno installed).
"""
import sys
import os


def convert(input_path, output_path):
    try:
        import uno
    except ImportError:
        print("ERROR: 'uno' module not found. Install python3-uno.", file=sys.stderr)
        sys.exit(4)

    from com.sun.star.beans import PropertyValue

    localContext = uno.getComponentContext()
    resolver = localContext.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", localContext)

    try:
        ctx = resolver.resolve(
            "uno:socket,host=localhost,port=2002,tcpNoDelay=1;"
            "urp;StarOffice.ComponentContext"
        )
    except Exception as e:
        print(f"Cannot connect to LO listener: {e}", file=sys.stderr)
        sys.exit(2)

    smgr = ctx.ServiceManager
    desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)

    input_url = uno.systemPathToFileUrl(os.path.abspath(input_path))
    output_url = uno.systemPathToFileUrl(os.path.abspath(output_path))

    def make_prop(name, value):
        p = PropertyValue()
        p.Name = name
        p.Value = value
        return p

    # Detect format to set correct import filter
    with open(input_path, 'rb') as fh:
        header = fh.read(32)
    is_wordml = header[:5] == b'<?xml'

    load_filter = "MS Word 2003 XML" if is_wordml else "MS Word 97"
    props = [
        make_prop("Hidden", True),
        make_prop("MacroExecutionMode", 4),
        make_prop("FilterName", load_filter),
    ]
    doc = desktop.loadComponentFromURL(input_url, "_blank", 0, props)

    if doc is None:
        print("LO could not open document", file=sys.stderr)
        sys.exit(3)

    try:
        filter_props = [
            make_prop("FilterName", "MS Word 2007 XML"),
            make_prop("Overwrite", True),
        ]
        doc.storeToURL(output_url, filter_props)
        print(f"Converted: {input_path} -> {output_path}", file=sys.stderr)
    finally:
        doc.close(True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: convert_uno.py <input> <output>", file=sys.stderr)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
