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
# Pas de plinthe sous des pieds de 20 mm : seulement à partir de 80 mm.
PLINTHE_MIN_FOOT_HEIGHT_MM = 80.0


def feet_need_plinthe(foot_height):
    try:
        return float(foot_height or 0.0) >= PLINTHE_MIN_FOOT_HEIGHT_MM
    except (TypeError, ValueError):
        return False


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


# Un caisson est « posé sur » un autre si son bas touche le dessus de celui-ci,
# à la même position X et façade alignée, à ce jeu près.
STACK_JOIN_TOLERANCE = 1.0


def get_cabinet_above_index(scene_cabinets, cab_index, origins=None):
    """Caisson posé sur `cab_index`, quelle que soit la façon dont il a été ajouté.

    `get_stacked_child_index` ne voit que le caisson ajouté « en haut » de
    celui-ci. Dans deux colonnes côte à côte, le caisson du haut de la seconde
    colonne est souvent ajouté « à droite » du haut de la première : il est
    pourtant bien posé sur le bas de la seconde. On le retrouve ici par la
    géométrie, la relation directe restant prioritaire.
    """
    direct = get_stacked_child_index(scene_cabinets, cab_index)
    if direct is not None or not (0 <= cab_index < len(scene_cabinets)):
        return direct
    if origins is None:
        origins = calculate_origins_recursively(scene_cabinets, 1.0)
    tol = STACK_JOIN_TOLERANCE
    ox, oy, oz = origins[cab_index]
    top = oz + float((scene_cabinets[cab_index].get('dims', {}) or {}).get('H_raw', 0.0) or 0.0)
    for j in range(len(scene_cabinets)):
        if j == cab_index:
            continue
        x, y, z = origins[j]
        if abs(x - ox) <= tol and abs(y - oy) <= tol and abs(z - top) <= tol:
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
    if hole.get('type') == 'etagere_taquet':
        return False   # crémaillère ⌀5/12 : même diamètre, mais pas un tiroir
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

# Hauteur de porte à partir de laquelle on pose 3 charnières (2 en dessous).
HINGE_THREE_MIN_DOOR_H = 450.0


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
    # 3 charnières (haut, milieu, bas) à partir de 450 mm de porte, sinon 2.
    # Espacement : 100mm du haut et du bas, puis répartition équitable
    positions = []
    if door_height >= HINGE_THREE_MIN_DOOR_H:
        positions.append(100.0)
        positions.append(door_height / 2.0)
        positions.append(door_height - 100.0)
    elif door_height > 200:
        positions.append(100.0)
        positions.append(door_height - 100.0)
    elif door_height > 100:
        positions.append(50.0)
        positions.append(door_height - 50.0)
    else:
        positions.append(door_height / 2.0)
    return positions

# Étagères mobiles en crémaillère : 2 rangées verticales de trous ⌀5 prof. 12,
# à 50 mm des bords avant et arrière du panneau, pas de 64 mm, sur toute la
# hauteur de la zone. Un seul jeu de trous par face, quel que soit le nombre
# d'étagères mobiles.
MOBILE_RACK_EDGE_MM = 50.0
MOBILE_RACK_PITCH_MM = 64.0   # un trou sur deux du système 32
MOBILE_RACK_END_MARGIN_MM = 32.0   # marge mini sous/sur la série de trous
MOBILE_RACK_DIAM = "⌀5/12"


def mobile_shelf_rack_y_range(cabinet, x_min, x_max, y_shelf):
    """Hauteur (y_min, y_max), repère du montant, de la zone qui reçoit une
    étagère mobile : bornée par les éléments FIXES (traverses, étagères fixes),
    jamais par les autres étagères mobiles."""
    dims = cabinet.get('dims', {}) or {}
    H = float(dims.get('H_raw', 0.0) or 0.0)
    t_tb = float(dims.get('t_tb_raw', 19.0) or 0.0)
    fixed_only = dict(cabinet)
    fixed_only['shelves'] = [s for s in (cabinet.get('shelves') or [])
                             if s.get('shelf_type', 'mobile') != 'mobile']
    x_c = (float(x_min) + float(x_max)) / 2.0
    for z in calculate_all_zones_2d(fixed_only):
        if z['x_min'] - 0.5 <= x_c <= z['x_max'] + 0.5 and z['y_min'] - 0.5 <= y_shelf <= z['y_max'] + 0.5:
            return float(z['y_min']), float(z['y_max'])
    return t_tb, H - t_tb


def mobile_shelf_rack_holes(panel_w, y_min, y_max, front=0.0):
    """Trous de crémaillère d'une face : 2 rangées (x = front + 50 et
    panel_w - 50 ; `front` = recul de l'étagère derrière un montant de charnière),
    pas de 64 mm, série centrée dans [y_min, y_max] avec au moins 32 mm de
    marge à chaque bout."""
    span = float(y_max) - float(y_min) - 2.0 * MOBILE_RACK_END_MARGIN_MM
    if span < 0.0 or float(panel_w) - float(front) <= 2.0 * MOBILE_RACK_EDGE_MM:
        return []
    n = int(span // MOBILE_RACK_PITCH_MM) + 1
    y0 = float(y_min) + (float(y_max) - float(y_min) - (n - 1) * MOBILE_RACK_PITCH_MM) / 2.0
    xs = (float(front) + MOBILE_RACK_EDGE_MM, float(panel_w) - MOBILE_RACK_EDGE_MM)
    return [{'type': 'etagere_taquet', 'x': x, 'y': y0 + i * MOBILE_RACK_PITCH_MM, 'diam_str': MOBILE_RACK_DIAM}
            for x in xs for i in range(n)]


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


# Fond moins haut que ce seuil : un seul tourillon par montant, donc pas de vis.
BACK_PANEL_SINGLE_DOWEL_MAX_H = 150.0


def back_panel_upright_dowel_positions(H_back):
    """Tourillons fond / montant le long de la hauteur du fond : un seul,
    centré, si le fond fait moins de 150 mm, sinon la règle générale."""
    H_back = float(H_back)
    if H_back < BACK_PANEL_SINGLE_DOWEL_MAX_H:
        return [H_back / 2.0]
    return back_panel_side_dowel_positions(H_back)


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
                  for y in back_panel_upright_dowel_positions(H_back)]
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
    dowels = back_panel_upright_dowel_positions(H_back)
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

