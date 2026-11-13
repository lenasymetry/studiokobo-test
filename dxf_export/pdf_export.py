"""PDF des feuilles d'usinage, généré à partir du DXF lui-même.

Une page A3 par présentation (layout) du DXF : ce que l'on voit dans le PDF est
exactement ce qu'AutoCAD afficherait (viewports, cotes, cartouche), donc on peut
contrôler les perçages et dimensions sans AutoCAD. Moteur : PyMuPDF (traits
fins comme sur le DXF).

Le moteur dessine les textes comme des formes : on y superpose donc une couche
de VRAIS textes invisibles (sélectionnables, recherchables), à la bonne place.
C'est ce que lit « KOBO Vérif » pour contrôler les feuilles.
"""
from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import ezdxf
import pymupdf
from ezdxf.addons.drawing import Frontend, RenderContext, layout
from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend

PAPER_W, PAPER_H, MARGIN = 420.0, 297.0, 10.0   # = dxf_export.machining_sheets
PT_PER_MM = 72.0 / 25.4

# (texte, centre x, centre y, hauteur, rotation °) dans le repère de l'entité.
_TextItem = Tuple[str, float, float, float, float]


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


def _centre(px: float, py: float, w: float, h: float, rot: float,
            h_align: int, v_align: int) -> Tuple[float, float]:
    """Centre du texte à partir de son point d'ancrage.
    h_align : 0 gauche, 1 centre, 2 droite ; v_align : 0 haut, 1 milieu, 2 bas."""
    a = math.radians(rot)
    dx, dy = math.cos(a), math.sin(a)          # sens du texte
    nx, ny = -dy, dx                           # normale (vers le haut du texte)
    along = (0.5 - 0.5 * h_align) * w          # 0 -> +w/2, 1 -> 0, 2 -> -w/2
    up = 0.5 * h * (v_align - 1)               # haut -> -h/2, milieu -> 0, bas -> +h/2
    return px + dx * along + nx * up, py + dy * along + ny * up


def _clean(s: str) -> str:
    """Codes spéciaux DXF -> caractères (%%c = Ø, %%d = °, %%p = ±)."""
    for code, ch in (("%%c", "Ø"), ("%%C", "Ø"), ("%%d", "°"), ("%%D", "°"), ("%%p", "±"), ("%%P", "±")):
        s = s.replace(code, ch)
    return s


def _entity_texts(e) -> Iterator[_TextItem]:
    """Textes affichés par une entité (TEXT, MTEXT, ou cote via son bloc)."""
    t = e.dxftype()
    if t == "TEXT":
        s = _clean((e.dxf.text or "").strip())
        if not s:
            return
        h = float(e.dxf.height)
        w = 0.6 * h * len(s) * float(e.dxf.get("width", 1.0) or 1.0)
        rot = float(e.dxf.get("rotation", 0.0) or 0.0)
        halign = int(e.dxf.get("halign", 0) or 0)
        valign = int(e.dxf.get("valign", 0) or 0)
        if halign or valign:
            p = e.dxf.align_point
        else:
            p = e.dxf.insert
        ha = {0: 0, 1: 1, 2: 2}.get(halign, 1)
        va = {0: 2, 1: 2, 2: 1, 3: 0}.get(valign, 2)   # ligne de base ~ bas
        cx, cy = _centre(p.x, p.y, w, h, rot, ha, va)
        yield s, cx, cy, h, rot
    elif t == "MTEXT":
        s = _clean(e.plain_text().replace("\n", " ").strip())
        if not s:
            return
        h = float(e.dxf.char_height)
        w = 0.6 * h * len(s)
        rot = float(e.dxf.get("rotation", 0.0) or 0.0)
        if e.dxf.hasattr("text_direction"):
            d = e.dxf.text_direction
            rot = math.degrees(math.atan2(d.y, d.x))
        ap = int(e.dxf.get("attachment_point", 1) or 1)
        ha, va = (ap - 1) % 3, (ap - 1) // 3
        p = e.dxf.insert
        cx, cy = _centre(p.x, p.y, w, h, rot, ha, va)
        yield s, cx, cy, h, rot
    elif t == "DIMENSION":
        try:
            for v in e.virtual_entities():
                if v.dxftype() in ("TEXT", "MTEXT"):
                    yield from _entity_texts(v)
        except Exception:
            return


