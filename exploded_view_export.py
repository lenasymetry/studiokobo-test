"""Vue éclatée du meuble (PDF « vue éclatée »).

Source : les panneaux de la scène, tels que le modèle SketchUp les construit
(`generate_sketchup_collada(..., collect=...)`), plus le caisson des tiroirs
(dos + fond). Chaque panneau est écarté de son caisson le long de son épaisseur,
dessiné en perspective isométrique (vectoriel), repéré par un numéro relié à son
panneau, et listé dans un tableau : repère, désignation, dimensions, matière.

Pages : une vue d'ensemble de la scène, puis une page par caisson.
"""
from __future__ import annotations

import datetime
import io
import math
import re
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

from sketchup_export import generate_sketchup_collada  # noqa: E402
from views_3d_export import (_DARK, _GREY_TXT, _draw_kobo_bar, _load_kobo_logo,  # noqa: E402
                             _MARGIN_B, _BAR_H)

FIG_W, FIG_H = 11.69, 8.27            # A4 paysage, comme le PDF des vues 3D

# Direction de vue : caméra devant-gauche-dessus (x droite, y profondeur, z haut).
_D = np.array([1.0, 1.0, -1.0]) / math.sqrt(3.0)          # sens du regard
_R = np.cross(_D, [0, 0, 1.0]); _R /= np.linalg.norm(_R)   # droite écran
_U = np.cross(_R, _D)                                      # haut écran

# Couleurs par famille (face avant, dessus, côté).
_COLORS = {
    "body":   ("#E8D9BE", "#F4EBD8", "#D5C4A4"),
    "door":   ("#BFC8D6", "#D6DDE8", "#A9B4C6"),
    "drawer": ("#B7D1DD", "#D0E3EC", "#9FC0CF"),
}


# ───────────────────────────── panneaux ───────────────────────────────────

def _base_name(label: str, cab: Dict) -> str:
    """Désignation alignée sur la fiche de débit."""
    name = label.split(" – ")[0].strip()
    m = re.match(r"^Séparateur (\d+)$", name)
    if m:
        return f"Montant secondaire {m.group(1)}"
    m = re.match(r"^Étagère (\d+)$", name)
    if m:
        idx = int(m.group(1)) - 1
        shelves = cab.get("shelves", []) or []
        kind = str(shelves[idx].get("shelf_type", "mobile")) if 0 <= idx < len(shelves) else "mobile"
        return f"Étagère {'fixe' if kind == 'fixe' else 'mobile'} {m.group(1)}"
    return name


def _material(rec: Dict, cab: Dict) -> str:
    role = rec.get("role")
    if role in ("drawer_face",):
        d = (cab.get("drawers", []) or [])
        j = rec.get("drawer", 0)
        return str((d[j] if j < len(d) else {}).get("material", "") or "")
    if role in ("drawer_back", "drawer_bottom"):
        d = (cab.get("drawers", []) or [])
        j = rec.get("drawer", 0)
        return str((d[j] if j < len(d) else {}).get("material_inner", "") or cab.get("material_body", "") or "")
    if rec["mat"] == "mat_door":
        return str((cab.get("door_props", {}) or {}).get("material", "") or "")
    return str(cab.get("material_body", "") or "")


def collect_panels(scene: Sequence[Dict]) -> List[Dict]:
    """Tous les panneaux de la scène (mm, repère scène), avec nom et matière."""
    raw: List[Dict] = []
    generate_sketchup_collada(list(scene), door_mode="closed", collect=raw)
    out = []
    for r in raw:
        cab = scene[r["cab"]] if 0 <= r["cab"] < len(scene) else {}
        r = dict(r)
        r["name"] = f"{_base_name(r['label'], cab)} (C{r['cab']})"
        r["family"] = {"mat_door": "door", "mat_drawer": "drawer"}.get(r["mat"], "body")
        r["material"] = _material(r, cab)
        dims = sorted((r["w"], r["d"], r["h"]), reverse=True)
        r["dims_txt"] = " × ".join(f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}" for v in dims)
        out.append(r)
    return out


# ───────────────────────────── éclatement ─────────────────────────────────

def _center(p: Dict) -> np.ndarray:
    return np.array([p["x"] + p["w"] / 2, p["y"] + p["d"] / 2, p["z"] + p["h"] / 2])


