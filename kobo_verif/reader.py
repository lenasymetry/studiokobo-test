"""Lecture d'un PDF de feuilles d'usinage produit par KOBO Studio.

Le PDF contient le dessin vectoriel (rectangles, cercles = trous, triangles) et
une couche de textes (cotes, repères de perçage, cartouche). On en tire, pour
chaque page, des objets exprimés en MILLIMÈTRES RÉELS de la pièce : l'échelle
est retrouvée en comparant le rectangle de la pièce à sa cote hors-tout.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pymupdf

TITLE_LABELS = ("DATE", "PROJET", "CORPS DE MEUBLE", "DESIGNATION", "ECHELLE", "FEUILLET", "QUANTITE")


@dataclass
class Text:
    s: str
    x: float          # centre, pt
    y: float
    horizontal: bool  # sens de lecture
    value: Optional[float] = None


@dataclass
class Circle:
    x: float          # centre, pt
    y: float
    d: float          # diamètre, pt


@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    def contains(self, x: float, y: float, pad: float = 0.0) -> bool:
        return self.x0 - pad <= x <= self.x1 + pad and self.y0 - pad <= y <= self.y1 + pad


@dataclass
class Callout:
    d: float
    depth: Optional[float]
    count: int
    raw: str


@dataclass
class SheetData:
    page: int
    title: Dict[str, str] = field(default_factory=dict)
    texts: List[Text] = field(default_factory=list)
    circles: List[Circle] = field(default_factory=list)
    rects: List[Rect] = field(default_factory=list)
    triangles: List[Tuple[Tuple[float, float], ...]] = field(default_factory=list)   # 3 sommets, pt
    callouts: List[Callout] = field(default_factory=list)
    # --- déduit ---
    main: Optional[Rect] = None            # face de la pièce
    strips: List[Rect] = field(default_factory=list)   # vues de tranche
    L_mm: Optional[float] = None
    W_mm: Optional[float] = None
    T_mm: Optional[float] = None           # épaisseur lue sur le dessin
    scale: Optional[float] = None          # pt par mm
    problems: List[str] = field(default_factory=list)

    @property
    def designation(self) -> str:
        return self.title.get("DESIGNATION", "")

    @property
    def caisson(self) -> Optional[int]:
        m = re.search(r"(\d+)", self.title.get("CORPS DE MEUBLE", ""))
        return int(m.group(1)) if m else None


_NUM = re.compile(r"^-?\d+(?:[.,]\d+)?$")
_CALLOUT = re.compile(r"Ø\s*(\d+(?:[.,]\d+)?)(?:\s*prof\.?\s*(\d+(?:[.,]\d+)?))?\s*(?:\((\d+)\s*x\))?", re.I)


def _num(s: str) -> Optional[float]:
    s = s.strip()
    return float(s.replace(",", ".")) if _NUM.match(s) else None


def read_pdf(data: bytes) -> List[SheetData]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    return [_read_page(i + 1, pg) for i, pg in enumerate(doc)]


def _read_page(n: int, pg) -> SheetData:
    sh = SheetData(page=n)
    if not pg.get_text().strip():
        sh.problems.append("PDF sans texte lisible : regénérez-le depuis KOBO Studio (bouton « Générer le PDF "
                           "des feuilles ») après avoir regénéré les livrables. Un ancien PDF ou une impression "
                           "AutoCAD ne peut pas être lu.")
        return sh
    W, H = pg.rect.width, pg.rect.height

    # --- textes -----------------------------------------------------------
    for b in pg.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            dx, dy = ln["dir"]
            horizontal = abs(dx) >= abs(dy)
            for sp in ln["spans"]:
                t = sp["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = sp["bbox"]
                sh.texts.append(Text(t, (x0 + x1) / 2, (y0 + y1) / 2, horizontal, _num(t)))
                m = _CALLOUT.search(t)
                if m and t.startswith("Ø"):
                    sh.callouts.append(Callout(
                        float(m.group(1).replace(",", ".")),
                        float(m.group(2).replace(",", ".")) if m.group(2) else None,
                        int(m.group(3)) if m.group(3) else 1, t))

    # --- cartouche : la valeur est sous son intitulé -----------------------
    for lab in TITLE_LABELS:
        label = next((t for t in sh.texts if t.s.upper() == lab and t.horizontal), None)
        if not label:
            continue
        below = [t for t in sh.texts if t.horizontal and 0 < t.y - label.y < 60 and abs(t.x - label.x) < 90
                 and t.s.upper() not in TITLE_LABELS]
        if below:
            sh.title[lab] = min(below, key=lambda t: (t.y - label.y) + abs(t.x - label.x)).s

    # --- dessin -------------------------------------------------------------
    for d in pg.get_drawings():
        items = d["items"]
        kinds = "".join(i[0] for i in items)
        r = d["rect"]
        stroke_only = d.get("fill") is None and d.get("color") is not None
        if kinds == "cccc" and stroke_only and abs(r.width - r.height) < 0.3 * max(r.width, 0.1):
            sh.circles.append(Circle((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, (r.width + r.height) / 2))
        elif stroke_only and kinds in ("qu", "re", "llll", "lllll") and r.width > 3 and r.height > 3:
            if r.width < W * 0.95:       # ni le cadre de la feuille ni un cartouche
                sh.rects.append(Rect(r.x0, r.y0, r.x1, r.y1))
        elif kinds == "lll" and r.width > 6 and r.height > 6 and r.width < 40 and r.height < 40:
            # triangle d'orientation (les flèches de cote sont bien plus petites)
            if r.y1 < H * 0.82:
                pts = []
                for it in items:
                    for q in (it[1], it[2]):
                        if not any(abs(q.x - a) < 0.2 and abs(q.y - b) < 0.2 for a, b in pts):
                            pts.append((q.x, q.y))
                if len(pts) == 3:
                    sh.triangles.append(tuple(pts))

    _interpret(sh, H)
    return sh


def _interpret(sh: SheetData, page_h: float) -> None:
    """Pièce principale, vues de tranche, échelle, cotes hors-tout."""
    zone_bottom = page_h * 0.82          # au-dessus du cartouche
    cands = [r for r in sh.rects if r.y1 < zone_bottom]
    if not cands:
        sh.problems.append("Aucun rectangle de pièce trouvé sur la feuille.")
        return
    sh.main = max(cands, key=lambda r: r.w * r.h)
    m = sh.main

    # cotes hors-tout : plus grande cote horizontale / verticale lue sur la feuille
    hs = [t.value for t in sh.texts if t.horizontal and t.value is not None and t.y < zone_bottom]
    vs = [t.value for t in sh.texts if not t.horizontal and t.value is not None and t.y < zone_bottom]
    if not hs or not vs:
        sh.problems.append("Cotes hors-tout illisibles : impossible de mettre le dessin à l'échelle.")
        return
    sh.L_mm, sh.W_mm = max(hs), max(vs)
    sh.scale = m.w / sh.L_mm
    ratio_dwg = m.w / m.h
    ratio_txt = sh.L_mm / sh.W_mm
    if abs(ratio_dwg / ratio_txt - 1) > 0.02:
        sh.problems.append(
            f"Le dessin ({m.w / sh.scale:.0f} x {m.h / sh.scale:.0f} mm à l'échelle de la longueur) "
            f"ne correspond pas aux cotes {sh.L_mm:g} x {sh.W_mm:g}.")

    # vues de tranche : bandes étroites alignées avec la pièce, hors pièce
    s = sh.scale
    for r in cands:
        if r is m:
            continue
        thin_v = r.w < m.w * 0.2 and r.h > m.h * 0.7 and (r.x1 <= m.x0 + 1 or r.x0 >= m.x1 - 1)
        thin_h = r.h < m.h * 0.2 and r.w > m.w * 0.7 and (r.y1 <= m.y0 + 1 or r.y0 >= m.y1 - 1)
        if thin_v or thin_h:
            sh.strips.append(r)
    # épaisseur : cote la plus proche d'une vue de tranche (les bandes sont dessinées
    # avec une épaisseur minimale, donc pas à l'échelle sur les grandes pièces)
    found = []
    for r in sh.strips:
        near = []
        for t in sh.texts:
            if t.value is None or not (0 < t.value <= 60):
                continue
            dx = max(r.x0 - t.x, 0, t.x - r.x1)
            dy = max(r.y0 - t.y, 0, t.y - r.y1)
            near.append((math.hypot(dx, dy), t.value))
        if near:
            dist, val = min(near)
            if dist < 30:
                found.append(val)
    if found:
        sh.T_mm = sorted(found)[len(found) // 2]