# Montant de charnière : montant secondaire de 100 mm de profondeur, posé à
# l'avant, qui sert uniquement à recevoir les charnières d'une porte de
# colonne. Il ne découpe pas le caisson pour les étagères : celles qui le
# croisent passent derrière (reculées de 100 mm + 1 mm de jeu).
HINGE_POST_DEPTH_MM = 100.0
HINGE_POST_SHELF_SETBACK_MM = HINGE_POST_DEPTH_MM + 1.0


def is_hinge_post(div):
    return bool((div or {}).get('hinge_post'))


def hinge_post_traverse_face_holes(div_x, t_lr):
    """Perçages des traverses (faces) pour un montant de charnière : trame de
    100 mm -> tourillons à 25 et 75 mm de l'avant, vis à 50 mm."""
    ys_vis, ys_dowel = calculate_hole_positions(HINGE_POST_DEPTH_MM)
    x_rel = float(div_x) - float(t_lr)
    return ([{'type': 'tourillon', 'x': x_rel, 'y': y, 'diam_str': "⌀8/10"} for y in ys_dowel]
            + [{'type': 'vis', 'x': x_rel, 'y': y, 'diam_str': "⌀3"} for y in ys_vis])


# Étagère mobile : jeu de pose retiré aux cotes d'une étagère fixe, pour
# qu'elle passe entre les montants et devant le fond.
MOBILE_SHELF_LENGTH_CLEARANCE_MM = 2.0
MOBILE_SHELF_DEPTH_CLEARANCE_MM = 20.0


def shelf_piece_dims(L_traverse, W_inner, shelf, setback=0.0, cabinet=None):
    """(longueur, largeur) d'une étagère, source unique pour la feuille de
    débit et la feuille d'usinage. Fixe : longueur de sa zone (traverse si
    elle couvre tout le caisson) x (profondeur - 19 - recul). Mobile : 2 mm de
    moins en longueur, 20 mm en profondeur."""
    L = float(L_traverse)
    if cabinet is not None:
        # Étagère limitée à une zone (entre montants) : on retire à la
        # traverse la largeur intérieure qu'elle ne couvre pas.
        dims = cabinet.get('dims', {}) or {}
        t_lr = float(dims.get('t_lr_raw', 19.0))
        inner = float(dims.get('L_raw', 0.0)) - 2.0 * t_lr
        x_min, x_max = shelf_x_span(cabinet, shelf)
        L -= max(0.0, inner - (x_max - x_min))
    W = float(W_inner) - float(setback)
    if (shelf or {}).get('shelf_type', 'mobile') == 'mobile':
        L -= MOBILE_SHELF_LENGTH_CLEARANCE_MM
        W -= MOBILE_SHELF_DEPTH_CLEARANCE_MM
    return max(0.0, L), max(0.0, W)


def shelf_x_span(cabinet, shelf):
    """Étendue (x_min, x_max) d'une étagère, repère caisson."""
    dims = cabinet.get('dims', {}) or {}
    t_lr = float(dims.get('t_lr_raw', 19.0))
    L_raw = float(dims.get('L_raw', 0.0))
    x0, w = shelf.get('stored_shelf_x_start_mm'), shelf.get('stored_shelf_width_mm')
    if x0 is not None and w is not None and float(w) > 0:
        return float(x0), float(x0) + float(w)
    z = shelf.get('stored_zone_coords') or {}
    if z.get('x_min') is not None and z.get('x_max') is not None:
        return float(z['x_min']), float(z['x_max'])
    return t_lr, L_raw - t_lr


def shelf_front_setback(cabinet, shelf):
    """Recul de l'étagère depuis l'avant : 101 mm si elle passe derrière un
    montant de charnière, sinon 0."""
    x_min, x_max = shelf_x_span(cabinet, shelf)
    for div in cabinet.get('vertical_dividers', []) or []:
        if is_hinge_post(div) and not div.get('_preview') \
                and x_min + 0.5 < float(div.get('position_x', 0.0)) < x_max - 0.5:
            return HINGE_POST_SHELF_SETBACK_MM
    return 0.0


def calculate_zones_from_dividers(cabinet, include_hinge_posts=False):
    """Calcule les zones X (colonnes) créées par les montants secondaires.

    Les montants de charnière ne comptent que pour les colonnes de porte
    (`include_hinge_posts=True`, voir `door_columns`)."""
    zones = []
    dims = cabinet['dims']
    L_raw = dims['L_raw']
    t_lr = dims['t_lr_raw']
    dividers = [d for d in (cabinet.get('vertical_dividers') or [])
                if include_hinge_posts or not is_hinge_post(d)]

    if not dividers:
        # Pas de montants secondaires : une seule zone
        zones.append({'id': 0, 'x_min': t_lr, 'x_max': L_raw - t_lr})
        return zones

    dividers = sorted(dividers, key=lambda d: d['position_x'])
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


DRAWER_STACK_GAP_MM = 2.0


def compute_drawer_stack_layout(cabinet, zone, stack_count, applique=False):
    """Hauteur des faces et position basse de chaque tiroir d'un assemblage empilé.

    Retourne une liste de `(drawer_bottom_offset, drawer_face_H_raw)` en mm, du bas
    vers le haut, dans la convention de `drawer_bottom_offset` : depuis le bas
    EXTÉRIEUR du caisson (comme les `y_min` / `y_max` des zones).

    `zone` : une zone de `calculate_all_zones_2d`, ou None pour tout le caisson
    (équivaut à la zone intérieure complète, de la traverse basse à la haute).
    Les tiroirs se répartissent la hauteur de la zone, 2 mm entre deux tiroirs.

    - Encastré : 2 mm de jeu en bas et en haut de la zone.
    - En applique : contre la traverse basse ou haute, la face recouvre la
      traverse (mêmes cotes qu'avant pour tout le caisson : de -1 à H_raw - 3) ;
      contre une étagère, la face s'arrête au bord de la zone, 1 mm de jeu.
    """
    n = max(1, int(stack_count))
    dims = cabinet['dims']
    H_raw = float(dims.get('H_raw', 1000.0))
    t_tb = float(dims.get('t_tb_raw', 19.0))
    y_min = float(zone['y_min']) if zone is not None else t_tb
    y_max = float(zone['y_max']) if zone is not None else H_raw - t_tb
    tol_mm = 1.0

    if applique:
        bottom = -1.0 if y_min <= t_tb + tol_mm else y_min + 1.0
        top = H_raw - 3.0 if y_max >= H_raw - t_tb - tol_mm else y_max - 1.0
    else:
        bottom = y_min + DRAWER_STACK_GAP_MM
        top = y_max - DRAWER_STACK_GAP_MM

    face_h = (top - bottom - (n - 1) * DRAWER_STACK_GAP_MM) / n
    face_h = max(10.0, face_h)
    return [(bottom + k * (face_h + DRAWER_STACK_GAP_MM), face_h) for k in range(n)]


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

