import math

from project_definitions import CACHE_PIED_FLOOR_CLEARANCE, cache_pied_drop_mm

def calculate_origins_recursively(scene_cabinets, unit_factor):
    """
    Calcule les origines absolues de chaque caisson dans la scène.
    
    Prend en compte les relations parent-enfant et les directions d'attachement :
    - 'left' : à gauche du caisson parent (X négatif)
    - 'right' : à droite du caisson parent (X positif)
    - 'up' : au-dessus du caisson parent (Z positif)
    """
    abs_origins = []
    
    # Trouver le caisson central (sans parent)
    central_index = None
    for i, cab in enumerate(scene_cabinets):
        if cab.get('parent_index') is None:
            central_index = i
            break
    
    if central_index is None:
        # Pas de caisson central, placer tous les caissons en ligne
        current_x = 0.0
        for cab in scene_cabinets:
            abs_origins.append((current_x, 0.0, 0.0))
            current_x += cab['dims']['L_raw'] * unit_factor
        return abs_origins
    
    # Calculer les origines récursivement en partant du caisson central
    # Utiliser un dictionnaire pour mémoriser les positions calculées
    position_cache = {}
    
    def calculate_position(cab_index):
        # Si déjà calculé, retourner la valeur en cache
        if cab_index in position_cache:
            return position_cache[cab_index]
        
        cab = scene_cabinets[cab_index]
        
        if cab.get('parent_index') is None:
            # Caisson central : origine à (0, 0, 0)
            pos = (0.0, 0.0, 0.0)
            position_cache[cab_index] = pos
            return pos
        
        # Caisson attaché : calculer la position relative au parent
        parent_index = cab['parent_index']
        
        # Vérifier que le parent existe
        if parent_index < 0 or parent_index >= len(scene_cabinets):
            # Parent invalide : placer à (0, 0, 0)
            pos = (0.0, 0.0, 0.0)
            position_cache[cab_index] = pos
            return pos
        
        # Calculer récursivement la position du parent
        parent_pos = calculate_position(parent_index)
        parent_cab = scene_cabinets[parent_index]
        attachment_dir = cab.get('attachment_dir', 'right')
        
        parent_L = parent_cab['dims']['L_raw'] * unit_factor
        parent_H = parent_cab['dims']['H_raw'] * unit_factor
        cab_L = cab['dims']['L_raw'] * unit_factor
        
        if attachment_dir == 'left':
            # À gauche : X négatif
            pos = (parent_pos[0] - cab_L, parent_pos[1], parent_pos[2])
        elif attachment_dir == 'right':
            # À droite : X positif
            pos = (parent_pos[0] + parent_L, parent_pos[1], parent_pos[2])
        elif attachment_dir == 'up':
            # Au-dessus : Z positif
            pos = (parent_pos[0], parent_pos[1], parent_pos[2] + parent_H)
        else:
            # Par défaut : à droite
            pos = (parent_pos[0] + parent_L, parent_pos[1], parent_pos[2])
        
        # Mettre en cache et retourner
        position_cache[cab_index] = pos
        return pos
    
    # Calculer les positions pour tous les caissons
    for i in range(len(scene_cabinets)):
        pos = calculate_position(i)
        abs_origins.append(pos)
    
    return abs_origins

# ─────────────────────────────────────────────────────────────────────────────
# Portes communes à deux caissons superposés
# ─────────────────────────────────────────────────────────────────────────────
# Un caisson posé sur un autre est un enfant d'`attachment_dir == 'up'` (voir
# `calculate_origins_recursively`). Le caisson DU BAS porte la porte : son
# `door_props['span_up']` indique que le vantail monte aussi devant le caisson
# du dessus. La porte garde toutes les autres règles d'une porte simple (jeu,
# modèle cache-pieds, charnières, chants) — seule la hauteur couverte change.


def cabinet_rests_on_floor(scene_cabinets, cab_index):
    """Le caisson repose-t-il sur le sol ?

    Faux dès qu'un maillon de sa chaîne de parenté est un empilement : un
    caisson posé sur un autre — ou accolé à un caisson lui-même superposé —
    repose sur le meuble, pas au sol. C'est ce qui décide de la plinthe : elle
    n'existe qu'au niveau du sol, une seule pour toute une pile.
    """
    if not (0 <= cab_index < len(scene_cabinets)):
        return False
    seen = set()
    index = cab_index
    while True:
        if index in seen or not (0 <= index < len(scene_cabinets)):
            # Parenté circulaire ou cassée : on ne revendique pas le sol.
            return False
        seen.add(index)
        cab = scene_cabinets[index]
        parent = cab.get('parent_index')
        if parent is None:
            return True
        if cab.get('attachment_dir') == 'up':
            return False
        index = parent


# Plinthe : cotes canoniques. La longueur d'une plinthe est la largeur qu'elle
# habille, moins les deux montants d'extrémité, plus une réserve de pose.
PLINTHE_END_ALLOWANCE = 100.0
PLINTHE_WIDTH = 80.0
PLINTHE_THICKNESS = 19.0
# Deux caissons sont jugés accolés si leurs bords se touchent à ce jeu près.
PLINTHE_JOIN_TOLERANCE = 1.0


def get_plinthe_groups(scene_cabinets):
    """Regroupe les caissons posés au sol en plinthes d'un seul tenant.

    Des caissons alignés et jointifs se partagent UNE plinthe continue courant
    devant toute la façade, et non une plinthe chacun : c'est une seule pièce à
    débiter et à poser. Un changement de matière coupe le groupe — une plinthe
    ne peut pas être de deux décors à la fois.

    Les caissons superposés sont exclus d'office (voir `cabinet_rests_on_floor`).

    Retourne une liste de dicts, dans l'ordre des X croissants :
    `indices` (caissons couverts), `length`, `width`, `thickness`, `material`.
    """
    origins = calculate_origins_recursively(scene_cabinets, 1.0)
    on_floor = []
    for i, cab in enumerate(scene_cabinets):
        if not cabinet_rests_on_floor(scene_cabinets, i):
            continue
        dims = cab.get('dims', {}) or {}
        L_raw = float(dims.get('L_raw', 0.0) or 0.0)
        fileur = float((cab.get('door_props') or {}).get('fileur_width', 0) or 0.0)
        on_floor.append({
            'index': i,
            'x_start': float(origins[i][0]),
            'x_end': float(origins[i][0]) + L_raw,
            # Largeur du meuble telle que saisie par l'utilisateur.
            'width': L_raw,
            't_lr': float(dims.get('t_lr_raw', 19.0) or 0.0),
            'material': str(cab.get('material_body', 'Matière Corps')),
        })
    on_floor.sort(key=lambda c: c['x_start'])

    groups = []
    for cab in on_floor:
        if groups:
            last = groups[-1]
            joined = (abs(cab['x_start'] - last['_x_end']) <= PLINTHE_JOIN_TOLERANCE
                      and cab['material'] == last['material'])
            if joined:
                last['indices'].append(cab['index'])
                last['_width'] += cab['width']
                last['_x_end'] = cab['x_end']
                last['_t_lr_right'] = cab['t_lr']
                continue
        groups.append({
            'indices': [cab['index']],
            'material': cab['material'],
            '_width': cab['width'],
            '_t_lr_left': cab['t_lr'],
            '_t_lr_right': cab['t_lr'],
            '_x_end': cab['x_end'],
        })

    for group in groups:
        # Longueur = largeur du meuble saisie (somme des caissons pour une
        # plinthe commune), sans les joues ni réserve de découpe.
        group['length'] = max(0.0, group.pop('_width'))
        group.pop('_t_lr_left', None)
        group.pop('_t_lr_right', None)
        group.pop('_x_end', None)
        group['width'] = PLINTHE_WIDTH
        group['thickness'] = PLINTHE_THICKNESS
    return groups


