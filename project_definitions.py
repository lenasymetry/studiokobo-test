# Contenu de project_definitions.py
# Contient les constantes et configurations par défaut

def get_default_dims_19():
    return {
        'L_raw': 600.0, 'W_raw': 600.0, 'H_raw': 800.0,
        't_lr_raw': 19.0, 't_fb_raw': 19.0, 't_tb_raw': 19.0  # OBLIGATOIREMENT 19mm PAR DÉFAUT
    }

def get_default_door_props_19():
    return {
        'has_door': False, 'door_type': 'single', 'door_opening': 'right',
        'door_thickness': 19.0, 'door_gap': 2.0, 'door_model': 'standard', 'material': 'Matière Porte',
        'hinge_mode': 'default',  # 'default' ou 'custom'
        'custom_hinge_positions': [],  # Liste des positions Y personnalisées en mm
        'fileur_width': 0,  # 0 = pas de fileur, 50 = 5 cm, 100 = 10 cm
        # Porte commune à deux caissons superposés : le vantail de ce caisson
        # monte aussi devant le caisson posé juste au-dessus (voir
        # `machining_logic.door_spans_stacked`).
        'span_up': False,
    }

def get_default_drawer_props_19():
    return {
        'has_drawer': False, 'drawer_face_H_raw': 150.0, 'drawer_face_thickness': 19.0,
        'drawer_gap': 2.0, 'drawer_bottom_offset': 0.0, 'drawer_handle_type': 'none',
        'drawer_handle_width': 150.0, 'drawer_handle_height': 40.0, 'drawer_handle_offset_top': 10.0,
        'material': 'Matière Tiroir',
        # Épaisseur intérieure (dos + fond) par défaut
        'inner_thickness': 16.0
    }

def get_default_drawer_props():
    """Retourne les propriétés par défaut pour un tiroir individuel."""
    return {
        'drawer_face_H_raw': 150.0,
        'drawer_face_thickness': 19.0,
        'drawer_gap': 2.0,
        'drawer_bottom_offset': 0.0,  # Position Y du bas du tiroir (en mm depuis la traverse inférieure)
        'drawer_system': 'TANDEMBOX',  # 'TANDEMBOX' ou 'LÉGRABOX'
        'drawer_tech_type': 'K',  # Pour TANDEMBOX: 'K', 'M', 'N', 'D'. Pour LÉGRABOX: 'N', 'M', 'K', 'C'
        'drawer_handle_type': 'none',
        'drawer_handle_width': 150.0,
        'drawer_handle_height': 40.0,
        'drawer_handle_offset_top': 10.0,
        'zone_id': None,
        'material': 'Matière Tiroir',
        # Épaisseur intérieure (dos + fond) par défaut
        'inner_thickness': 16.0
    }

def get_default_vertical_divider_props():
    """Retourne les propriétés par défaut pour un montant vertical secondaire."""
    return {
        'position_x': 300.0,  # Position en mm depuis le montant gauche
        'thickness': 19.0,
        'material': 'Matière Corps'
    }

def get_default_vertical_shelf_props():
    """Retourne les propriétés par défaut pour une étagère verticale."""
    return {
        'position_x': 300.0,  # Position en mm depuis le montant gauche
        'bottom_y': 100.0,  # Position Y du bas (en mm depuis la traverse inférieure)
        'top_y': 400.0,  # Position Y du haut (en mm depuis la traverse inférieure)
        'thickness': 19.0,
        'material': 'Matière Corps'
    }

JOUE_KEYS = ('gauche', 'droite', 'dessus', 'dessous')

# Pièce du corps que chaque joue vient habiller. C'est elle qui donne ses
# dimensions à la joue : aucune cote n'est saisie à la main.
JOUE_COVERED_PART = {
    'gauche': 'Montant Gauche',
    'droite': 'Montant Droit',
    'dessus': 'Traverse Haut',
    'dessous': 'Traverse Bas',
}

# Jeu laissé entre le sol et le bas d'un panneau qui descend devant les pieds
# (porte cache-pieds, joue latérale) : de quoi passer un tapis, une plinthe
# souple ou un sol irrégulier sans que la façade ne frotte.
CACHE_PIED_FLOOR_CLEARANCE = 10.0
# Descente des portes et joues cache-pieds sous le bas du caisson (mm), fixe
# quelle que soit la hauteur des pieds ; limitée pour garder au moins
# CACHE_PIED_FLOOR_CLEARANCE au-dessus du sol avec des pieds bas.
CACHE_PIED_DROP = 70.0


def cache_pied_drop_mm(foot_height):
    """Descente d'un panneau cache-pieds sous le caisson, en mm."""
    return max(0.0, min(CACHE_PIED_DROP, float(foot_height or 0.0) - CACHE_PIED_FLOOR_CLEARANCE))


def get_default_joue_props():
    """Retourne les propriétés par défaut pour une joue.

    Les cotes ne sont plus stockées : elles sont recalculées à la volée par
    `get_joue_dimensions` à partir du caisson (voir cette fonction).
    """
    return {
        'enabled': False,
        'material': 'Matière Corps',
    }

