#!/usr/bin/env python3
"""Produit les sept figures du mémoire, en PNG 300 ppp et en PDF vectoriel.

Toutes les valeurs tracées sont relues dans les fichiers produits par l'outil : aucun chiffre
n'est saisi à la main dans ce script. Les sources sont, dans l'ordre des figures :

===  ================================================  ==========================================
fig  sujet                                             source
===  ================================================  ==========================================
01   décadence par site                                runs/health_20260815.json
02   les 121 patches Magnitude par catégorie           benchmark_doctor/ground_truth/magnitude_reason_labels.json
03   ablation des détecteurs (P/R, puis par catégorie) runs/validation_ablation_20260815.json
04   courbe longitudinale 03/2024 → 08/2026            runs/longitudinal_curves_20260815.csv + longitudinal_20260815.json
05   coût et performance des approches de la couche L3 runs/ablation_ambiguity_20260815.json
06   désaccord inter-patcheurs                         data/ground_truth.json
07   architecture fonctionnelle de l'outil             schéma, sans données
===  ================================================  ==========================================

Les légendes rédigées sont écrites dans ``figures/legendes.md`` par le même script, et leurs
chiffres sont interpolés depuis les mêmes fichiers : une relance après une nouvelle campagne
met à jour la figure ET sa légende, sans risque de désaccord entre les deux.

Usage :
    python3 figures/make_figures.py            # les sept figures + les légendes
    python3 figures/make_figures.py --only 3 5 # seulement les figures 3 et 5
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path
from typing import Any

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

import figstyle as st
from figstyle import (
    DATA,
    FIGURES_DIR,
    GRAYS,
    GRAYS2,
    GRAYS3,
    GRID,
    INK,
    INK_MUTED,
    INK_SOFT,
    ROOT,
    RULE,
    SURFACE,
    WIDTH_FULL,
    fr,
    light_axes,
    load_json,
    pct,
    save,
    usd,
)

RUNS = ROOT / "runs"

HEALTH = RUNS / "health_20260815.json"
ABLATION = RUNS / "validation_ablation_20260815.json"
CURVES = RUNS / "longitudinal_curves_20260815.csv"
LONGITUDINAL = RUNS / "longitudinal_20260815.json"
AMBIGUITY = RUNS / "ablation_ambiguity_20260815.json"
GROUND_TRUTH = DATA / "ground_truth.json"
MAGNITUDE_LABELS = ROOT / "benchmark_doctor" / "ground_truth" / "magnitude_reason_labels.json"

#: Libellés français des huit catégories de la taxonomie, en version courte pour les axes.
CATEGORY_SHORT = {
    "T1": "dérive temporelle",
    "T2": "dérive de contenu",
    "T3": "accès et effets de bord",
    "T4": "instabilité d'interface",
    "T5": "ambiguïté",
    "T6": "solutions multiples",
    "T7": "fragilité d'évaluation",
    "T8": "dépendance de timing",
}
CATEGORY_ORDER = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]


def fig01() -> dict[str, Any]:
    """Répartition des notes de stabilité par site, quinze barres horizontales empilées.

    Forme retenue : une composition (part-à-tout) par site, et non une simple part de tâches
    dégradées. La part dégradée seule vaut 100 % sur cinq sites : elle n'ordonnerait plus rien.
    L'empilement conserve l'information de gravité (D contre B) qui, elle, discrimine.
    """
    card = load_json(HEALTH)
    by_site = card["by_site"]
    summary = card["summary"]

    sites = sorted(by_site, key=lambda s: by_site[s]["mean_stability"])
    grades = ["D", "C", "B", "A"]
    # Plus la note est basse, plus l'aplat est sombre : l'encre suit la dégradation.
    colors = {"D": GRAYS[0], "C": GRAYS[1], "B": GRAYS[2], "A": GRAYS[3]}
    text_on = {"D": "#ffffff", "C": "#ffffff", "B": INK, "A": INK}

    fig, ax = plt.subplots(figsize=(WIDTH_FULL, 4.9))
    ypos = np.arange(len(sites))[::-1]

    for i, site in enumerate(sites):
        entry = by_site[site]
        n = entry["n"]
        left = 0.0
        for grade in grades:
            count = entry["grades"].get(grade, 0)
            if count == 0:
                continue
            width = 100.0 * count / n
            ax.barh(
                ypos[i], width, left=left, height=0.62,
                color=colors[grade], edgecolor=SURFACE, linewidth=0.8,
            )
            if width >= 6.5:
                # Le fond de l'étiquette reprend la couleur du segment : il masque le trait
                # de repère qui, sinon, barre certains chiffres.
                ax.text(
                    left + width / 2, ypos[i], str(count),
                    ha="center", va="center", fontsize=6.8, color=text_on[grade], zorder=6,
                    bbox=dict(facecolor=colors[grade], edgecolor="none", pad=0.9),
                )
            left += width

    # Repère : part du corpus entier sous la note A.
    below_a = 100.0 * summary["rate_below_A"]
    ax.axvline(below_a, color=INK, linewidth=0.8, linestyle=(0, (3, 2)), zorder=5)
    ax.text(
        below_a - 1.2, len(sites) - 0.15,
        f"corpus entier : {pct(below_a)} sous la note A",
        ha="right", va="center", fontsize=6.8, color=INK_SOFT,
    )

    # Colonnes de droite : score moyen et effectif.
    ax.text(105, len(sites) - 0.15, "score\nmoyen", ha="center", va="center",
            fontsize=6.8, color=INK_SOFT, linespacing=1.15)
    ax.text(119, len(sites) - 0.15, "tâches", ha="center", va="center",
            fontsize=6.8, color=INK_SOFT)
    for i, site in enumerate(sites):
        entry = by_site[site]
        ax.text(105, ypos[i], fr(entry["mean_stability"], 3), ha="center", va="center",
                fontsize=7, color=INK)
        ax.text(119, ypos[i], str(entry["n"]), ha="center", va="center",
                fontsize=7, color=INK_SOFT)

    ax.set_yticks(ypos)
    ax.set_yticklabels(sites, fontsize=7.5, color=INK)
    ax.set_xlim(0, 126)
    ax.set_ylim(-0.7, len(sites) + 0.4)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0", "25", "50", "75", "100 %"])
    ax.set_xlabel("part des tâches du site, par note de stabilité")
    ax.tick_params(axis="y", length=0)
    light_axes(ax)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color(RULE)
    ax.spines["bottom"].set_bounds(0, 100)  # l'axe s'arrête à 100 %, pas aux colonnes de texte

    handles = [
        mpatches.Patch(facecolor=colors[g], label=lab)
        for g, lab in [
            ("D", "D : score < 0,25"),
            ("C", "C : 0,25 à 0,50"),
            ("B", "B : 0,50 à 0,75"),
            ("A", "A : score ≥ 0,75"),
        ]
    ]
    ax.legend(handles=handles, ncols=4, loc="lower left", bbox_to_anchor=(0, 1.01),
              handlelength=1.1, columnspacing=1.0, fontsize=7)

    fig.suptitle(
        "Figure 1. Décadence par site : les 643 tâches de WebVoyager notées au 15 août 2026",
        x=0.0, ha="left", y=1.02, fontsize=9.5, fontweight="bold",
    )
    files = save(fig, "fig01_decadence_par_site")

    worst = sites[0]
    second = sites[1]
    best = sites[-1]
    return {
        "files": files,
        "facts": {
            "worst": worst,
            "worst_mean": by_site[worst]["mean_stability"],
            "worst_d": by_site[worst]["grades"]["D"],
            "worst_n": by_site[worst]["n"],
            "second": second,
            "second_mean": by_site[second]["mean_stability"],
            "best": best,
            "best_mean": by_site[best]["mean_stability"],
            "below_a": below_a,
            "n_below_a": summary["n_below_A"],
            "n_tasks": summary["n_tasks"],
            "n_sites_all_below_a": sum(
                1 for s in sites if by_site[s]["rate_below_A"] >= 1.0
            ),
            "mean_stability": summary["mean_stability"],
        },
    }


def fig02() -> dict[str, Any]:
    """Prévalence des huit catégories dans les 121 patches Magnitude, relus un à un.

    Deux panneaux, parce que deux questions distinctes : à gauche « de quoi meurt une tâche »
    (catégorie principale, ventilée par la décision prise), à droite « ce qui accompagne la
    cause principale » (catégorie secondaire, qui compte les co-occurrences et non des parts).
    """
    labels = load_json(MAGNITUDE_LABELS)

    primary_modify = {c: 0 for c in CATEGORY_ORDER}
    primary_remove = {c: 0 for c in CATEGORY_ORDER}
    secondary = {c: 0 for c in CATEGORY_ORDER}
    n_borderline = 0
    for entry in labels.values():
        bucket = primary_modify if entry["action"] == "modify" else primary_remove
        bucket[entry["categorie"]] += 1
        if entry.get("categorie_secondaire"):
            secondary[entry["categorie_secondaire"]] += 1
        if entry.get("limite"):
            n_borderline += 1

    n_total = len(labels)
    n_modify = sum(primary_modify.values())
    n_remove = sum(primary_remove.values())
    n_secondary = sum(secondary.values())

    fig, (axl, axr) = plt.subplots(
        1, 2, figsize=(WIDTH_FULL, 3.2), gridspec_kw={"width_ratios": [1.7, 1], "wspace": 0.32}
    )
    ypos = np.arange(len(CATEGORY_ORDER))[::-1]
    ylabels = [f"{c} · {CATEGORY_SHORT[c]}" for c in CATEGORY_ORDER]

    # --- panneau gauche : catégorie principale, ventilée par décision
    for i, code in enumerate(CATEGORY_ORDER):
        m, r = primary_modify[code], primary_remove[code]
        # Le détail par segment n'est écrit que si la barre est composite : ailleurs, le total
        # de fin de barre dit déjà tout, et une étiquette de plus serait du bruit.
        split = bool(m) and bool(r)
        if m:
            axl.barh(ypos[i], m, height=0.6, color=GRAYS2[0], edgecolor=SURFACE, linewidth=0.8)
            if split and m >= 6:
                axl.text(m / 2, ypos[i], str(m), ha="center", va="center",
                         fontsize=6.8, color="#ffffff")
        if r:
            axl.barh(ypos[i], r, left=m, height=0.6, color=GRAYS2[1],
                     edgecolor=SURFACE, linewidth=0.8, hatch=st.HATCH_LIGHT)
            if split and r >= 6:
                axl.text(m + r / 2, ypos[i], str(r), ha="center", va="center",
                         fontsize=6.8, color=INK)
        total = m + r
        if total:
            axl.text(total + 1.4, ypos[i], str(total), ha="left", va="center",
                     fontsize=7, color=INK_SOFT)
        else:
            axl.text(1.0, ypos[i], "0", ha="left", va="center", fontsize=7, color=INK_MUTED)

    axl.set_yticks(ypos)
    axl.set_yticklabels(ylabels, fontsize=7.2, color=INK)
    axl.set_xlim(0, 80)
    axl.set_xlabel("nombre de tâches patchées")
    axl.set_title(f"catégorie principale (n = {n_total})", fontsize=8.2, loc="left", pad=16)
    axl.tick_params(axis="y", length=0)
    light_axes(axl, x_grid=True)
    axl.spines["left"].set_visible(False)

    handles = [
        mpatches.Patch(facecolor=GRAYS2[0], label=f"réécriture ({n_modify})"),
        mpatches.Patch(facecolor=GRAYS2[1], hatch=st.HATCH_LIGHT, label=f"suppression ({n_remove})"),
    ]
    axl.legend(handles=handles, ncols=2, loc="lower left", bbox_to_anchor=(0, 1.0),
               handlelength=1.1, fontsize=7)

    # --- panneau droit : catégorie secondaire (co-occurrences)
    for i, code in enumerate(CATEGORY_ORDER):
        value = secondary[code]
        if value:
            axr.barh(ypos[i], value, height=0.6, color=GRAYS[2], edgecolor=SURFACE, linewidth=0.8)
            axr.text(value + 0.2, ypos[i], str(value), ha="left", va="center",
                     fontsize=7, color=INK_SOFT)
        else:
            axr.text(0.15, ypos[i], "0", ha="left", va="center", fontsize=7, color=INK_MUTED)
    axr.set_yticks(ypos)
    axr.set_yticklabels([c for c in CATEGORY_ORDER], fontsize=7.2, color=INK_SOFT)
    axr.set_xlim(0, 9.5)
    axr.set_xticks([0, 2, 4, 6, 8])
    axr.set_xlabel("co-occurrences")
    axr.set_title(f"catégorie secondaire (n = {n_secondary})", fontsize=8.2, loc="left", pad=16)
    axr.tick_params(axis="y", length=0)
    light_axes(axr, x_grid=True)
    axr.spines["left"].set_visible(False)

    fig.suptitle(
        "Figure 2. Les 121 patches Magnitude du 6 juillet 2025, classés dans la taxonomie",
        x=0.0, ha="left", y=1.07, fontsize=9.5, fontweight="bold",
    )
    files = save(fig, "fig02_patches_magnitude_taxonomie")

    return {
        "files": files,
        "facts": {
            "n_total": n_total,
            "n_modify": n_modify,
            "n_remove": n_remove,
            "n_secondary": n_secondary,
            "n_borderline": n_borderline,
            "t1": primary_modify["T1"] + primary_remove["T1"],
            "t1_modify": primary_modify["T1"],
            "t2": primary_modify["T2"] + primary_remove["T2"],
            "t3": primary_modify["T3"] + primary_remove["T3"],
            "t4": primary_modify["T4"] + primary_remove["T4"],
            "t5": primary_modify["T5"] + primary_remove["T5"],
            "t8": primary_modify["T8"] + primary_remove["T8"],
            "empty": [c for c in CATEGORY_ORDER if primary_modify[c] + primary_remove[c] == 0],
        },
    }


#: Décalages des étiquettes du plan précision-rappel, réglés à la main pour éviter les
#: chevauchements. En points typographiques.
#: (seuil servant d'ancre, décalage x, décalage y) par configuration.
_PR_LABEL_OFFSETS = {
    "L1": ("high", 7, 3),
    "L2": ("high", -7, -11),
    "L3": ("high", -8, 6),
    "L1+L2": ("high", 0, 9),
    "L1+L3": ("high", 8, 1),
    "L1+L2+L3": ("medium", 0, 8),
}


def fig03() -> dict[str, Any]:
    """Ablation par couche : plan précision-rappel à gauche, rappel par catégorie à droite.

    Le plan précision-rappel porte les six configurations à leurs deux seuils, reliées par un
    segment : le déplacement le long du segment est l'arbitrage de seuil, le déplacement entre
    segments est l'apport d'une couche. Les courbes d'iso-F1 permettent de lire le compromis
    sans lire les chiffres.
    """
    abl = load_json(ABLATION)
    truth = "signalee_1"
    configs = ["L1", "L2", "L3", "L1+L2", "L1+L3", "L1+L2+L3"]

    fig, (axa, axb) = plt.subplots(
        1, 2, figsize=(WIDTH_FULL, 3.5), gridspec_kw={"width_ratios": [1, 1.12], "wspace": 0.3}
    )

    # --- panneau a : plan précision-rappel
    for f1 in (0.2, 0.4, 0.6, 0.8):
        r = np.linspace(f1 / 2 + 0.002, 1.0, 200)
        p = f1 * r / (2 * r - f1)
        keep = (p <= 1.02) & (p >= 0.0)
        axa.plot(r[keep], p[keep], color=GRID, linewidth=0.6, zorder=1)
        # étiquette de l'iso-F1 posée sur la courbe, à l'intérieur du cadre
        axa.text(0.985, f1 * 0.985 / (1.97 - f1) + 0.012, f"F1 = {fr(f1, 1)}", fontsize=6.0,
                 color=INK_MUTED, va="bottom", ha="right")

    points = {}
    for cfg in configs:
        pts = {}
        for seuil, marker_kw in (
            ("medium", dict(facecolor=SURFACE, edgecolor=INK, linewidth=0.9)),
            ("high", dict(facecolor=INK, edgecolor=INK, linewidth=0.9)),
        ):
            m = abl["ablation"][cfg]["seuils"][seuil]["contre"][truth]
            pts[seuil] = (m["recall"], m["precision"], m["f1"], m["n_flagged"])
        points[cfg] = pts
        (rm, pm, _, _), (rh, ph, _, _) = pts["medium"], pts["high"]
        axa.plot([rm, rh], [pm, ph], color=INK_MUTED, linewidth=0.8, zorder=2, solid_capstyle="round")
        axa.scatter([rm], [pm], s=26, facecolor=SURFACE, edgecolor=INK, linewidth=0.9, zorder=3)
        axa.scatter([rh], [ph], s=26, facecolor=INK, edgecolor=INK, linewidth=0.9, zorder=3)
        anchor, dx, dy = _PR_LABEL_OFFSETS[cfg]
        ax_r, ax_p = (rh, ph) if anchor == "high" else (rm, pm)
        align = "center" if dx == 0 else ("left" if dx > 0 else "right")
        axa.annotate(cfg, (ax_r, ax_p), textcoords="offset points", xytext=(dx, dy),
                     fontsize=7, color=INK, ha=align)

    axa.set_xlim(0, 1.0)
    axa.set_ylim(0, 1.05)
    axa.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    axa.set_xticklabels(["0", "0,25", "0,50", "0,75", "1"])
    axa.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    axa.set_yticklabels(["0", "0,25", "0,50", "0,75", "1"])
    axa.set_xlabel("rappel")
    axa.set_ylabel("précision")
    axa.set_title("(a) plan précision-rappel", fontsize=8.2, loc="left", pad=29)
    light_axes(axa)

    axa.legend(
        handles=[
            Line2D([], [], marker="o", linestyle="none", markerfacecolor=INK,
                   markeredgecolor=INK, markersize=5, label="seuil strict (HIGH)"),
            Line2D([], [], marker="o", linestyle="none", markerfacecolor=SURFACE,
                   markeredgecolor=INK, markersize=5, label="seuil intermédiaire (MEDIUM)"),
        ],
        ncols=2, loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=7, handletextpad=0.3,
    )

    # --- panneau b : rappel par catégorie, seuil MEDIUM
    cat_configs = ["L1", "L1+L2", "L1+L2+L3"]
    cats = [c for c in CATEGORY_ORDER if c in abl["par_categorie"]["L1"]["medium"]]
    n_group = len(cat_configs)
    width = 0.26
    xbase = np.arange(len(cats))

    for j, cfg in enumerate(cat_configs):
        block = abl["par_categorie"][cfg]["medium"]
        good = [100 * block[c]["rappel_bonne_categorie"] for c in cats]
        raw = [100 * block[c]["rappel_brut"] for c in cats]
        offset = (j - (n_group - 1) / 2) * width
        axb.bar(xbase + offset, good, width * 0.92, color=GRAYS3[j],
                edgecolor=SURFACE, linewidth=0.6, zorder=3)
        axb.bar(xbase + offset, np.array(raw) - np.array(good), width * 0.92, bottom=good,
                color=GRAYS3[j], edgecolor=SURFACE, linewidth=0.6, hatch=st.HATCH_LIGHT, zorder=3)

    axb.set_xticks(xbase)
    axb.set_xticklabels(
        [f"{c}\n({abl['par_categorie']['L1']['medium'][c]['n_verite']})" for c in cats],
        fontsize=7,
    )
    axb.set_ylim(0, 108)
    axb.set_yticks([0, 25, 50, 75, 100])
    axb.set_yticklabels(["0", "25", "50", "75", "100 %"])
    axb.set_ylabel("rappel")
    axb.set_xlabel("catégorie de la taxonomie (effectif de la vérité terrain)")
    axb.set_title("(b) rappel par catégorie, seuil intermédiaire (MEDIUM)", fontsize=8.2, loc="left", pad=29)
    light_axes(axb, y_grid=True)

    handles = [mpatches.Patch(facecolor=GRAYS3[j], label=cfg) for j, cfg in enumerate(cat_configs)]
    handles.append(
        mpatches.Patch(facecolor="#ffffff", edgecolor=INK_MUTED, linewidth=0.6,
                       hatch=st.HATCH_LIGHT, label="signalée pour un autre motif")
    )
    axb.legend(handles=handles, ncols=2, loc="lower left", bbox_to_anchor=(0, 1.0),
               fontsize=6.8, handlelength=1.1, columnspacing=0.9)
    # la trame doit se lire en gris sur blanc dans la légende : on force l'encre de la trame
    for patch in axb.get_legend().get_patches():
        if patch.get_hatch():
            patch.set_edgecolor(INK_MUTED)

    fig.suptitle(
        "Figure 3. Ablation des couches de détection de benchmark-doctor",
        x=0.0, ha="left", y=1.10, fontsize=9.5, fontweight="bold",
    )
    files = save(fig, "fig03_ablation_detecteurs")

    auc = {cfg: abl["ordonnancement"][cfg][truth]["auc"] for cfg in configs}
    med = abl["par_categorie"]["L1+L2+L3"]["medium"]
    return {
        "files": files,
        "facts": {
            "points": points,
            "auc": auc,
            "auc_best": max(auc, key=auc.get),
            "t2_l1_medium": abl["par_categorie"]["L1"]["medium"]["T2"],
            "t2_full_medium": med["T2"],
            "t4": med["T4"],
            "t8": med["T8"],
            "t1": med["T1"],
            "n_truth": abl["ground_truths"][truth]["n"],
        },
    }


#: Style de chaque courbe : (couleur, style de trait, marqueur, libellé de légende).
_CURVE_STYLE = {
    "A_praticiens": (INK, "-", "o", "A. observée par les praticiens (WebVoyager, 643)"),
    "B_instrument_high": (GRAYS[2], "-", None, "B. instrument constant, corpus d'origine (643)"),
    "Bprime_corpus_repare_high": (INK, (0, (5, 2)), None, "B′. instrument constant, corpus réparé (590)"),
    "D_online_mind2web": (GRAYS[1], (0, (1.2, 1.6)), "s", "D. contrôle Online-Mind2Web (300)"),
}

#: Décalage vertical de l'étiquette de fin de courbe, en points : B et B′ se terminent à moins
#: d'un point de pourcentage l'une de l'autre et leurs étiquettes se superposeraient.
_CURVE_LABEL_DY = {
    "A_praticiens": 0,
    "B_instrument_high": 5,
    "Bprime_corpus_repare_high": -5,
    "D_online_mind2web": 0,
}


def _read_curves() -> dict[str, list[tuple[dt.date, float]]]:
    """Relit le CSV des courbes et le regroupe par série."""
    series: dict[str, list[tuple[dt.date, float]]] = {}
    with CURVES.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            series.setdefault(row["courbe"], []).append(
                (dt.date.fromisoformat(row["date"]), float(row["pct"]))
            )
    for key in series:
        series[key].sort()
    return series


def fig04() -> dict[str, Any]:
    """Quatre courbes de mortalité sur le même axe, avec les jalons des patch-sets.

    Les quatre séries sont des parts de leur propre corpus : elles partagent donc un axe et un
    seul, malgré des dénominateurs différents (643, 590, 300). Ce point est rappelé dans la
    légende, faute de quoi la comparaison serait trompeuse.
    """
    series = _read_curves()
    longi = load_json(LONGITUDINAL)
    publication = dt.date.fromisoformat(longi["meta"]["publication"])
    measured = dt.date.fromisoformat(longi["meta"]["date_de_mesure"])

    fig, ax = plt.subplots(figsize=(WIDTH_FULL, 3.9))

    # Jalons : les six annotateurs indépendants.
    jalons = [j for j in longi["courbe_A_praticiens"]["jalons"] if j["annotateur_independant"]]
    pretty = {
        "browseruse": "browser-use", "convergence": "Convergence", "magnitude": "Magnitude",
        "fara": "Fara", "alumnium": "Alumnium", "skyvern_2026": "Skyvern",
    }
    seen = set()
    for j in jalons:
        if j["source"] in seen:
            continue
        seen.add(j["source"])
        date = dt.date.fromisoformat(j["date"])
        ax.axvline(date, color=GRID, linewidth=0.6, zorder=0)
        # La date est déjà portée par l'abscisse : l'étiquette ne redit que le nom.
        ax.text(
            date, 35.0, pretty.get(j["source"], j["source"]),
            rotation=90, ha="right", va="top", fontsize=6.4, color=INK_MUTED,
        )

    # Censure à gauche : entre la publication et le premier audit, personne n'a regardé. Le
    # trait est volontairement le plus discret de la figure, puisqu'il n'est pas une mesure.
    first = series["A_praticiens"][0]
    ax.plot(
        [publication, first[0]], [0, first[1]],
        color=GRAYS[3], linewidth=0.9, linestyle=(0, (1, 2.5)), zorder=2,
    )
    ax.text(
        dt.date(2024, 3, 25), 22.5,
        "censure à gauche : aucune\nobservation entre la publication\net le premier audit",
        fontsize=6.6, color=INK_SOFT, ha="left", va="top", linespacing=1.3,
    )

    for key, (color, linestyle, marker, label) in _CURVE_STYLE.items():
        pts = series[key]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        drawstyle = "steps-post" if key in ("A_praticiens", "D_online_mind2web") else "default"
        ax.plot(xs, ys, color=color, linestyle=linestyle, linewidth=1.4,
                drawstyle=drawstyle, label=label, zorder=4)
        if marker:
            ax.plot(xs, ys, linestyle="none", marker=marker, markersize=3.2,
                    markerfacecolor=color, markeredgecolor=color, zorder=5)
        # étiquette directe au dernier point
        ax.annotate(
            pct(ys[-1], 1), (xs[-1], ys[-1]), textcoords="offset points",
            xytext=(4, _CURVE_LABEL_DY[key] - 1),
            fontsize=6.8, color=color if color != GRAYS[2] else INK_SOFT, va="center",
        )

    ax.set_xlim(publication - dt.timedelta(days=20), measured + dt.timedelta(days=170))
    ax.set_ylim(0, 36)
    ax.set_yticks([0, 10, 20, 30])
    ax.set_yticklabels(["0", "10", "20", "30 %"])
    ax.set_ylabel("part du corpus jugée invalide")
    ax.set_xticks([dt.date(y, m, 1) for y in (2024, 2025, 2026) for m in (1, 7)])
    ax.set_xticklabels(["01/2024", "07/2024", "01/2025", "07/2025", "01/2026", "07/2026"])
    ax.set_xlabel("date")
    light_axes(ax, y_grid=True)

    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncols=2, fontsize=6.9,
              handlelength=2.0, columnspacing=1.0)

    fig.suptitle(
        "Figure 4. Mortalité des tâches de mars 2024 à août 2026, selon l'instrument de mesure",
        x=0.0, ha="left", y=1.10, fontsize=9.5, fontweight="bold",
    )
    files = save(fig, "fig04_courbe_longitudinale")

    est = longi["taux_de_decadence"]["estimateurs"]
    return {
        "files": files,
        "facts": {
            "a_first": series["A_praticiens"][0],
            "a_last": series["A_praticiens"][-1],
            "b_last": series["B_instrument_high"][-1],
            "bprime_first": series["Bprime_corpus_repare_high"][0],
            "bprime_last": series["Bprime_corpus_repare_high"][-1],
            "d_last": series["D_online_mind2web"][-1],
            "a2": est["A2_increments_post_premier_audit"],
            "b": est["B_instrument_constant_L1_high"],
            "bprime": est["B_prime_instrument_sur_corpus_repare"],
            "d": est["D_controle_online_mind2web"]
            if "D_controle_online_mind2web" in est
            else next(v for k, v in est.items() if k.startswith("D")),
            "n_jalons": len(seen),
        },
    }


#: (libellé court, libellé d'axe sur deux lignes, famille) par clé de l'ablation d'ambiguïté.
_L3_METHODS = {
    "always_positive": ("tout positif", "tout\npositif", "reference"),
    "site_majority": ("majorité par site", "majorité\npar site", "reference"),
    "heuristic": ("règle lexicale", "règle\nlexicale", "reference"),
    "a_tfidf": ("(a) TF-IDF", "(a)\nTF-IDF", "approche"),
    "b_minilm": ("(b) MiniLM local", "(b)\nMiniLM", "approche"),
    "c_openrouter_embed": ("(c) embeddings", "(c) embeddings", "approche"),
    "d_llm_judge_rubric": ("(d) juge flash-lite\n(rubrique)", "(d) juge flash-lite", "approche"),
    "d_llm_judge_plain": ("(d) juge flash-lite\n(prompt minimal)", "", "variante"),
    "d_llm_judge_gemini-2_5-flash": ("(d′) juge flash", "", "variante"),
    "d_llm_judge_claude-haiku-4_5": ("(d′) juge haiku 4.5", "", "variante"),
}

_L3_MARKERS = {
    "approche": dict(marker="o", s=34, facecolor=INK, edgecolor=INK, linewidth=0.9, zorder=5),
    "variante": dict(marker="s", s=26, facecolor=GRAYS[2], edgecolor=INK, linewidth=0.7, zorder=4),
    "reference": dict(marker="^", s=28, facecolor=SURFACE, edgecolor=INK_MUTED, linewidth=0.8, zorder=3),
}

#: Décalages d'étiquettes, en points, réglés à la main pour éviter les chevauchements.
_L3_LABEL_OFFSETS = {
    # panneau de gauche : seul l'AUC est écrit, le nom étant porté par l'axe
    "always_positive": (0, -14),
    "site_majority": (0, 8),
    "heuristic": (0, -14),
    "a_tfidf": (0, 8),
    "b_minilm": (0, 8),
    # panneau de droite : nom et AUC, blocs de deux lignes centrés verticalement sur le décalage
    "c_openrouter_embed": (7, 6),
    "d_llm_judge_rubric": (10, -13),
    "d_llm_judge_plain": (0, 22),
    "d_llm_judge_gemini-2_5-flash": (0, 20),
    "d_llm_judge_claude-haiku-4_5": (-9, 0),
}


def fig05() -> dict[str, Any]:
    """Compromis coût / performance des quatre approches de la couche L3.

    Deux panneaux, parce qu'un axe logarithmique ne représente pas la gratuité : les méthodes
    sans appel facturé occupent un panneau catégoriel à gauche, les méthodes facturées un axe
    logarithmique à droite. La rupture est explicite, ce qui vaut mieux qu'un zéro déguisé.
    """
    abl = load_json(AMBIGUITY)
    results = {r["key"]: r for r in abl["results"]}
    costs = abl["cost_projection"]

    free = [k for k in _L3_METHODS if costs[k]["usd_per_year_weekly_643"] == 0]
    paid = [k for k in _L3_METHODS if costs[k]["usd_per_year_weekly_643"] > 0]
    paid.sort(key=lambda k: costs[k]["usd_per_year_weekly_643"])

    fig, (axl, axr) = plt.subplots(
        1, 2, figsize=(WIDTH_FULL, 3.4), sharey=True,
        gridspec_kw={"width_ratios": [0.72, 1], "wspace": 0.06},
    )

    baseline = results["always_positive"]["fixed_threshold_0_5"]["f1"]
    for ax in (axl, axr):
        ax.axhline(baseline, color=INK_MUTED, linewidth=0.7, linestyle=(0, (4, 2.5)), zorder=1)

    # --- panneau gauche : coût nul. Le nom est porté par l'axe, l'étiquette ne dit que l'AUC.
    for i, key in enumerate(free):
        f1 = results[key]["fixed_threshold_0_5"]["f1"]
        _, _, family = _L3_METHODS[key]
        axl.scatter([i], [f1], **_L3_MARKERS[family])
        dx, dy = _L3_LABEL_OFFSETS[key]
        axl.annotate(
            f"AUC {fr(results[key]['auc'], 2)}", (i, f1), textcoords="offset points",
            xytext=(dx, dy), ha="center", fontsize=6.2, color=INK_MUTED,
        )
    axl.set_xticks(range(len(free)))
    axl.set_xticklabels([_L3_METHODS[k][1] for k in free], fontsize=6.5, linespacing=1.2)
    axl.set_xlim(-0.6, len(free) - 0.4)
    axl.set_ylim(0.25, 0.94)
    axl.set_yticks([0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    axl.set_yticklabels([fr(v, 1) for v in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)])
    axl.set_ylabel("F1 au seuil 0,5")
    axl.set_title("aucun appel facturé", fontsize=8.0, loc="left", pad=6)
    light_axes(axl, y_grid=True)

    # --- panneau droit : coût facturé, échelle logarithmique
    for key in paid:
        cost = costs[key]["usd_per_year_weekly_643"]
        f1 = results[key]["fixed_threshold_0_5"]["f1"]
        label, _, family = _L3_METHODS[key]
        axr.scatter([cost], [f1], **_L3_MARKERS[family])
        dx, dy = _L3_LABEL_OFFSETS[key]
        align = "center" if dx == 0 else ("left" if dx > 0 else "right")
        axr.annotate(
            f"{label}\nAUC {fr(results[key]['auc'], 2)}", (cost, f1),
            textcoords="offset points", xytext=(dx, dy), ha=align, va="center",
            fontsize=6.4, color=INK_SOFT, linespacing=1.25,
        )
    axr.set_xscale("log")
    axr.set_xlim(0.008, 150)
    axr.set_xticks([0.01, 0.1, 1, 10, 100])
    axr.set_xticklabels(["0,01 $", "0,10 $", "1 $", "10 $", "100 $"])
    axr.set_title("coût facturé à l'appel (échelle logarithmique)", fontsize=8.0, loc="left", pad=6)
    axr.tick_params(axis="y", length=0)
    light_axes(axr, x_grid=True, y_grid=True)
    axr.spines["left"].set_visible(False)

    fig.supxlabel(
        "coût annuel d'une surveillance hebdomadaire des 643 tâches",
        x=0.54, ha="center", y=-0.08, fontsize=8, color=INK,
    )
    axl.text(
        -0.5, baseline + 0.012, f"plancher trivial : F1 = {fr(baseline, 2)}",
        fontsize=6.3, color=INK_MUTED, ha="left", va="bottom",
    )

    handles = [
        Line2D([], [], marker="o", linestyle="none", markerfacecolor=INK, markeredgecolor=INK,
               markersize=5, label="approche évaluée (a) à (d)"),
        Line2D([], [], marker="s", linestyle="none", markerfacecolor=GRAYS[2],
               markeredgecolor=INK, markersize=5, label="variante de prompt ou de modèle"),
        Line2D([], [], marker="^", linestyle="none", markerfacecolor=SURFACE,
               markeredgecolor=INK_MUTED, markersize=5, label="référence naïve"),
    ]
    fig.legend(handles=handles, ncols=3, loc="lower left", bbox_to_anchor=(0.0, 1.0),
               fontsize=7, handletextpad=0.3, columnspacing=1.2)

    fig.suptitle(
        "Figure 5. Coût et performance des quatre approches candidates pour la couche L3",
        x=0.0, ha="left", y=1.12, fontsize=9.5, fontweight="bold",
    )
    files = save(fig, "fig05_cout_performance_l3")

    return {
        "files": files,
        "facts": {
            "n_annotated": abl["annotations"]["n"],
            "baseline_f1": baseline,
            "best_f1_key": max(results, key=lambda k: results[k]["fixed_threshold_0_5"]["f1"]),
            "results": {k: results[k] for k in _L3_METHODS},
            "costs": {k: costs[k] for k in _L3_METHODS},
        },
    }


_ANNOTATORS = [
    ("browseruse", "browser-use\n12/2024"),
    ("convergence", "Convergence\n02/2025"),
    ("magnitude", "Magnitude\n07/2025"),
    ("fara", "Fara\n08/2025"),
    ("alumnium", "Alumnium\n03/2026"),
    ("skyvern_2026", "Skyvern\n05/2026"),
]


def fig06() -> dict[str, Any]:
    """Matrice orientée du désaccord dur, et distribution du nombre d'annotateurs signalants.

    La matrice n'est pas symétrique et ne doit pas l'être : « supprimée par A, conservée telle
    quelle par B » n'est pas la même affirmation que l'inverse. Les effectifs sont imprimés
    dans chaque case, ce qui rend la lecture indépendante du niveau de gris.
    """
    gt = load_json(GROUND_TRUTH)
    stats = gt["statistiques"]
    matrix_src = stats["desaccord"]["matrice_orientee"]
    coverage = stats["couverture"]

    keys = [k for k, _ in _ANNOTATORS]
    labels = [lab for _, lab in _ANNOTATORS]
    n = len(keys)
    hard = np.full((n, n), np.nan)
    soft = np.zeros((n, n), dtype=int)
    for i, a in enumerate(keys):
        for j, b in enumerate(keys):
            if i == j:
                continue
            entry = matrix_src.get(f"{a}|{b}", {})
            hard[i, j] = entry.get("supprimee_par_a_conservee_intacte_par_b", 0)
            soft[i, j] = entry.get("supprimee_par_a_reecrite_par_b", 0)

    fig, (axm, axd) = plt.subplots(
        1, 2, figsize=(WIDTH_FULL, 3.5), gridspec_kw={"width_ratios": [1.5, 1], "wspace": 0.42}
    )

    vmax = float(np.nanmax(hard))
    cmap = plt.get_cmap("Greys")
    for i in range(n):
        for j in range(n):
            if i == j:
                axm.add_patch(
                    mpatches.Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor="#f2f2f2",
                                       edgecolor=SURFACE, linewidth=1.2)
                )
                axm.text(j, i, "–", ha="center", va="center", fontsize=7.5, color=INK_MUTED)
                continue
            value = hard[i, j]
            shade = 0.06 + 0.72 * (value / vmax)
            axm.add_patch(
                mpatches.Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor=cmap(shade),
                                   edgecolor=SURFACE, linewidth=1.2)
            )
            axm.text(
                j, i, str(int(value)), ha="center", va="center", fontsize=7.6,
                color="#ffffff" if shade > 0.45 else INK,
            )

    axm.set_xlim(-0.5, n - 0.5)
    axm.set_ylim(n - 0.5, -0.5)
    axm.set_xticks(range(n))
    axm.set_yticks(range(n))
    # En colonne, seul le nom : la date est déjà portée par la ligne homonyme.
    axm.set_xticklabels([lab.split("\n")[0] for lab in labels], fontsize=6.3, color=INK_SOFT,
                        rotation=22, ha="right", rotation_mode="anchor")
    axm.set_yticklabels(labels, fontsize=6.3, color=INK_SOFT, linespacing=1.15)
    axm.set_xlabel("B : conserve la tâche telle quelle", fontsize=7.5)
    axm.set_ylabel("A : supprime la tâche", fontsize=7.5)
    axm.tick_params(length=0)
    for spine in axm.spines.values():
        spine.set_visible(False)
    axm.set_title("(a) désaccord dur, en nombre de tâches", fontsize=8.2, loc="left", pad=8)

    # --- panneau b : distribution du nombre d'annotateurs signalants (1 à 6)
    dist = coverage["distribution_nb_annotateurs_signalant"]
    xs = [1, 2, 3, 4, 5, 6]
    ys = [dist[str(k)] for k in xs]
    bars = axd.bar(xs, ys, width=0.66, color=GRAYS[2], edgecolor=SURFACE, linewidth=0.8, zorder=3)
    bars[-1].set_color(GRAYS[0])
    for x, y in zip(xs, ys):
        axd.text(x, y + 1.8, str(y), ha="center", va="bottom", fontsize=7,
                 color=INK if x == 6 else INK_SOFT)
    axd.set_xticks(xs)
    axd.set_xlabel("nombre d'annotateurs signalant la tâche")
    axd.set_ylabel("nombre de tâches")
    axd.set_ylim(0, max(ys) * 1.24)
    light_axes(axd, y_grid=True)
    axd.set_title("(b) accord entre les six annotateurs", fontsize=8.2, loc="left", pad=8)
    axd.text(
        0.62, max(ys) * 0.97,
        f"{coverage['signalee_par_au_moins_1']} tâches sont signalées\nau moins une fois ; "
        f"{coverage['jamais_signalee']} autres\nne le sont par personne et\nne figurent pas ici",
        fontsize=6.5, color=INK_MUTED, ha="left", va="top", linespacing=1.3,
    )

    fig.suptitle(
        "Figure 6. Les six patch-sets ne mesurent pas le même benchmark",
        x=0.0, ha="left", y=1.045, fontsize=9.5, fontweight="bold",
    )
    files = save(fig, "fig06_desaccord_inter_patcheurs")

    flat = [(keys[i], keys[j], int(hard[i, j])) for i in range(n) for j in range(n) if i != j]
    flat.sort(key=lambda t: -t[2])
    return {
        "files": files,
        "facts": {
            "n_hard": stats["desaccord"]["taches_en_desaccord_dur"],
            "max_pair": flat[0],
            # toutes les paires ex æquo au maximum : il y en a deux dans la mesure du 15/08
            "top_pairs": [t for t in flat if t[2] == flat[0][2]],
            "total_soft": int(soft.sum()),
            "dist": dist,
            "jamais": coverage["jamais_signalee"],
            "unanime": coverage["signalee_par_tous"],
            "au_moins_1": coverage["signalee_par_au_moins_1"],
            "labels": dict(_ANNOTATORS),
        },
    }


#: Hauteur du schéma fonctionnel, en pouces, et conversion unité → point typographique. Le
#: repère du schéma va de 0 à 100 sur les deux axes et l'axe occupe exactement la figure :
#: une unité d'ordonnée vaut donc `FIG7_HEIGHT × 72 / 100` points. Cette conversion sert à
#: centrer les blocs de texte dans les boîtes sans tâtonner.
FIG7_HEIGHT = 4.2
PT_PER_UNIT_Y = FIG7_HEIGHT * 72 / 100


def _box(ax, x, y, w, h, title, body, *, dashed=False, emphasis=False,
         title_size=7.0, body_size=5.9):
    """Trace une boîte du schéma fonctionnel, texte vertically centré, et retourne ses bords.

    Le bloc de texte (titre + corps) est centré sur le milieu de la boîte, sa hauteur étant
    calculée à partir des tailles de police converties en unités du repère.
    """
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0,rounding_size=1.4",
            linewidth=1.3 if emphasis else 1.0,
            edgecolor=INK_SOFT if dashed else INK,
            facecolor="#f0f0f0" if emphasis else SURFACE,
            linestyle=(0, (3, 2)) if dashed else "-",
            zorder=3,
        )
    )
    cx, cy = x + w / 2, y + h / 2
    title_h = title_size / PT_PER_UNIT_Y
    n_lines = body.count("\n") + 1 if body else 0
    body_h = n_lines * body_size * 1.35 / PT_PER_UNIT_Y
    gap = 0.9 if body else 0.0
    top = cy + (title_h + gap + body_h) / 2
    ax.text(cx, top, title, ha="center", va="top", fontsize=title_size,
            fontweight="bold", color=INK, zorder=4)
    if body:
        ax.text(cx, top - title_h - gap, body, ha="center", va="top", fontsize=body_size,
                color=INK_SOFT, linespacing=1.35, zorder=4)
    return {"x": x, "y": y, "w": w, "h": h, "cx": cx, "cy": cy,
            "right": x + w, "top": y + h}


def _arrow(ax, start, end, *, rad=0.0, muted=False):
    """Trace une flèche entre deux points du schéma."""
    ax.add_patch(
        FancyArrowPatch(
            start, end,
            arrowstyle="-|>", mutation_scale=7, linewidth=0.85,
            color=INK_MUTED if muted else INK,
            connectionstyle=f"arc3,rad={rad}", shrinkA=1.5, shrinkB=1.5, zorder=2,
        )
    )


def fig07() -> dict[str, Any]:
    """Schéma d'architecture fonctionnelle : le flux et sa boucle de re-mesure.

    Le schéma est fonctionnel et non technique : il montre ce que chaque étape produit et qui
    décide, pas les modules ni les bibliothèques. La boucle de retour est l'objet même du
    mémoire : une réparation n'est pas un état stable, elle est une observation datée de plus.
    """
    card = load_json(HEALTH)
    cost = card["cost"]
    summary = card["summary"]
    by_layer = cost["by_layer"]

    fig = plt.figure(figsize=(WIDTH_FULL, FIG7_HEIGHT))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    cols = [0.5, 26.5, 52.5, 78.5]
    bw = 21.0
    y_a, bh_a = 62.0, 26.0
    y_b, bh_b = 16.0, 22.0

    def layer_cost(key: str) -> str:
        entry = by_layer.get(key, {})
        value = entry.get("usd", 0.0)
        return "sans coût d'API" if value == 0 else f"{usd(value)}"

    # --- rangée haute : le corpus, les trois couches, l'agrégation, la carte
    corpus = _box(ax, cols[0], y_a, bw, bh_a, "Corpus de tâches",
                  f"{summary['n_tasks']} énoncés\net leur URL de départ")

    lgap = 1.0
    lh = (bh_a - 2 * lgap) / 3
    layers = []
    specs = [
        ("L1 · analyse statique", f"dates, effets de bord,\nréférences · {layer_cost('L1')}"),
        ("L2 · sondes web", f"disponibilité, anti-bot,\ncontenu · {layer_cost('L2')}"),
        ("L3 · juge LLM", f"ambiguïté, résolubilité\n{layer_cost('L3')} par campagne"),
    ]
    for i, (title, body) in enumerate(specs):
        y = y_a + bh_a - lh - i * (lh + lgap)
        layers.append(_box(ax, cols[1], y, bw, lh, title, body,
                           title_size=6.3, body_size=5.4))

    aggregation = _box(ax, cols[2], y_a, bw, bh_a, "Agrégation",
                       "OU-bruité par catégorie\nscore de stabilité S\nnote A à D",
                       emphasis=True)
    health = _box(ax, cols[3], y_a, bw, bh_a, "Carte de santé",
                  "JSON et HTML\nprévalence par catégorie\ncoût et date de mesure")

    # --- rangée basse : l'arbitrage humain, la décision, le patch, le sous-ensemble
    arbitration = _box(ax, cols[3], y_b, bw, bh_b, "Arbitrage humain",
                       "l'outil trie les constats,\nle verdict reste humain", dashed=True)
    decision = _box(ax, cols[2], y_b, bw, bh_b, "Décision datée",
                    "conserver, réécrire\nou retirer")
    patch = _box(ax, cols[1], y_b, bw, bh_b, "Patch canonique",
                 "énoncé corrigé\net métadonnées\nde stabilité")
    verified = _box(ax, cols[0], y_b, bw, bh_b, "Sous-ensemble vérifié",
                    "WebVoyager-Verified\navec verdict par tâche")

    # --- flux : éventail vers les couches, éventail vers l'agrégation
    for layer in layers:
        _arrow(ax, (corpus["right"], corpus["cy"]), (layer["x"], layer["cy"]))
        _arrow(ax, (layer["right"], layer["cy"]), (aggregation["x"], aggregation["cy"]))
    _arrow(ax, (aggregation["right"], aggregation["cy"]), (health["x"], health["cy"]))
    _arrow(ax, (health["cx"], health["y"]), (arbitration["cx"], arbitration["top"]))
    _arrow(ax, (arbitration["x"], arbitration["cy"]), (decision["right"], decision["cy"]))
    _arrow(ax, (decision["x"], decision["cy"]), (patch["right"], patch["cy"]))
    _arrow(ax, (patch["x"], patch["cy"]), (verified["right"], verified["cy"]))
    _arrow(ax, (verified["cx"], verified["top"]), (corpus["cx"], corpus["y"]))

    ax.text(verified["cx"] + 1.8, (verified["top"] + corpus["y"]) / 2,
            "re-mesure planifiée\n(intégration continue\nhebdomadaire)",
            ha="left", va="center", fontsize=6.0, color=INK_MUTED, linespacing=1.35)

    # --- annotations : ce qui structure les couches, ce qui en sort
    ax.text(cols[1] + bw / 2, y_a + bh_a + 1.6,
            "détection en trois couches,\npar coût croissant",
            ha="center", va="bottom", fontsize=6.2, color=INK_SOFT, linespacing=1.3)
    ax.text((cols[1] + bw + cols[2]) / 2, y_a - 2.2,
            "constats horodatés :\ncatégorie T1 à T8, sévérité,\ncanal d'observation, confiance",
            ha="center", va="top", fontsize=6.0, color=INK_MUTED, linespacing=1.35)

    handles = [
        mpatches.Patch(facecolor=SURFACE, edgecolor=INK, linewidth=1.0,
                       label="étape automatique"),
        mpatches.Patch(facecolor="#f0f0f0", edgecolor=INK, linewidth=1.3,
                       label="agrégation et notation"),
        mpatches.Patch(facecolor=SURFACE, edgecolor=INK_SOFT, linewidth=1.0,
                       linestyle=(0, (3, 2)), label="intervention humaine"),
    ]
    ax.legend(handles=handles, ncols=3, loc="lower left", bbox_to_anchor=(0.0, -0.02),
              fontsize=7, handlelength=1.4)

    fig.suptitle(
        "Figure 7. Architecture fonctionnelle de benchmark-doctor",
        x=0.0, ha="left", y=1.05, fontsize=9.5, fontweight="bold",
    )
    files = save(fig, "fig07_architecture_fonctionnelle")

    return {
        "files": files,
        "facts": {
            "n_tasks": summary["n_tasks"],
            "total_usd": cost["total_usd"],
            "usd_per_task": cost["usd_per_task"],
            "by_layer": by_layer,
            "total_calls": cost["total_calls"],
        },
    }


def build_captions(facts: dict[int, dict[str, Any]]) -> str:
    """Rédige les légendes des figures produites, chiffres interpolés depuis les mesures."""
    day = st.long_date_fr(st.REFERENCE_DATE)
    lines: list[str] = [
        "# Légendes des figures",
        "",
        "Généré par `figures/make_figures.py`. Chaque légende est rédigée pour être collée telle",
        "quelle sous la figure correspondante dans le mémoire. Tous les chiffres sont relus dans",
        "les fichiers de mesure de l'outil : aucun n'est saisi à la main, et une relance après une",
        "nouvelle campagne met à jour la figure et sa légende ensemble.",
        "",
        f"Date de mesure gelée : **{day}**.",
        "",
        "Insertion dans le mémoire : chaque figure est calibrée pour la largeur utile d'une page",
        f"A4 aux marges du vademecum, soit {fr(PAGE_WIDTH_CM, 0)} cm. Les PNG portent une",
        "résolution de 300 ppp dans leur en-tête, les PDF sont entièrement vectoriels et leurs",
        "polices y sont incorporées. `python3 figures/make_figures.py --check` revérifie ces trois",
        "propriétés sur les fichiers écrits.",
        "",
    ]

    def block(number: int, stem: str, source: str, caption: str) -> None:
        lines.extend([
            f"## Figure {number}",
            "",
            f"**Fichiers** : `{stem}.png` (300 ppp) et `{stem}.pdf` (vectoriel)  ",
            f"**Source des données** : `{source}`  ",
            f"**Reproduction** : `python3 figures/make_figures.py --only {number}`",
            "",
            caption,
            "",
        ])

    if 1 in facts:
        f = facts[1]["facts"]
        block(
            1, "fig01_decadence_par_site", "runs/health_20260815.json",
            f"Figure 1. Décadence par site : les {f['n_tasks']} tâches de WebVoyager notées au "
            f"{day}. Chaque barre représente la totalité des tâches d'un site, ventilées par note "
            "de stabilité, les sites étant classés du plus dégradé au moins dégradé. La note "
            "agrège les constats des trois couches de détection selon la formule du chapitre 3. "
            f"Sur l'ensemble du corpus, {f['n_below_a']} tâches sur {f['n_tasks']} "
            f"({pct(f['below_a'])}) reçoivent une note inférieure à A, et le score moyen s'établit "
            f"à {fr(f['mean_stability'], 3)}. Deux sous-ensembles se détachent : {f['worst']} "
            f"(score moyen {fr(f['worst_mean'], 3)}, dont {f['worst_d']} tâches sur "
            f"{f['worst_n']} notées D) et {f['second']} ({fr(f['second_mean'], 3)}), tous deux "
            f"composés de tâches transactionnelles à date codée en dur. À l'opposé, {f['best']} "
            f"conserve un score moyen de {fr(f['best_mean'], 3)}. Sur {f['n_sites_all_below_a']} "
            "des 15 sites, aucune tâche n'atteint la note A : la part de tâches dégradées ne "
            "suffirait donc pas à ordonner les sites, c'est la gravité qui les sépare.",
        )

    if 2 in facts:
        f = facts[2]["facts"]
        empty = " et ".join(f["empty"])
        block(
            2, "fig02_patches_magnitude_taxonomie",
            "benchmark_doctor/ground_truth/magnitude_reason_labels.json",
            f"Figure 2. Les {f['n_total']} patches publiés par Magnitude le 6 juillet 2025, "
            "classés dans la taxonomie du chapitre 2 par relecture manuelle de chaque raison "
            f"invoquée. À gauche, la catégorie principale, ventilée entre les {f['n_modify']} "
            f"réécritures et les {f['n_remove']} suppressions ; à droite, les {f['n_secondary']} "
            "catégories secondaires, qui comptent des co-occurrences et non des parts. La dérive "
            f"temporelle domine avec {f['t1']} tâches, dont {f['t1_modify']} traitées par simple "
            "réécriture de la date : c'est le mode de décadence le plus fréquent, et le seul que "
            "l'annotateur ait jugé réparable sans retirer la tâche du corpus. Viennent ensuite la "
            f"dérive de contenu ({f['t2']}), l'accès et les effets de bord ({f['t3']}), "
            f"l'instabilité d'interface ({f['t4']}), l'ambiguïté ({f['t5']}) et la dépendance de "
            f"timing ({f['t8']}), toutes traitées par suppression. Les catégories {empty} ne "
            "reçoivent aucune tâche en catégorie principale, ce qui ne signifie pas qu'elles sont "
            "absentes du corpus mais qu'aucune raison publiée ne les invoque comme cause "
            f"première. {f['n_borderline']} classements ont été notés comme cas frontaliers.",
        )

    if 3 in facts:
        f = facts[3]["facts"]
        p = f["points"]
        auc = f["auc"]
        t2l1 = f["t2_l1_medium"]
        t2full = f["t2_full_medium"]
        block(
            3, "fig03_ablation_detecteurs", "runs/validation_ablation_20260815.json",
            "Figure 3. Ablation des couches de détection, mesurée sur les constats seuls et jamais "
            "sur le score publié : celui-ci intègre un a priori tiré de la même vérité terrain, et "
            "le valider contre elle serait circulaire. La vérité de référence est « tâche signalée "
            f"par au moins un des six annotateurs indépendants » ({f['n_truth']} tâches sur 643). "
            "(a) Chaque configuration apparaît à ses deux seuils, reliés par un segment : le point "
            "plein est le seuil HIGH, le point creux le seuil MEDIUM. La couche L1 seule atteint "
            f"une précision de {fr(p['L1']['high'][1], 3)} pour un rappel de "
            f"{fr(p['L1']['high'][0], 3)} ; l'empilement complet L1+L2+L3 porte le rappel à "
            f"{fr(p['L1+L2+L3']['medium'][0], 3)} au seuil MEDIUM, mais la précision tombe à "
            f"{fr(p['L1+L2+L3']['medium'][1], 3)}. L'outil complet est un instrument de tri, pas "
            "un instrument de verdict. En ordonnancement sans seuil, la meilleure aire sous la "
            f"courbe revient à {f['auc_best']} (AUC {fr(auc[f['auc_best']], 3)}), contre "
            f"{fr(auc['L1'], 3)} pour L1 seule et {fr(auc['L1+L2+L3'], 3)} pour l'empilement "
            "complet : ajouter la couche L3 améliore le rappel au seuil et dégrade "
            "l'ordonnancement. (b) Rappel par catégorie sur les 121 tâches étiquetées, au seuil "
            "MEDIUM ; la portion pleine de chaque barre correspond aux tâches signalées par un "
            "constat de la bonne catégorie, la portion hachurée à celles attrapées pour un autre "
            f"motif. La dérive de contenu (T2) passe de {pct(100 * t2l1['rappel_brut'], 0)} avec "
            f"L1 seule à {pct(100 * t2full['rappel_brut'], 0)} avec les trois couches, mais seules "
            f"{t2full['n_rappel_bonne_categorie']} des {t2full['n_verite']} tâches le sont pour la "
            "bonne raison. Aucun détecteur ne couvre l'instabilité d'interface (T4) ni la "
            "dépendance de timing (T8) : quand ces tâches sont signalées, c'est toujours par un "
            "constat d'une autre catégorie.",
        )

    if 4 in facts:
        f = facts[4]["facts"]
        block(
            4, "fig04_courbe_longitudinale",
            "runs/longitudinal_curves_20260815.csv et runs/longitudinal_20260815.json",
            "Figure 4. Mortalité des tâches de mars 2024 à août 2026, selon l'instrument de "
            "mesure. Les quatre séries sont des parts de leur propre corpus et partagent donc un "
            "axe unique, malgré des dénominateurs différents. La courbe A cumule les tâches "
            "signalées par au moins un des six annotateurs indépendants, aux dates de leurs "
            f"publications respectives : elle passe de {pct(f['a_first'][1])} au premier audit de "
            f"décembre 2024 à {pct(f['a_last'][1])} en mai 2026. Elle est massivement censurée à "
            "gauche, puisque personne n'a examiné le corpus pendant les neuf mois qui ont suivi sa "
            "publication : le trait pointillé initial est une reconstitution, pas une mesure. La "
            "courbe B applique un instrument constant, le détecteur temporel L1 rejoué mois par "
            f"mois sur le corpus figé d'origine : elle est plate à {pct(f['b_last'][1], 2)} depuis "
            "avril 2024, ce qui est un résultat en soi, le corpus d'origine ne contenant presque "
            "aucune date encore future à sa publication. La courbe B′ applique le même instrument "
            "au corpus réparé par Magnitude en juillet 2025 : partie de "
            f"{pct(f['bprime_first'][1], 2)} le jour de la réparation, elle atteint "
            f"{pct(f['bprime_last'][1], 2)} treize mois plus tard, ce qui montre qu'une réparation "
            "se défait. La courbe D sert de contrôle sur Online-Mind2Web, benchmark activement "
            f"maintenu, dont le journal de remplacement donne {pct(f['d_last'][1])} de tâches "
            "remplacées sur la même période. L'estimateur retenu pour le mémoire est celui des "
            f"incréments postérieurs au premier audit, soit {pct(100 * f['a2']['taux_annuel'])} "
            f"par an [{fr(100 * f['a2']['taux_annuel_ic95'][0], 1)} ; "
            f"{fr(100 * f['a2']['taux_annuel_ic95'][1], 1)}] ; l'instrument constant borne cette "
            f"valeur par le bas à {pct(100 * f['b']['taux_annuel'])} et le benchmark maintenu par "
            f"le haut à {pct(100 * f['d']['taux_annuel'])}.",
        )

    if 5 in facts:
        f = facts[5]["facts"]
        res, cost = f["results"], f["costs"]

        def f1(key: str) -> float:
            return res[key]["fixed_threshold_0_5"]["f1"]

        def yearly(key: str) -> str:
            return usd(cost[key]["usd_per_year_weekly_643"])

        ecart = 100 * (f1("d_llm_judge_gemini-2_5-flash") - f1("d_llm_judge_rubric"))
        block(
            5, "fig05_cout_performance_l3", "runs/ablation_ambiguity_20260815.json",
            f"Figure 5. Coût et performance des quatre approches candidates pour la couche L3, "
            f"évaluées sur les {f['n_annotated']} tâches annotées à la main pour l'ambiguïté, en "
            "validation croisée à cinq plis. L'ordonnée est le F1 au seuil de décision 0,5, "
            "l'abscisse le coût annuel d'une surveillance hebdomadaire des 643 tâches ; les "
            "méthodes sans appel facturé occupent le panneau de gauche, un axe logarithmique ne "
            "pouvant représenter la gratuité. Le plancher trivial, obtenu en déclarant toutes les "
            f"tâches ambiguës, vaut F1 = {fr(f['baseline_f1'], 3)} : une méthode qui ne le dépasse "
            "pas ne mesure rien. L'approche (a) TF-IDF avec régression logistique atteint "
            f"{fr(f1('a_tfidf'), 3)} pour un coût nul, l'approche (c) par embeddings "
            f"{fr(f1('c_openrouter_embed'), 3)} pour {yearly('c_openrouter_embed')} par an, et le "
            f"juge LLM économique (d) {fr(f1('d_llm_judge_rubric'), 3)} pour "
            f"{yearly('d_llm_judge_rubric')} par an. La seule configuration nettement supérieure "
            f"est le même juge sur un modèle plus coûteux : {fr(f1('d_llm_judge_gemini-2_5-flash'), 3)} "
            f"pour {yearly('d_llm_judge_gemini-2_5-flash')} par an, soit un ordre de grandeur de "
            "plus. Deux enseignements pour le mémoire : la qualité du juge tient au modèle bien "
            "plus qu'au prompt, puisque le même prompt sur un modèle économique perd "
            f"{fr(ecart, 0)} points de F1 ; et le coût reste, dans tous les cas de figure, "
            "négligeable devant celui d'une exécution d'agents sur le même corpus.",
        )

    if 6 in facts:
        f = facts[6]["facts"]
        lab = {k: v.replace("\n", " ") for k, v in f["labels"].items()}
        named = [f"{lab[a]} contre {lab[b]}" for a, b, _ in f["top_pairs"]]
        pairs = " et ".join([", ".join(named[:-1]), named[-1]]) if len(named) > 1 else named[0]
        part_unanime = 100 * f["unanime"] / f["au_moins_1"]
        block(
            6, "fig06_desaccord_inter_patcheurs", "data/ground_truth.json",
            "Figure 6. Les six annotateurs indépendants ne mesurent pas le même benchmark. "
            "(a) Matrice orientée du désaccord dur : chaque case donne le nombre de tâches que "
            "l'annotateur en ligne a supprimées de son corpus et que l'annotateur en colonne a "
            "conservées sans la moindre modification. La matrice n'est pas symétrique, et elle ne "
            "doit pas l'être, les deux affirmations n'étant pas équivalentes. Le désaccord le plus "
            f"marqué atteint {f['max_pair'][2]} tâches et concerne {pairs}. Au total, "
            f"{f['n_hard']} tâches font l'objet d'un désaccord dur, et {f['total_soft']} cas "
            "supplémentaires opposent une suppression à une réécriture. (b) Distribution du nombre "
            "d'annotateurs signalant chaque tâche, parmi les "
            f"{f['au_moins_1']} tâches signalées au moins une fois. La distribution est bimodale : "
            f"{f['unanime']} tâches font l'unanimité des six annotateurs, {f['dist']['1']} ne sont "
            f"signalées que par un seul, et {f['jamais']} tâches, non représentées ici, ne sont "
            f"signalées par personne. Autrement dit, {pct(part_unanime)} seulement des tâches "
            "signalées le sont à l'unanimité : le reste relève d'un arbitrage que chaque équipe a "
            "tranché seule, sans le publier.",
        )

    if 7 in facts:
        f = facts[7]["facts"]
        block(
            7, "fig07_architecture_fonctionnelle",
            "schéma ; les chiffres cités proviennent de runs/health_20260815.json",
            "Figure 7. Architecture fonctionnelle de benchmark-doctor. Le schéma décrit ce que "
            "chaque étape produit et qui décide, non les modules du programme. Le corpus traverse "
            "trois couches de détection ordonnées par coût croissant : l'analyse statique L1, les "
            "sondes web L2 et le juge LLM L3. Chaque couche émet des constats horodatés portant "
            "une catégorie de la taxonomie, une sévérité, un canal d'observation et une "
            "confiance ; l'agrégation les combine par un OU-bruité en un score de stabilité et une "
            "note de A à D, restitués dans une carte de santé. La campagne complète sur les "
            f"{f['n_tasks']} tâches a coûté {usd(f['total_usd'])} pour "
            f"{st.count_fr(f['total_calls'])} appels, soit {fr(f['usd_per_task'], 5)} $ par tâche, "
            "la totalité étant imputable à la couche L3. Le point important est la boucle : la "
            "carte de santé n'est pas un verdict mais un tri, l'arbitrage reste humain, et le "
            "sous-ensemble vérifié qui en résulte retourne dans la file de surveillance. Une "
            "réparation n'est pas un état stable, c'est une observation datée de plus, ce que "
            "confirme la courbe B′ de la figure 4.",
        )

    return "\n".join(lines)


BUILDERS = {1: fig01, 2: fig02, 3: fig03, 4: fig04, 5: fig05, 6: fig06, 7: fig07}

#: Largeur utile d'une page A4 aux marges du vademecum (2,5 cm), en centimètres.
PAGE_WIDTH_CM = 16.0


def _png_geometry(path: Path) -> tuple[int, int, int]:
    """Lit largeur, hauteur (pixels) et résolution (ppp) d'un PNG, sans dépendance externe.

    Le fragment `pHYs` porte la résolution en pixels par mètre : c'est lui que le traitement
    de texte lit pour insérer l'image à sa taille physique. Sans lui, une image de 1 800 px
    serait insérée à 96 ppp, soit près de 48 cm de large.
    """
    raw = path.read_bytes()
    width, height = int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    dpi = 0
    offset = 8
    while offset < len(raw) - 8:
        length = int.from_bytes(raw[offset:offset + 4], "big")
        kind = raw[offset + 4:offset + 8]
        if kind == b"pHYs":
            px_per_metre = int.from_bytes(raw[offset + 8:offset + 12], "big")
            dpi = round(px_per_metre * 0.0254)
            break
        if kind == b"IDAT":
            break
        offset += 12 + length
    return width, height, dpi


def verify() -> int:
    """Contrôle les sorties (résolution, largeur imprimable, PDF vectoriel) ; renvoie 0
    si tout passe, 1 sinon, en imprimant les motifs d'échec ligne à ligne."""
    problems = 0
    for number in sorted(BUILDERS):
        stem = STEMS[number]
        png, pdf = FIGURES_DIR / f"{stem}.png", FIGURES_DIR / f"{stem}.pdf"
        notes = []
        if not png.exists() or not pdf.exists():
            print(f"fig{number:02d}  MANQUANT")
            problems += 1
            continue
        width_px, height_px, dpi = _png_geometry(png)
        width_cm = width_px / dpi * 2.54 if dpi else float("inf")
        if dpi != 300:
            notes.append(f"résolution {dpi} ppp au lieu de 300")
        if width_cm > PAGE_WIDTH_CM + 0.3:
            notes.append(f"largeur {width_cm:.1f} cm au-delà des {PAGE_WIDTH_CM:.0f} cm utiles")
        raw = pdf.read_bytes()
        if b"/FontFile2" not in raw:
            notes.append("polices non incorporées dans le PDF")
        if b"/Subtype /Image" in raw:
            notes.append("le PDF contient une image matricielle")
        status = "OK  " if not notes else "ÉCHEC"
        print(f"fig{number:02d}  {status}  {width_cm:5.1f} × {height_px / dpi * 2.54:5.1f} cm"
              f"  {'; '.join(notes)}")
        problems += bool(notes)
    print("contrôle réussi" if not problems else f"{problems} figure(s) en défaut")
    return 1 if problems else 0