def get_plinthe_for_cabinet(scene_cabinets, cab_index):
    """Plinthe portée par ce caisson, ou None.

    Une plinthe commune à plusieurs caissons est rattachée au premier d'entre
    eux (le plus à gauche) : les suivants n'en portent pas, sans quoi la même
    pièce serait débitée plusieurs fois.
    """
    for group in get_plinthe_groups(scene_cabinets):
        if group['indices'] and group['indices'][0] == cab_index:
            return group
    return None


def format_plinthe_labels(indices):
    """Référence et colonne « Caisson » d'une plinthe, simple ou commune."""
    reference = "Plinthe (" + "+".join(f"C{k}" for k in indices) + ")"
    caissons = ", ".join(f"C{k}" for k in indices)
    return reference, caissons


def get_cache_pied_drop(has_feet, foot_height):
    """Descente d'une porte cache-pieds sous le bas du caisson, en mm.

    Descente fixe de `CACHE_PIED_DROP` (70 mm) sous le caisson, quelle que
    soit la hauteur des pieds, limitée pour rester à au moins
    `CACHE_PIED_FLOOR_CLEARANCE` mm du sol. Sans pieds, le caisson pose déjà
    au sol et la porte ne descend pas plus bas que lui.
    """
    if not has_feet:
        return 0.0
    return cache_pied_drop_mm(foot_height)


def get_door_vertical_geometry(door_height_raw, door_props, has_feet=False,
                               foot_height=0.0):
    """Hauteur d'un vantail et position de son bas, en mm.

    Retourne `(hauteur, z_bas)`, `z_bas` étant mesuré depuis le bas du caisson
    (négatif quand la porte descend plus bas que lui).

    * modèle standard   : jeu en haut ET en bas -> hauteur = H - 2 × jeu ;
    * modèle cache-pieds: jeu en haut seulement, le bas descendant devant les
      pieds jusqu'à `CACHE_PIED_FLOOR_CLEARANCE` du sol.

    `door_height_raw` est la hauteur habillée par la porte — celle du caisson,
    ou la somme des deux quand la porte est commune à deux caissons superposés
    (voir `get_door_span_height`).
    """
    height = float(door_height_raw or 0.0)
    gap = float(door_props.get('door_gap', 2.0) or 0.0)
    if door_props.get('door_model') == 'floor_length':
        drop = get_cache_pied_drop(has_feet, foot_height)
        return height + drop - gap, -drop
    return height - 2.0 * gap, gap


def get_stacked_child_index(scene_cabinets, cab_index):
    """Index du caisson posé directement au-dessus de `cab_index`, sinon None."""
    for j, cab in enumerate(scene_cabinets):
        if cab.get('parent_index') == cab_index and cab.get('attachment_dir') == 'up':
            return j
    return None


def door_spans_stacked(scene_cabinets, cab_index):
    """La porte de ce caisson couvre-t-elle aussi le caisson du dessus ?"""
    if not (0 <= cab_index < len(scene_cabinets)):
        return False
    door_props = scene_cabinets[cab_index].get('door_props', {}) or {}
    if not (door_props.get('has_door') and door_props.get('span_up')):
        return False
    return get_stacked_child_index(scene_cabinets, cab_index) is not None


def get_door_span_height(scene_cabinets, cab_index):
    """Hauteur brute (mm) couverte par la porte de `cab_index`.

    C'est la hauteur du caisson, augmentée de celle du caisson du dessus quand
    la porte est commune aux deux.
    """
    if not (0 <= cab_index < len(scene_cabinets)):
        return 0.0
    height = float(scene_cabinets[cab_index].get('dims', {}).get('H_raw', 0.0) or 0.0)
    if door_spans_stacked(scene_cabinets, cab_index):
        child = get_stacked_child_index(scene_cabinets, cab_index)
        height += float(scene_cabinets[child].get('dims', {}).get('H_raw', 0.0) or 0.0)
    return height


def is_covered_by_stacked_door(scene_cabinets, cab_index):
    """Ce caisson est-il déjà habillé par la porte commune du caisson du dessous ?

    Sa propre porte ne doit alors être ni dessinée, ni débitée, ni usinée : elle
    ferait double emploi avec le vantail commun.
    """
    if not (0 <= cab_index < len(scene_cabinets)):
        return False
    cab = scene_cabinets[cab_index]
    parent_index = cab.get('parent_index')
    if parent_index is None or cab.get('attachment_dir') != 'up':
        return False
    return door_spans_stacked(scene_cabinets, parent_index)


def apply_door_spans(scene_cabinets):
    """Inscrit sur chaque caisson l'état résolu de sa porte.

    `door_span_height` : hauteur brute que la porte doit couvrir (mm).
    `door_span_covered` : le caisson est masqué par la porte commune du dessous.

    Ces deux clés dérivées sont recalculées à chaque exécution, de sorte que
    tous les consommateurs (débit, 3D, plans d'usinage, SketchUp) lisent la même
    valeur sans avoir à reparcourir la scène eux-mêmes.
    """
    for i, cab in enumerate(scene_cabinets):
        cab['door_span_height'] = get_door_span_height(scene_cabinets, i)
        cab['door_span_covered'] = is_covered_by_stacked_door(scene_cabinets, i)
    return scene_cabinets


def get_cabinet_door_height_raw(cab):
    """Hauteur brute à utiliser pour la porte d'un caisson déjà annoté.

    Repli sur la hauteur du caisson si `apply_door_spans` n'a pas été appelé
    (anciens projets, appels directs des modules d'export).
    """
    span = cab.get('door_span_height')
    if span:
        return float(span)
    return float(cab.get('dims', {}).get('H_raw', 0.0) or 0.0)


def cabinet_door_is_hidden(cab):
    """La porte propre de ce caisson doit-elle être ignorée ?"""
    return bool(cab.get('door_span_covered', False))


def calculate_hole_positions(W_raw):
    """
    Calcule les positions des trous de vis et tourillons sur une profondeur W_raw.
    
    Nouvelle logique d'alternance vis/tourillons :
    - Toujours commencer par 1 tourillon et finir sur 1 tourillon
    - Les 2 tourillons les plus proches des bords sont à 25mm du bord
    - Ensuite, selon la longueur totale :
      * 0 à 300mm : 2 tourillons au total (= 1 vis entre eux)
      * 300 à 500mm : 3 tourillons au total (2 vis)
      * 500 à 700mm : 4 tourillons au total (3 vis)
      * 700mm ou plus : 5 tourillons au total (4 vis)
    """
    ys_vis = []
    ys_dowel = []
    
    # Les tourillons aux bords sont toujours à 25mm
    edge_dowel = 25.0
    
    # Déterminer le nombre total de tourillons selon la longueur
    if W_raw <= 300.0:
        num_dowels = 2  # 1 à chaque bord, pas de tourillons au milieu
    elif W_raw <= 500.0:
        num_dowels = 3  # 1 à chaque bord + 1 au milieu
    elif W_raw <= 700.0:
        num_dowels = 4  # 1 à chaque bord + 2 au milieu
    else:
        num_dowels = 5  # 1 à chaque bord + 3 au milieu
    
    # Nombre de vis = nombre de tourillons - 1 (car alternance)
    num_vis = num_dowels - 1
    
    # Espace disponible pour placer les tourillons/vis au milieu
    available_length = W_raw - (2 * edge_dowel)
    
    # Placer le premier tourillon au bord gauche
    ys_dowel.append(edge_dowel)
    
    # Si on a des tourillons au milieu (num_dowels > 2)
    if num_dowels > 2:
        # Nombre de tourillons au milieu
        middle_dowels = num_dowels - 2
        
        # On divise l'espace disponible en (middle_dowels + 1) intervalles égaux
        # Les tourillons du milieu sont placés aux limites de ces intervalles
        interval = available_length / (middle_dowels + 1)
        
        # Placer les tourillons au milieu
        for i in range(1, middle_dowels + 1):
            dowel_pos = edge_dowel + (i * interval)
            ys_dowel.append(dowel_pos)
        
        # Placer les vis entre les tourillons (au milieu de chaque intervalle)
        for i in range(middle_dowels + 1):
            vis_pos = edge_dowel + ((i + 0.5) * interval)
            ys_vis.append(vis_pos)
    else:
        # Cas spécial : seulement 2 tourillons (un à chaque bord)
        # Une seule vis au milieu de l'espace disponible
        vis_pos = edge_dowel + (available_length / 2.0)
        ys_vis.append(vis_pos)
    
    # Placer le dernier tourillon au bord droit
    ys_dowel.append(W_raw - edge_dowel)
    
    # Trier les listes pour l'ordre croissant
    ys_dowel.sort()
    ys_vis.sort()
    
    return ys_vis, ys_dowel

