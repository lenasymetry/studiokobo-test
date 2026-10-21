"""Feuilles d'usinage DXF : une présentation (layout) A3 par pièce.

Source : les données brutes de chaque pièce (dimensions, chants, perçages en
face et sur les tranches), celles qui alimentent aussi les feuilles d'usinage
du site (export_manager.generate_stacked_html_plans(output_format='plans')).

Règles de mise en page appliquées :
- 1 pièce = 1 présentation A3 paysage, cadre + cartouche dans la feuille ;
- la pièce est dessinée en vraie grandeur dans l'espace objet, la fenêtre de
  présentation l'affiche à une échelle normalisée (1:1, 1:2, 1:5, 1:10...) ;
- textes et cotes à 2,5 mm sur le papier quelle que soit l'échelle (DIMSCALE) ;
- pièce plus haute que large : tournée de 90° (comme sur le site) ;
- les 4 tranches autour de la face, hachurées quand elles reçoivent un chant ;
- cotes en chaîne accrochées au bord de la pièce, côté cote : aucune ligne de
  rappel ne traverse la pièce ; une seule cote par position ;
- un repère par type de perçage (diamètre/profondeur et nombre) ;
- triangles d'orientation : vide = bas du corps de meuble, plein = avant.
"""

from __future__ import annotations

import io
import math
import re
from typing import Dict, List, Optional, Tuple

import ezdxf
from ezdxf.enums import TextEntityAlignment

from .sanitize import sanitize_table_name, sanitize_text
from .titleblock import add_title_block

# --- Feuille (mm papier) -----------------------------------------------------
PAPER_W = 420.0
PAPER_H = 297.0
MARGIN = 10.0
TITLEBLOCK_H = 48.0
DRAW_X0 = MARGIN
DRAW_X1 = PAPER_W - MARGIN
DRAW_Y0 = MARGIN + TITLEBLOCK_H
DRAW_Y1 = PAPER_H - MARGIN
DRAW_PAD = 8.0

# --- Distances en mm papier (multipliées par l'échelle dans le modèle) -------
TXT_H = 2.5            # hauteur des textes / cotes
ARROW = 2.0            # flèches de cote
DIM_ROW = 7.0          # bord -> 1re ligne de cote
DIM_STEP = 7.0         # entre deux lignes de cote
TRANCHE_GAP_DIMS = DIM_ROW + 2 * DIM_STEP   # face -> tranche, côté cotes (2 rangées)
TRANCHE_GAP = 8.0      # face -> tranche, côté sans cote
TRANCHE_MIN = 4.0      # épaisseur mini affichée d'une tranche
CALLOUT_ROW = 7.0      # tranche haute -> ligne des repères de perçage de face
CALLOUT_TEXT_W = 30.0  # largeur réservée à un repère latéral
TRIANGLE = 5.0

STANDARD_SCALES = [1.0, 2.0, 2.5, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0]

LAYERS = {
    "CONTOUR": 7,
    "TRANCHES": 7,
    "HACHURES": 8,
    "TROUS": 7,
    "AXES": 8,
    "USINAGE": 6,
    "COTES": 1,
    "TEXTES": 7,
    "REPERES": 7,
    "CADRE": 7,
    "VIEWPORTS": 8,
}
DIMSTYLE = "KOBO_COTES"


# =============================================================================
# Utilitaires
# =============================================================================

def _num(value, default=None):
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace(",", ".").strip()
            if not value:
                return default
        return float(value)
    except Exception:
        return default


def _fmt(value: float) -> str:
    v = round(float(value), 1)
    return str(int(v)) if abs(v - round(v)) < 1e-6 else f"{v:.1f}"


def _hole_diameter(diam_str: str, default: float = 5.0) -> float:
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(diam_str or ""))
    return float(m.group(1).replace(",", ".")) if m else default


def _hole_label(diam_str: str) -> str:
    """'⌀8/22' -> '%%c8 prof. 22' (symbole diamètre AutoCAD)."""
    raw = str(diam_str or "").replace("⌀", "").replace("Ø", "").strip()
    if "/" in raw:
        d, p = raw.split("/", 1)
        return f"%%c{d.strip()} prof. {p.strip()}"
    return f"%%c{raw}"


def _unique_sorted(values, tol=0.05):
    out = []
    for v in sorted(values):
        if not out or abs(v - out[-1]) > tol:
            out.append(v)
    return out


ROW_STEP = 5.0         # écart entre deux rangées d'une chaîne étagée (mm papier)


