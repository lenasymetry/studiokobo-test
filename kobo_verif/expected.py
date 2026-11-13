"""Pièces attendues d'un caisson, à partir de ses seules dimensions globales.

Mêmes règles que la feuille de débit du site (machining_logic.carcass_piece_dims),
recalculées ici de façon INDÉPENDANTE du PDF contrôlé.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from machining_logic import FOND_REBATE_MM, carcass_piece_dims


@dataclass
class Caisson:
    index: int
    L: float            # largeur hors-tout
    H: float            # hauteur
    P: float            # profondeur
    fileur: float = 0.0


@dataclass
class Thicknesses:
    montants: float = 19.0
    traverses: float = 19.0
    fond: float = 19.0


@dataclass
class Expected:
    kind: str                       # clé du type de pièce
    label: str
    dims: Optional[Tuple[float, float]]   # (a, b) sans ordre imposé
    thickness: Optional[float]
    bound: Optional[Tuple[float, float]] = None   # maxima (a, b) quand seule une borne est connue


def piece_kind(designation: str) -> Optional[str]:
    d = designation.lower()
    if "traverse bas" in d:
        return "traverse_bas"
    if "traverse haut" in d:
        return "traverse_haut"
    if "montant gauche" in d:
        return "montant_gauche"
    if "montant droit" in d:
        return "montant_droit"
    if "fond" in d and "tiroir" not in d:
        return "fond"
    if "montant secondaire" in d:
        return "montant_secondaire"
    if "etagere fixe" in d or "étagère fixe" in d:
        return "etagere_fixe"
    if "etagere mobile" in d or "étagère mobile" in d:
        return "etagere_mobile"
    return None


CORE_KINDS = ("traverse_bas", "traverse_haut", "montant_gauche", "montant_droit", "fond")


def expected_for(kind: str, c: Caisson, t: Thicknesses) -> Optional[Expected]:
    body = carcass_piece_dims({"dims": {"L_raw": c.L, "W_raw": c.P, "H_raw": c.H,
                                        "t_lr_raw": t.montants},
                               "door_props": {"fileur_width": c.fileur}})
    if kind in ("traverse_bas", "traverse_haut"):
        return Expected(kind, "Traverse", (body["L_traverse"], body["W_traverse"]), t.traverses)
    if kind in ("montant_gauche", "montant_droit"):
        return Expected(kind, "Montant", (c.H, c.P), t.montants)
    if kind == "fond":
        return Expected(kind, "Fond", (body["fond_W"], body["fond_H"]), t.fond)
    if kind == "montant_secondaire":
        return Expected(kind, "Montant secondaire", (body["W_inner"], c.H - 2.0 * t.traverses), t.montants)
    if kind == "etagere_fixe":
        # longueur = sa zone (jamais plus que la traverse), profondeur = profondeur - 19
        return Expected(kind, "Étagère fixe", None, t.traverses,
                        bound=(body["L_traverse"], body["W_inner"]))
    if kind == "etagere_mobile":
        return Expected(kind, "Étagère mobile", None, t.traverses,
                        bound=(body["L_traverse"] - 2.0, body["W_inner"] - 20.0))
    return None