def is_drawer_slide_hole(hole):
    """Détecte les trous de coulisses de tiroir à partir du diamètre."""
    diam_str = str(hole.get('diam_str', ''))
    return (
        ("5/12" in diam_str)
        or ("5/11.5" in diam_str)
        or ((("⌀3" in diam_str) or ("/3" in diam_str)) and ("/10" not in diam_str))
    )

def merge_drawer_panel_holes(face_holes, tranche_longue_holes, tranche_cote_holes=None):
    """Fusionne les trous utiles aux cotes Y des faces/dos de tiroir."""
    merged = []
    for holes in (face_holes, tranche_longue_holes, tranche_cote_holes):
        if holes:
            merged.extend(holes)
    return merged

def get_hinge_y_positions(door_height, custom_positions=None):
    """Calcule les positions Y des charnières pour une porte de hauteur donnée.
    
    Args:
        door_height: Hauteur de la porte en mm
        custom_positions: Liste optionnelle de positions Y personnalisées en mm. Si fournie, cette liste est retournée telle quelle.
    
    Returns:
        Liste des positions Y des charnières en mm
    """
    # Si des positions personnalisées sont fournies, les utiliser
    if custom_positions is not None and len(custom_positions) > 0:
        return sorted([float(pos) for pos in custom_positions])
    
    # Sinon, utiliser le calcul par défaut
    # 3 charnières standard : une en haut, une au milieu, une en bas
    # Espacement : 100mm du haut et du bas, puis répartition équitable
    positions = []
    if door_height > 200:
        positions.append(100.0)
        positions.append(door_height / 2.0)
        positions.append(door_height - 100.0)
    elif door_height > 100:
        positions.append(50.0)
        positions.append(door_height - 50.0)
    else:
        positions.append(door_height / 2.0)
    return positions

def get_mobile_shelf_holes(h_side, t_tb, shelf, W_mont):
    """Calcule les trous pour les taquets d'une étagère mobile."""
    holes = []
    y_pos = t_tb + shelf.get('height', 0.0)
    # Trous de taquets : mêmes coordonnées X que les trous
    # d'assemblage montant / traverse (vis + tourillons), pour
    # respecter une trame unique sur la profondeur du montant.
    ys_vis, ys_dowel = calculate_hole_positions(W_mont)
    x_positions = sorted(set(ys_vis + ys_dowel))
    for x in x_positions:
        holes.append({'type': 'etagere_taquet', 'x': x, 'y': y_pos, 'diam_str': "⌀5"})
    return holes

def calculate_back_panel_holes(W_back, H_back, cabinet):
    """
    Calcule les trous pour le panneau arrière.
    
    Règle :
    - Les 2 trous les plus proches du haut et du bas doivent être à 50 mm des bords
    - L'espacement entre les trous est d'environ 100 mm, ajusté pour respecter les 50 mm aux bords
    - Pour chaque montant secondaire, les trous doivent être au centre du montant
    """
    import math
    holes = []
    dims = cabinet.get('dims', {}) or {}
    L_raw = float(dims.get('L_raw', W_back + 2.0))
    H_raw = float(dims.get('H_raw', H_back + 2.0))
    t_tb = float(dims.get('t_tb_raw', 19.0))
    # Le panneau arrière est centré sur le caisson (jeu réparti sur les bords).
    back_off_x = (L_raw - float(W_back)) / 2.0
    back_off_y = (H_raw - float(H_back)) / 2.0
    interior_h = H_raw - 2.0 * t_tb

    # Trous de tourillons pour les montants secondaires (dans l'axe du montant,
    # répartis sur la hauteur réelle du montant).
    for div in cabinet.get('vertical_dividers', []) or []:
        # position_x = axe du montant, mesuré depuis le bord gauche du caisson.
        x_rel = float(div['position_x']) - back_off_x

        if div.get('_force_full_height') or div.get('bottom_y') is None or div.get('top_y') is None:
            div_bottom, div_top = 0.0, interior_h
        else:
            div_bottom = max(0.0, min(interior_h, float(div['bottom_y'])))
            div_top = max(div_bottom, min(interior_h, float(div['top_y'])))
        full_height = div_bottom <= 0.5 and div_top >= interior_h - 0.5

        if full_height:
            # Premier/dernier trou à 50 mm des bords du panneau.
            y_start = 50.0
            y_end = float(H_back) - 50.0
        else:
            # Montant partiel : 50 mm de ses extrémités (ramené au repère du panneau).
            seg_lo = t_tb + div_bottom - back_off_y
            seg_hi = t_tb + div_top - back_off_y
            y_start = seg_lo + 50.0
            y_end = seg_hi - 50.0
            if y_end <= y_start:
                y_start = y_end = (seg_lo + seg_hi) / 2.0

        if y_end <= y_start:
            holes.append({'type': 'tourillon', 'x': x_rel, 'y': (y_start + y_end) / 2.0, 'diam_str': "⌀8/22"})
            continue

        # Espacement selon la hauteur du meuble : ~500 mm au-delà de 1,50 m,
        # ~300 mm entre 1 m et 1,50 m, ~100 mm en dessous ; ajusté pour tomber
        # juste aux extrémités.
        if H_raw > 1500.0:
            target_spacing = 500.0
        elif H_raw > 1000.0:
            target_spacing = 300.0
        else:
            target_spacing = 100.0
        available_space = y_end - y_start
        num_intervals = max(1, round(available_space / target_spacing))
        spacing = available_space / num_intervals
        for i in range(num_intervals + 1):
            holes.append({'type': 'tourillon', 'x': x_rel, 'y': y_start + i * spacing, 'diam_str': "⌀8/22"})

    return holes


def back_panel_side_dowel_positions(H_back):
    """Tourillons des tranches gauche/droite du fond encastré, le long de sa
    hauteur : 50 mm des angles, puis ~300 mm (~100 mm si moins de 300 mm)."""
    import math
    edge = 50.0
    H_back = float(H_back)
    if H_back <= 2.0 * edge:
        return [H_back / 2.0]
    start, end = edge, H_back - edge
    target = 100.0 if H_back < 300.0 else 300.0
    n = max(1, round((end - start) / target))
    step = (end - start) / n
    return [start + i * step for i in range(n + 1)]


def calculate_back_panel_edge_holes(W_back, H_back):
    """Perçages des tranches du fond encastré.

    Le fond se loge entre les montants et entre les traverses (pleine
    profondeur). Tranches gauche/droite : tourillons, qui entrent dans les
    montants (voir back_panel_upright_holes). Tranches haut/bas : pas de
    perçage, le fond est vissé à travers le panneau des traverses (voir
    back_panel_traverse_holes).
    Retourne (trous des tranches haut/bas, trous des tranches gauche/droite).
    """
    side_holes = [{'type': 'tourillon', 'x': 0.0, 'y': y, 'diam_str': "⌀8/22"}
                  for y in back_panel_side_dowel_positions(H_back)]
    return [], side_holes


