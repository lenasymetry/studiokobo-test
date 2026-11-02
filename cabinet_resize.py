"""Mise à jour des éléments intérieurs quand les dimensions d'un caisson changent.

Principe : les épaisseurs ne bougent pas, seul l'espace LIBRE entre les pièces
est étiré ou réduit dans la même proportion. Un élément au milieu reste au
milieu, des étagères régulièrement espacées le restent, et un double montant
reste collé.

Deux niveaux par axe, pour que les bords des zones restent alignés :
- X : les montants secondaires d'abord (ils font les colonnes), puis, dans
  chaque colonne, les étagères verticales à la même hauteur que l'élément ;
- Y : les étagères qui traversent un montant d'abord, puis, dans chaque
  colonne, les étagères propres à cette colonne.

Repères (voir `calculate_all_zones_2d`) : x depuis le bord gauche extérieur du
caisson ; y « extérieur » depuis le bas du caisson (zones, tiroirs, portes
importées, tringles) ; y « intérieur » depuis le dessus de la traverse basse
(`height` des étagères, `bottom_y` / `top_y` des montants et étagères verticales).
"""

import copy

from machining_logic import compute_drawer_stack_layout

TOL_MM = 1.0


def _merge(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + 0.01:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _gap_anchors(lo, hi, lo2, hi2, solids):
    """Ancres (ancien, nouveau) : solides de largeur fixe, vides mis à l'échelle."""
    solids = _merge([(max(lo, a), min(hi, b)) for a, b in solids if min(hi, b) > max(lo, a)])
    solid_w = sum(b - a for a, b in solids)
    free, free2 = (hi - lo) - solid_w, (hi2 - lo2) - solid_w
    k = max(0.01, free2 / free) if free > 1e-6 else 1.0
    anchors, cur, prev = [(lo, lo2)], lo2, lo
    for a, b in solids:
        cur += (a - prev) * k
        anchors.append((a, cur))
        cur += b - a
        anchors.append((b, cur))
        prev = b
    anchors.append((hi, hi2))
    return anchors


def _interp(anchors, v):
    for (a0, n0), (a1, n1) in zip(anchors, anchors[1:]):
        if a0 <= v <= a1:
            return n0 if a1 - a0 < 1e-9 else n0 + (v - a0) * (n1 - n0) / (a1 - a0)
    return v


class _Axis:
    """Correspondance ancien -> nouveau sur un axe du caisson.

    [0, ext] = dimension extérieure, [lo, hi] = intérieur (entre les parois)."""

    def __init__(self, ext, lo, hi, ext2, lo2, hi2, primary):
        self.ext, self.lo, self.hi = ext, lo, hi
        self.ext2, self.lo2, self.hi2 = ext2, lo2, hi2
        self.primary = _merge(primary)
        self.anchors1 = _gap_anchors(lo, hi, lo2, hi2, self.primary)

    def _outer(self, v):
        if v <= 0.0:
            return v
        if v < self.lo:
            return v * self.lo2 / self.lo if self.lo > 0 else v
        if v >= self.ext:
            return v + self.ext2 - self.ext
        span = self.ext - self.hi
        return self.hi2 + (v - self.hi) * ((self.ext2 - self.hi2) / span if span > 0 else 1.0)

    def map(self, v, secondary=()):
        v = float(v)
        if v < self.lo or v > self.hi:
            return self._outer(v)
        anchors = self.anchors1
        if secondary:
            # Chaque vide entre deux solides primaires garde ses bornes
            # (déjà placées) et redistribue ses solides secondaires.
            for (g0, n0), (g1, n1) in zip(anchors[0::2], anchors[1::2]):
                if g0 - TOL_MM <= v <= g1 + TOL_MM:
                    inside = [(a, b) for a, b in secondary if a >= g0 - 0.01 and b <= g1 + 0.01]
                    if inside:
                        anchors = _gap_anchors(g0, g1, n0, n1, inside)
                    break
        return _interp(anchors, v)


def _overlap(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0) > TOL_MM


def rescale_cabinet_contents(cabinet, old_dims):
    """Replace les éléments de `cabinet` (dims déjà mises à jour) depuis `old_dims`."""
    new_dims = cabinet['dims']
    L, H = float(old_dims['L_raw']), float(old_dims['H_raw'])
    t_lr, t_tb = float(old_dims['t_lr_raw']), float(old_dims['t_tb_raw'])
    L2, H2 = float(new_dims['L_raw']), float(new_dims['H_raw'])
    t_lr2, t_tb2 = float(new_dims['t_lr_raw']), float(new_dims['t_tb_raw'])
    if (L, H, t_lr, t_tb) == (L2, H2, t_lr2, t_tb2):
        return

    dividers = [d for d in cabinet.get('vertical_dividers') or [] if not d.get('_preview')]
    vshelves = [v for v in cabinet.get('vertical_shelves') or [] if not v.get('_preview')]
    shelves = [s for s in cabinet.get('shelves') or [] if not s.get('_preview')]
    inner_h = H - 2.0 * t_tb

    def div_x(d):
        th = float(d.get('thickness', 19.0))
        return float(d['position_x']) - th / 2.0, float(d['position_x']) + th / 2.0

    def div_y(d):
        if d.get('_force_full_height') or d.get('bottom_y') is None or d.get('top_y') is None:
            return t_tb, H - t_tb
        return t_tb + float(d['bottom_y']), t_tb + float(d['top_y'])

    def vs_y(v):
        return t_tb + float(v.get('bottom_y', 0.0)), t_tb + float(v.get('top_y', inner_h))

    def shelf_x(s):
        x0, w = s.get('stored_shelf_x_start_mm'), s.get('stored_shelf_width_mm')
        if x0 is None or w is None or float(w) <= 0:
            return t_lr, L - t_lr
        return float(x0), float(x0) + float(w)

    def shelf_y(s):
        y0 = t_tb + float(s.get('height', 0.0))
        return y0, y0 + float(s.get('thickness', 19.0))

    div_centers = [float(d['position_x']) for d in dividers]
    primary_sh = [s for s in shelves if any(shelf_x(s)[0] + TOL_MM < c < shelf_x(s)[1] - TOL_MM for c in div_centers)]
    column_sh = [s for s in shelves if s not in primary_sh]

    X = _Axis(L, t_lr, L - t_lr, L2, t_lr2, L2 - t_lr2, [div_x(d) for d in dividers])
    Y = _Axis(H, t_tb, H - t_tb, H2, t_tb2, H2 - t_tb2, [shelf_y(s) for s in primary_sh])

    def _vs_x(v_):
        th = float(v_.get('thickness', 19.0))
        return float(v_['position_x']) - th / 2.0, float(v_['position_x']) + th / 2.0

    def mx(v, y0, y1):
        """x d'un élément qui occupe la hauteur [y0, y1] (repère extérieur)."""
        return X.map(v, [_vs_x(o) for o in vshelves if _overlap(*vs_y(o), y0, y1)])

    def my(v, x0, x1):
        """y extérieur d'un élément qui occupe la largeur [x0, x1]."""
        return Y.map(v, [shelf_y(o) for o in column_sh if _overlap(*shelf_x(o), x0, x1)])

    def map_zone(z):
        if not isinstance(z, dict) or not all(k in z for k in ('x_min', 'x_max', 'y_min', 'y_max')):
            return z
        x0, x1, y0, y1 = (float(z[k]) for k in ('x_min', 'x_max', 'y_min', 'y_max'))
        out = dict(z)
        out['x_min'], out['x_max'] = mx(x0, y0, y1), mx(x1, y0, y1)
        out['y_min'], out['y_max'] = my(y0, x0, x1), my(y1, x0, x1)
        return out

    updates = []  # (objet, clé, valeur) appliqués à la fin : tout est calculé sur l'ancien état

    for d in dividers:
        x0, x1 = div_x(d)
        updates.append((d, 'position_x', X.map(float(d['position_x']))))
        if d.get('bottom_y') is not None and d.get('top_y') is not None:
            y0, y1 = div_y(d)
            updates.append((d, 'bottom_y', max(0.0, my(y0, x0, x1) - t_tb2)))
            updates.append((d, 'top_y', my(y1, x0, x1) - t_tb2))
        if d.get('stored_zone_coords'):
            updates.append((d, 'stored_zone_coords', map_zone(d['stored_zone_coords'])))

    for v in vshelves:
        th = float(v.get('thickness', 19.0))
        y0, y1 = vs_y(v)
        cx = float(v['position_x'])
        x0, x1 = cx - th / 2.0, cx + th / 2.0
        updates.append((v, 'position_x', mx(cx, y0, y1)))
        updates.append((v, 'bottom_y', max(0.0, my(y0, x0, x1) - t_tb2)))
        updates.append((v, 'top_y', my(y1, x0, x1) - t_tb2))
        if v.get('stored_zone_coords'):
            updates.append((v, 'stored_zone_coords', map_zone(v['stored_zone_coords'])))

    for s in shelves:
        x0, x1 = shelf_x(s)
        y0, y1 = shelf_y(s)
        new_y0 = Y.map(y0) if s in primary_sh else my(y0, x0, x1)
        updates.append((s, 'height', new_y0 - t_tb2))
        if s.get('stored_shelf_x_start_mm') is not None and s.get('stored_shelf_width_mm') is not None:
            nx0, nx1 = mx(x0, y0, y1), mx(x1, y0, y1)
            updates.append((s, 'stored_shelf_x_start_mm', nx0))
            updates.append((s, 'stored_shelf_width_mm', nx1 - nx0))
        if s.get('stored_zone_coords'):
            updates.append((s, 'stored_zone_coords', map_zone(s['stored_zone_coords'])))

    # Tiroirs : un assemblage empilé est recalculé dans sa zone redimensionnée
    # (faces égales, 2 mm entre elles) ; un tiroir seul suit sa zone.
    drawers = [d for d in cabinet.get('drawers') or [] if not d.get('_preview')]
    old_cab = dict(cabinet, dims=dict(new_dims, **{k: old_dims[k] for k in ('L_raw', 'H_raw', 't_lr_raw', 't_tb_raw')}))
    groups = {}
    for d in drawers:
        z = d.get('stored_zone_coords')
        key = tuple(round(float(z[k]), 2) for k in ('x_min', 'x_max', 'y_min', 'y_max')) if z else None
        groups.setdefault((key, bool(d.get('_applique_mode'))), []).append(d)
    new_cab = dict(cabinet)
    for (key, applique), group in groups.items():
        zone_old = dict(zip(('x_min', 'x_max', 'y_min', 'y_max'), key)) if key else None
        zone_new = map_zone(zone_old) if zone_old else None
        group = sorted(group, key=lambda d: float(d.get('drawer_bottom_offset', 0.0)))
        layout_old = compute_drawer_stack_layout(old_cab, zone_old, len(group), applique=applique)
        is_stack = len(group) > 1 and all(
            abs(float(d.get('drawer_bottom_offset', 0.0)) - b) <= TOL_MM
            and abs(float(d.get('drawer_face_H_raw', 0.0)) - h) <= TOL_MM
            for d, (b, h) in zip(group, layout_old))
        if is_stack:
            for d, (b, h) in zip(group, compute_drawer_stack_layout(new_cab, zone_new, len(group), applique=applique)):
                updates.append((d, 'drawer_bottom_offset', b))
                updates.append((d, 'drawer_face_H_raw', h))
        else:
            x0, x1 = (zone_old['x_min'], zone_old['x_max']) if zone_old else (t_lr, L - t_lr)
            for d in group:
                b = float(d.get('drawer_bottom_offset', 0.0))
                top = b + float(d.get('drawer_face_H_raw', 0.0))
                nb, nt = my(b, x0, x1), my(top, x0, x1)
                updates.append((d, 'drawer_bottom_offset', nb))
                updates.append((d, 'drawer_face_H_raw', max(10.0, nt - nb)))
        for d in group:
            if zone_new:
                updates.append((d, 'stored_zone_coords', zone_new))
            if d.get('x_left_mm') is not None and d.get('x_right_mm') is not None:
                b = float(d.get('drawer_bottom_offset', 0.0))
                top = b + float(d.get('drawer_face_H_raw', 0.0))
                updates.append((d, 'x_left_mm', mx(float(d['x_left_mm']), b, top)))
                updates.append((d, 'x_right_mm', mx(float(d['x_right_mm']), b, top)))

    for door in cabinet.get('imported_doors') or []:
        b = float(door.get('door_bottom_offset', 0.0))
        top = b + float(door.get('door_face_H_raw', 0.0))
        xl, xr = float(door.get('x_left_mm', 0.0)), float(door.get('x_right_mm', 0.0))
        nb, nt = my(b, xl, xr), my(top, xl, xr)
        updates.append((door, 'x_left_mm', mx(xl, b, top)))
        updates.append((door, 'x_right_mm', mx(xr, b, top)))
        updates.append((door, 'door_bottom_offset', nb))
        updates.append((door, 'door_face_H_raw', max(10.0, nt - nb)))
        if door.get('stored_zone_coords'):
            updates.append((door, 'stored_zone_coords', map_zone(door['stored_zone_coords'])))

    for rail in cabinet.get('rails') or []:
        if rail.get('zone_coords'):
            updates.append((rail, 'zone_coords', map_zone(rail['zone_coords'])))

    for obj, key, value in updates:
        obj[key] = round(value, 2) if isinstance(value, float) else copy.deepcopy(value)
