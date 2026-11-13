"""Mise en forme du constat de vérification (texte)."""
from __future__ import annotations

import datetime
from collections import defaultdict
from typing import List, Sequence

from .checks import ERR, INFO, WARN, Finding, verdict
from .reader import SheetData

ICON = {ERR: "ERREUR", WARN: "ATTENTION", INFO: "OK"}


def constat_text(project: str, sheets: Sequence[SheetData], findings: Sequence[Finding]) -> str:
    state, e, w = verdict(findings)
    lines: List[str] = [
        "KOBO VÉRIF - CONSTAT DE VÉRIFICATION DES FEUILLES D'USINAGE",
        f"Projet : {project or '-'}    Date : {datetime.date.today().strftime('%d/%m/%Y')}",
        f"Feuilles lues : {len(sheets)}",
        f"AVIS : {state}  ({e} erreur(s), {w} point(s) d'attention)",
        "",
    ]
    by = defaultdict(list)
    for f in findings:
        if f.sev != INFO:
            by[(f.page or 0, f.piece)].append(f)
    if not by:
        lines.append("Aucune anomalie détectée sur les points contrôlés.")
    for (page, piece), fs in sorted(by.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        lines.append(f"[Feuille {page}] {piece}" if page else f"[{piece}]")
        for f in sorted(fs, key=lambda f: f.sev != ERR):
            lines.append(f"  - {ICON[f.sev]} ({f.rule}) : {f.message}")
        lines.append("")
    lines.append("Le constat ne remplace pas un contrôle visuel : il vérifie les dimensions, les perçages,")
    lines.append("les repères et l'orientation lus dans le PDF, pas la conception du meuble.")
    return "\n".join(lines)
