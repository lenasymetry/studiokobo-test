"""PDF des feuilles d'usinage, généré à partir du DXF lui-même.

Une page A3 par présentation (layout) du DXF : ce que l'on voit dans le PDF est
exactement ce qu'AutoCAD afficherait (viewports, cotes, cartouche), donc on peut
contrôler les perçages et dimensions sans AutoCAD. Moteur : PyMuPDF (vrais
textes, épaisseurs de trait fines comme sur le DXF).
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import ezdxf
import pymupdf
from ezdxf.addons.drawing import Frontend, RenderContext, layout
from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend


def _ensure_fonts() -> None:
    """Serveur sans police système (Streamlit Cloud) : ezdxf remplace alors chaque
    texte par un rectangle vide. On lui donne les polices fournies avec matplotlib."""
    import matplotlib
    from ezdxf.fonts import fonts

    fm = fonts.font_manager
    if fm.has_font("DejaVuSans.ttf") or fm.has_font("DejaVu Sans"):
        return
    fm.scan_folder(Path(matplotlib.get_data_path()) / "fonts" / "ttf")
    fm.fallback_font_name = lambda: "DejaVuSans.ttf"


def dxf_to_pdf(dxf_bytes: bytes) -> Optional[bytes]:
    """Retourne un PDF multipage (1 page par feuille) ou None si rien à tracer."""
    _ensure_fonts()
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