def _back_panel_axis_from_front(cabinet):
    """Axe du fond encastré dans l'épaisseur, mesuré depuis l'avant du caisson."""
    dims = cabinet.get('dims', {}) or {}
    W_raw = float(dims.get('W_raw', 0.0))
    t_fb = float(dims.get('t_fb_raw', 18.0))
    return W_raw - FOND_REBATE_MM + t_fb / 2.0


def back_panel_upright_holes(cabinet, W_mont):
    """Perçages des montants gauche/droit pour le fond encastré : tourillons en
    face de ceux des tranches du fond, et une vis entre chaque paire de
    tourillons, dans l'axe du fond. Retourne (trous Mg, trous Md) dans le
    repère des feuilles de montant (Mg : avant en x = 0, Md : avant en x = W)."""
    dims = cabinet.get('dims', {}) or {}
    H_raw = float(dims.get('H_raw', 0.0))
    H_back = carcass_piece_dims(cabinet)['fond_H']
    off_y = (H_raw - H_back) / 2.0                         # fond centré en hauteur
    x_front = _back_panel_axis_from_front(cabinet)
    dowels = back_panel_side_dowel_positions(H_back)
    screws = [(a + b) / 2.0 for a, b in zip(dowels, dowels[1:])]
    mg, md = [], []
    for y in dowels:
        mg.append({'type': 'tourillon', 'x': x_front, 'y': off_y + y, 'diam_str': "⌀8/22"})
        md.append({'type': 'tourillon', 'x': float(W_mont) - x_front, 'y': off_y + y, 'diam_str': "⌀8/22"})
    for y in screws:
        mg.append({'type': 'vis', 'x': x_front, 'y': off_y + y, 'diam_str': "⌀3"})
        md.append({'type': 'vis', 'x': float(W_mont) - x_front, 'y': off_y + y, 'diam_str': "⌀3"})
    return mg, md


def back_panel_traverse_holes(cabinet):
    """Trous de vis dans le panneau des traverses haut et bas pour fixer le fond
    encastré par ses tranches haut/bas : dans l'axe du fond, 50 mm des angles du
    fond puis ~300 mm. Repère de la feuille de traverse (x depuis le montant
    gauche, y depuis l'avant)."""
    dims = cabinet.get('dims', {}) or {}
    t_lr = float(dims.get('t_lr_raw', 19.0))
    body = carcass_piece_dims(cabinet)
    off_x = (body['L_eff'] - body['fond_W']) / 2.0 - t_lr    # fond centré, repère traverse
    y = _back_panel_axis_from_front(cabinet)
    return [{'type': 'vis', 'x': off_x + x, 'y': y, 'diam_str': "⌀3"}
            for x in back_panel_side_dowel_positions(body['fond_W'])]


def detect_collisions(cabinet):
    """Détecte les collisions entre éléments."""
    # Stub pour l'instant
    return []

def calculate_zones_from_dividers(cabinet):
    """Calcule les zones X (colonnes) créées par les montants secondaires."""
    zones = []
    dims = cabinet['dims']
    L_raw = dims['L_raw']
    t_lr = dims['t_lr_raw']
    
    if 'vertical_dividers' not in cabinet or not cabinet['vertical_dividers']:
        # Pas de montants secondaires : une seule zone
        zones.append({'id': 0, 'x_min': t_lr, 'x_max': L_raw - t_lr})
        return zones
    
    dividers = sorted(cabinet['vertical_dividers'], key=lambda d: d['position_x'])
    x_min = t_lr
    
    for idx, div in enumerate(dividers):
        div_x = div['position_x']
        div_th = div.get('thickness', 19.0)
        div_left = div_x - div_th / 2.0
        zones.append({'id': idx, 'x_min': x_min, 'x_max': div_left})
        x_min = div_x + div_th / 2.0
    
    zones.append({'id': len(dividers), 'x_min': x_min, 'x_max': L_raw - t_lr})
    return zones

def calculate_vertical_zones_in_x_zone(x_zone, cabinet):
    """Calcule les zones verticales (Y) dans une zone X donnée."""
    zones = []
    dims = cabinet['dims']
    H_raw = dims['H_raw']
    t_tb = dims['t_tb_raw']
    tol_mm = 1.0

    y_min_global = t_tb
    y_max_global = H_raw - t_tb
    blocking_elements = []
    
    # Collecter tous les éléments horizontaux qui bloquent
    if 'shelves' in cabinet:
        L_raw = dims['L_raw']
        t_lr = dims['t_lr_raw']
        for s in cabinet['shelves']:
            if s.get('_preview', False):
                continue

            # Si la largeur stockee n'existe pas, on considere l'etagere sur toute la largeur interieure.
            s_x_start = s.get('stored_shelf_x_start_mm')
            s_width = s.get('stored_shelf_width_mm')
            if s_x_start is None or s_width is None or s_width <= 0:
                s_x_start = t_lr
                s_x_end = L_raw - t_lr
            else:
                s_x_end = s_x_start + s_width

            if s_x_start < x_zone['x_max'] and s_x_end > x_zone['x_min']:
                y0 = t_tb + float(s.get('height', 0.0))
                th = float(s.get('thickness', 19.0))
                y1 = y0 + max(0.0, th)
                # Clamp aux limites interieures du caisson
                y0 = max(y_min_global, min(y0, y_max_global))
                y1 = max(y_min_global, min(y1, y_max_global))
                if y1 - y0 > 0.0:
                    blocking_elements.append({'y0': y0, 'y1': y1})
    
    # IMPORTANT : Les tiroirs NE sont PAS des éléments bloquants pour le calcul des zones
    # Les tiroirs sont simplement placés dans des zones existantes créées par les étagères et traverses
    # Ils ne doivent pas créer de nouvelles zones verticales
    
    # Fusionner les intervalles bloquants proches (<= 1 mm) pour eviter les micro-zones parasites.
    blocking_elements.sort(key=lambda e: e['y0'])
    merged = []
    for elem in blocking_elements:
        if not merged:
            merged.append({'y0': elem['y0'], 'y1': elem['y1']})
            continue
        last = merged[-1]
        if elem['y0'] <= last['y1'] + tol_mm:
            last['y1'] = max(last['y1'], elem['y1'])
        else:
            merged.append({'y0': elem['y0'], 'y1': elem['y1']})

    # Construire les zones vides entre intervalles bloquants.
    cursor = y_min_global
    for blk in merged:
        if blk['y0'] > cursor + tol_mm:
            zones.append({'y_min': cursor, 'y_max': blk['y0']})
        cursor = max(cursor, blk['y1'])

    if cursor < y_max_global - tol_mm:
        zones.append({'y_min': cursor, 'y_max': y_max_global})
    
    return zones

def calculate_all_zones_2d(cabinet, include_all_elements=True):
    """Calcule toutes les zones 2D (X et Y) dans le caisson."""
    zones = []
    x_zones = calculate_zones_from_dividers(cabinet)
    
    if not x_zones:
        x_zones = [{'id': 0, 'x_min': cabinet['dims']['t_lr_raw'], 'x_max': cabinet['dims']['L_raw'] - cabinet['dims']['t_lr_raw']}]
    
    zone_id = 0
    for x_zone in x_zones:
        y_zones = calculate_vertical_zones_in_x_zone(x_zone, cabinet)
        for y_zone in y_zones:
            zones.append({
                'id': zone_id,
                'label': f"Zone {zone_id}",
                'x_min': x_zone['x_min'],
                'x_max': x_zone['x_max'],
                'y_min': y_zone['y_min'],
                'y_max': y_zone['y_max']
            })
            zone_id += 1
    
    return zones