def explode(panels: List[Dict], strength: float = 1.0) -> None:
    """Ajoute à chaque panneau son décalage `off` (mm) : écarté du centre de son
    caisson le long de son épaisseur, en proportion de sa distance au centre."""
    by_cab = defaultdict(list)
    for p in panels:
        by_cab[p["cab"]].append(p)
    for cab, items in by_cab.items():
        body = [p for p in items if p["role"] == "panel" and p["family"] == "body"] or items
        lo = np.min([[p["x"], p["y"], p["z"]] for p in body], axis=0)
        hi = np.max([[p["x"] + p["w"], p["y"] + p["d"], p["z"] + p["h"]] for p in body], axis=0)
        c = (lo + hi) / 2.0
        size = float(np.max(hi - lo))
        base, k = 0.14 * size * strength, 0.85 * strength
        pull = 0.80 * size * strength
        for p in items:
            off = np.zeros(3)
            role = p["role"]
            if role == "drawer_face":
                off[1] = -(pull + 0.30 * size * strength)
            elif role == "drawer_back":
                off[1] = -pull * 0.62
                off[2] = 0.14 * size * strength
            elif role == "drawer_bottom":
                off[1] = -pull * 0.62
                off[2] = -0.12 * size * strength
            elif role == "plinthe":
                off[1] = -base
                off[2] = -base * 1.2
            else:
                dims = np.array([p["w"], p["d"], p["h"]])
                a = int(np.argmin(dims))                      # axe de l'épaisseur
                if p["family"] == "door" or p["family"] == "drawer":
                    a = 1
                diff = _center(p)[a] - c[a]
                sign = 1.0 if diff >= 0 else -1.0
                if p["family"] in ("door", "drawer"):
                    sign = -1.0                               # vers l'avant
                    diff = -(c[1] - p["y"])
                elif p["name"].startswith("Joue"):
                    pass
                off[a] = sign * (base + k * abs(diff))
            p["off"] = off


def spread_cabinets(panels: List[Dict], margin: float = 300.0) -> None:
    """Vue d'ensemble : chaque caisson éclaté est posé à droite du précédent sur l'écran
    (bas aligné) : les caissons empilés ou voisins ne se recouvrent plus."""
    by_cab = defaultdict(list)
    for p in panels:
        by_cab[p["cab"]].append(p)

    def corners(p):
        x, y, z = p["x"] + p["off"][0], p["y"] + p["off"][1], p["z"] + p["off"][2]
        return [np.array([x + a * p["w"], y + b * p["d"], z + c * p["h"]])
                for a in (0, 1) for b in (0, 1) for c in (0, 1)]

    cursor = None
    for cab in sorted(by_cab):
        items = by_cab[cab]
        rs = [float(np.dot(c, _R)) for p in items for c in corners(p)]
        lo_r, hi_r = min(rs), max(rs)
        lo_z = min(p["z"] + p["off"][2] for p in items)
        target = 0.0 if cursor is None else cursor + margin
        shift = _R * (target - lo_r) + np.array([0.0, 0.0, -lo_z])
        for p in items:
            p["off"] = p["off"] + shift
        cursor = hi_r + (target - lo_r)


# ───────────────────────────── dessin ─────────────────────────────────────

def _project(pt: np.ndarray) -> Tuple[float, float]:
    return float(np.dot(pt, _R)), float(np.dot(pt, _U))


def _faces(p: Dict):
    x0, y0, z0 = p["x"] + p["off"][0], p["y"] + p["off"][1], p["z"] + p["off"][2]
    x1, y1, z1 = x0 + p["w"], y0 + p["d"], z0 + p["h"]
    front = [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]     # y min
    top = [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]       # z max
    left = [(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)]      # x min
    return {"front": front, "top": top, "left": left}


def _visible_anchor(i, order_pos, order, polys, panels):
    """Point d'attache du panneau i : sur sa plus grande face VISIBLE, pris là où
    aucun panneau plus proche de la caméra ne le recouvre."""
    from matplotlib.path import Path
    p = panels[i]
    areas = {"front": p["w"] * p["h"], "top": p["w"] * p["d"], "left": p["d"] * p["h"]}
    nearer = [Path(poly) for j in order[order_pos + 1:] for (_, poly) in polys[j]]
    for fname in sorted(areas, key=areas.get, reverse=True):
        poly = dict(polys[i])[fname]
        quad = np.array(poly)
        cen = quad.mean(axis=0)
        cands = []
        for u in (0.5, 0.25, 0.75, 0.12, 0.88):
            for v in (0.5, 0.25, 0.75, 0.12, 0.88):
                pt = (quad[0] * (1 - u) + quad[1] * u) * (1 - v) + (quad[3] * (1 - u) + quad[2] * u) * v
                cands.append(pt)
        cands = np.array(cands)
        free = np.ones(len(cands), dtype=bool)
        for path in nearer:
            free &= ~path.contains_points(cands)
        if free.any():
            idx = np.where(free)[0]
            best = idx[np.argmin(np.linalg.norm(cands[idx] - cen, axis=1))]
            return tuple(cands[best])
    return tuple(np.mean(dict(polys[i])["front"], axis=0))