def get_joue_length_and_z_offset(joue_key, base_length, has_feet, foot_height):
    """Longueur réelle et décalage Z (vers le bas) d'une joue.

    Les joues gauche/droite descendent devant les pieds : on prolonge la
    longueur de la même descente qu'une porte cache-pieds (70 mm, voir
    `cache_pied_drop_mm`), pour que les deux panneaux s'alignent en bas. On décale
    d'autant le point de départ vers le bas. Les joues dessus/dessous ne sont
    pas concernées.
    """
    if joue_key not in ('gauche', 'droite') or not has_feet:
        return base_length, 0.0
    extra = cache_pied_drop_mm(foot_height)
    return base_length + extra, -extra

def get_joue_dimensions(joue_key, dims, has_feet=False, foot_height=0.0,
                        fileur_width=0.0):
    """Dimensions automatiques d'une joue, en mm. Rien n'est saisi par l'utilisateur.

    Une joue est un habillage rapporté : elle recouvre exactement la pièce à
    laquelle elle est associée et en reprend donc les cotes —
      * joue gauche / droite -> le montant correspondant
        (longueur = hauteur du caisson, largeur = profondeur, épaisseur = t_lr) ;
      * joue dessus / dessous -> la traverse correspondante
        (longueur = entre-montants, largeur = profondeur, épaisseur = t_tb),
        d'où un décalage en X d'une épaisseur de montant.

    Si le meuble est sur pieds, les joues gauche/droite descendent jusqu'au sol
    pour cacher les pieds, comme une porte cache-pieds : la longueur est
    prolongée de la hauteur des pieds (1 mm de jeu au sol) et le panneau démarre
    d'autant plus bas (`z_offset` négatif).

    Retourne un dict : length, width, thickness, x_offset, z_offset (mm).
    """
    dims = dims or {}
    L_eff = max(0.0, float(dims.get('L_raw', 0.0) or 0.0) - float(fileur_width or 0.0))
    W = float(dims.get('W_raw', 0.0) or 0.0)
    H = float(dims.get('H_raw', 0.0) or 0.0)
    t_lr = float(dims.get('t_lr_raw', 19.0) or 0.0)
    t_tb = float(dims.get('t_tb_raw', 19.0) or 0.0)

    if joue_key in ('gauche', 'droite'):
        base_length, thickness, x_offset = H, t_lr, 0.0
    else:
        base_length, thickness, x_offset = max(0.0, L_eff - 2.0 * t_lr), t_tb, t_lr

    length, z_offset = get_joue_length_and_z_offset(
        joue_key, base_length, has_feet, foot_height
    )
    return {
        'length': length,
        'width': W,
        'thickness': thickness,
        'x_offset': x_offset,
        'z_offset': z_offset,
    }

def get_legrabox_specs():
    """Retourne les spécifications pour le système LÉGRABOX (N, M, K, C)."""
    return {
        'N': {
            'back_height': 39.0,
            'face_holes': {
                'x_offset': 12.0,  # Distance du bord
                'y_coords': [45.5, 61.5],
                'diam_str': '⌀10/12'
            },
            'back_holes': {
                'x_offset': 9.0,  # Distance du bord
                'y_coords': [19.0],
                'diam_str': '⌀2.5/3'
            },
            'bottom_holes': {
                'x_offset': 48.5,  # Distance du bord
                'y_coords': [24.0, 152.0],
                'diam_str': '⌀2.5/3'
            }
        },
        'M': {
            'back_height': 63.0,
            'face_holes': {
                'x_offset': 12.0,
                'y_coords': [51.0, 83.0],
                'diam_str': '⌀10/12'
            },
            'back_holes': {
                'x_offset': 9.0,
                'y_coords': [19.0, 51.0],
                'diam_str': '⌀2.5/3'
            },
            'bottom_holes': {
                'x_offset': 48.5,
                'y_coords': [24.0, 152.0],
                'diam_str': '⌀2.5/3'
            }
        },
        'K': {
            'back_height': 101.0,
            'face_holes': {
                'x_offset': 12.0,
                'y_coords': [51.0, 83.0],
                'diam_str': '⌀10/12'
            },
            'back_holes': {
                'x_offset': 9.0,
                'y_coords': [19.0, 51.0, 83.0],
                'diam_str': '⌀2.5/3'
            },
            'bottom_holes': {
                'x_offset': 48.5,
                'y_coords': [24.0, 152.0],
                'diam_str': '⌀2.5/3'
            }
        },
        'C': {
            'back_height': 148.0,
            'face_holes': {
                'x_offset': 12.0,
                'y_coords': [51.0, 83.0, 179.0],
                'diam_str': '⌀10/12'
            },
            'back_holes': {
                'x_offset': 9.0,
                'y_coords': [19.0, 51.0, 115.0, 131.0],
                'diam_str': '⌀2.5/3'
            },
            'bottom_holes': {
                'x_offset': 48.5,
                'y_coords': [24.0, 152.0],
                'diam_str': '⌀2.5/3'
            }
        }
    }