def _stagger(positions, lo, hi, s):
    """Chaîne de cotes étagée : chaque cote va sur la 1re rangée où son texte
    ne chevauche pas celui d'une autre. Retourne ([(a, b, rangée)], nb rangées)."""
    pts = _unique_sorted([lo] + [p for p in positions if lo - 0.05 <= p <= hi + 0.05] + [hi])
    rows, segs = [], []
    for a, b in zip(pts, pts[1:]):
        if b - a < 0.05:
            continue
        tw = (len(_fmt(b - a)) * TXT_H * 0.75 + 1.5) * s
        c = (a + b) / 2.0
        for r in range(len(rows) + 1):
            if r == len(rows):
                rows.append(-1e18)
            if c - tw / 2.0 >= rows[r]:
                rows[r] = c + tw / 2.0
                segs.append((a, b, r))
                break
    return segs, max(1, len(rows))


def _face_rows(sheet, s):
    face = sheet.face_holes()
    if not face:
        return 0, 0
    _, nx = _stagger([h["_x"] for h in face], 0.0, sheet.Wd, s)
    _, ny = _stagger([h["_y"] for h in face], 0.0, sheet.Hd, s)
    return nx, ny


def _tranche_rows(sheet, side_info, side, s):
    holes = side_info["holes"]
    if not holes:
        return 0
    horizontal = side in ("bottom", "top")
    pos = []
    for h in holes:
        px, py = sheet.edge_point(side_info["edge"], h["_t"])
        pos.append(px if horizontal else py)
    _, n = _stagger(pos, 0.0, sheet.Wd if horizontal else sheet.Hd, s)
    return n


def _circle_touches_triangle(cx, cy, r, tri):
    """Vrai si le disque (cx, cy, r) recoupe le triangle."""
    (x1, y1), (x2, y2), (x3, y3) = tri

    def side(ax, ay, bx, by):
        return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

    d1, d2, d3 = side(x1, y1, x2, y2), side(x2, y2, x3, y3), side(x3, y3, x1, y1)
    if (d1 >= 0 and d2 >= 0 and d3 >= 0) or (d1 <= 0 and d2 <= 0 and d3 <= 0):
        return True  # centre dans le triangle

    def seg_dist(ax, ay, bx, by):
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((cx - ax) * vx + (cy - ay) * vy) / L2))
        qx, qy = ax + t * vx, ay + t * vy
        return math.hypot(cx - qx, cy - qy)

    return min(seg_dist(x1, y1, x2, y2), seg_dist(x2, y2, x3, y3), seg_dist(x3, y3, x1, y1)) < r


def _cutout_props(cut):
    if not cut:
        return None
    if isinstance(cut, dict):
        return cut
    if isinstance(cut, (tuple, list)) and len(cut) >= 3:
        return {"type": "integrated_cutout", "width": cut[0], "height": cut[1], "offset_top": cut[2]}
    return None


def _display_title(title: str) -> str:
    """Désignation lisible à l'atelier (cartouche et onglet)."""
    t = str(title or "")
    if t.lower().startswith("panneau arri"):
        t = "Fond (panneau arrière)" + t[len("Panneau Arrière (F)"):]
    t = re.sub(r"Montant Secondaire (\d+) \((C\d+)\) - ([12])/2",
               lambda m: f"Montant secondaire {m.group(1)} ({m.group(2)}) - face {m.group(3)}/2", t)
    return t


def _layout_name(index: int, corps: str, title: str) -> str:
    """Nom d'onglet AutoCAD : caractères interdits (<>/\\":;?*|,=`) remplacés."""
    import unicodedata
    raw = f"{index:02d} - {corps} - {title}" if corps else f"{index:02d} - {title}"
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    raw = raw.replace("/", "-")
    raw = re.sub(r'[<>\\":;?*|,=`]', "", raw)
    return re.sub(r"\s+", " ", raw).strip()[:120]


def _triangles_for(title: str):
    """Repères d'orientation (mêmes règles que les feuilles du site).

    Retourne [(bord, plein)] avec bord parmi 'avant'(y=0), 'arriere'(y=W),
    'gauche'(x=0), 'droit'(x=L) du repère de la pièce.
    """
    t = (title or "").lower()
    for a, b in (("é", "e"), ("è", "e"), ("ê", "e"), ("ç", "c")):
        t = t.replace(a, b)
    # Joues latérales : longueur = hauteur du meuble. Bord 'gauche' (x = 0) =
    # bas du meuble, bord 'avant' (y = 0) = avant du meuble.
    # Joues gauche et droite = pièces symétriques : le bas du meuble est d'un
    # côté de la feuille pour l'une, de l'autre côté pour l'autre.
    if "joue" in t and "droite" in t:
        return [("droit", False), ("avant", True)]
    if "joue" in t and "gauche" in t:
        return [("gauche", False), ("avant", True)]
    if "joue" in t:
        return [("avant", True)]
    if "fileur colonne" in t or "plinthe" in t:
        return [("avant", False)]
    if "fond (panneau" in t or "panneau arriere" in t:
        return [("avant", False)]
    if "traverse bas" in t or "traverse haut" in t:
        return [("avant", True)]
    if "montant droit" in t or ("montant" in t and "1/2" in t):
        return [("avant", False), ("droit", True)]
    if "montant gauche" in t or ("montant" in t and "2/2" in t):
        return [("avant", False), ("gauche", True)]
    if "etagere" in t:
        return [("avant", True)]
    if "fond" in t and "tiroir" in t:
        return [("avant", True)]
    if ("face" in t or "facade" in t or "dos" in t) and "tiroir" in t:
        return [("avant", False)]
    if "porte" in t:
        return [("avant", False)]
    # Toute feuille porte au moins le repère du bas du corps de meuble.
    return [("avant", False)]