def _draw_scene(ax, panels: List[Dict], numbers: Dict[int, str], marker_fs: float):
    order = sorted(range(len(panels)),
                   key=lambda i: -float(np.dot(_center(panels[i]) + panels[i]["off"], _D)))
    pts_all = []
    polys = {}
    for i in order:                                   # du plus loin au plus proche
        p = panels[i]
        cols = _COLORS[p["family"]]
        faces = _faces(p)
        polys[i] = []
        for name, col in zip(("left", "front", "top"), (cols[2], cols[0], cols[1])):
            poly = [_project(np.array(v)) for v in faces[name]]
            polys[i].append((name, poly))
            ax.add_patch(Polygon(poly, closed=True, facecolor=col, edgecolor=_DARK, linewidth=0.5,
                                 joinstyle="round", zorder=2))
            pts_all.extend(poly)
    anchors = {i: _visible_anchor(i, k, order, polys, panels) for k, i in enumerate(order)}
    return anchors, pts_all


def _place_markers(anchors: Dict[int, Tuple[float, float]], bounds, min_gap: float):
    """Repères poussés hors du dessin depuis son centre, puis écartés entre eux."""
    (xmin, xmax, ymin, ymax) = bounds
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    pos = {}
    for i, (ax_, ay_) in anchors.items():
        vx, vy = ax_ - cx, ay_ - cy
        n = math.hypot(vx, vy) or 1.0
        pos[i] = [ax_ + vx / n * min_gap * 3.2, ay_ + vy / n * min_gap * 3.2]
    keys = list(pos)
    for _ in range(80):
        moved = False
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                pa, pb = pos[keys[a]], pos[keys[b]]
                dx, dy = pb[0] - pa[0], pb[1] - pa[1]
                d = math.hypot(dx, dy)
                if d < min_gap:
                    if d < 1e-6:
                        dx, dy, d = 1.0, 0.3, 1.04
                    push = (min_gap - d) / 2 + 0.01
                    ux, uy = dx / d, dy / d
                    pa[0] -= ux * push; pa[1] -= uy * push
                    pb[0] += ux * push; pb[1] += uy * push
                    moved = True
        if not moved:
            break
    return pos


def _render_view(fig, rect, panels: List[Dict], numbers: Dict[int, str], marker_fs: float):
    ax = fig.add_axes(rect)
    ax.set_aspect("equal")
    ax.axis("off")
    anchors, pts = _draw_scene(ax, panels, numbers, marker_fs)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    bounds = (min(xs), max(xs), min(ys), max(ys))
    span = max(bounds[1] - bounds[0], bounds[3] - bounds[2])
    gap = span * (0.032 if len(panels) <= 30 else 0.026)
    pos = _place_markers(anchors, bounds, gap)
    for i, (mx, my) in pos.items():
        ax_, ay_ = anchors[i]
        ax.plot([ax_, mx], [ay_, my], color="white", linewidth=1.8, zorder=4, solid_capstyle="round")
        ax.plot([ax_, mx], [ay_, my], color="#C85529", linewidth=0.7, zorder=5, solid_capstyle="round")
        ax.plot([ax_], [ay_], marker="o", markersize=3.4, markerfacecolor="#C85529",
                markeredgecolor="white", markeredgewidth=0.6, zorder=6)
    for i, (mx, my) in pos.items():
        ax.text(mx, my, numbers[i], ha="center", va="center", fontsize=marker_fs, color="white",
                fontweight="bold", zorder=8,
                bbox=dict(boxstyle="circle,pad=0.22", fc="#C85529", ec="none"))
    allx = xs + [p[0] for p in pos.values()]
    ally = ys + [p[1] for p in pos.values()]
    pad = span * 0.04
    ax.set_xlim(min(allx) - pad, max(allx) + pad)
    ax.set_ylim(min(ally) - pad, max(ally) + pad)
    return ax


def _table(fig, items: List[Tuple[str, str, str, str]], top: float, bottom: float, title: Optional[str] = None):
    """Tableau repère / désignation / dimensions / matière, en colonnes."""
    rows = len(items)
    avail = top - bottom
    row_h = 0.0125
    per_col = max(1, int(avail / row_h))
    ncols = max(1, math.ceil(rows / per_col))
    if ncols > 3:
        ncols = 3
        per_col = math.ceil(rows / 3)
        row_h = avail / per_col
    fs = 6.2 if row_h >= 0.0118 else max(4.6, 6.2 * row_h / 0.0118)
    col_w = 0.94 / ncols
    for c in range(ncols):
        x0 = 0.03 + c * col_w
        chunk = items[c * per_col:(c + 1) * per_col]
        if c == 0 and False:
            pass
        for r, (num, name, dims, mat) in enumerate(chunk):
            y = top - (r + 0.5) * row_h
            fig.text(x0, y, num, fontsize=fs, fontweight="bold", color="#C85529", va="center", ha="left")
            fig.text(x0 + 0.032, y, name, fontsize=fs, color=_DARK, va="center", ha="left")
            fig.text(x0 + col_w - 0.012, y, dims + (f"  ·  {mat[:16]}" if mat and ncols < 3 else ""),
                     fontsize=fs, color=_GREY_TXT, va="center", ha="right")
            if r:
                fig.add_artist(plt.Line2D([x0, x0 + col_w - 0.012], [y + row_h / 2, y + row_h / 2],
                                          transform=fig.transFigure, color="#E2E2E2", linewidth=0.4))