def vertical_shelf_span(vs):
    """(bas, haut) d'une étagère verticale, en mm depuis le dessus de la traverse basse."""
    bottom = max(0.0, float(vs.get('bottom_y', 0.0) or 0.0))
    top = max(bottom, float(vs.get('top_y', 0.0) or 0.0))
    return bottom, top


def get_vertical_shelf_tranche_holes(depth, vs_th):
    """Tourillons ⌀8 dans les tranches haute et basse d'une étagère verticale.

    Feuille : longueur (x) = hauteur de l'étagère, largeur (y) = profondeur
    depuis l'avant. Mêmes positions que les tourillons des planches qui la
    reçoivent (`vertical_shelf_plank_holes`), pour que l'assemblage tombe juste.
    """
    _, ys_dowel = calculate_hole_positions(depth)
    return [{'type': 'tourillon', 'x': vs_th / 2.0, 'y': y, 'diam_str': "⌀8/22"} for y in ys_dowel]


def vertical_shelf_plank_holes(cabinet, vs, x_start, y_offset=0.0):
    """Perçages de face d'une planche (traverse ou étagère fixe) qui reçoit une
    étagère verticale : tourillons ⌀8 + vis ⌀3 intercalées, dans l'axe de
    l'étagère. `x_start` = abscisse caisson du bord gauche de la planche ;
    `y_offset` = recul de l'avant de la planche par rapport à l'avant du caisson."""
    depth = carcass_piece_dims(cabinet)['W_inner']
    ys_vis, ys_dowel = calculate_hole_positions(depth)
    x_rel = float(vs.get('position_x', 0.0)) - float(x_start)
    holes = []
    for t, ys, d in (('tourillon', ys_dowel, "⌀8/10"), ('vis', ys_vis, "⌀3")):
        for y in ys:
            y_rel = float(y) - float(y_offset)
            if y_rel > 0.0:
                holes.append({'type': t, 'x': x_rel, 'y': y_rel, 'diam_str': d})
    return holes


def vertical_shelf_traverse_holes(cabinet):
    """(trous traverse basse, trous traverse haute) pour les étagères verticales
    qui reposent sur la traverse basse ou montent jusqu'à la traverse haute."""
    dims = cabinet.get('dims', {}) or {}
    t_lr = float(dims.get('t_lr_raw', 19.0))
    interior_h = float(dims.get('H_raw', 0.0)) - 2.0 * float(dims.get('t_tb_raw', 19.0))
    bottom_holes, top_holes = [], []
    for vs in cabinet.get('vertical_shelves', []) or []:
        bottom, top = vertical_shelf_span(vs)
        if bottom <= 0.5:
            bottom_holes.extend(vertical_shelf_plank_holes(cabinet, vs, t_lr))
        if top >= interior_h - 0.5:
            top_holes.extend(vertical_shelf_plank_holes(cabinet, vs, t_lr))
    return bottom_holes, top_holes


def vertical_shelf_fixed_shelf_holes(cabinet, shelf, setback=0.0):
    """Perçages de face d'une étagère FIXE pour les étagères verticales posées
    dessus ou suspendues dessous (une étagère mobile ne peut pas les recevoir)."""
    if shelf.get('shelf_type', 'mobile') != 'fixe':
        return []
    t_lr = float((cabinet.get('dims', {}) or {}).get('t_lr_raw', 19.0))
    s_bottom = float(shelf.get('height', 0.0))
    s_top = s_bottom + float(shelf.get('thickness', 19.0))
    x0 = shelf.get('stored_shelf_x_start_mm')
    w = shelf.get('stored_shelf_width_mm')
    x_min = float(x0) if x0 is not None else t_lr
    x_max = x_min + float(w) if (x0 is not None and w is not None) else float('inf')
    holes = []
    for vs in cabinet.get('vertical_shelves', []) or []:
        if not (x_min - 0.5 <= float(vs.get('position_x', 0.0)) <= x_max + 0.5):
            continue
        bottom, top = vertical_shelf_span(vs)
        if abs(bottom - s_top) <= 1.0 or abs(top - s_bottom) <= 1.0:
            holes.extend(vertical_shelf_plank_holes(cabinet, vs, x_min, setback))
    return holes


def vertical_shelf_plans(cabinet, cab_idx):
    """Feuilles d'usinage des étagères verticales : (titre, L = hauteur,
    W = profondeur, épaisseur, chants, trous de face, tranches longues,
    tranches côtés = haut/bas, découpe)."""
    depth = carcass_piece_dims(cabinet)['W_inner']
    chants = {"Chant Avant": True, "Chant Arrière": False, "Chant Gauche": False, "Chant Droit": False}
    plans = []
    for k, vs in enumerate(cabinet.get('vertical_shelves', []) or [], start=1):
        bottom, top = vertical_shelf_span(vs)
        if top - bottom <= 0.0:
            continue
        th = float(vs.get('thickness', 19.0))
        plans.append((f"Etagère Verticale {k} (C{cab_idx})", top - bottom, depth, th, dict(chants),
                      [], [], get_vertical_shelf_tranche_holes(depth, th), None))
    return plans


def apply_face_hole_depths(panel_name, face_holes):
    """Profondeurs imposées des perçages de FACE (pas des tranches).

    - Porte : cuvette de charnière ⌀35 et ses 2 vis ⌀8 -> profondeur 13.
    - Joue (face apparente de l'autre côté) : tourillons ⌀8 -> profondeur 12.
    - Toute autre pièce : tout trou ⌀8 -> profondeur 14.
    - Partout : vis ⌀3 -> profondeur 14.
    Retourne une nouvelle liste (les dictionnaires d'origine ne sont pas modifiés).
    """
    import re as _re
    name = str(panel_name or "").lower()
    is_door = "porte" in name or "door" in name
    is_joue = "joue" in name
    out = []
    for h in face_holes or []:
        h = dict(h)
        if h.get("type") == "pied":
            # Trou de pied : ⌀8 profondeur 25, fixé par `foot_holes_by_piece`.
            out.append(h)
            continue
        raw = str(h.get("diam_str", ""))
        m = _re.search(r"(\d+(?:[.,]\d+)?)", raw)
        diam = float(m.group(1).replace(",", ".")) if m else None
        if diam is not None:
            if is_door and abs(diam - 35.0) < 0.01:
                h["diam_str"] = "⌀35/13"
            elif is_door and abs(diam - 8.0) < 0.01:
                h["diam_str"] = "⌀8/13"
            elif is_joue and abs(diam - 8.0) < 0.01:
                h["diam_str"] = "⌀8/12"
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