# =============================================================================
# Géométrie d'une feuille (repère dessiné, pièce éventuellement tournée)
# =============================================================================

class _Sheet:
    def __init__(self, plan: dict):
        self.plan = plan
        self.title = str(plan.get("title", "Pièce"))
        self.L = float(plan["L"])
        self.W = float(plan["W"])
        self.T = float(plan.get("T", 18.0))
        self.rotated = self.W > self.L
        # Dimensions dessinées
        self.Wd = self.W if self.rotated else self.L
        self.Hd = self.L if self.rotated else self.W

    # (x, y) pièce -> (x, y) dessin. Rotation identique au site : (W - y, x).
    def tr(self, x, y):
        if self.rotated:
            return (self.W - y, x)
        return (x, y)

    def edge_side(self, edge: str) -> str:
        """Côté dessiné ('bottom','top','left','right') d'un bord de la pièce."""
        mid = {
            "avant": (self.L / 2.0, 0.0),
            "arriere": (self.L / 2.0, self.W),
            "gauche": (0.0, self.W / 2.0),
            "droit": (self.L, self.W / 2.0),
        }[edge]
        x, y = self.tr(*mid)
        if abs(y) < 1e-6:
            return "bottom"
        if abs(y - self.Hd) < 1e-6:
            return "top"
        if abs(x) < 1e-6:
            return "left"
        return "right"

    def edge_point(self, edge: str, t: float) -> Tuple[float, float]:
        """Point dessiné d'un bord, paramètre t mesuré le long du bord (repère pièce)."""
        p = {
            "avant": (t, 0.0),
            "arriere": (t, self.W),
            "gauche": (0.0, t),
            "droit": (self.L, t),
        }[edge]
        return self.tr(*p)

    def edge_holes(self) -> Dict[str, List[dict]]:
        """Perçages de tranche par bord (paramètre le long du bord)."""
        out = {"avant": [], "arriere": [], "gauche": [], "droit": []}
        for h in self.plan.get("tranche_long_holes") or []:
            t = _num(h.get("x"), None)
            if t is None:
                t = _num(h.get("y"), None)
            if t is None or t < -0.5 or t > self.L + 0.5:
                continue
            for e in ("avant", "arriere"):
                out[e].append({**h, "_t": t})
        for h in self.plan.get("tranche_side_holes") or []:
            t = _num(h.get("y"), None)
            if t is None:
                t = _num(h.get("x"), None)
            if t is None or t < -0.5 or t > self.W + 0.5:
                continue
            for e in ("gauche", "droit"):
                out[e].append({**h, "_t": t})
        return out

    def face_holes(self) -> List[dict]:
        out = []
        for h in self.plan.get("face_holes") or []:
            x, y = _num(h.get("x")), _num(h.get("y"))
            if x is None or y is None:
                continue
            if x < -0.5 or x > self.L + 0.5 or y < -0.5 or y > self.W + 0.5:
                continue
            dx, dy = self.tr(x, y)
            out.append({**h, "_x": dx, "_y": dy})
        return out


def _side_layout(sheet: _Sheet, s: float):
    """Position des 4 tranches (repère dessiné) pour l'échelle s."""
    td = max(sheet.T, TRANCHE_MIN * s)
    eh = sheet.edge_holes()
    face = sheet.face_holes()
    has_face_x = bool(face)
    sides = {}
    for edge in ("avant", "arriere", "gauche", "droit"):
        side = sheet.edge_side(edge)
        sides[side] = {"edge": edge, "holes": eh[edge]}
    # Cotes de face (X en bas, Y à gauche) + cotes hors tout : 2 rangées.
    gap = {
        "bottom": TRANCHE_GAP_DIMS * s,
        "left": TRANCHE_GAP_DIMS * s,
        "top": TRANCHE_GAP * s,
        "right": TRANCHE_GAP * s,
    }
    if not has_face_x:
        gap["bottom"] = (DIM_ROW + DIM_STEP) * s
        gap["left"] = (DIM_ROW + DIM_STEP) * s
    else:
        # Rangées de la chaîne étagée + cote hors tout + marge avant la tranche.
        nx, ny = _face_rows(sheet, s)
        gap["bottom"] = (DIM_ROW + (nx - 1) * ROW_STEP + DIM_STEP + 7.0) * s
        gap["left"] = (DIM_ROW + (ny - 1) * ROW_STEP + DIM_STEP + 7.0) * s
    return td, sides, gap


