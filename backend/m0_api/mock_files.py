"""Byte-level mock file generators for the binary/text contract endpoints
(raster layer PNGs, §4.7 exports, §5 #22 static files) — stand-ins until
M1/M3/M4/M5/M6 produce real rasters and export bundles."""

from __future__ import annotations

import io
import zipfile

# A valid 1x1 transparent PNG, used for every raster layer overlay
# (contract §2.6 LayerRef, §5 #11) until a real one exists.
TRANSPARENT_PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000100febf19850000000049454e44ae426082"
)

_MINIMAL_PDF_HEAD = b"%PDF-1.4\n"
_MINIMAL_PDF_BODY = b"""1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj
trailer<</Root 1 0 R>>
%%EOF
"""


def mock_png() -> bytes:
    return TRANSPARENT_PNG_1X1


def mock_pdf(title: str) -> bytes:
    """A minimal but structurally valid single-page PDF, labelled as a mock."""
    comment = f"% {title} (mock export — no real report generator yet)\n".encode()
    return _MINIMAL_PDF_HEAD + comment + _MINIMAL_PDF_BODY


def text_report_pdf(text: str) -> bytes:
    """Small valid one-page PDF containing the supplied report text."""
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 40 740 Td ({safe}) Tj ET".encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(out)


def mock_kml(site_id: str, query_id: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{site_id} {query_id} (mock export — M6 not implemented yet)</name>
  </Document>
</kml>
""".encode()


def mock_shapefile_zip(site_id: str, query_id: str) -> bytes:
    """A real zip archive (readable by any zip tool), holding a placeholder
    note rather than an actual .shp/.shx/.dbf/.prj/.cpg bundle."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "README.txt",
            f"Mock shapefile bundle for site={site_id} query={query_id}.\n"
            "M6 has not generated real .shp/.shx/.dbf/.prj/.cpg files yet.\n",
        )
    return buf.getvalue()
