"""Règles de contrôle des feuilles d'usinage."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .expected import CORE_KINDS, Caisson, Thicknesses, expected_for, piece_kind
from .reader import Circle, SheetData

ERR, WARN, INFO = "error", "warn", "info"

TOL_DIM = 0.6          # mm : écart toléré sur une dimension de pièce
TOL_DIAM = 0.5         # mm : écart entre diamètre dessiné et repère
TOL_COTE = 0.7         # mm : cote retrouvée sur le dessin
MIN_WALL = 3.0         # mm : matière mini entre un trou de face et le bord
MIN_WEB = 2.0          # mm : matière mini entre deux trous


@dataclass
class Finding:
    sev: str
    page: Optional[int]
    piece: str
    rule: str
    message: str


def _fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _label(sh: SheetData) -> str:
    c = sh.title.get("CORPS DE MEUBLE", "")
    return f"{c} - {sh.designation}".strip(" -") or f"page {sh.page}"


def _dist_point_triangle(px: float, py: float, tri) -> float:
    """Distance d'un point à un triangle plein (0 s'il est dedans)."""
    def seg(ax, ay, bx, by):
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
    (x1, y1), (x2, y2), (x3, y3) = tri
    d = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if d:
        a = ((y2 - y3) * (px - x3) + (x3 - x2) * (py - y3)) / d
        b = ((y3 - y1) * (px - x3) + (x1 - x3) * (py - y3)) / d
        if a >= 0 and b >= 0 and 1 - a - b >= 0:
            return 0.0
    return min(seg(x1, y1, x2, y2), seg(x2, y2, x3, y3), seg(x3, y3, x1, y1))


def holes_mm(sh: SheetData):
    """Trous en mm : (face, tranches). Face : (x, y, d) depuis le coin haut-gauche
    de la pièce ; tranche : (x, y, d, bande) avec x,y repérés sur la pièce."""
    s, m = sh.scale, sh.main
    face, edge, orphan = [], [], []
    for c in sh.circles:
        if m.contains(c.x, c.y):
            face.append(((c.x - m.x0) / s, (c.y - m.y0) / s, c.d / s))
            continue
        for i, r in enumerate(sh.strips):
            if r.contains(c.x, c.y, pad=1.0):
                edge.append(((c.x - m.x0) / s, (c.y - m.y0) / s, c.d / s, i))
                break
        else:
            orphan.append(c)
    return face, edge, orphan


def check_sheet(sh: SheetData, caissons: Dict[int, Caisson], th: Thicknesses) -> List[Finding]:
    out: List[Finding] = []
    lab = _label(sh)

    def add(sev, rule, msg):
        out.append(Finding(sev, sh.page, lab, rule, msg))

    for p in sh.problems:
        add(ERR, "lecture", p)
    if sh.main is None or not sh.scale:
        return out

    L, W, T = sh.L_mm, sh.W_mm, sh.T_mm
    kind = piece_kind(sh.designation)
    cab = caissons.get(sh.caisson) if sh.caisson is not None else None

    # --- 1. dimensions de la pièce face aux dimensions du meuble --------------------
    if kind and cab is None:
        add(WARN, "dimensions", f"{sh.title.get('CORPS DE MEUBLE', 'Caisson ?')} absent de la saisie : "
                                "dimensions non contrôlées.")
    elif kind and cab:
        exp = expected_for(kind, cab, th)
        if exp and exp.dims:
            a, b = exp.dims
            ok_dir = abs(L - a) <= TOL_DIM and abs(W - b) <= TOL_DIM
            ok_swap = abs(L - b) <= TOL_DIM and abs(W - a) <= TOL_DIM
            if ok_dir or ok_swap:
                add(INFO, "dimensions", f"{_fmt(L)} x {_fmt(W)} mm conforme au meuble "
                                        f"(attendu {_fmt(a)} x {_fmt(b)}).")
            else:
                add(ERR, "dimensions", f"Pièce {_fmt(L)} x {_fmt(W)} mm alors que le meuble donne "
                                       f"{_fmt(a)} x {_fmt(b)} mm.")
        elif exp and exp.bound:
            ba, bb = exp.bound
            lo, hi = sorted((L, W))
            # étagère : profondeur = bb ; longueur <= ba
            ok = (abs(L - bb) <= TOL_DIM and L >= 0 and W <= ba + TOL_DIM) or \
                 (abs(W - bb) <= TOL_DIM and L <= ba + TOL_DIM)
            if ok:
                add(INFO, "dimensions", f"{_fmt(L)} x {_fmt(W)} mm compatible (profondeur {_fmt(bb)}, "
                                        f"longueur <= {_fmt(ba)}).")
            else:
                add(ERR, "dimensions", f"{exp.label} {_fmt(L)} x {_fmt(W)} mm : profondeur attendue "
                                       f"{_fmt(bb)} mm et longueur <= {_fmt(ba)} mm.")
        if exp and exp.thickness and T:
            if abs(T - exp.thickness) > 0.1:
                add(ERR, "épaisseur", f"Épaisseur cotée {_fmt(T)} mm, attendue {_fmt(exp.thickness)} mm.")
    elif not kind:
        add(INFO, "dimensions", f"{_fmt(L)} x {_fmt(W)} mm : type de pièce sans contrôle par les "
                                "dimensions globales (contrôles de perçage appliqués).")

    # --- 2. trous ---------------------------------------------------------------------
    face, edge, orphan = holes_mm(sh)
    for c in orphan:
        add(WARN, "trou", f"Cercle de Ø{_fmt(c.d / sh.scale)} mm hors de la pièce et de ses vues de tranche.")

    for i, (x, y, d) in enumerate(face):
        r = d / 2.0
        gaps = {"gauche": x - r, "droit": L - x - r, "haut": y - r, "bas": W - y - r}
        side, gap = min(gaps.items(), key=lambda kv: kv[1])
        pos = f"trou Ø{_fmt(d)} à ({_fmt(x)} ; {_fmt(y)}) mm du coin haut-gauche"
        if gap < -0.5:
            add(ERR, "trou", f"{pos.capitalize()} : dépasse du bord {side} de la pièce.")
        elif gap < MIN_WALL:
            add(WARN, "trou", f"{pos.capitalize()} : seulement {_fmt(gap)} mm de matière vers le bord {side}.")
    for i in range(len(face)):
        for j in range(i + 1, len(face)):
            (x1, y1, d1), (x2, y2, d2) = face[i], face[j]
            web = math.hypot(x1 - x2, y1 - y2) - (d1 + d2) / 2.0
            if web < 0:
                add(ERR, "trou", f"Deux trous de face se chevauchent : Ø{_fmt(d1)} en ({_fmt(x1)} ; {_fmt(y1)}) "
                                 f"et Ø{_fmt(d2)} en ({_fmt(x2)} ; {_fmt(y2)}).")
            elif web < MIN_WEB:
                add(WARN, "trou", f"Deux trous de face très proches ({_fmt(web)} mm de matière) : Ø{_fmt(d1)} en "
                                  f"({_fmt(x1)} ; {_fmt(y1)}) et Ø{_fmt(d2)} en ({_fmt(x2)} ; {_fmt(y2)}).")

    # tranche : le trou doit être centré dans l'épaisseur et y tenir
    if T:
        for (x, y, d, bi) in edge:
            r = sh.strips[bi]
            s = sh.scale
            # position dans l'épaisseur, dans le sens étroit de la bande
            if r.w < r.h:    # bande verticale
                across = ((x * s + sh.main.x0) - r.x0) / r.w
            else:
                across = ((y * s + sh.main.y0) - r.y0) / r.h
            if d > T - 2 * 2:
                add(ERR, "trou", f"Trou de tranche Ø{_fmt(d)} trop gros pour une épaisseur de {_fmt(T)} mm.")
            if abs(across - 0.5) > 0.06:
                add(WARN, "trou", f"Trou de tranche Ø{_fmt(d)} non centré dans l'épaisseur de la pièce.")

    # --- 3. repères de perçage <-> trous dessinés -----------------------------------------
    drawn = Counter(round(d * 2) / 2 for (_, _, d) in face) + Counter(round(c[2] * 2) / 2 for c in edge)
    tranche_n = Counter(round(c[2] * 2) / 2 for c in edge)
    face_n = Counter(round(d * 2) / 2 for (_, _, d) in face)
    callout_total = Counter()
    for co in sh.callouts:
        callout_total[round(co.d * 2) / 2] += co.count
    for dia in sorted(set(drawn) | set(callout_total)):
        n_draw, n_call = drawn.get(dia, 0), callout_total.get(dia, 0)
        if n_call == 0:
            add(WARN, "repère", f"{n_draw} trou(s) Ø{_fmt(dia)} dessiné(s) sans repère de perçage (Ø / profondeur).")
        elif n_draw != n_call:
            add(ERR, "repère", f"Repères : {n_call} trou(s) Ø{_fmt(dia)}, mais {n_draw} dessiné(s).")
    # profondeur : un trou de face ne peut pas être plus profond que l'épaisseur
    if T:
        for co in sh.callouts:
            if co.depth is None:
                continue
            dia = round(co.d * 2) / 2
            if co.depth > T + 0.01:
                if face_n.get(dia, 0) and not tranche_n.get(dia, 0):
                    add(ERR, "profondeur", f"Trou Ø{_fmt(co.d)} prof. {_fmt(co.depth)} mm percé en face d'un "
                                           f"panneau de {_fmt(T)} mm : il traverse la pièce.")

    # --- 4. cotes <-> géométrie -------------------------------------------------------------
    s = sh.scale
    m = sh.main
    ref_x = {0.0, L}
    ref_y = {0.0, W}
    for (x, y, d) in face:
        ref_x.add(round(x, 2)); ref_y.add(round(y, 2))
    for (x, y, d, bi) in edge:
        ref_x.add(round(x, 2)); ref_y.add(round(y, 2))
    # position des tranches (bords des bandes) : cotes d'épaisseur
    skip = {round(v, 2) for v in (L, W)}
    if T:
        skip.add(round(T, 2))
    zone_bottom = 0.82 * 841.0
    for t in (sh.texts if kind else []):     # tiroirs, portes... : retraits/feuillures non repérés
        if t.value is None or t.y > zone_bottom or t.value in (0,):
            continue
        if round(t.value, 2) in skip:
            continue
        refs = ref_x if t.horizontal else ref_y
        ok = any(abs(abs(b - a) - t.value) <= TOL_COTE for a in refs for b in refs)
        if not ok:
            # une cote d'épaisseur d'une tranche, ou un petit retrait : tolérer les valeurs <= épaisseur
            if T and t.value <= T + 0.01:
                continue
            add(WARN, "cote", f"Cote {_fmt(t.value)} mm sans correspondance avec les trous ni les bords du dessin.")

    # --- 5. triangles d'orientation ----------------------------------------------------------
    if not sh.triangles:
        add(ERR, "orientation", "Triangle d'orientation absent de la feuille.")
    else:
        for tr in sh.triangles:
            for c in sh.circles:
                if _dist_point_triangle(c.x, c.y, tr) < c.d / 2.0:
                    add(ERR, "orientation", "Un triangle d'orientation recouvre un trou.")
                    break
    return out


def check_document(sheets: Sequence[SheetData], caissons: Dict[int, Caisson],
                   th: Thicknesses) -> List[Finding]:
    out: List[Finding] = []
    for sh in sheets:
        out.extend(check_sheet(sh, caissons, th))

    # numérotation des feuillets
    nums = []
    for sh in sheets:
        f = sh.title.get("FEUILLET", "")
        if "/" in f:
            try:
                a, b = f.split("/")
                nums.append((int(a), int(b)))
            except ValueError:
                pass
    if nums:
        total = nums[0][1]
        if total != len(sheets):
            out.append(Finding(WARN, None, "Document", "feuillets",
                               f"Le cartouche annonce {total} feuilles, le PDF en contient {len(sheets)}."))

    # pièces de base présentes pour chaque caisson déclaré
    seen = {}
    for sh in sheets:
        k = piece_kind(sh.designation)
        if k and sh.caisson is not None:
            seen.setdefault(sh.caisson, set()).add(k)
    names = {"traverse_bas": "Traverse Bas", "traverse_haut": "Traverse Haut", "montant_gauche": "Montant Gauche",
             "montant_droit": "Montant Droit", "fond": "Fond"}
    for idx in caissons:
        present = seen.get(idx, set())
        if not present and not any(sh.caisson == idx for sh in sheets):
            out.append(Finding(WARN, None, f"Caisson {idx}", "pièces", "Aucune feuille pour ce caisson dans le PDF."))
            continue
        for k in CORE_KINDS:
            if k not in present:
                out.append(Finding(WARN, None, f"Caisson {idx}", "pièces",
                                   f"Pas de feuille « {names[k]} » (normal seulement si cette pièce n'existe pas)."))

    # montants gauche / droit : mêmes perçages (symétriques)
    by = {}
    for sh in sheets:
        k = piece_kind(sh.designation)
        if k in ("montant_gauche", "montant_droit") and sh.caisson is not None and sh.scale:
            face, edge, _ = holes_mm(sh)
            sig = (len(face), len(edge), tuple(sorted(Counter(round(d) for (_, _, d) in face).items())))
            by.setdefault(sh.caisson, {})[k] = (sh, sig)
    for idx, d in by.items():
        if len(d) == 2 and d["montant_gauche"][1] != d["montant_droit"][1]:
            g, r = d["montant_gauche"], d["montant_droit"]
            out.append(Finding(WARN, g[0].page, f"Caisson {idx} - Montants", "symétrie",
                               f"Montant gauche et droit n'ont pas les mêmes perçages "
                               f"({g[1][0]} trous de face / {g[1][1]} de tranche contre "
                               f"{r[1][0]} / {r[1][1]})."))
    return out


def verdict(findings: Sequence[Finding]) -> Tuple[str, int, int]:
    e = sum(1 for f in findings if f.sev == ERR)
    w = sum(1 for f in findings if f.sev == WARN)
    state = "À CORRIGER" if e else ("À VÉRIFIER" if w else "CONFORME")
    return state, e, w
