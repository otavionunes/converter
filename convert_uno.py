"""
convert_uno.py — Convert a .doc to .docx via a running LibreOffice UNO listener.
Usage: python3 convert_uno.py <input.doc> <output.docx>
Connects to soffice --accept listener on port 2002.
"""
import sys
import os

def convert(input_path, output_path):
    import uno
    from com.sun.star.beans import PropertyValue
    from com.sun.star.lang import DisposedException

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

    props = [make_prop("Hidden", True), make_prop("MacroExecutionMode", 4)]
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
    finally:
        doc.close(True)

    print(f"Converted: {input_path} -> {output_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: convert_uno.py <input> <output>", file=sys.stderr)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