# LÉGRABOX : longueurs nominales (NL) Blum et profondeur intérieure minimale
# du corps = NL + 3 mm (fiche « Position de vissage des coulisses »).
LEGRABOX_NOMINAL_LENGTHS = (270, 300, 350, 400, 450, 500, 550, 600, 650)
LEGRABOX_NL_DEPTH_MARGIN_MM = 3.0
# La hauteur F n'existe qu'en NL 450 à 650.
LEGRABOX_NL_MIN_BY_TECH = {'F': 450}
LEGRABOX_LOADS_KG = (40, 70)
# Fiche Blum : vis de coulisse au moins 38 mm au-dessus du panneau qui porte le
# tiroir (traverse basse de 19 : 57 mm du bas du montant).
LEGRABOX_SLIDE_MIN_ABOVE_ZONE_MM = 38.0


def legrabox_inner_depth(cabinet):
    """Profondeur intérieure du corps (devant le fond encastré), en mm."""
    W_raw = float((cabinet.get('dims', {}) or {}).get('W_raw', 0.0))
    return max(0.0, W_raw - FOND_REBATE_MM)


def legrabox_nl_options(cabinet, drp):
    """Longueurs nominales qui rentrent dans le caisson pour ce tiroir (croissant)."""
    depth = legrabox_inner_depth(cabinet)
    nl_min = LEGRABOX_NL_MIN_BY_TECH.get(drp.get('drawer_tech_type', 'K'), 0)
    return [nl for nl in LEGRABOX_NOMINAL_LENGTHS
            if nl >= nl_min and nl + LEGRABOX_NL_DEPTH_MARGIN_MM <= depth]


def legrabox_nominal_length(cabinet, drp):
    """NL du tiroir : celle choisie (`legrabox_nl`) si elle rentre, sinon la
    plus grande qui rentre. None si le caisson est trop peu profond."""
    options = legrabox_nl_options(cabinet, drp)
    if not options:
        return None
    chosen = drp.get('legrabox_nl')
    try:
        chosen = int(chosen) if chosen is not None else None
    except (TypeError, ValueError):
        chosen = None
    return chosen if chosen in options else options[-1]


def legrabox_load(drp, nl):
    """Charge de la coulisse (kg). La coulisse 40 kg s'arrête à NL 600 :
    NL 650 passe en 70 kg."""
    try:
        load = int(drp.get('legrabox_load', 40))
    except (TypeError, ValueError):
        load = 40
    if load not in LEGRABOX_LOADS_KG:
        load = 40
    if nl is not None and nl > 600:
        load = 70
    return load


def legrabox_slide_hole_xs(nl, load):
    """Positions de vissage de la coulisse LÉGRABOX sur le montant, en mm
    depuis l'avant du caisson (fiche Blum, NL 450 à 650) : repère à 37,
    trou à 9 devant (28), puis 32 / 224 / 256 / 320 / 416 derrière.
    None hors de la fiche (NL < 450) : l'appelant garde son tableau."""
    if nl is None or nl < 450:
        return None
    xs = [28.0, 37.0, 69.0, 261.0, 293.0]
    if (load == 40 and nl >= 550) or (load == 70 and nl >= 500):
        xs.append(357.0)
    if load == 70 and nl >= 650:
        xs.append(453.0)
    return xs


def drawer_slide_hole_xs(cabinet, drp):
    """Trous de coulisse LÉGRABOX selon la longueur nominale, ou None si le
    tiroir n'est pas une LÉGRABOX couverte par la fiche."""
    if drp.get('drawer_system') != 'LÉGRABOX':
        return None
    nl = legrabox_nominal_length(cabinet, drp)
    return legrabox_slide_hole_xs(nl, legrabox_load(drp, nl))


# Façade de tiroir en applique : jeu entre la façade et le bord extérieur de
# chaque montant qui tient le tiroir.
DRAWER_FACE_EDGE_GAP_MM = 1.0


def _vertical_separators(cabinet):
    """Montants secondaires et étagères verticales : [(x_gauche, x_droite)]."""
    spans = []
    for el in list(cabinet.get('vertical_dividers') or []) + list(cabinet.get('vertical_shelves') or []):
        if el.get('_preview') or el.get('position_x') is None:
            continue
        th = float(el.get('thickness', 19.0))
        cx = float(el['position_x'])
        spans.append((cx - th / 2.0, cx + th / 2.0))
    return spans


def _separator_at(cabinet, x, face, tol=1.0):
    """Montant secondaire / étagère verticale dont la face `face` ('left' /
    'right') est en `x` (repère caisson) : (x_gauche, x_droite), sinon None."""
    for sp in _vertical_separators(cabinet):
        if abs((sp[0] if face == 'left' else sp[1]) - x) <= tol:
            return sp
    return None


def _is_single_separator(cabinet, sp, tol=1.0):
    """Montant secondaire simple : aucun autre panneau ne le touche (sinon
    c'est un double montant)."""
    return not any(o is not sp and (abs(o[1] - sp[0]) <= tol or abs(o[0] - sp[1]) <= tol)
                   for o in _vertical_separators(cabinet))


def drawer_opening_span(cabinet, drp, zones):
    """Ouverture du tiroir (x_min, x_max), repère caisson : entre les faces
    des montants qui l'encadrent. Bornes explicites (import web), sinon zone,
    sinon tout le caisson."""
    dims = cabinet.get('dims', {}) or {}
    t_lr = float(dims.get('t_lr_raw', 19.0))
    if drp.get('_use_explicit_x_bounds') and drp.get('x_left_mm') is not None and drp.get('x_right_mm') is not None:
        x0, x1 = float(drp['x_left_mm']), float(drp['x_right_mm'])
        if x1 > x0:
            return x0, x1
    zone = find_element_zone(drp, zones)
    if zone is not None:
        return float(zone['x_min']), float(zone['x_max'])
    return t_lr, carcass_piece_dims(cabinet)['L_eff'] - t_lr


