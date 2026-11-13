"""PDF des feuilles d'usinage, généré à partir du DXF lui-même.

Une page A3 par présentation (layout) du DXF : ce que l'on voit dans le PDF est
exactement ce qu'AutoCAD afficherait (viewports, cotes, cartouche), donc on peut
contrôler les perçages et dimensions sans AutoCAD.
"""
from __future__ import annotations

import io
import re
from typing import Optional

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from ezdxf.addons.drawing import Frontend, RenderContext  # noqa: E402
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # noqa: E402


def dxf_to_pdf(dxf_bytes: bytes) -> Optional[bytes]:
    """Retourne un PDF multipage (1 page par feuille) ou None si rien à tracer."""
    doc = ezdxf.read(io.StringIO(dxf_bytes.decode("utf-8", errors="replace")))
    pages = []
    for name in doc.layout_names_in_taborder():
        if name == "Model":
            continue
        layout = doc.layouts.get(name)
        if not any(e.dxftype() == "VIEWPORT" for e in layout):
            continue
        pages.append(layout)
    if not pages:
        return None

    out = io.BytesIO()
    with PdfPages(out) as pdf:
        for layout in pages:
            w, h = layout.dxf.paper_width, layout.dxf.paper_height
            w, h = (w, h) if w and h else (420.0, 297.0)
            fig = plt.figure(figsize=(w / 25.4, h / 25.4))
            try:
                ax = fig.add_axes([0, 0, 1, 1])
                ax.set_axis_off()
                Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(layout, finalize=True)
                pdf.savefig(fig)
            finally:
                plt.close(fig)
    return out.getvalue()
