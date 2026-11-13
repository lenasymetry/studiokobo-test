"""Page Streamlit « KOBO Vérif »."""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict

import pandas as pd
import streamlit as st

from .checks import ERR, INFO, WARN, Finding, check_document, holes_mm, verdict
from .expected import Caisson, Thicknesses, piece_kind
from .reader import read_pdf
from .report import constat_text

COLS = ["Caisson n°", "Largeur (mm)", "Hauteur (mm)", "Profondeur (mm)", "Fileur (mm)"]


@st.cache_data(show_spinner=False, max_entries=3)
def _read(data: bytes):
    return read_pdf(data)


def _page_png(data: bytes, page: int, dpi: int = 80) -> bytes:
    import pymupdf
    with pymupdf.open(stream=data, filetype="pdf") as d:
        return d[page - 1].get_pixmap(dpi=dpi).tobytes("png")


def render() -> None:
    top = st.columns([1, 5])
    if top[0].button("↩ Changer d'outil"):
        st.session_state["app_mode"] = None
        st.rerun()
    st.title("KOBO Vérif")
    st.caption("Contrôle des feuilles d'usinage : on dépose le PDF et les dimensions du meuble, "
               "le programme relit chaque feuille et rend un constat.")

    st.subheader("1. Le PDF des feuilles d'usinage")
    up = st.file_uploader("PDF généré par KOBO Studio (« Feuilles d'usinage »)", type="pdf",
                          key="verif_pdf")
    sheets = None
    if up is not None:
        data = up.getvalue()
        with st.spinner("Lecture du PDF…"):
            try:
                sheets = _read(data)
            except Exception as exc:
                st.error(f"PDF illisible : {exc}")
        if sheets is not None and not any(s.main for s in sheets):
            st.error("Aucune feuille d'usinage KOBO reconnue dans ce PDF. Utilisez le PDF généré par le site "
                     "(bouton « Générer le PDF des feuilles »), pas une impression d'AutoCAD.")
            sheets = None
        elif sheets is not None:
            found = sorted({s.caisson for s in sheets if s.caisson is not None})
            st.success(f"{len(sheets)} feuille(s) lue(s). Caissons trouvés : "
                       f"{', '.join(f'C{c}' for c in found) or 'aucun'}.")

    st.subheader("2. Les dimensions du meuble")
    st.caption("Dimensions hors-tout de chaque caisson (en mm). Un caisson sans dimensions n'est pas contrôlé.")
    found = sorted({s.caisson for s in sheets if s.caisson is not None}) if sheets else [0]
    sig = hashlib.md5(str(found).encode()).hexdigest()
    if st.session_state.get("verif_cab_sig") != sig:
        st.session_state["verif_cab_sig"] = sig
        st.session_state["verif_cab_df"] = pd.DataFrame(
            {COLS[0]: found, COLS[1]: [None] * len(found), COLS[2]: [None] * len(found),
             COLS[3]: [None] * len(found), COLS[4]: [0.0] * len(found)})
    df = st.data_editor(
        st.session_state["verif_cab_df"], num_rows="dynamic", hide_index=True, use_container_width=True,
        key="verif_cab_editor",
        column_config={
            COLS[0]: st.column_config.NumberColumn(COLS[0], min_value=0, step=1, format="%d"),
            COLS[1]: st.column_config.NumberColumn(COLS[1], min_value=0, step=1),
            COLS[2]: st.column_config.NumberColumn(COLS[2], min_value=0, step=1),
            COLS[3]: st.column_config.NumberColumn(COLS[3], min_value=0, step=1),
            COLS[4]: st.column_config.NumberColumn(COLS[4], min_value=0, step=1),
        })
    with st.expander("Épaisseurs des panneaux (mm)", expanded=False):
        c1, c2, c3 = st.columns(3)
        t_m = c1.number_input("Montants", value=19.0, step=1.0)
        t_t = c2.number_input("Traverses", value=19.0, step=1.0)
        t_f = c3.number_input("Fond", value=19.0, step=1.0)

    caissons = {}
    for _, r in df.iterrows():
        try:
            idx, L, H, P = int(r[COLS[0]]), float(r[COLS[1]]), float(r[COLS[2]]), float(r[COLS[3]])
        except (TypeError, ValueError):
            continue
        if L > 0 and H > 0 and P > 0:
            fil = r[COLS[4]]
            caissons[idx] = Caisson(idx, L, H, P, float(fil) if fil == fil and fil else 0.0)

    st.subheader("3. Vérification")
    go = st.button("🔎 Lancer la vérification", type="primary", disabled=sheets is None)
    if go and sheets is not None:
        with st.spinner("Contrôle des feuilles…"):
            findings = check_document(sheets, caissons, Thicknesses(t_m, t_t, t_f))
        st.session_state["verif_result"] = (hashlib.md5(up.getvalue()).hexdigest(), findings,
                                           sorted(caissons), up.name)
    res = st.session_state.get("verif_result")
    if not res or sheets is None or res[0] != hashlib.md5(up.getvalue()).hexdigest():
        if sheets is not None:
            st.info("Renseignez les dimensions puis lancez la vérification.")
        return
    _show(up.getvalue(), sheets, res[1], res[2], res[3])