def drawer_face_span(cabinet, drp, zones):
    """Emprise X (x0, x1) de la façade d'un tiroir en applique, repère caisson.

    La façade couvre les deux montants qui tiennent le tiroir et s'arrête à
    1 mm de leur bord extérieur : montant principal -> 1 mm du bord du
    caisson ; double montant secondaire -> 1 mm du milieu (joint de 2 mm avec
    la façade voisine). Deux tiroirs en applique ne partagent jamais un
    montant secondaire simple (voir `applique_drawer_conflicts`)."""
    t_lr = float((cabinet.get('dims', {}) or {}).get('t_lr_raw', 19.0))
    x_lo, x_hi = drawer_opening_span(cabinet, drp, zones)
    sp = _separator_at(cabinet, x_lo, 'right')
    x0 = (sp[0] if sp else x_lo - t_lr) + DRAWER_FACE_EDGE_GAP_MM
    sp = _separator_at(cabinet, x_hi, 'left')
    x1 = (sp[1] if sp else x_hi + t_lr) - DRAWER_FACE_EDGE_GAP_MM
    return x0, max(x0, x1)


def applique_drawer_conflicts(cabinet, zones):
    """Tiroirs posés côte à côte de part et d'autre d'un montant secondaire
    SIMPLE : leurs façades en applique se chevaucheraient. [(i, j)] indices
    (dans cabinet['drawers']) des tiroirs en conflit ; il faut un double
    montant entre eux. Toutes les façades sont débitées en applique, sauf
    celles des tiroirs à l'anglaise (posées à l'intérieur)."""
    drawers = cabinet.get('drawers') or []
    info = []
    for i, d in enumerate(drawers):
        if d.get('_preview') or d.get('drawer_system') == 'ANGLAISE':
            continue
        x_lo, x_hi = drawer_opening_span(cabinet, d, zones)
        y0 = float(d.get('drawer_bottom_offset', 0.0))
        info.append((i, x_lo, x_hi, y0, y0 + float(d.get('drawer_face_H_raw', 150.0))))
    conflicts = []
    for i, _, x_hi, y0, y1 in info:
        sp = _separator_at(cabinet, x_hi, 'left')
        if sp is None or not _is_single_separator(cabinet, sp):
            continue
        for j, x_lo2, _, v0, v1 in info:
            if j != i and abs(x_lo2 - sp[1]) <= 1.0 and min(y1, v1) - max(y0, v0) > 0.0:
                conflicts.append((i, j))
    return conflicts


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
    has_span = zone is not None or bool(drp.get('_use_explicit_x_bounds'))
    z_x0, z_x1 = drawer_opening_span(cabinet, drp, zones)
    zone_total = (z_x1 - z_x0) if has_span else L_eff

    nl = None
    if system == 'LÉGRABOX':
        # LW = largeur intérieure de l'ouverture (entre les faces des montants,
        # principaux ou secondaires) : dos LW - 38, fond LW - 35.
        lw = z_x1 - z_x0
        box_face = zone_total - 2.0 * gap
        back_w = max(0.0, lw - 38.0)
        back_h = get_legrabox_specs().get(tech, get_legrabox_specs()['K'])['back_height']
        bottom_w = max(0.0, lw - 35.0)
        # Fond = NL - 10 (dos bois). Caisson trop court pour toute NL :
        # ancien calcul sur la profondeur.
        nl = legrabox_nominal_length(cabinet, drp)
        bottom_d = (nl - 10.0) if nl is not None else max(0.0, W_raw - 2.0 * t_lr - 10.0)
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

    # Façade : largeur de son ouverture (voir drawer_face_span) ; tiroir seul
    # sur toute la largeur -> largeur utile du caisson - 4 mm.
    face_x0, face_x1 = drawer_face_span(cabinet, drp, zones)
    face_w = max(0.0, face_x1 - face_x0)
    # Bords du caisson de tiroir (même règle que la façade « zone »).
    if has_span:
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
        'nl': nl, 'load': legrabox_load(drp, nl) if nl is not None else None,
    }


def door_columns(cabinet):
    """Colonnes où poser une porte : entre deux montants (principaux ou
    secondaires), sur toute la hauteur. [{'x_min', 'x_max'}] en mm, repère
    caisson (faces intérieures des montants)."""
    return [{'x_min': float(z['x_min']), 'x_max': float(z['x_max'])}
            for z in calculate_zones_from_dividers(cabinet, include_hinge_posts=True)]


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


def door_on_hinge_post(cabinet):
    """La colonne de la porte native est-elle bordée d'un montant de charnière
    (montant de 100 mm posé exprès pour les charnières) ?"""
    span = door_zone_span(cabinet)
    if span is None:
        return False
    for div in cabinet.get('vertical_dividers', []) or []:
        if not is_hinge_post(div) or div.get('_preview'):
            continue
        c = float(div.get('position_x', 0.0))
        th = float(div.get('thickness', 19.0))
        tol = max(6.0, th + 1.0)
        if abs(c + th / 2.0 - span[0]) <= tol or abs(c - th / 2.0 - span[1]) <= tol:
            return True
    return False


def door_sheet_hinge_side(cabinet):
    """Bord des cuvettes sur la feuille d'usinage d'une porte simple native :
    'left' | 'right'. Le sens d'ouverture choisi, sauf pour une porte posée
    sur un montant de charnière : cuvettes sur le bord opposé (symétrie)."""
    dp = cabinet.get('door_props', {}) or {}
    side = 'left' if dp.get('door_opening') == 'left' else 'right'
    if door_on_hinge_post(cabinet):
        return 'right' if side == 'left' else 'left'
    return side


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

# Bandeau LED sous la joue de dessous : rainure débouchante sur toute la
# longueur, parallèle au bord arrière (bord arrière, côté mur -> bord de la rainure).
LED_GROOVE_OFFSET_MM = 50.0
LED_GROOVE_WIDTH_MM = 4.0
LED_GROOVE_DEPTH_MM = 8.0


def joue_led_grooves(cabinet, joue_key):
    """Rainure(s) de bandeau LED d'une joue, repère de sa feuille d'usinage
    (offset mesuré depuis le bord arrière, côté mur). Seule la joue de dessous en a."""
    joue = ((cabinet or {}).get('joues', {}) or {}).get(joue_key, {}) or {}
    if joue_key != 'dessous' or not (joue.get('enabled') and joue.get('led_strip')):
        return []
    return [{
        'offset': LED_GROOVE_OFFSET_MM,
        'from_edge': 'arriere',
        'width': LED_GROOVE_WIDTH_MM,
        'depth': LED_GROOVE_DEPTH_MM,
        'label': 'Rainure bandeau LED',
    }]