def get_vertical_divider_tranche_holes(W_mont, div_th):
    """
    Calcule les trous sur les tranches (haut et bas) d'un montant secondaire.
    
    Règle : Même système que les montants principaux (vis + tourillons)
    - Tourillons : tous les 100 mm avec 25 mm de marge aux bords
    - Vis : tous les 100 mm également, décalées de 50 mm par rapport aux tourillons
    
    IMPORTANT : Pour les tranches longues (haut et bas), la fonction de dessin utilise
    h['x'] comme position le long de la longueur du panneau (qui est W_mont pour un montant).
    """
    holes = []
    # Utiliser le même système que pour les montants principaux
    ys_vis, ys_dowel = calculate_hole_positions(W_mont)
    
    # Trous sur les TRANCHES (haut et bas) : vis ⌀3/10
    # Le système de dessin appliquera ces trous aux deux tranches
    # IMPORTANT : utiliser 'x' pour la position le long de la longueur (W_mont)
    for y_pos in ys_vis:
        holes.append({'type': 'vis', 'x': y_pos, 'y': 0, 'diam_str': "⌀3/10"})
    for y_pos in ys_dowel:
        holes.append({'type': 'tourillon', 'x': y_pos, 'y': 0, 'diam_str': "⌀8/22"})
    
    return holes


def get_vertical_divider_holes(W_raw, h_side, t_tb, div_x, t_lr):
    """
    Retourne lesrous pour les faces d'un montant secondaire (vertical divider).
    Ces trous servent à assembler le diviseur avec les traverses haute et basse.
    
    Args:
        W_raw: Profondeur brute du caisson
        h_side: Hauteur du montant
        t_tb: Épaisseur des traverses
        div_x: Position X du diviseur
        t_lr: Épaisseur des montants latéraux
        
    Returns:
        Liste de dictionnaires de trous
    """
    holes = []
    ys_vis, ys_dowel = calculate_hole_positions(W_raw)
    
    # Trous en haut et en bas pour l'assemblage avec les traverses
    for x in ys_vis:
        holes.append({'type':'vis','x':x,'y':t_tb/2,'diam_str':"⌀3"})
        holes.append({'type':'vis','x':x,'y':h_side-t_tb/2,'diam_str':"⌀3"})
    for x in ys_dowel:
        holes.append({'type':'tourillon','x':x,'y':t_tb/2,'diam_str':"⌀8/10"})
        holes.append({'type':'tourillon','x':x,'y':h_side-t_tb/2,'diam_str':"⌀8/10"})
    
    return holes

def get_traverse_holes_for_divider(L_trav, div_x, t_lr, t_tb, W_raw):
    """
    Calcule les trous sur les tranches des traverses pour un montant secondaire.
    
    Règle demandée :
    - Les trous de tourillons sur la tranche de la traverse doivent être
      alignés en profondeur avec ceux présents sur les bords des montants
      principaux gauche/droite (même pas de 100 mm avec 25 mm de marge aux bords).
    - Uniquement des tourillons (pas de vis).
    """
    holes = []
    # Position du montant secondaire projetée sur la longueur de la traverse
    x_rel = div_x - t_lr
    # Reprendre exactement le même pas que pour les montants principaux
    _, ys_dowel = calculate_hole_positions(W_raw)
    for y in ys_dowel:
        holes.append({'type': 'tourillon', 'x': x_rel, 'y': y, 'diam_str': "⌀8/22"})
    return holes

def get_traverse_face_holes_for_divider(L_trav, div_x, t_lr, t_tb, W_raw, t_fb):
    """
    Calcule les trous sur les faces des traverses pour un montant secondaire.
    
    Règle :
    - Utilise la même logique que les trous de tourillons sur les tranches des traverses
    - MAIS adapté à la profondeur réelle du montant secondaire (W - t_fb)
    - Les montants secondaires ne vont pas jusqu'au fond (profondeur réduite)
    - Uniquement des tourillons (pas de vis)
    """
    holes = []
    # Position relative du montant secondaire
    x_rel = div_x - t_lr
    
    # Calculer la profondeur réelle du montant secondaire
    # Les montants secondaires ont une profondeur de W - t_fb (ne vont pas jusqu'au fond)
    divider_depth = W_raw - t_fb
    
    # Utiliser la logique standard mais avec la profondeur réduite
    _, ys_dowel = calculate_hole_positions(divider_depth)
    
    for y in ys_dowel:
        holes.append({'type': 'tourillon', 'x': x_rel, 'y': y, 'diam_str': "⌀8/10"})
    
    return holes

def get_mounting_holes_for_zone_element(element, zone, cabinet):
    """Calcule les trous de montage pour un élément dans une zone."""
    # Stub pour l'instant
    return []

def get_vertical_shelf_tranche_holes(W_mont, vs_th):
    """Calcule les trous sur les tranches (haut et bas) d'une étagère verticale."""
    holes = []
    # Trous de tourillons : aux 2 extrémités à 25mm des DEUX bords
    # Premier tourillon à 25mm du bord bas
    holes.append({'type': 'tourillon', 'x': vs_th/2, 'y': 25.0, 'diam_str': "⌀8/22"})
    # Dernier tourillon à 25mm du bord haut
    holes.append({'type': 'tourillon', 'x': vs_th/2, 'y': W_mont - 25.0, 'diam_str': "⌀8/22"})
    
    # Trous intermédiaires si nécessaire (espacement de 100mm entre les tourillons)
    # Calculer le nombre de trous intermédiaires
    available_space = W_mont - 50.0  # Espace entre les deux tourillons aux extrémités
    if available_space > 100.0:
        num_intermediate = int((available_space - 25.0) / 100.0)  # Nombre de trous intermédiaires
        for i in range(1, num_intermediate + 1):
            y_pos = 25.0 + (i * 100.0)
            if y_pos < W_mont - 25.0:  # S'assurer qu'on ne dépasse pas le dernier tourillon
                holes.append({'type': 'tourillon', 'x': vs_th/2, 'y': y_pos, 'diam_str': "⌀8/22"})
    
    return holes


def apply_face_hole_depths(panel_name, face_holes):
    """Profondeurs imposées des perçages de FACE (pas des tranches).

    - Porte : cuvette de charnière ⌀35 et ses 2 vis ⌀8 -> profondeur 13.
    - Toute autre pièce : tout trou ⌀8 -> profondeur 14.
    - Partout : vis ⌀3 -> profondeur 14.
    Retourne une nouvelle liste (les dictionnaires d'origine ne sont pas modifiés).
    """
    import re as _re
    name = str(panel_name or "").lower()
    is_door = "porte" in name or "door" in name
    out = []
    for h in face_holes or []:
        h = dict(h)
        raw = str(h.get("diam_str", ""))
        m = _re.search(r"(\d+(?:[.,]\d+)?)", raw)
        diam = float(m.group(1).replace(",", ".")) if m else None
        if diam is not None:
            if is_door and abs(diam - 35.0) < 0.01:
                h["diam_str"] = "⌀35/13"
            elif is_door and abs(diam - 8.0) < 0.01:
                h["diam_str"] = "⌀8/13"
            elif not is_door and abs(diam - 8.0) < 0.01:
                h["diam_str"] = "⌀8/14"
            elif abs(diam - 3.0) < 0.01:
                h["diam_str"] = "⌀3/14"
        out.append(h)
    return out