def _extents(sheet: _Sheet, s: float):
    td, sides, gap = _side_layout(sheet, s)
    out = {}
    for k, v in sides.items():
        if not v["holes"]:
            out[k] = 0.0
            continue
        n = _tranche_rows(sheet, v, k, s)
        ngroups = len({h.get("diam_str", "") for h in v["holes"]})
        chain = DIM_ROW + (n - 1) * ROW_STEP
        if k in ("left", "right"):
            out[k] = (chain + DIM_STEP + CALLOUT_TEXT_W) * s
        else:
            out[k] = (chain + DIM_STEP * (1 + ngroups)) * s
    top_callouts = (CALLOUT_ROW + 4.0) * s if sheet.face_holes() else 0.0
    minx = -(gap["left"] + td + out["left"] + 6 * s)
    maxx = sheet.Wd + gap["right"] + td + out["right"] + 6 * s
    miny = -(gap["bottom"] + td + out["bottom"] + 6 * s)
    maxy = sheet.Hd + gap["top"] + td + max(out["top"], top_callouts) + 6 * s
    return minx, miny, maxx, maxy


def _choose_scale(sheet: _Sheet) -> float:
    """Facteur de cadrage (mm modèle par mm papier) : la pièce, ses tranches et
    ses cotes occupent la zone de dessin au plus grand, marge comprise.

    Les annotations (textes, cotes, décalages) sont définies en mm papier et
    grandissent avec le facteur : on cherche donc le point fixe
    s = max(largeur(s) / largeur dispo, hauteur(s) / hauteur dispo)."""
    avail_w = (DRAW_X1 - DRAW_X0) - 2 * DRAW_PAD
    avail_h = (DRAW_Y1 - DRAW_Y0) - 2 * DRAW_PAD
    s = 1.0
    for _ in range(60):
        minx, miny, maxx, maxy = _extents(sheet, s)
        need = max((maxx - minx) / avail_w, (maxy - miny) / avail_h)
        if abs(need - s) <= 1e-4 * max(1.0, s):
            s = need
            break
        s = need
    # Sécurité : vérifier que tout tient, sinon élargir légèrement.
    for _ in range(20):
        minx, miny, maxx, maxy = _extents(sheet, s)
        if (maxx - minx) <= avail_w * s + 1e-6 and (maxy - miny) <= avail_h * s + 1e-6:
            break
        s *= 1.02
    return max(s, 1e-3)


# =============================================================================
# Dessin dans l'espace objet
# =============================================================================