def _insert_invisible(pg, s: str, cx_pt: float, cy_pt: float, size_pt: float, rot: float) -> None:
    """Texte invisible centré en (cx_pt, cy_pt) ; page en pt, origine en haut."""
    r = int(round(rot / 90.0)) % 4 * 90            # PyMuPDF : multiples de 90°
    w = pymupdf.get_text_length(s, fontname="helv", fontsize=size_pt)
    # sens du texte à l'écran (y vers le bas) pour la rotation r
    dx, dy = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}[r]
    nx, ny = dy, -dx                               # côté « bas » de la ligne
    x = cx_pt - dx * w / 2 + nx * size_pt * 0.35 * -1
    y = cy_pt - dy * w / 2 + ny * size_pt * 0.35 * -1
    pg.insert_text((x, y), s, fontname="helv", fontsize=size_pt, rotate=r, render_mode=3)


def _add_text_layer(pg, lay, doc) -> int:
    """Superpose les textes du layout (cartouche + vue du viewport) à la page.
    Le cadre de la feuille remplit la largeur de la page : échelle et décalage
    s'en déduisent (mm papier -> pt)."""
    frame_w_mm = PAPER_W - 2 * MARGIN
    frame_h_mm = PAPER_H - 2 * MARGIN
    s = pg.rect.width / frame_w_mm
    y_top = (pg.rect.height - frame_h_mm * s) / 2.0     # haut du cadre, en pt

    def to_pt(x_mm: float, y_mm: float) -> Tuple[float, float]:
        return (x_mm - MARGIN) * s, y_top + (PAPER_H - MARGIN - y_mm) * s

    n = 0
    # 1) cartouche : textes directement en coordonnées papier
    for e in lay:
        for txt, cx, cy, h, rot in _entity_texts(e):
            px, py = to_pt(cx, cy)
            _insert_invisible(pg, txt, px, py, h * s, rot)
            n += 1

    # 2) fenêtre(s) sur le modèle : modèle -> papier -> pt
    msp = doc.modelspace()
    for vp in (e for e in lay if e.dxftype() == "VIEWPORT"):
        if int(vp.dxf.get("id", 0) or 0) <= 1 or not vp.dxf.get("view_height"):
            continue
        k = float(vp.dxf.height) / float(vp.dxf.view_height)    # papier / modèle
        vcx, vcy = vp.dxf.view_center_point.x, vp.dxf.view_center_point.y
        pcx, pcy = vp.dxf.center.x, vp.dxf.center.y
        half_w, half_h = float(vp.dxf.width) / 2.0, float(vp.dxf.height) / 2.0
        mx0, mx1 = vcx - half_w / k, vcx + half_w / k
        my0, my1 = vcy - half_h / k, vcy + half_h / k
        for e in msp:
            if e.dxftype() not in ("TEXT", "MTEXT", "DIMENSION"):
                continue
            # présélection : point de repère de l'entité dans la zone visible
            if e.dxftype() == "DIMENSION":
                ref = e.dxf.get("text_midpoint") or e.dxf.get("defpoint")
            else:
                ref = e.dxf.insert
            if ref is None or not (mx0 - 50 <= ref.x <= mx1 + 50 and my0 - 50 <= ref.y <= my1 + 50):
                continue
            for txt, cx, cy, h, rot in _entity_texts(e):
                ux, uy = pcx + (cx - vcx) * k, pcy + (cy - vcy) * k
                if abs(ux - pcx) > half_w or abs(uy - pcy) > half_h:
                    continue
                px, py = to_pt(ux, uy)
                _insert_invisible(pg, txt, px, py, h * k * s, rot)
                n += 1
    return n


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
            pg = part[0]
            try:
                _add_text_layer(pg, lay, doc)
            except Exception as exc:       # le PDF reste utilisable sans la couche texte
                print(f"[PDF] couche texte indisponible ({name}) : {exc}")
            out.insert_pdf(part)
    if out.page_count == 0:
        return None
    return out.tobytes(garbage=3, deflate=True)