def apply_tranche_hole_depths(tranche_holes):
    """Profondeurs imposées des perçages de TRANCHE : tourillon ⌀8 ->
    profondeur 25, vis ⌀3 -> profondeur 14."""
    import re as _re
    out = []
    for h in tranche_holes or []:
        h = dict(h)
        m = _re.search(r"(\d+(?:[.,]\d+)?)", str(h.get("diam_str", "")))
        diam = float(m.group(1).replace(",", ".")) if m else None
        if diam is not None:
            if abs(diam - 8.0) < 0.01:
                h["diam_str"] = "⌀8/25"
            elif abs(diam - 3.0) < 0.01:
                h["diam_str"] = "⌀3/14"
        out.append(h)
    return out


# Le fond est encastré : il se loge derrière les traverses, étagères et
# montants secondaires, qui s'arrêtent donc à cette distance de l'arrière.
FOND_REBATE_MM = 19.0
# Jeu total retiré au fond encastré sur sa largeur et sa hauteur.
FOND_INSET_MM = 38.0


def carcass_piece_dims(cabinet):
    """Dimensions des pièces de corps, source unique pour la feuille de débit
    et les feuilles d'usinage.

    - L_traverse : longueur des traverses / étagères (largeur utile, fileur déduit) ;
    - W_inner : largeur des étagères fixes et montants secondaires
      (profondeur - 19 : ils s'arrêtent devant le fond encastré) ;
    - W_traverse : largeur des traverses haut/bas (pleine profondeur, le fond
      se loge entre elles et entre les montants) ;
    - fond_W x fond_H : fond encastré (largeur utile - 38) x (hauteur - 38).
    """
    dims = cabinet.get('dims', {}) or {}
    fileur_w = float((cabinet.get('door_props', {}) or {}).get('fileur_width', 0) or 0.0)
    L_eff = max(0.0, float(dims.get('L_raw', 0.0)) - fileur_w)
    t_lr = float(dims.get('t_lr_raw', 19.0))
    W_raw = float(dims.get('W_raw', 0.0))
    H_raw = float(dims.get('H_raw', 0.0))
    return {
        'L_eff': L_eff,
        'L_traverse': max(0.0, L_eff - 2.0 * t_lr),
        'W_inner': max(0.0, W_raw - FOND_REBATE_MM),
        # Traverses haut/bas : pleine profondeur, le fond se loge entre elles.
        'W_traverse': W_raw,
        'fond_W': max(0.0, L_eff - FOND_INSET_MM),
        'fond_H': max(0.0, H_raw - FOND_INSET_MM),
    }


def find_element_zone(element, zones, tol=1.0):
    """Zone d'un élément (tiroir...) : d'abord par ses coordonnées enregistrées
    (l'indice peut être périmé si les zones ont été recalculées), sinon par indice."""
    coords = element.get('stored_zone_coords')
    if coords:
        for zone in zones:
            if (abs(float(zone['x_min']) - float(coords['x_min'])) <= tol
                    and abs(float(zone['x_max']) - float(coords['x_max'])) <= tol
                    and float(zone['y_min']) - tol <= float(coords.get('y_min', zone['y_min']))
                    and float(coords.get('y_max', zone['y_max'])) <= float(zone['y_max']) + tol):
                return zone
        # Même colonne, quelle que soit la hauteur.
        for zone in zones:
            if (abs(float(zone['x_min']) - float(coords['x_min'])) <= tol
                    and abs(float(zone['x_max']) - float(coords['x_max'])) <= tol):
                return zone
    zone_id = element.get('zone_id')
    if zone_id is not None and 0 <= zone_id < len(zones):
        return zones[zone_id]
    return None


def drawer_piece_dims(cabinet, drp, zones):
    """Dimensions des pièces d'un tiroir, source unique (débit + usinage).

    `zones` : zones 2D du caisson calculées sur sa largeur utile (fileur déduit).
    Retourne aussi la position X (repère caisson) du caisson de tiroir, pour
    placer les perçages de la façade en face de lui.
    """
    from project_definitions import get_legrabox_specs
    dims = cabinet.get('dims', {}) or {}
    body = carcass_piece_dims(cabinet)
    L_eff = body['L_eff']
    t_lr = float(dims.get('t_lr_raw', 19.0))
    W_raw = float(dims.get('W_raw', 0.0))
    t_fb = float(dims.get('t_fb_raw', 0.0))
    system = drp.get('drawer_system', 'TANDEMBOX')
    tech = drp.get('drawer_tech_type', 'K')
    gap = float(drp.get('drawer_gap', 2.0))

    zone = find_element_zone(drp, zones)
    if zone is not None:
        z_x0, z_x1 = float(zone['x_min']), float(zone['x_max'])
    else:
        z_x0, z_x1 = t_lr, L_eff - t_lr
    zone_total = (z_x1 - z_x0) if zone is not None else L_eff
    zone_interior = zone_total - 2.0 * t_lr

    if system == 'LÉGRABOX':
        box_face = zone_total - 2.0 * gap
        back_w = max(0.0, zone_interior - 38.0)
        back_h = get_legrabox_specs().get(tech, get_legrabox_specs()['K'])['back_height']
        bottom_w = max(0.0, zone_interior - 35.0)
        bottom_d = max(0.0, W_raw - 2.0 * t_lr - 10.0)
    elif system == 'ANGLAISE':
        box_face = max(0.0, zone_total - 4.0)
        back_w = max(0.0, box_face - 40.0)
        back_h = {'N': 69.0, 'M': 84.0, 'K': 116.0, 'D': 199.0}.get(tech, 116.0)
        bottom_w = max(0.0, box_face - 49.0)
        bottom_d = W_raw - (20.0 + t_fb)
    else:
        box_face = zone_total - 2.0 * gap
        back_w = max(0.0, box_face - 40.0)
        back_h = {'N': 69.0, 'M': 84.0, 'K': 116.0, 'D': 199.0}.get(tech, 116.0)
        bottom_w = max(0.0, box_face - 49.0)
        bottom_d = W_raw - (20.0 + t_fb)

    # Façade : toute la largeur utile du caisson - 4 mm, posée à 2 mm du bord.
    face_w = max(0.0, L_eff - 4.0)
    face_x0 = 2.0
    # Bords du caisson de tiroir (même règle que la façade « zone »).
    if zone is not None:
        box_x0 = z_x0 + gap
        box_x1 = z_x1 - gap
    else:
        box_x0, box_x1 = face_x0, face_x0 + face_w
    return {
        'system': system, 'tech': tech,
        'face_w': face_w, 'face_h': float(drp.get('drawer_face_H_raw', 150.0)),
        'face_t': float(drp.get('drawer_face_thickness', 19.0)),
        'box_x0_on_face': box_x0 - face_x0, 'box_x1_on_face': box_x1 - face_x0,
        'back_w': back_w, 'back_h': float(back_h),
        'bottom_w': bottom_w, 'bottom_d': bottom_d,
        'inner_t': float(drp.get('inner_thickness', 16.0)),
    }


def door_columns(cabinet):
    """Colonnes où poser une porte : entre deux montants (principaux ou
    secondaires), sur toute la hauteur. [{'x_min', 'x_max'}] en mm, repère
    caisson (faces intérieures des montants)."""
    return [{'x_min': float(z['x_min']), 'x_max': float(z['x_max'])}
            for z in calculate_zones_from_dividers(cabinet)]


def door_zone_span(cabinet):
    """Ouverture couverte par la porte native du caisson : (x_min, x_max) en mm
    (faces des montants qui la bordent), ou None si la porte couvre tout le caisson."""
    dp = cabinet.get('door_props', {}) or {}
    zx = dp.get('zone_x')
    if isinstance(zx, dict) and zx.get('x_min') is not None and zx.get('x_max') is not None:
        x0, x1 = float(zx['x_min']), float(zx['x_max'])
        if x1 > x0:
            return (x0, x1)
    # Ancien format : indice dans les zones 2D.
    zone_id = dp.get('zone_id')
    if zone_id is not None:
        try:
            zones = calculate_all_zones_2d(cabinet)
        except Exception:
            zones = []
        if 0 <= zone_id < len(zones):
            return (float(zones[zone_id]['x_min']), float(zones[zone_id]['x_max']))
    return None