class _Drawer:
    def __init__(self, msp, ox: float, oy: float, s: float):
        self.msp = msp
        self.ox = ox
        self.oy = oy
        self.s = s

    def P(self, x, y):
        return (self.ox + x, self.oy + y)

    def rect(self, x0, y0, x1, y1, layer="CONTOUR", dashed=False):
        attribs = {"layer": layer}
        if dashed:
            attribs["linetype"] = "DASHED"
            attribs["ltscale"] = self.s
        self.msp.add_lwpolyline([self.P(x0, y0), self.P(x1, y0), self.P(x1, y1), self.P(x0, y1)],
                                close=True, dxfattribs=attribs)

    def line(self, x0, y0, x1, y1, layer="CONTOUR"):
        self.msp.add_line(self.P(x0, y0), self.P(x1, y1), dxfattribs={"layer": layer})

    def hatch(self, x0, y0, x1, y1):
        h = self.msp.add_hatch(dxfattribs={"layer": "HACHURES"})
        h.set_pattern_fill("ANSI31", scale=0.5 * self.s)
        h.paths.add_polyline_path([self.P(x0, y0), self.P(x1, y0), self.P(x1, y1), self.P(x0, y1)], is_closed=True)

    def circle(self, x, y, d):
        self.msp.add_circle(self.P(x, y), radius=max(0.25, d / 2.0), dxfattribs={"layer": "TROUS"})

    def text(self, txt, x, y, align=TextEntityAlignment.MIDDLE_LEFT, h=TXT_H, layer="TEXTES"):
        t = self.msp.add_text(txt, dxfattribs={"layer": layer, "height": h * self.s, "style": "Standard"})
        t.set_placement(self.P(x, y), align=align)
        return t

    def dim(self, p1, p2, axis: str, base_coord: float, text: Optional[str] = None):
        """Cote linéaire. axis 'x' : ligne de cote horizontale à y=base_coord."""
        if axis == "x":
            base = self.P(p1[0], base_coord)
            angle = 0
        else:
            base = self.P(base_coord, p1[1])
            angle = 90
        if abs((p2[0] - p1[0]) if axis == "x" else (p2[1] - p1[1])) < 0.05:
            return
        d = self.msp.add_linear_dim(
            base=base, p1=self.P(*p1), p2=self.P(*p2), angle=angle,
            dimstyle=DIMSTYLE, override={"dimscale": self.s},
            dxfattribs={"layer": "COTES"},
        )
        if text is not None:
            d.dimension.dxf.text = text
        d.render()

    def chain(self, positions: List[float], axis: str, edge_coord: float, base_coord: float,
              lo: float, hi: float, direction: float = -1.0) -> int:
        """Chaîne de cotes du bord lo au bord hi en passant par chaque position,
        étagée vers l'extérieur (direction -1 : vers le bas / la gauche).
        Retourne le nombre de rangées utilisées."""
        segs, nrows = _stagger(positions, lo, hi, self.s)
        for a, b, r in segs:
            base = base_coord + direction * r * ROW_STEP * self.s
            if axis == "x":
                self.dim((a, edge_coord), (b, edge_coord), "x", base)
            else:
                self.dim((edge_coord, a), (edge_coord, b), "y", base)
        return nrows

    def triangle(self, apex, direction, filled, holes=(), edge_len=0.0):
        """Triangle de repère : pointe sur le bord, orientée vers l'extérieur.

        Il ne doit cacher aucun perçage : s'il en touche un, sa hauteur est
        réduite (même base) jusqu'à le dégager.
        """
        size = TRIANGLE * self.s
        full_hgt = size * math.sqrt(3) / 2.0
        dx, dy = direction
        px, py = -dy * size / 2.0, dx * size / 2.0
        tx, ty = abs(dy), abs(dx)                       # direction le long du bord

        def corners(ax, ay, h):
            bx, by = ax - dx * h, ay - dy * h          # milieu de la base (intérieur)
            return [(ax, ay), (bx + px, by + py), (bx - px, by - py)]

        def hits(tri):
            return any(_circle_touches_triangle(hx, hy, r + 0.3 * self.s, tri) for hx, hy, r in holes)

        def shrink(ax, ay):
            h = full_hgt
            while h > full_hgt * 0.1 and hits(corners(ax, ay, h)):
                h *= 0.9
            return h if not hits(corners(ax, ay, h)) else 0.0

        # 1) Même position, hauteur réduite (même base) si un perçage est touché.
        ax, ay = apex
        hgt = shrink(ax, ay)
        # 2) Trop petit pour rester lisible : décalé le long du même bord, au
        #    plus près du milieu, là où il tient sans cacher de perçage.
        if hgt < 0.6 * full_hgt and edge_len:
            step = size / 4.0
            best = None
            k = 1
            while k * step <= edge_len / 2.0 - size / 2.0:
                for sign in (1, -1):
                    cx, cy = apex[0] + sign * tx * k * step, apex[1] + sign * ty * k * step
                    h = shrink(cx, cy)
                    if h >= 0.6 * full_hgt:
                        best = (cx, cy, h)
                        break
                if best:
                    break
                k += 1
            if best:
                ax, ay, hgt = best
        if hgt <= 0.0:
            hgt = full_hgt * 0.1
        pts = [self.P(x, y) for x, y in corners(ax, ay, hgt)]
        self.msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "REPERES"})
        if filled:
            h = self.msp.add_hatch(color=7, dxfattribs={"layer": "REPERES"})
            h.paths.add_polyline_path(pts, is_closed=True)

    def callout(self, hole_xy, knee_xy, label, count, to_left=False):
        """Repère de perçage : ligne de rappel du trou au coude, palier, texte."""
        s = self.s
        x, y = hole_xy
        kx, ky = knee_xy
        tx = kx + (-3 * s if to_left else 3 * s)
        self.msp.add_lwpolyline([self.P(x, y), self.P(kx, ky), self.P(tx, ky)], dxfattribs={"layer": "TEXTES"})
        txt = f"{label}  ({count}x)" if count > 1 else label
        align = TextEntityAlignment.MIDDLE_RIGHT if to_left else TextEntityAlignment.MIDDLE_LEFT
        self.text(txt, tx + (-1 * s if to_left else 1 * s), ky, align=align)