def _show(pdf: bytes, sheets, findings, declared, filename) -> None:
    state, e, w = verdict(findings)
    if not declared:
        st.warning("Aucune dimension de caisson saisie : seuls les contrôles de perçage ont été faits.")
    box = {"À CORRIGER": st.error, "À VÉRIFIER": st.warning, "CONFORME": st.success}[state]
    box(f"**Avis : {state}** — {e} erreur(s) bloquante(s), {w} point(s) d'attention "
        f"sur {len(sheets)} feuille(s).")

    problems = [f for f in findings if f.sev != INFO]
    tab_a, tab_b, tab_c = st.tabs(["Anomalies", "Toutes les feuilles", "Constat à télécharger"])

    with tab_a:
        if not problems:
            st.success("Aucune anomalie détectée sur les points contrôlés.")
        groups = defaultdict(list)
        for f in problems:
            groups[(f.page or 0, f.piece)].append(f)
        for (page, piece), fs in sorted(groups.items()):
            has_err = any(f.sev == ERR for f in fs)
            head = f"{'🔴' if has_err else '🟠'} Feuille {page} — {piece}" if page else f"🟠 {piece}"
            with st.expander(head, expanded=has_err):
                for f in sorted(fs, key=lambda f: f.sev != ERR):
                    (st.error if f.sev == ERR else st.warning)(f"**{f.rule.capitalize()}** — {f.message}")
                if page:
                    st.image(_page_png(pdf, page), use_column_width=True)

    with tab_b:
        by_page = defaultdict(list)
        for f in findings:
            by_page[f.page].append(f)
        rows = []
        for sh in sheets:
            fs = by_page.get(sh.page, [])
            face, edge, _ = holes_mm(sh) if sh.main and sh.scale else ([], [], [])
            nerr = sum(f.sev == ERR for f in fs)
            nw = sum(f.sev == WARN for f in fs)
            rows.append({
                "Feuille": sh.page,
                "Caisson": sh.title.get("CORPS DE MEUBLE", ""),
                "Pièce": sh.designation,
                "Dimensions (mm)": f"{sh.L_mm:g} x {sh.W_mm:g}" if sh.L_mm else "?",
                "Épaisseur": f"{sh.T_mm:g}" if sh.T_mm else "?",
                "Trous face / tranche": f"{len(face)} / {len(edge)}",
                "Statut": "🔴 erreur" if nerr else ("🟠 attention" if nw else "🟢 ok"),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        choice = st.selectbox("Voir une feuille", [s.page for s in sheets],
                              format_func=lambda p: f"{p} — {sheets[p - 1].designation}")
        st.image(_page_png(pdf, choice, 100), use_column_width=True)

    with tab_c:
        txt = constat_text(filename.rsplit('.', 1)[0], sheets, findings)
        st.text_area("Constat", txt, height=360)
        st.download_button("⬇️ Télécharger le constat (.txt)", txt.encode("utf-8"),
                           "Constat_verification.txt", "text/plain")

    with st.expander("Ce qui est contrôlé"):
        st.markdown(
            "- **Dimensions** de chaque pièce du corps (traverses, montants, fond, montants secondaires, étagères) "
            "recalculées depuis les dimensions du meuble, et épaisseur cotée.\n"
            "- **Trous** : dans la pièce, matière suffisante vers les bords, pas de chevauchement, "
            "trous de tranche centrés et plus petits que l'épaisseur.\n"
            "- **Repères de perçage** (Ø, profondeur, nombre) : même nombre de trous dessinés que de trous annoncés, "
            "profondeur compatible avec l'épaisseur.\n"
            "- **Cotes** : chaque cote retrouvée sur le dessin (bords et trous).\n"
            "- **Orientation** : triangle présent et sans trou dessous.\n"
            "- **Ensemble** : pièces de base présentes par caisson, numérotation des feuillets, montants gauche/droit symétriques.")