def column_filler_spans(cabinet):
    """Fileurs de colonne : planches fixes, sans usinage, posées en façade des
    colonnes que la porte ne couvre pas (caisson à montant(s) secondaire(s)).

    Ne modifient pas les dimensions du caisson. Retourne [(x_min, x_max)] des
    colonnes habillées (faces des montants qui les bordent), dans l'ordre.
    """
    dp = cabinet.get('door_props', {}) or {}
    if not dp.get('has_door') or cabinet_door_is_hidden(cabinet):
        return []
    door_span = door_zone_span(cabinet)
    if door_span is None:
        return []
    wanted = dp.get('column_fillers') or []
    out = []
    for col in door_columns(cabinet):
        x0, x1 = col['x_min'], col['x_max']
        if abs(x0 - door_span[0]) <= 1.0 and abs(x1 - door_span[1]) <= 1.0:
            continue  # colonne de la porte
        if any(abs(x0 - float(w['x_min'])) <= 1.0 and abs(x1 - float(w['x_max'])) <= 1.0 for w in wanted):
            # Recouvrement en applique, comme une porte fermée sur cette colonne.
            out.append(column_cover_span(cabinet, (x0, x1)))
    return out


def column_filler_width(cabinet, span):
    """Largeur d'un fileur de colonne : même règle que la porte (ouverture - 2 jeux)."""
    gap = float((cabinet.get('door_props', {}) or {}).get('door_gap', 2.0) or 0.0)
    return max(0.0, (span[1] - span[0]) - 2.0 * gap)


def column_cover_span(cabinet, col_span):
    """Zone couverte EN APPLIQUE par une porte ou un fileur posé sur une colonne.

    `col_span` = (x_min, x_max) : faces des montants qui bordent la colonne.
    Côté montant principal : jusqu'au bord extérieur du caisson (moins le jeu) ;
    côté montant secondaire : jusqu'au milieu du montant (ou du double montant),
    moins un demi-jeu. Retourne (x0, x1) tel que le panneau aille de x0 + jeu à
    x1 - jeu (même convention que l'ouverture d'une porte pleine largeur).
    """
    dims = cabinet.get('dims', {}) or {}
    t_lr = float(dims.get('t_lr_raw', 19.0))
    L_raw = float(dims.get('L_raw', 0.0))
    gap = float((cabinet.get('door_props', {}) or {}).get('door_gap', 2.0) or 0.0)
    dividers = cabinet.get('vertical_dividers', []) or []
    faces = [(float(d.get('position_x', 0.0)) - float(d.get('thickness', 19.0)) / 2.0,
              float(d.get('position_x', 0.0)) + float(d.get('thickness', 19.0)) / 2.0) for d in dividers]

    def _block_left(face_x):
        # Montants secondaires collés à gauche de la face : bord gauche du bloc.
        left = None
        cur = face_x
        while True:
            hit = next((f for f in faces if abs(f[1] - cur) <= 1.0), None)
            if hit is None:
                return left
            left = cur = hit[0]

    def _block_right(face_x):
        right = None
        cur = face_x
        while True:
            hit = next((f for f in faces if abs(f[0] - cur) <= 1.0), None)
            if hit is None:
                return right
            right = cur = hit[1]

    x_min, x_max = float(col_span[0]), float(col_span[1])
    if abs(x_min - t_lr) <= 1.0:
        a = gap                                    # bord extérieur du caisson
    else:
        bl = _block_left(x_min)
        a = ((bl + x_min) / 2.0 if bl is not None else x_min) + gap / 2.0
    if abs(x_max - (L_raw - t_lr)) <= 1.0:
        b = L_raw - gap
    else:
        br = _block_right(x_max)
        b = ((br + x_max) / 2.0 if br is not None else x_max) - gap / 2.0
    return (a - gap, b + gap)


def door_cover_span(cabinet):
    """Zone couverte par la porte native posée dans une colonne (applique),
    ou None si elle couvre tout le caisson. Voir column_cover_span."""
    span = door_zone_span(cabinet)
    return column_cover_span(cabinet, span) if span is not None else None


JOUE_SIDE_KEYS = ('gauche', 'droite')
# Une joue de meuble à porte avance pour couvrir l'épaisseur de la porte et le
# jeu porte/montant.
JOUE_DOOR_FRONT_EXTENSION = 20.0
JOUE_TOP_BOTTOM_KEYS = ('dessus', 'dessous')


def joue_drawer_advance_available(cabinet, joue_key):
    """Une joue dessus/dessous peut-elle avancer devant les façades de tiroir ?
    (caisson à tiroir(s), sans porte qui déclenche déjà l'avancée)."""
    return (joue_key in JOUE_TOP_BOTTOM_KEYS and bool(cabinet.get('drawers'))
            and not cabinet_has_front_door(cabinet))


def cabinet_has_front_door(cabinet):
    """Le caisson a-t-il une porte en façade (propre, importée, de colonne ou
    commune avec le caisson du dessous) ?"""
    dp = cabinet.get('door_props', {}) or {}
    return bool(dp.get('has_door') or cabinet.get('imported_doors') or cabinet_door_is_hidden(cabinet))


def apply_joue_spans(scene_cabinets):
    """Inscrit sur chaque caisson l'état résolu de ses joues latérales.

    `joue_spans[cote]` :
    - span_height : hauteur couverte (celle du caisson, + celle du caisson du
      dessus si la joue leur est commune) ;
    - covered : joue masquée par la joue commune du caisson du dessous ;
    - on_floor : le caisson repose au sol (seule condition pour qu'une joue
      cache-pieds descende devant les pieds).
    """
    for i, cab in enumerate(scene_cabinets):
        H = float(cab.get('dims', {}).get('H_raw', 0.0) or 0.0)
        joues = cab.get('joues', {}) or {}
        child = get_stacked_child_index(scene_cabinets, i)
        parent = cab.get('parent_index')
        is_upper = parent is not None and cab.get('attachment_dir') == 'up' and 0 <= parent < len(scene_cabinets)
        spans = {}
        for key in JOUE_SIDE_KEYS:
            joue = joues.get(key, {}) or {}
            span_up = bool(joue.get('enabled') and joue.get('span_up') and child is not None)
            span_h = H
            if span_up:
                span_h += float(scene_cabinets[child].get('dims', {}).get('H_raw', 0.0) or 0.0)
            covered = False
            if is_upper:
                pj = (scene_cabinets[parent].get('joues', {}) or {}).get(key, {}) or {}
                covered = bool(pj.get('enabled') and pj.get('span_up'))
            front_door = cabinet_has_front_door(cab)
            if span_up:
                front_door = front_door or cabinet_has_front_door(scene_cabinets[child])
            spans[key] = {
                'front_door': front_door,
                'span_height': span_h,
                'span_up': span_up,
                'covered': covered,
                'on_floor': cabinet_rests_on_floor(scene_cabinets, i),
            }
        cab['joue_spans'] = spans
    return scene_cabinets