def _draw_sheet(sheet: _Sheet, msp, ox: float, oy: float, s: float):
    D = _Drawer(msp, ox, oy, s)
    Wd, Hd = sheet.Wd, sheet.Hd
    td, sides, gap = _side_layout(sheet, s)
    chants = sheet.plan.get("chants") or {}
    chant_key = {"avant": "Chant Avant", "arriere": "Chant Arrière", "gauche": "Chant Gauche", "droit": "Chant Droit"}

    # --- Face ------------------------------------------------------------------
    D.rect(0, 0, Wd, Hd)

    # --- Tranches -----------------------------------------------------------------
    tranche_rects = {
        "bottom": (0, -gap["bottom"] - td, Wd, -gap["bottom"]),
        "top": (0, Hd + gap["top"], Wd, Hd + gap["top"] + td),
        "left": (-gap["left"] - td, 0, -gap["left"], Hd),
        "right": (Wd + gap["right"], 0, Wd + gap["right"] + td, Hd),
    }
    dimensioned_signature = {}
    for side, (x0, y0, x1, y1) in tranche_rects.items():
        info = sides[side]
        edge = info["edge"]
        D.rect(x0, y0, x1, y1, layer="TRANCHES")
        if chants.get(chant_key[edge]):
            D.hatch(x0, y0, x1, y1)
        horizontal = side in ("bottom", "top")
        cx_mid = (x0 + x1) / 2.0
        cy_mid = (y0 + y1) / 2.0
        positions = []
        for h in info["holes"]:
            px, py = sheet.edge_point(edge, h["_t"])
            pos = px if horizontal else py
            positions.append(pos)
            d = _hole_diameter(h.get("diam_str"), 8.0)
            # Trou vu de bout dans l'épaisseur de la tranche : cercle limité à la tranche.
            D.circle(pos if horizontal else cx_mid, cy_mid if horizontal else pos, min(d, td * 0.8))

        # Épaisseur réelle de la tranche (dessin agrandi si trop fine).
        if side == "bottom":
            D.dim((0, y0), (0, y1), "y", -6 * s, text=_fmt(sheet.T))
        elif side == "left":
            D.dim((x0, Hd), (x1, Hd), "x", Hd + 6 * s, text=_fmt(sheet.T))

        if not positions:
            continue
        # Une seule chaîne par jeu de perçages identique (bords opposés).
        sig = (horizontal, tuple(round(p, 1) for p in _unique_sorted(positions)))
        if sig in dimensioned_signature:
            continue
        dimensioned_signature[sig] = side
        # Axe des perçages dans l'épaisseur : à l'autre bout de la tranche que
        # la cote d'épaisseur, pour ne pas les superposer.
        if side == "bottom":
            nr = D.chain(positions, "x", y0, y0 - DIM_ROW * s, 0, Wd, -1)
            D.dim((Wd, cy_mid), (Wd, y1), "y", Wd + 6 * s, text=_fmt(sheet.T / 2.0))
        elif side == "top":
            nr = D.chain(positions, "x", y1, y1 + DIM_ROW * s, 0, Wd, +1)
        elif side == "left":
            nr = D.chain(positions, "y", x0, x0 - DIM_ROW * s, 0, Hd, -1)
            D.dim((x0, 0), (cx_mid, 0), "x", -6 * s, text=_fmt(sheet.T / 2.0))
        else:
            nr = D.chain(positions, "y", x1, x1 + DIM_ROW * s, 0, Hd, +1)
        extra = (nr - 1) * ROW_STEP
        # Repère du type de perçage de tranche, à l'extérieur de la chaîne de cotes.
        groups = {}
        for h in info["holes"]:
            groups.setdefault(h.get("diam_str", ""), []).append(h)
        for k, (ds, hs) in enumerate(groups.items()):
            px, py = sheet.edge_point(edge, hs[0]["_t"])
            if side == "bottom":
                D.callout((px, cy_mid), (px + 4 * s, y0 - (DIM_ROW + extra + DIM_STEP * (1 + k)) * s), _hole_label(ds), len(hs))
            elif side == "top":
                D.callout((px, cy_mid), (px + 4 * s, y1 + (DIM_ROW + extra + DIM_STEP * (1 + k)) * s), _hole_label(ds), len(hs))
            elif side == "left":
                D.callout((cx_mid, py), (x0 - (DIM_ROW + extra + DIM_STEP) * s, py + 4 * s + k * DIM_STEP * s),
                          _hole_label(ds), len(hs), to_left=True)
            else:
                D.callout((cx_mid, py), (x1 + (DIM_ROW + extra + DIM_STEP) * s, py + 4 * s + k * DIM_STEP * s),
                          _hole_label(ds), len(hs))

    # --- Perçages en face --------------------------------------------------------
    face = sheet.face_holes()
    for h in face:
        D.circle(h["_x"], h["_y"], _hole_diameter(h.get("diam_str"), 5.0))
    if face:
        # Une chaîne par axe, étagée pour que les textes ne se chevauchent pas.
        nx = D.chain([h["_x"] for h in face], "x", 0, -DIM_ROW * s, 0, Wd, -1)
        ny = D.chain([h["_y"] for h in face], "y", 0, -DIM_ROW * s, 0, Hd, -1)
        groups = {}
        for h in face:
            groups.setdefault(h.get("diam_str", ""), []).append(h)
        # Repères alignés au-dessus de la tranche haute, de gauche à droite,
        # chacun relié au trou le plus haut de son type.
        y_row = Hd + gap["top"] + td + CALLOUT_ROW * s
        x_free = 0.0
        refs = []
        used_x = []
        # Types les moins nombreux d'abord : ils ont le moins de choix de trou.
        for ds, hs in sorted(groups.items(), key=lambda g: len(g[1])):
            label_w = (len(_hole_label(ds)) + 6) * TXT_H * 0.75 * s + 8 * s
            candidates = sorted(hs, key=lambda h: (-h["_y"], h["_x"]))
            ref = next((h for h in candidates if all(abs(h["_x"] - u) >= label_w for u in used_x)), candidates[0])
            used_x.append(ref["_x"])
            refs.append((ref, ds, len(hs)))
        for ref, ds, n in sorted(refs, key=lambda r: r[0]["_x"]):
            label = _hole_label(ds)
            text_w = (len(label) + 6) * TXT_H * 0.75 * s
            kx = max(ref["_x"], x_free)
            D.callout((ref["_x"], ref["_y"]), (kx, y_row), label, n)
            x_free = kx + 3 * s + text_w + 4 * s
    if face:
        D.dim((0, 0), (Wd, 0), "x", -(DIM_ROW + (nx - 1) * ROW_STEP + DIM_STEP) * s)
        D.dim((0, 0), (0, Hd), "y", -(DIM_ROW + (ny - 1) * ROW_STEP + DIM_STEP) * s)
    else:
        D.dim((0, 0), (Wd, 0), "x", -DIM_ROW * s)
        D.dim((0, 0), (0, Hd), "y", -DIM_ROW * s)

    # --- Découpe de poignée / passe-doigt ----------------------------------------
    cut = _cutout_props(sheet.plan.get("cutout"))
    if cut:
        L, W = sheet.L, sheet.W
        off = _num(cut.get("offset_top"), 10.0)
        if str(cut.get("type", "integrated_cutout")) == "finger_pull":
            a, b = sheet.tr(0, W - off), sheet.tr(L, W - off)
            D.line(a[0], a[1], b[0], b[1], layer="USINAGE")
        else:
            cw, ch = _num(cut.get("width"), 150.0), _num(cut.get("height"), 40.0)
            cx0, cx1 = (L - cw) / 2.0, (L + cw) / 2.0
            cy1 = W - off
            cy0 = cy1 - ch
            p0, p1 = sheet.tr(cx0, cy0), sheet.tr(cx1, cy1)
            rx0, rx1 = min(p0[0], p1[0]), max(p0[0], p1[0])
            ry0, ry1 = min(p0[1], p1[1]), max(p0[1], p1[1])
            D.rect(rx0, ry0, rx1, ry1, layer="USINAGE", dashed=True)
            D.dim((rx0, ry1), (rx1, ry1), "x", ry1 + 5 * s)
            D.dim((rx1, ry0), (rx1, ry1), "y", rx1 + 5 * s)

    # --- Feuillure (LÉGRABOX) ---------------------------------------------------
    if sheet.plan.get("has_rebate"):
        R = 38.0
        for x in (R, sheet.L - R):
            a, b = sheet.tr(x, 0), sheet.tr(x, sheet.W)
            D.line(a[0], a[1], b[0], b[1], layer="USINAGE")
        a = sheet.tr(0, sheet.W)
        b = sheet.tr(R, sheet.W)
        if not sheet.rotated:
            D.dim((0, Hd), (R, Hd), "x", Hd + 5 * s)
            D.dim((Wd - R, Hd), (Wd, Hd), "x", Hd + 5 * s)
        else:
            D.dim((Wd, 0), (Wd, R), "y", Wd + 5 * s)
            D.dim((Wd, Hd - R), (Wd, Hd), "y", Wd + 5 * s)

    # --- Repères d'orientation -------------------------------------------------
    for edge, filled in _triangles_for(sheet.title):
        side = sheet.edge_side(edge)
        apex = {"bottom": (Wd / 2.0, 0.0), "top": (Wd / 2.0, Hd),
                "left": (0.0, Hd / 2.0), "right": (Wd, Hd / 2.0)}[side]
        direction = {"bottom": (0, -1), "top": (0, 1), "left": (-1, 0), "right": (1, 0)}[side]
        D.triangle(apex, direction, filled,
                   holes=[(h["_x"], h["_y"], _hole_diameter(h.get("diam_str"), 5.0) / 2.0) for h in face],
                   edge_len=Wd if side in ("bottom", "top") else Hd)

    return _extents(sheet, s)


