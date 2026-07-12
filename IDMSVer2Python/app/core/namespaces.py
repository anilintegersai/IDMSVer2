"""OOXML XML namespaces used across the word processing layer."""

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
CUSTOM_XML_NS = "http://yourcompany.com/insert-metadata"

NSMAP = {"w": W_NS, "r": R_NS, "wp": WP_NS, "a": A_NS, "pic": PIC_NS}


def w_tag(local: str) -> str:
    return f"{{{W_NS}}}{local}"


def r_tag(local: str) -> str:
    return f"{{{R_NS}}}{local}"