def _header(fig, project: str, client: str, subtitle: str, date_str: str):
    fig.text(0.03, 0.955, project or "Projet", fontsize=13, fontweight="bold", color=_DARK, ha="left", va="center")
    fig.text(0.03, 0.927, "Vue éclatée" + (f" — {client}" if client else ""), fontsize=8.5,
             color=_GREY_TXT, ha="left", va="center")
    fig.text(0.97, 0.955, subtitle, fontsize=11, fontweight="bold", color=_DARK, ha="right", va="center")
    fig.text(0.97, 0.927, date_str, fontsize=8, color="#9A9A9A", ha="right", va="center")
    fig.add_artist(plt.Line2D([0.03, 0.97], [0.907, 0.907], transform=fig.transFigure,
                              color="#CCCCCC", linewidth=0.6))


def _page(pdf: PdfPages, panels: List[Dict], project: str, client: str, subtitle: str,
          numbers: Dict[int, str], note: str = "", logo=None, with_table: bool = True):
    fig = plt.figure(figsize=(FIG_W, FIG_H))
    fig.patch.set_facecolor("white")
    date_str = datetime.date.today().strftime("%d/%m/%Y")
    _header(fig, project, client, subtitle, date_str)
    bar_top = _MARGIN_B + _BAR_H
    n = len(panels)
    items = [(numbers[i], panels[i]["name"], panels[i]["dims_txt"], panels[i]["material"]) for i in range(n)]
    if with_table:
        rows_needed = math.ceil(n / 3)
        table_h = min(0.36, max(0.12, rows_needed * 0.0125 + 0.02))
    else:
        table_h = 0.03
    view_bottom = bar_top + 0.02 + table_h
    marker_fs = 6.0 if n <= 24 else (5.0 if n <= 45 else 4.2)
    _render_view(fig, [0.03, view_bottom, 0.94, 0.9 - view_bottom], panels, numbers, marker_fs)
    if with_table:
        _table(fig, items, top=bar_top + 0.015 + table_h, bottom=bar_top + 0.015)
    if note:
        fig.text(0.03, bar_top + 0.012, note, fontsize=6.5, color=_GREY_TXT, ha="left", va="center")
    _draw_kobo_bar(fig, logo)
    pdf.savefig(fig, dpi=150)
    plt.close(fig)


# ───────────────────────────── export ─────────────────────────────────────

def generate_exploded_view_pdf(scene: Sequence[Dict], project_name: str = "", client: str = "") -> Optional[bytes]:
    """PDF « vue éclatée » : vue d'ensemble puis une page par caisson."""
    scene = [c for c in scene if isinstance(c, dict)]
    panels = collect_panels(scene)
    if not panels:
        return None
    logo = _load_kobo_logo()
    cab_ids = sorted({p["cab"] for p in panels})
    out = io.BytesIO()
    with PdfPages(out) as pdf:
        # --- vue d'ensemble -------------------------------------------------
        over = [dict(p) for p in panels]
        explode(over, strength=0.9)
        if len(cab_ids) > 1:
            spread_cabinets(over)
        over_nums = {}
        per_cab = defaultdict(int)
        for i, p in enumerate(over):
            per_cab[p["cab"]] += 1
            over_nums[i] = f"{p['cab']}.{per_cab[p['cab']]}" if len(cab_ids) > 1 else str(per_cab[p["cab"]])
        big = len(over) > 66
        _page(pdf, over, project_name, client, "Ensemble du meuble", over_nums,
              note=("Caissons présentés côte à côte (pas à leur position réelle) ; détail de chaque panneau page par caisson." if len(cab_ids) > 1 else ""),
              logo=logo, with_table=not big)
        # --- une page par caisson -----------------------------------------------
        for cab in cab_ids:
            items = [dict(p) for p in panels if p["cab"] == cab]
            explode(items, strength=1.0)
            nums = {i: str(i + 1) for i in range(len(items))}
            _page(pdf, items, project_name, client, f"Caisson {cab}", nums, logo=logo)
    return out.getvalue()