# =============================================================================
# Document
# =============================================================================

def _setup_doc():
    doc = ezdxf.new("R2010", setup=True)
    doc.units = 4  # mm
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    doc.header["$PSLTSCALE"] = 1
    for name, color in LAYERS.items():
        if name not in doc.layers:
            doc.layers.new(name, dxfattribs={"color": color})
    doc.layers.get("VIEWPORTS").dxf.plot = 0
    ds = doc.dimstyles.new(DIMSTYLE)
    ds.dxf.dimtxt = TXT_H
    ds.dxf.dimasz = ARROW
    ds.dxf.dimexo = 1.0
    ds.dxf.dimexe = 1.25
    ds.dxf.dimgap = 0.8
    ds.dxf.dimtad = 1
    ds.dxf.dimtih = 0
    ds.dxf.dimtoh = 0
    ds.dxf.dimdec = 1
    ds.dxf.dimzin = 8
    ds.dxf.dimdsep = ord(",")
    ds.dxf.dimclrd = 256
    ds.dxf.dimclre = 256
    ds.dxf.dimclrt = 256
    ds.dxf.dimtmove = 1
    ds.dxf.dimscale = 1.0
    ds.dxf.dimlfac = 1.0
    return doc


def _setup_layout(doc, name: str):
    layout = doc.layouts.new(name)
    layout.page_setup(size=(PAPER_W, PAPER_H), margins=(0, 0, 0, 0), units="mm",
                      offset=(0, 0), rotation=0, scale=(1, 1), name="ISO_full_bleed_A3_(420.00_x_297.00_MM)",
                      device="DWG To PDF.pc3")
    # Cadre de la feuille.
    layout.add_lwpolyline([(MARGIN, MARGIN), (PAPER_W - MARGIN, MARGIN),
                           (PAPER_W - MARGIN, PAPER_H - MARGIN), (MARGIN, PAPER_H - MARGIN)],
                          close=True, dxfattribs={"layer": "CADRE"})
    return layout


