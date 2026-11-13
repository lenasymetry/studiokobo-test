"""PDF des feuilles d'usinage, généré à partir du DXF lui-même.

Une page A3 par présentation (layout) du DXF : ce que l'on voit dans le PDF est
exactement ce qu'AutoCAD afficherait (viewports, cotes, cartouche), donc on peut
contrôler les perçages et dimensions sans AutoCAD. Moteur : PyMuPDF (vrais
textes, épaisseurs de trait fines comme sur le DXF).
"""
from __future__ import annotations

import io
from typing import Optional

import ezdxf
import pymupdf
from ezdxf.addons.drawing import Frontend, RenderContext, layout
from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend


def dxf_to_pdf(dxf_bytes: bytes) -> Optional[bytes]:
    """Retourne un PDF multipage (1 page par feuille) ou None si rien à tracer."""
    doc = ezdxf.read(io.StringIO(dxf_bytes.decode("utf-8", errors="replace")))
    ctx = RenderContext(doc)
    out = pymupdf.open()
    for name in doc.layout_names_in_taborder():
        if name == "Model":
            continue
        lay = doc.layouts.get(name)
        if not any(e.dxftype() == "VIEWPORT" for e in lay):
            continue
        backend = PyMuPdfBackend()
        Frontend(ctx, backend).draw_layout(lay)
        page = layout.Page(420, 297, layout.Units.mm, margins=layout.Margins.all(0))
        data = backend.get_pdf_bytes(page, settings=layout.Settings(fit_page=True, scale=1))
        with pymupdf.open("pdf", data) as part:
            out.insert_pdf(part)
    if out.page_count == 0:
        return None
    return out.tobytes(garbage=3, deflate=True)