#: Nom de fichier (sans extension) par numéro de figure.
STEMS = {
    1: "fig01_decadence_par_site",
    2: "fig02_patches_magnitude_taxonomie",
    3: "fig03_ablation_detecteurs",
    4: "fig04_courbe_longitudinale",
    5: "fig05_cout_performance_l3",
    6: "fig06_desaccord_inter_patcheurs",
    7: "fig07_architecture_fonctionnelle",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", type=int, default=None,
                        help="numéros de figures à produire (par défaut : toutes)")
    parser.add_argument("--no-captions", action="store_true",
                        help="ne pas réécrire figures/legendes.md")
    parser.add_argument("--check", action="store_true",
                        help="ne rien produire : contrôler les sorties déjà écrites")
    args = parser.parse_args()

    if args.check:
        raise SystemExit(verify())

    st.apply_style()
    wanted = args.only or sorted(BUILDERS)

    facts: dict[int, dict[str, Any]] = {}
    for number in wanted:
        result = BUILDERS[number]()
        facts[number] = result
        for path in result["files"]:
            print(f"écrit : {path.relative_to(ROOT)}")

    if not args.no_captions and len(wanted) == len(BUILDERS):
        captions = build_captions(facts)
        target = FIGURES_DIR / "legendes.md"
        target.write_text(captions, encoding="utf-8")
        print(f"écrit : {target.relative_to(ROOT)}")
    elif not args.no_captions:
        print("légendes non réécrites : les sept figures sont nécessaires (--only partiel)")


if __name__ == "__main__":
    main()