def export_machining_sheets_dxf(plans: List[dict], project_info: Optional[dict] = None,
                                logo_path: Optional[str] = None) -> bytes:
    """Construit le DXF : une présentation A3 par feuille d'usinage."""
    project_info = project_info or {}
    doc = _setup_doc()
    msp = doc.modelspace()

    total = len(plans)
    vp_w = (DRAW_X1 - DRAW_X0) - 2.0
    vp_h = (DRAW_Y1 - DRAW_Y0) - 2.0
    # Chaque pièce occupe dans l'espace objet un emplacement plus large que ce
    # que sa fenêtre peut montrer : aucune autre pièce n'apparaît sur sa feuille.
    slot_left = 0.0
    used_names = set()
    for i, plan in enumerate(plans, start=1):
        sheet = _Sheet(plan)
        s = _choose_scale(sheet)
        minx, miny, maxx, maxy = _extents(sheet, s)
        view_w = vp_w * s
        view_h = vp_h * s
        slot_margin = max(view_w, view_h)          # vide de sécurité entre emplacements
        cx = slot_left + view_w / 2.0
        cy = 0.0
        ox = cx - (minx + maxx) / 2.0
        oy = cy - (miny + maxy) / 2.0
        _draw_sheet(sheet, msp, ox, oy, s)
        slot_left = cx + view_w / 2.0 + slot_margin

        proj = plan.get("project") or {}
        corps = str(proj.get("corps_meuble", "")).replace("Caisson", "C").replace(" ", "")
        designation = _display_title(sheet.title)
        base_name = _layout_name(i, corps, designation.replace(f"({corps})", "").replace("  ", " ").strip())
        name = base_name
        k = 2
        while name.upper() in used_names:
            name = f"{base_name} ({k})"
            k += 1
        used_names.add(name.upper())
        layout = _setup_layout(doc, name)

        vp = layout.add_viewport(
            center=((DRAW_X0 + DRAW_X1) / 2.0, (DRAW_Y0 + DRAW_Y1) / 2.0),
            size=(vp_w, vp_h),
            view_center_point=(cx, cy),
            view_height=view_h,
            dxfattribs={"layer": "VIEWPORTS"},
        )
        try:
            vp.dxf.flags = vp.dxf.flags | 16384  # échelle verrouillée
        except Exception:
            pass

        meta = {
            "date": proj.get("date") or project_info.get("date", ""),
            "project_name": proj.get("project_name") or project_info.get("project_name", ""),
            "corps_meuble": proj.get("corps_meuble", ""),
            "part_name": designation,
            "quantity": proj.get("quantity", 1),
            # Feuille cadrée au plus grand : ne pas mesurer sur le plan.
            "scale": "SANS ECHELLE",
            "sheet_index": i,
            "total_sheets": total,
            "client": project_info.get("client", ""),
            "version": project_info.get("version", "V1"),
        }
        add_title_block(layout, paper_w=PAPER_W, paper_h=PAPER_H, margin=MARGIN,
                        metadata=meta, logo_path=logo_path, text_height=2.5,
                        titleblock_height=TITLEBLOCK_H)

    # Présentation vide créée par défaut par ezdxf.
    if total and "Layout1" in doc.layouts:
        try:
            doc.layouts.delete("Layout1")
        except Exception:
            pass

    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")