def joue_drawer_advance_available(cabinet, joue_key):
    """Une joue dessus/dessous peut-elle avancer devant les façades de tiroir ?
    (caisson à tiroir(s) en applique — seuls leurs façades sortent du caisson —
    sans porte qui déclenche déjà l'avancée)."""
    has_applique = any(bool((d or {}).get('_applique_mode')) for d in (cabinet.get('drawers') or []))
    return (joue_key in JOUE_TOP_BOTTOM_KEYS and has_applique
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
    # Caisson posé sur chacun (par la géométrie : voir get_cabinet_above_index),
    # et en retour celui sur lequel chacun repose.
    origins = calculate_origins_recursively(scene_cabinets, 1.0)
    above = [get_cabinet_above_index(scene_cabinets, i, origins) for i in range(len(scene_cabinets))]
    below = {j: i for i, j in enumerate(above) if j is not None}
    for i, cab in enumerate(scene_cabinets):
        H = float(cab.get('dims', {}).get('H_raw', 0.0) or 0.0)
        joues = cab.get('joues', {}) or {}
        child = above[i]
        parent = below.get(i)
        is_upper = parent is not None
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
    _apply_top_joue_spans(scene_cabinets)
    return scene_cabinets


# Deux caissons sont « côte à côte » pour une joue de dessus commune si leurs
# bords se touchent et que leurs dessus et leurs façades sont alignés, à ce
# jeu près.
TOP_JOUE_JOIN_TOLERANCE = 1.0


def _fileur_sides(cab):
    """Largeur du fileur à gauche et à droite du caisson, en mm."""
    dp = cab.get('door_props', {}) or {}
    fileur = float(dp.get('fileur_width', 0) or 0.0)
    if fileur <= 0.0:
        return 0.0, 0.0
    return (fileur, 0.0) if dp.get('door_opening', 'right') == 'left' else (0.0, fileur)


def get_top_joue_neighbor_index(scene_cabinets, cab_index, origins=None):
    """Caisson accolé à droite de `cab_index`, dessus et façade alignés, sinon None."""
    if not (0 <= cab_index < len(scene_cabinets)):
        return None
    if origins is None:
        origins = calculate_origins_recursively(scene_cabinets, 1.0)
    tol = TOP_JOUE_JOIN_TOLERANCE
    cab = scene_cabinets[cab_index]
    d = cab.get('dims', {}) or {}
    x_end = origins[cab_index][0] + float(d.get('L_raw', 0.0) or 0.0)
    top = origins[cab_index][2] + float(d.get('H_raw', 0.0) or 0.0)
    for j, other in enumerate(scene_cabinets):
        if j == cab_index:
            continue
        od = other.get('dims', {}) or {}
        if (abs(origins[j][0] - x_end) <= tol
                and abs(origins[j][1] - origins[cab_index][1]) <= tol
                and abs(origins[j][2] + float(od.get('H_raw', 0.0) or 0.0) - top) <= tol):
            return j
    return None


def _apply_top_joue_spans(scene_cabinets):
    """Joue de dessus commune à deux caissons côte à côte (`joues.dessus.span_right`).

    Pendant des joues latérales communes aux caissons superposés : la joue du
    caisson de gauche s'allonge sur celui de droite, dont la joue de dessus est
    alors masquée (`covered`). Un caisson déjà couvert ne peut pas lancer sa
    propre joue commune : on parcourt donc les caissons de gauche à droite.
    """
    origins = calculate_origins_recursively(scene_cabinets, 1.0)
    covered = set()
    order = sorted(range(len(scene_cabinets)), key=lambda k: origins[k][0])
    for i in order:
        cab = scene_cabinets[i]
        joue = (cab.get('joues', {}) or {}).get('dessus', {}) or {}
        neighbor = get_top_joue_neighbor_index(scene_cabinets, i, origins)
        is_covered = i in covered
        span_right = bool(joue.get('enabled') and joue.get('span_right')
                          and neighbor is not None and not is_covered)
        span = {'covered': is_covered, 'span_right': span_right,
                'neighbor': neighbor, 'front_door': cabinet_has_front_door(cab)}
        if span_right:
            covered.add(neighbor)
            nb = scene_cabinets[neighbor]
            # Du début utile de ce caisson (après un fileur à gauche) à la fin
            # utile du voisin (avant un fileur à droite).
            start = origins[i][0] + _fileur_sides(cab)[0]
            end = (origins[neighbor][0] + float(nb.get('dims', {}).get('L_raw', 0.0) or 0.0)
                   - _fileur_sides(nb)[1])
            span['span_length'] = max(0.0, end - start)
            span['front_door'] = span['front_door'] or cabinet_has_front_door(nb)
        cab.setdefault('joue_spans', {})['dessus'] = span
    return scene_cabinets


def _apply_joue_custom_height(geo, joue):
    """Hauteur choisie d'une joue latérale, plus courte que la hauteur complète.

    Ancrée en bas : le bas de la joue ne bouge pas (cache-pieds compris), la
    joue s'arrête plus bas. Ancrée en haut : le haut reste au ras du meuble et
    le bas remonte. Une valeur nulle ou supérieure garde la hauteur complète.
    """
    try:
        wanted = float(joue.get('custom_height') or 0.0)
    except (TypeError, ValueError):
        wanted = 0.0
    full = float(geo['length'])
    if wanted <= 0.0 or wanted >= full:
        return geo
    if joue.get('height_anchor', 'bottom') == 'top':
        geo['z_offset'] = float(geo['z_offset']) + (full - wanted)
    geo['length'] = wanted
    return geo


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
    elif joue_key == 'dessus':
        span = (cabinet.get('joue_spans', {}) or {}).get('dessus', {}) or {}
        if span.get('covered'):
            return None
        if span.get('span_right'):
            # Joue commune avec le caisson de droite : la longueur couvre les
            # deux caissons (fileurs d'extrémité exclus, déjà déduits).
            dims['L_raw'] = float(span.get('span_length', dims.get('L_raw', 0.0)) or 0.0)
            fileur_width = 0.0
            front_door = bool(span.get('front_door', front_door))
    geo = get_joue_dimensions(joue_key, dims, feet, foot_height, fileur_width)
    if joue_key in JOUE_SIDE_KEYS:
        _apply_joue_custom_height(geo, joue)
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
JOUE_DOWEL_MIN_EDGE = 10.0    # tourillon gardé s'il reste à 10 mm du bord de la joue
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
        child = get_cabinet_above_index(scene_cabinets, cab_index)
        if child is not None:
            covered.append((scene_cabinets[child], float(cab.get('dims', {}).get('H_raw', 0.0))))
    holes = []
    for c, base in covered:
        for h in upright_joue_holes(c):
            z = below + base + float(h['y'])
            if not (JOUE_DOWEL_MIN_EDGE <= z <= length - JOUE_DOWEL_MIN_EDGE):
                continue  # joue raccourcie : ce tourillon tombe hors du panneau
            x = z if joue_key == 'gauche' else length - z
            holes.append({'type': 'tourillon', 'x': x, 'y': front + float(h['x']), 'diam_str': "⌀8"})
    return holes


# --- Tringles -------------------------------------------------------------------
# Tringle de penderie posée dans une zone : visible en 3D et comptée dans la
# feuille de débit, sans usinage. Axe à 60 mm sous le haut de la zone, à
# mi-profondeur ; section ovale 30 x 15 mm.
RAIL_TOP_OFFSET_MM = 60.0
RAIL_SECTION_H_MM = 30.0
RAIL_SECTION_D_MM = 15.0


def normalize_vertical_shelves(cabinet):
    """Recale les étagères verticales dans le repère « depuis la traverse basse ».

    Les anciennes poses copiaient les cotes de la zone (mesurées depuis le bas
    du caisson) : l'étagère se retrouvait une épaisseur de traverse trop haut,
    engagée dans la planche du dessus. Signature : bottom_y/top_y égaux à
    stored_zone_coords. Les étagères recalées sont marquées `y_frame='inner'`.
    """
    t_tb = float((cabinet.get('dims', {}) or {}).get('t_tb_raw', 19.0))
    for vs in cabinet.get('vertical_shelves', []) or []:
        if vs.get('y_frame') == 'inner':
            continue
        z = vs.get('stored_zone_coords') or {}
        try:
            if (abs(float(vs.get('bottom_y')) - float(z['y_min'])) < 0.5
                    and abs(float(vs.get('top_y')) - float(z['y_max'])) < 0.5):
                vs['bottom_y'] = max(0.0, float(vs['bottom_y']) - t_tb)
                vs['top_y'] = max(vs['bottom_y'], float(vs['top_y']) - t_tb)
        except (KeyError, TypeError, ValueError):
            pass
        vs['y_frame'] = 'inner'


# Pieds d'angle : axe à 50 mm du bout de la traverse basse (côté montant) ET
# à 50 mm de son bord avant / arrière : même écart des deux côtés de l'angle.
FOOT_EDGE_OFFSET_MM = 50.0
# Seuls les pieds de 20 mm se fixent par un trou dans la traverse basse.
DRILLED_FOOT_HEIGHT_MM = 20.0
FOOT_HOLE_DIAM_STR = "⌀8/25"


def _is_drilled_foot(foot_height):
    return foot_height is not None and abs(float(foot_height) - DRILLED_FOOT_HEIGHT_MM) <= 0.5


def _intermediate_foot_supports(scene_cabinets, origins):
    """Montants qui peuvent porter un pied intermédiaire de 20 mm : [(x de l'axe,
    y du pied arrière)], repère scène. Montants secondaires posés sur la traverse
    basse (double montant : un seul des deux) et montants de jonction de caissons.
    Pied arrière d'un montant secondaire : 50 mm de SON arrière (il s'arrête
    avant le fond), pour rester à l'écart de son dernier tourillon."""
    supports = []
    for i, (cab, (ox, oy, _)) in enumerate(zip(scene_cabinets, origins)):
        if not cabinet_rests_on_floor(scene_cabinets, i):
            continue
        rear = oy + carcass_piece_dims(cab)['W_inner'] - FOOT_EDGE_OFFSET_MM
        prev = None
        for div in sorted(cab.get('vertical_dividers') or [], key=lambda d: float(d.get('position_x', 0.0))):
            if not _foot_divider_stands_on_traverse(div):
                continue
            cx, th = float(div['position_x']), float(div.get('thickness', 19.0))
            if prev is None or cx - prev[0] > (th + prev[1]) / 2.0 + 1.0:
                supports.append((ox + cx, rear))
            prev = (cx, th)
        t_lr = float(cab['dims'].get('t_lr_raw', 19.0))
        right = ox + carcass_piece_dims(cab)['L_eff']
        if any(j != i and abs(o[0] - right) < 1.0 and cabinet_rests_on_floor(scene_cabinets, j)
               for j, o in enumerate(origins)):
            supports.append((right - t_lr / 2.0, oy + float(cab['dims']['W_raw']) - FOOT_EDGE_OFFSET_MM))
    return supports


def _foot_divider_stands_on_traverse(div):
    if div.get('_preview') or div.get('position_x') is None or is_hinge_post(div):
        return False
    return bool(div.get('_force_full_height')) or div.get('bottom_y') is None or float(div['bottom_y']) <= 0.5


def _intermediate_foot_rows(xl, xr, n_rows, supports, default_rear):
    """Rangées intermédiaires [(x, y du pied arrière)] : chacune va sur le montant
    libre le plus proche de sa place régulière ; s'il n'y a plus de montant, au
    milieu du plus grand intervalle restant."""
    regular = [xl + (xr - xl) * k / (n_rows + 1) for k in range(1, n_rows + 1)]
    candidates = [s for s in supports if xl + 1.0 < s[0] < xr - 1.0]
    pairs = sorted((abs(rx - s[0]), r, c) for r, rx in enumerate(regular) for c, s in enumerate(candidates))
    free_rows, free_supports, rows = set(range(n_rows)), set(range(len(candidates))), []
    for _, r, c in pairs:
        if r in free_rows and c in free_supports:
            free_rows.discard(r)
            free_supports.discard(c)
            rows.append(candidates[c])
    for _ in free_rows:
        edges = sorted([xl, xr] + [x for x, _ in rows])
        lo, hi = max(zip(edges, edges[1:]), key=lambda g: g[1] - g[0])
        rows.append(((lo + hi) / 2.0, default_rear))
    return sorted(rows)


def foot_positions_mm(scene_cabinets, extra_feet=False, extra_rows=0, foot_height=None):
    """Axes des pieds (x, y) en mm dans le repère de la scène (y = 0 à l'avant).

    4 pieds aux coins, à `FOOT_EDGE_OFFSET_MM` du bout de la traverse basse
    (le montant extérieur est ajouté) et de ses bords avant / arrière, plus,
    au-delà de 1 m de large, `extra_rows` rangées intermédiaires (avant +
    arrière) réparties régulièrement. Source unique pour la vue 3D et l'usinage.

    Pieds de 20 mm (vissés) : ceux des côtés sont dans l'axe du montant
    extérieur, les intermédiaires dans l'axe d'un montant secondaire."""
    if not scene_cabinets:
        return []
    origins = calculate_origins_recursively(scene_cabinets, 1.0)
    lefts = [o[0] for o in origins]
    rights = [o[0] + float(c['dims']['L_raw']) for o, c in zip(origins, scene_cabinets)]
    x0, x1 = min(lefts), max(rights)
    y0 = min(o[1] for o in origins)
    y1 = max(o[1] + float(c['dims']['W_raw']) for o, c in zip(origins, scene_cabinets))
    # Épaisseur du montant extérieur gauche / droit (caisson en bout de meuble).
    left_cab, right_cab = scene_cabinets[lefts.index(x0)], scene_cabinets[rights.index(x1)]
    t_left = float(left_cab['dims'].get('t_lr_raw', 19.0))
    t_right = float(right_cab['dims'].get('t_lr_raw', 19.0))
    n_mid = int(extra_rows or 0) if (extra_feet and (x1 - x0) > 1000.0) else 0
    y_front, y_rear = y0 + FOOT_EDGE_OFFSET_MM, y1 - FOOT_EDGE_OFFSET_MM
    if _is_drilled_foot(foot_height):
        xl = x0 + t_left / 2.0
        xr = origins[rights.index(x1)][0] + carcass_piece_dims(right_cab)['L_eff'] - t_right / 2.0
        rows = [(xl, y_rear)] + _intermediate_foot_rows(
            xl, xr, n_mid, _intermediate_foot_supports(scene_cabinets, origins), y_rear) + [(xr, y_rear)]
        return [(x, y) for x, rear in rows for y in (y_front, rear)]
    xl, xr = x0 + t_left + FOOT_EDGE_OFFSET_MM, x1 - t_right - FOOT_EDGE_OFFSET_MM
    xs = [xl + (xr - xl) * k / (n_mid + 1) for k in range(n_mid + 2)]
    return [(x, y) for x in xs for y in (y_front, y_rear)]


def foot_holes_by_piece(scene_cabinets, cab_index, foot_height, extra_feet=False, extra_rows=0):
    """Trous des pieds de 20 mm d'un caisson posé au sol, par pièce :
    {'traverse': [...], 'mg': [...], 'md': [...], 'dividers': {indice: [...]}}.

    Traverse basse : x depuis le montant gauche, y depuis l'avant (un pied sous un
    montant secondaire la traverse et se visse dans la tranche du montant).
    Montants : perçage de la seule tranche basse, x le long de la profondeur."""
    out = {'traverse': [], 'mg': [], 'md': [], 'dividers': {}}
    if not _is_drilled_foot(foot_height) or not cabinet_rests_on_floor(scene_cabinets, cab_index):
        return out
    cab = scene_cabinets[cab_index]
    ox, oy, _ = calculate_origins_recursively(scene_cabinets, 1.0)[cab_index]
    t_lr = float(cab['dims'].get('t_lr_raw', 19.0))
    piece = carcass_piece_dims(cab)
    W = float(cab['dims']['W_raw'])

    def edge_hole(x):
        return {'type': 'pied', 'x': x, 'y': 0.0, 'diam_str': FOOT_HOLE_DIAM_STR, 'only_edge': 'avant'}

    for fx, fy in foot_positions_mm(scene_cabinets, extra_feet, extra_rows, foot_height):
        x_cab, y_rel = fx - ox, fy - oy
        if not 0.0 < y_rel < W:
            continue
        if 0.0 <= x_cab <= t_lr:
            out['mg'].append(edge_hole(y_rel))
        elif piece['L_eff'] - t_lr <= x_cab <= piece['L_eff']:
            out['md'].append(edge_hole(W - y_rel))
        elif t_lr < x_cab < piece['L_eff'] - t_lr:
            out['traverse'].append({'type': 'pied', 'x': x_cab - t_lr, 'y': y_rel, 'diam_str': FOOT_HOLE_DIAM_STR})
            for k, div in enumerate(cab.get('vertical_dividers') or []):
                if _foot_divider_stands_on_traverse(div) and abs(float(div['position_x']) - x_cab) < 0.5:
                    out['dividers'].setdefault(k, []).append(edge_hole(y_rel))
    return out


def scene_floor_width_mm(scene_cabinets):
    """Largeur totale (mm) du meuble, de l'extrémité gauche à la droite."""
    if not scene_cabinets:
        return 0.0
    origins = calculate_origins_recursively(scene_cabinets, 1.0)
    x0 = min(o[0] for o in origins)
    x1 = max(o[0] + float(c['dims']['L_raw']) for o, c in zip(origins, scene_cabinets))
    return x1 - x0


def default_extra_feet_rows(width_mm):
    """Rangées de pieds intermédiaires par défaut : un appui au moins tous les mètres."""
    import math
    return max(1, math.ceil(float(width_mm) / 1000.0) - 1)


def cabinet_rails(cabinet):
    """Tringles du caisson : [{'x_min', 'x_max', 'y_min', 'y_max'}] en mm
    (zone d'accueil, repère caisson, y depuis le bas du caisson)."""
    out = []
    for r in (cabinet or {}).get('rails', []) or []:
        z = r.get('zone_coords') or {}
        try:
            x0, x1 = float(z['x_min']), float(z['x_max'])
            y0, y1 = float(z['y_min']), float(z['y_max'])
        except (KeyError, TypeError, ValueError):
            continue
        if x1 > x0 and y1 > y0:
            out.append({'x_min': x0, 'x_max': x1, 'y_min': y0, 'y_max': y1})
    return out


def rail_axis_height(zone):
    """Hauteur de l'axe d'une tringle (mm depuis le bas du caisson)."""
    return max(float(zone['y_min']) + RAIL_SECTION_H_MM / 2.0,
               float(zone['y_max']) - RAIL_TOP_OFFSET_MM)
