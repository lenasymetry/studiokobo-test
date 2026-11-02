"""Nomenclature de la quincaillerie du projet (PDF).

Les quantités de vis, tourillons et charnières sont prises sur les feuilles
d'usinage réellement exportées (mêmes listes de trous que le DXF) :
- 1 trou de vis = 1 vis ;
- 2 trous de tourillon = 1 tourillon ;
- 1 lot cuvette ⌀35 + 2 vis ⌀8 sur une porte = 1 charnière.
Une ligne dont la quantité est nulle n'est pas écrite.
"""

import io
import math
from collections import OrderedDict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from machining_logic import cabinet_rails


def _plan_quantity(plan):
    try:
        return max(1, int((plan.get("project") or {}).get("quantity", 1) or 1))
    except (TypeError, ValueError):
        return 1


def _plan_holes(plan):
    """Trous percés sur la pièce : face + tranches (chaque liste de tranche est
    percée sur les DEUX tranches opposées). Une face 2/2 est la même pièce que
    sa face 1/2 : ses tranches, déjà comptées, ne le sont pas une 2e fois."""
    holes = list(plan.get("face_holes") or [])
    if "2/2" not in str(plan.get("title", "")):
        for key in ("tranche_long_holes", "tranche_side_holes"):
            holes.extend(list(plan.get(key) or []) * 2)
    return [h for h in holes if isinstance(h, dict)]


def count_hardware(sheet_plans):
    """{'vis', 'tourillon_trous', 'charniere'} sur l'ensemble des feuilles."""
    vis = tour = hinges = 0
    for plan in sheet_plans or []:
        qty = _plan_quantity(plan)
        for h in _plan_holes(plan):
            if h.get("hinge"):
                hinges += qty if h.get("hinge") == "cup" else 0
            elif h.get("type") == "vis":
                vis += qty
            elif h.get("type") == "tourillon":
                tour += qty
    return {"vis": vis, "tourillon_trous": tour, "charniere": hinges}


def _drawer_label(drp):
    system = str(drp.get("drawer_system", "TANDEMBOX") or "TANDEMBOX")
    tech = str(drp.get("drawer_tech_type", "K") or "K")
    if system == "ANGLAISE":
        return f"Tiroir à l'anglaise - type {tech}"
    return f"Tiroir {system} - type {tech}"


def nomenclature_lines(scene, sheet_plans):
    """[(désignation, quantité, détail)] sans les lignes à 0."""
    lines = []

    rail_lengths = OrderedDict()
    drawers = OrderedDict()
    for i, cab in enumerate(scene or []):
        if not isinstance(cab, dict):
            continue
        for rz in cabinet_rails(cab):
            length = round(rz["x_max"] - rz["x_min"])
            rail_lengths.setdefault(length, []).append(f"C{i}")
        for drp in cab.get("drawers") or []:
            drawers.setdefault(_drawer_label(drp), []).append(f"C{i}")

    n_rails = sum(len(v) for v in rail_lengths.values())
    if n_rails:
        detail = " ; ".join(
            f"{len(cabs)} × {length} mm ({', '.join(dict.fromkeys(cabs))})"
            for length, cabs in rail_lengths.items()
        )
        lines.append(("Tringle", n_rails, detail))

    counts = count_hardware(sheet_plans)
    if counts["vis"]:
        lines.append(("Vis", counts["vis"], "1 trou de vis = 1 vis"))
    n_dowels = math.ceil(counts["tourillon_trous"] / 2)
    if n_dowels:
        lines.append(("Tourillon", n_dowels, f"{counts['tourillon_trous']} trous de tourillon (2 trous = 1 tourillon)"))
    if counts["charniere"]:
        lines.append(("Charnière", counts["charniere"], "1 cuvette ⌀35 + 2 vis ⌀8 = 1 charnière"))

    for label, cabs in drawers.items():
        lines.append((label, len(cabs), ", ".join(dict.fromkeys(cabs))))

    return lines


def generate_nomenclature_pdf(lines, project_name="", client="", date_str=""):
    """PDF A4 paysage : en-tête projet + tableau de la quincaillerie."""
    from views_3d_export import _draw_kobo_bar, _load_kobo_logo, _FIG_W_IN, _FIG_H_IN

    fig = plt.figure(figsize=(_FIG_W_IN, _FIG_H_IN))
    fig.text(0.05, 0.92, "NOMENCLATURE", fontsize=20, fontweight="bold", color="#1E1E1E")
    info = [("Projet", project_name), ("Client", client), ("Date", date_str)]
    fig.text(0.05, 0.875, "    ".join(f"{k} : {v}" for k, v in info if v),
             fontsize=10, color="#5A5A5A")

    ax = fig.add_axes([0.05, 0.12, 0.90, 0.72])
    ax.axis("off")
    if lines:
        table = ax.table(
            cellText=[[label, str(qty), detail] for label, qty, detail in lines],
            colLabels=["Désignation", "Qté", "Détail"],
            colWidths=[0.30, 0.08, 0.62],
            cellLoc="left",
            loc="upper center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 1.9)
        for (row, col), cell in table.get_celld().items():
            cell.set_edgecolor("#1E1E1E")
            if col == 1:
                cell.set_text_props(ha="center")
                cell._loc = "center"
            if row == 0:
                cell.set_text_props(fontweight="bold")
                cell.set_facecolor("#EBEBEB")
    else:
        ax.text(0.5, 0.9, "Aucune quincaillerie dans ce projet.", ha="center", fontsize=11)

    _draw_kobo_bar(fig, _load_kobo_logo())

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        pdf.savefig(fig)
    plt.close(fig)
    return buf.getvalue()