def cabinet_joue_dims(cabinet, joue_key, has_feet=False, foot_height=0.0, fileur_width=0.0):
    """Dimensions d'une joue en tenant compte de la joue commune (caissons
    superposés) et du modèle cache-pieds. None si la joue est masquée par la
    joue commune du caisson du dessous."""
    from project_definitions import get_joue_dimensions
    joue = (cabinet.get('joues', {}) or {}).get(joue_key, {}) or {}
    dims = dict(cabinet.get('dims', {}) or {})
    feet = False
    front_door = cabinet_has_front_door(cabinet)
    if joue_key in JOUE_SIDE_KEYS:
        span = (cabinet.get('joue_spans', {}) or {}).get(joue_key, {}) or {}
        if span.get('covered'):
            return None
        dims['H_raw'] = float(span.get('span_height', dims.get('H_raw', 0.0)) or 0.0)
        # Modèle cache-pieds (défaut, comportement historique) : descend devant
        # les pieds uniquement si le caisson repose au sol.
        feet = bool(has_feet) and joue.get('model', 'floor_length') == 'floor_length' \
            and span.get('on_floor', True)
        front_door = bool(span.get('front_door', front_door))
    geo = get_joue_dimensions(joue_key, dims, feet, foot_height, fileur_width)
    # Meuble à porte : la joue avance de 20 mm pour couvrir la porte.
    # Caisson à tiroir : avancée optionnelle des joues dessus/dessous (façade
    # 19 mm + 1 mm de jeu tiroir/caisson).
    drawer_adv = bool(joue.get('drawer_front_advance')) and joue_drawer_advance_available(cabinet, joue_key)
    ext = JOUE_DOOR_FRONT_EXTENSION if (front_door or drawer_adv) else 0.0
    geo['width'] = float(geo['width']) + ext
    geo['front_offset'] = ext
    return geo


# Tranche arrière (contre le mur) d'un montant principal, dans le repère commun
# feuille de débit / feuille d'usinage (avant du montant gauche en x = 0,
# avant du montant droit en x = largeur).
UPRIGHT_WALL_EDGE = {'Montant Gauche': 'Chant Droit', 'Montant Droit': 'Chant Gauche'}


def migrate_upright_wall_chants(scene_cabinets):
    """Une seule fois par caisson : retire le chant de la tranche contre le mur
    des montants principaux encore réglés « tout chanté » (ancien défaut)."""
    for cab in scene_cabinets:
        if cab.get('_upright_wall_chant_v2'):
            continue
        for piece in cab.get('debit_data', []) or []:
            ref = str(piece.get('Référence Pièce', '')).split(' (')[0].strip()
            edge = UPRIGHT_WALL_EDGE.get(ref)
            if edge and all(bool(piece.get(k, True)) for k in
                            ('Chant Avant', 'Chant Arrière', 'Chant Gauche', 'Chant Droit')):
                piece[edge] = False
        cab['_upright_wall_chant_v2'] = True
    return scene_cabinets


def migrate_traverse_wall_chants(scene_cabinets):
    """Une seule fois par caisson : retire le chant de la tranche arrière
    (contre le mur) des traverses encore réglées sur l'ancien défaut
    (avant + arrière chantés)."""
    for cab in scene_cabinets:
        if cab.get('_traverse_wall_chant_v2'):
            continue
        for piece in cab.get('debit_data', []) or []:
            ref = str(piece.get('Référence Pièce', '')).split(' (')[0].strip()
            if ref in ('Traverse Bas', 'Traverse Haut') and piece.get('Chant Avant', True) \
                    and piece.get('Chant Arrière', True) and not piece.get('Chant Gauche', False) \
                    and not piece.get('Chant Droit', False):
                piece['Chant Arrière'] = False
        cab['_traverse_wall_chant_v2'] = True
    return scene_cabinets


def debit_piece_chants(cabinet, ref_key, default):
    """Chants d'une pièce de structure tels que réglés dans la feuille de débit."""
    for piece in cabinet.get('debit_data', []) or []:
        ref = str(piece.get('Référence Pièce', '')).split(' (')[0].strip()
        if ref == ref_key:
            return {k: bool(piece.get(k, default.get(k, False))) for k in
                    ('Chant Avant', 'Chant Arrière', 'Chant Gauche', 'Chant Droit')}
    return dict(default)


# --- Assemblage montant / joue -------------------------------------------------
JOUE_DOWEL_EDGE = 40.0        # premier/dernier tourillon depuis les bords haut/bas
JOUE_DOWEL_SPACING = 400.0    # espacement visé entre tourillons d'une ligne
UPRIGHT_JOUE_SIDE = {'mg': 'gauche', 'md': 'droite'}


def joue_dowel_heights(H):
    """Hauteurs des tourillons montant/joue le long du montant : 40 mm des
    bords puis ~400 mm, répartis régulièrement."""
    H = float(H)
    if H <= 2.0 * JOUE_DOWEL_EDGE:
        return [H / 2.0]
    start, end = JOUE_DOWEL_EDGE, H - JOUE_DOWEL_EDGE
    n = max(1, round((end - start) / JOUE_DOWEL_SPACING))
    step = (end - start) / n
    return [start + i * step for i in range(n + 1)]


def joue_dowel_depths(W):
    """Les 2 lignes verticales : à 1/4 et 3/4 de la profondeur du montant."""
    return [float(W) / 4.0, 3.0 * float(W) / 4.0]


def upright_has_joue(cabinet, upright):
    """Le montant ('mg' | 'md') est-il habillé d'une joue (propre ou commune
    avec le caisson du dessous) ?"""
    key = UPRIGHT_JOUE_SIDE[upright]
    span = (cabinet.get('joue_spans', {}) or {}).get(key, {}) or {}
    if span.get('covered'):
        return True
    joue = (cabinet.get('joues', {}) or {}).get(key, {}) or {}
    return bool(joue.get('enabled'))


def upright_joue_holes(cabinet):
    """Tourillons de la face extérieure (2/2) d'un montant habillé d'une joue,
    repère de la feuille de montant (x = profondeur, y = hauteur)."""
    dims = cabinet.get('dims', {}) or {}
    return [{'type': 'tourillon', 'x': x, 'y': y, 'diam_str': "⌀8"}
            for x in joue_dowel_depths(float(dims.get('W_raw', 0.0)))
            for y in joue_dowel_heights(float(dims.get('H_raw', 0.0)))]


def joue_assembly_holes(scene_cabinets, cab_index, joue_key, has_feet=False, foot_height=0.0):
    """Tourillons d'une joue latérale, en face de ceux des montants qu'elle
    habille (y compris le caisson du dessus pour une joue commune).

    Repère de la feuille de joue : x le long de la hauteur (joue gauche : x = 0
    en bas ; joue droite : x = 0 en haut, la feuille étant symétrique), y depuis
    l'avant. La partie cache-pieds (sous le caisson) et l'avancée devant une
    porte ne sont pas collées au montant : les trous en tiennent compte."""
    if joue_key not in JOUE_SIDE_KEYS or not (0 <= cab_index < len(scene_cabinets)):
        return []
    cab = scene_cabinets[cab_index]
    fileur = float((cab.get('door_props', {}) or {}).get('fileur_width', 0) or 0.0)
    geo = cabinet_joue_dims(cab, joue_key, has_feet, foot_height, fileur)
    if geo is None:
        return []
    length = float(geo['length'])
    below = -float(geo.get('z_offset', 0.0))          # partie cache-pieds
    front = float(geo.get('front_offset', 0.0))        # avancée devant la porte
    covered = [(cab, 0.0)]
    span = (cab.get('joue_spans', {}) or {}).get(joue_key, {}) or {}
    if span.get('span_up'):
        child = get_stacked_child_index(scene_cabinets, cab_index)
        if child is not None:
            covered.append((scene_cabinets[child], float(cab.get('dims', {}).get('H_raw', 0.0))))
    holes = []
    for c, base in covered:
        for h in upright_joue_holes(c):
            z = below + base + float(h['y'])
            x = z if joue_key == 'gauche' else length - z
            holes.append({'type': 'tourillon', 'x': x, 'y': front + float(h['x']), 'diam_str': "⌀8"})
    return holes
