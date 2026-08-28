#!/usr/bin/env python3
"""Étude longitudinale de la décadence de WebVoyager (mars 2024 → août 2026).

Le script produit deux courbes de mortalité indépendantes, qui ne mesurent pas la même
chose, et refuse d'en publier une seule.

Courbe A, la mortalité vue par les praticiens : cumul des tâches signalées (réécrites ou
supprimées) par au moins un des six annotateurs indépendants, à chaque jalon daté. C'est
une observation du monde réel, mais elle est censurée à gauche (le premier audit date de
décembre 2024, neuf mois et demi après la publication, et signale d'emblée 121 tâches dont
on ignore quand elles sont mortes, ni même si elles l'ont jamais été), l'effort
d'observation varie d'un annotateur à l'autre, et « signalée » ne veut pas dire « cassée » :
Magnitude re-date par précaution, Skyvern rafraîchit en masse.

Courbe B, la mortalité vue par un instrument constant : le détecteur L1 est rejoué sur le
corpus d'origine, inchangé, à chaque date du calendrier ; seule la date de référence
avance. Chaque tâche a donc une date de décès exacte et calculable, le jour où sa date
interne bascule dans le passé. Aucun des défauts ci-dessus, mais un seul mode de décadence
vu, le temporel (T1) : tout ce qui se passe sur le site lui échappe.

Les deux courbes bornent le phénomène. B est une mesure exacte d'un sous-ensemble des
causes, A une mesure bruitée de toutes les causes ; leur écart est lui-même un résultat.

Le script publie aussi la rouille des correctifs (parmi les 68 énoncés réécrits par
Magnitude en 07/2025, combien sont périmés au 15/08/2026 ; le chiffre préliminaire de
10/68 était faux, voir `patch_rot`), la décadence accumulée hors patch-sets, la santé
comparée des sept forks mesurés chacun à sa date de naissance puis au 15/08/2026, et un
contrôle Online-Mind2Web, benchmark activement maintenu dont le journal de remplacement
daté donne un taux de décadence observé sous surveillance.

Usage :

    python3 analysis_longitudinal.py                 # tout, écrit runs/longitudinal_20260815.*
    python3 analysis_longitudinal.py --step 1        # courbe B au pas mensuel (défaut : 1 mois)
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from benchmark_doctor import __version__, load_webvoyager, run_l1  # noqa: E402
from benchmark_doctor.models import Severity, Task  # noqa: E402
from benchmark_doctor.detectors.l1_temporal import (  # noqa: E402
    TemporalIntent,
    classify_temporal_intent,
    extract_date_mentions,
)


#: Publication de WebVoyager : dernier commit du dépôt officiel, gelé depuis.
T0 = _dt.date(2024, 3, 2)
#: Date de notre mesure. Gelée, comme dans run_all.py.
TODAY = _dt.date(2026, 8, 15)

RUNS = ROOT / "runs"
DATA = ROOT / "data"
RAW = DATA / "raw"
GROUND_TRUTH = DATA / "ground_truth.json"

OUT_JSON = RUNS / "longitudinal_20260815.json"
OUT_CSV = RUNS / "longitudinal_curves_20260815.csv"

INDEPENDENT_SOURCES = (
    "browseruse",
    "convergence",
    "magnitude",
    "fara",
    "alumnium",
    "skyvern_2026",
)

#: Les sept corpus publiés, avec la date à laquelle chacun a été figé, et le fichier des
#: identifiants que le fork a lui-même déclarés hors corpus. `None` = aucune exclusion
#: publiée. Convergence est au format CSV et n'est pas rechargé ici (son verdict figure
#: dans la base réconciliée).
#:
#: `browseruse_tasks.jsonl` contient **encore** les 55 tâches listées dans
#: `WebVoyagerImpossibleTasks.json` : mesurer browser-use sur les 643 lignes du fichier
#: revient à lui imputer des tâches qu'il avait retirées. Neuf des douze constats « à sa
#: naissance » en provenaient, ce qui multipliait son taux de naissance par près de quatre
#: (1,9 % contre 0,5 %). Le corpus réel du fork est de 588 tâches.
FORKS: tuple[tuple[str, str, _dt.date, str | None], ...] = (
    ("WebVoyager original", "webvoyager_original.jsonl", T0, None),
    ("browser-use", "browseruse_tasks.jsonl", _dt.date(2024, 12, 15), "browseruse_impossible.json"),
    ("Skyvern 01/2025", "skyvern_tasks_20250116.jsonl", _dt.date(2025, 1, 16), None),
    ("Magnitude 07/2025", "magnitude_patched.jsonl", _dt.date(2025, 7, 6), None),
    ("Microsoft Fara 08/2025", "fara_webvoyager_20250831.jsonl", _dt.date(2025, 8, 31), None),
    ("Alumnium 03/2026", "alumnium_patched.jsonl", _dt.date(2026, 3, 17), None),
    ("Skyvern 05/2026", "skyvern_tasks.jsonl", _dt.date(2026, 5, 4), None),
)


def months_between(a: _dt.date, b: _dt.date) -> float:
    """Écart en mois moyens (365,2425 / 12 jours). Une seule convention pour tout le script."""
    return (b - a).days / 30.436875


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Intervalle de confiance à 95 % d'une proportion (score de Wilson).

    Wald est écarté : les proportions manipulées ici sont parfois proches de 0 ou de 1
    (65/65 patches périmés), où il produit des bornes hors de [0, 1] ou de largeur nulle.
    """
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    demi = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - demi), min(1.0, centre + demi))


def hazard(k: int, n: int, months: float) -> dict[str, Any]:
    """Taux de décadence à risque constant déduit d'une proportion observée sur une durée.

    Modèle : S(t) = e^{−λt}, donc λ = −ln(1 − k/n) / Δt. Le taux annuel publié est la
    probabilité qu'une tâche saine à t soit signalée dans les douze mois, 1 − e^{−12λ},
    et non 12λ : confondre les deux surestime de plusieurs points dès que le taux dépasse
    quelques pour cent. L'hypothèse de risque constant est fausse et assumée, elle sert de
    résumé comparable entre corpus, pas de modèle du monde. Les bornes viennent de
    l'intervalle de Wilson, transporté par la même transformation (monotone, donc l'ordre
    des bornes est conservé).
    """
    if n == 0 or months <= 0:
        return {"n": n, "k": k, "months": round(months, 2), "lambda_mois": None}
    p = k / n
    lo, hi = wilson(k, n)

    def lam(x: float) -> float:
        x = min(max(x, 0.0), 0.999999)
        return -math.log(1 - x) / months

    return {
        "n": n,
        "k": k,
        "proportion": round(p, 4),
        "ic95_proportion": [round(lo, 4), round(hi, 4)],
        "months": round(months, 2),
        "lambda_mois": round(lam(p), 5),
        "lambda_mois_ic95": [round(lam(lo), 5), round(lam(hi), 5)],
        "taux_annuel": round(1 - math.exp(-12 * lam(p)), 4),
        "taux_annuel_ic95": [
            round(1 - math.exp(-12 * lam(lo)), 4),
            round(1 - math.exp(-12 * lam(hi)), 4),
        ],
        "demi_vie_mois": round(math.log(2) / lam(p), 1) if lam(p) > 0 else None,
    }


def month_grid(start: _dt.date, end: _dt.date, step_months: int = 1) -> list[_dt.date]:
    """Grille de dates au pas mensuel, du 1er du mois, bornes incluses."""
    out: list[_dt.date] = []
    y, m = start.year, start.month
    while _dt.date(y, m, 1) <= end:
        out.append(_dt.date(y, m, 1))
        m += step_months
        while m > 12:
            m -= 12
            y += 1
    if out[-1] != end:
        out.append(end)
    return out


def curve_annotators(gt: Mapping[str, Any]) -> dict[str, Any]:
    """Cumul des tâches signalées par ≥1 annotateur, jalon par jalon.

    Recalculé depuis les verdicts bruts : les jalons sont les dates réelles de gel de
    chaque patch-set.
    """
    tasks = gt["taches"]
    n_total = len(tasks)
    # Le cumul principal ne retient que les six annotateurs indépendants ; le cumul
    # « toutes sources » est publié en regard pour montrer de combien Emergence et le
    # doublon Skyvern gonflent le chiffre.
    events: list[tuple[_dt.date, str, str, str]] = []
    for t in tasks:
        for v in t["verdicts"]:
            if v["action"] in ("modify", "remove"):
                events.append((_dt.date.fromisoformat(v["date"]), v["source"], t["id"], v["action"]))
    events.sort()

    milestones: list[dict[str, Any]] = []
    seen_indep: set[str] = set()
    seen_all: set[str] = set()
    removed_indep: set[str] = set()
    by_source_date: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for date, source, task_id, action in events:
        by_source_date[(date.isoformat(), source)].append((task_id, action))

    for (date_s, source), items in sorted(by_source_date.items()):
        indep = source in INDEPENDENT_SOURCES
        new_indep = 0
        for task_id, action in items:
            seen_all.add(task_id)
            if indep:
                if task_id not in seen_indep:
                    new_indep += 1
                seen_indep.add(task_id)
                if action == "remove":
                    removed_indep.add(task_id)
        date = _dt.date.fromisoformat(date_s)
        milestones.append(
            {
                "date": date_s,
                "source": source,
                "annotateur_independant": indep,
                "mois_depuis_publication": round(months_between(T0, date), 2),
                "signalees_par_cette_source": len(items),
                "nouvelles_vs_cumul_independants": new_indep if indep else 0,
                "cumul_independants": len(seen_indep),
                "cumul_independants_pct": round(100 * len(seen_indep) / n_total, 1),
                "cumul_supprimees_independants": len(removed_indep),
                "cumul_toutes_sources": len(seen_all),
            }
        )

    first = next(m for m in milestones if m["annotateur_independant"])
    last = [m for m in milestones if m["annotateur_independant"]][-1]
    return {
        "n_taches": n_total,
        "jalons": milestones,
        "lecture": {
            "premier_audit": first["date"],
            "signalees_au_premier_audit": first["cumul_independants"],
            "dernier_jalon": last["date"],
            "cumul_final": last["cumul_independants"],
            "cumul_final_pct": last["cumul_independants_pct"],
            "censure_a_gauche": (
                f"{first['cumul_independants']} tâches sont déjà signalées au premier "
                f"audit ({first['date']}), soit "
                f"{round(months_between(T0, _dt.date.fromisoformat(first['date'])), 1)} mois "
                "après la publication : leur date de décès est inconnue et peut précéder "
                "la publication elle-même."
            ),
        },
    }


def flag_dates(
    tasks: Sequence[Task],
    grid: Sequence[_dt.date],
    threshold: Severity,
) -> tuple[dict[str, _dt.date | None], list[tuple[_dt.date, int]]]:
    """Pour chaque tâche, la première date de la grille où L1 la signale, plus la courbe
    (date, nombre de tâches signalées).

    La grille est mensuelle : la date de décès est connue au mois près, ce qui suffit à une
    courbe couvrant trente mois et évite 900 passes de détection.
    """
    death: dict[str, _dt.date | None] = {t.task_id: None for t in tasks}
    curve: list[tuple[_dt.date, int]] = []
    for day in grid:
        health = run_l1(tasks, today=day, benchmark="webvoyager")
        n = 0
        for v in health.verdicts:
            if v.is_flagged(threshold):
                n += 1
                if death[v.task.task_id] is None:
                    death[v.task.task_id] = day
        curve.append((day, n))
    return death, curve


def time_bombs(tasks: Sequence[Task], birth: _dt.date) -> dict[str, Any]:
    """Combien de tâches portaient, à la naissance du corpus, une date encore à venir ?

    C'est la question qui décide si une courbe de mortalité temporelle peut monter. Une
    tâche dont la date est déjà passée à la publication est morte-née : elle ne décline
    pas, elle est défectueuse à la construction. Une tâche dont la date est future est une
    bombe à retardement dont on peut calculer l'échéance. Sans bombes, la courbe est plate,
    et c'est un résultat sur le benchmark, pas une panne de mesure.
    """
    dead_born = bombs = dateless = yearless = 0
    horizons: list[int] = []
    for t in tasks:
        mentions = extract_date_mentions(t.question)
        if not mentions:
            dateless += 1
            continue
        if all(m.kind == "month_day" for m in mentions):
            yearless += 1
            continue
        future = [m for m in mentions if m.is_future(birth)]
        if future:
            bombs += 1
            dates = [m.as_date() for m in future]
            dates = [d for d in dates if d]
            if dates:
                horizons.append((min(dates) - birth).days)
        elif any(m.is_past(birth) for m in mentions):
            dead_born += 1
    return {
        "date_de_naissance": birth.isoformat(),
        "n_taches": len(tasks),
        "sans_date": dateless,
        "date_sans_millesime_seulement": yearless,
        "deja_perimees_a_la_naissance": dead_born,
        "bombes_a_retardement": bombs,
        "horizon_median_jours": (
            int(sorted(horizons)[len(horizons) // 2]) if horizons else None
        ),
        "lecture": (
            f"{bombs} tâches seulement portaient une date encore à venir le "
            f"{birth.isoformat()} : la décadence temporelle mesurable *après* la "
            "publication est donc bornée par ce nombre, quelle que soit la durée "
            "d'observation."
        ),
    }


def curve_instrument(
    tasks: Sequence[Task],
    *,
    start: _dt.date = T0,
    end: _dt.date = TODAY,
    step_months: int = 1,
    corpus: str = "webvoyager_original.jsonl",
) -> dict[str, Any]:
    """Courbe B : L1 rejoué mois par mois sur un corpus figé, aux deux seuils."""
    grid = month_grid(start, end, step_months)
    out: dict[str, Any] = {
        "corpus": corpus,
        "n_taches": len(tasks),
        "debut": start.isoformat(),
        "fin": end.isoformat(),
        "grille": [d.isoformat() for d in grid],
        "pas_mois": step_months,
        "bombes_a_retardement": time_bombs(tasks, start),
        "seuils": {},
    }
    for name, threshold in (("high", Severity.HIGH), ("medium", Severity.MEDIUM)):
        death, curve = flag_dates(tasks, grid, threshold)
        n0 = curve[0][1]
        n_end = curve[-1][1]
        alive_at_t0 = len(tasks) - n0
        new_deaths = n_end - n0
        by_site_death = defaultdict(int)
        by_site_n = Counter()
        for t in tasks:
            by_site_n[t.site or "?"] += 1
            if death[t.task_id] is not None and death[t.task_id] > grid[0]:
                by_site_death[t.site or "?"] += 1
        by_period = Counter()
        for task_id, d in death.items():
            if d is None or d == grid[0]:
                continue
            by_period[f"{d.year}-S{1 if d.month <= 6 else 2}"] += 1
        out["seuils"][name] = {
            "courbe": [
                {
                    "date": d.isoformat(),
                    "mois": round(months_between(start, d), 2),
                    "n_signalees": n,
                    "pct": round(100 * n / len(tasks), 2),
                    "survie": round(1 - n / len(tasks), 4),
                }
                for d, n in curve
            ],
            "mortes_a_la_publication": n0,
            "mortes_a_la_publication_pct": round(100 * n0 / len(tasks), 2),
            "vivantes_a_la_publication": alive_at_t0,
            "nouvelles_morts": new_deaths,
            "n_signalees_final": n_end,
            "n_signalees_final_pct": round(100 * n_end / len(tasks), 2),
            "risque_sur_les_vivantes": hazard(
                new_deaths, alive_at_t0, months_between(start, end)
            ),
            "deces_par_semestre": dict(sorted(by_period.items())),
            "deces_par_site": {
                site: {
                    "n": by_site_n[site],
                    "nouveaux_deces": by_site_death.get(site, 0),
                    "taux": round(by_site_death.get(site, 0) / by_site_n[site], 3),
                }
                for site in sorted(by_site_n, key=lambda s: -by_site_death.get(s, 0))
            },
            "dates_de_deces": {
                k: (v.isoformat() if v else None) for k, v in sorted(death.items())
            },
        }
    return out


#: Mois en toutes lettres, pour la reproduction de l'extracteur de 2026-08-15.
_LEGACY_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        "january february march april may june july august september october november "
        "december".split()
    )
}


def _legacy_stale(text: str, today: _dt.date) -> bool:
    """L'extracteur du 15/08/2026, reproduit à l'identique.

    Il est conservé parce que l'écart entre son résultat et le nôtre est le chiffre corrigé
    du mémoire, et qu'il faut pouvoir l'exhiber. Sa première branche cherche une année
    inférieure à l'année courante n'importe où dans la phrase, et ne voit donc rien quand
    le correctif a été daté DANS l'année courante ; la seconde cherche un motif « Mois AAAA »
    adjacents avec mois antérieur au mois courant, et rate « March 15, 2026 », où le
    quantième s'intercale. Or Magnitude a re-daté vers janvier-mars 2026, très
    majoritairement au format « Mois JJ, AAAA » : les deux branches se ratent l'une l'autre.
    """
    import re

    if [y for y in re.findall(r"\b(20[23]\d)\b", text) if int(y) < today.year]:
        return True
    for month, year in re.findall(r"\b([A-Z][a-z]+)\s+(20[23]\d)\b", text):
        m = _LEGACY_MONTHS.get(month.lower())
        if m and (int(year) < today.year or (int(year) == today.year and m < today.month)):
            return True
    return False


def patch_rot(today: _dt.date = TODAY) -> dict[str, Any]:
    """Les 68 énoncés réécrits par Magnitude en 07/2025 sont-ils encore valides ?

    Plusieurs lectures sont publiées côte à côte parce qu'elles donnent des chiffres
    différents et que le mémoire doit dire laquelle il cite : `avec_date` (le correctif
    porte-t-il une date du tout ? les 3 patches de changement de produit n'en ont pas et ne
    peuvent donc pas re-pourrir), `date_passee` (mesure textuelle, indépendante de toute
    politique) et `perime_bloquant` (mesure opérationnelle : une requête archivistique
    datée vieillit sans casser, une tâche transactionnelle non).

    Le chiffre préliminaire du 15/08 (10/68) venait d'un extracteur qui exigeait
    l'adjacence « Mois AAAA » et testait `année < 2026`. Il ratait donc « December 20,
    2025 » (jour intercalé) et toutes les dates de janvier à juillet 2026. Le script
    recompte les deux façons pour que l'écart soit vérifiable et non pas asséné.
    """
    patches = json.loads((RAW / "magnitude_patches.json").read_text(encoding="utf-8"))
    rewrites = {k: v for k, v in patches.items() if v.get("new")}
    removals = {k: v for k, v in patches.items() if not v.get("new")}

    originals = {t.task_id: t for t in load_webvoyager(RAW / "webvoyager_original.jsonl")}

    rows: list[dict[str, Any]] = []
    for task_id, patch in sorted(rewrites.items()):
        new_text = patch["new"]
        base = originals.get(task_id)
        patched_task = Task(
            task_id=task_id,
            question=new_text,
            site=base.site if base else task_id.split("--")[0],
            start_url=base.start_url if base else None,
            benchmark="webvoyager",
        )
        mentions = extract_date_mentions(new_text)
        past = [m for m in mentions if m.is_past(today)]
        future = [m for m in mentions if m.is_future(today)]
        yearless = [m for m in mentions if m.kind == "month_day"]
        intent = classify_temporal_intent(patched_task)
        health = run_l1([patched_task], today=today)
        verdict = health.verdicts[0]
        naive_stale = _legacy_stale(new_text, today)
        rows.append(
            {
                "id": task_id,
                "site": patched_task.site,
                "raison_magnitude": patch.get("reason"),
                "nouvel_enonce": new_text,
                "dates_trouvees": [m.text for m in mentions],
                "dates_passees": [m.text for m in past],
                "dates_futures": [m.text for m in future],
                "dates_sans_millesime": [m.text for m in yearless],
                "intention": intent.intent.value if hasattr(intent.intent, "value") else str(intent.intent),
                "perime_texte": bool(past),
                "perime_bloquant": bool(past) and intent.intent is TemporalIntent.TRANSACTIONAL,
                "signale_L1_high": verdict.is_flagged(Severity.HIGH),
                "signale_L1_medium": verdict.is_flagged(Severity.MEDIUM),
                "detecte_par_lextracteur_fautif_du_15_08": naive_stale,
            }
        )

    n = len(rows)
    with_date = [r for r in rows if r["dates_trouvees"]]
    stale = [r for r in rows if r["perime_texte"]]
    blocking = [r for r in rows if r["perime_bloquant"]]
    high = [r for r in rows if r["signale_L1_high"]]
    naive = [r for r in rows if r["detecte_par_lextracteur_fautif_du_15_08"]]
    still_future = [r for r in rows if r["dates_futures"] and not r["perime_texte"]]
    delta = months_between(_dt.date(2025, 7, 6), today)

    return {
        "patch_set": "magnitudedev/webvoyager data/patches.json @ 2025-07-06",
        "n_patches": len(patches),
        "n_reecritures": n,
        "n_suppressions": len(removals),
        "date_du_patch": "2025-07-06",
        "date_de_mesure": today.isoformat(),
        "mois_ecoules": round(delta, 2),
        "resultats": {
            "reecritures_portant_une_date": len(with_date),
            "reecritures_deja_perimees_texte": len(stale),
            "reecritures_deja_perimees_texte_pct": round(100 * len(stale) / n, 1),
            "perimees_sur_les_seules_datees": f"{len(stale)}/{len(with_date)}",
            "perimees_et_bloquantes": len(blocking),
            "perimees_et_bloquantes_pct_des_datees": round(
                100 * len(blocking) / len(with_date), 1
            ),
            "signalees_L1_high_au_15_08_2026": len(high),
            "encore_une_date_future": len(still_future),
            "detectees_par_lextracteur_fautif": len(naive),
            "ecart_explique": (
                f"L'extracteur du 15/08 en trouvait {len(naive)} ; il exigeait l'adjacence "
                "« Mois AAAA » et testait année < 2026, ce qui écartait les dates à jour "
                "intercalé (« December 20, 2025 ») et l'ensemble de janvier-juillet 2026. "
                f"Le compte correct est {len(stale)}."
            ),
        },
        "risque": hazard(len(stale), len(with_date), delta),
        "detail": rows,
    }


def unseen_decay(gt: Mapping[str, Any], findings_path: Path) -> dict[str, Any]:
    """Tâches que l'outil signale aujourd'hui et qu'aucun praticien n'a jamais touchées.

    Mesuré contre deux référentiels. Magnitude seul (07/2025) donne ce que treize mois de
    décadence ont ajouté à un corpus qu'un praticien avait pourtant nettoyé : c'est le
    chiffre du cadrage (41). L'union des six annotateurs donne ce que personne n'a jamais
    vu, ni en 2024 ni en 2026 : c'est le chiffre honnête pour dire que l'outil trouve du
    neuf, et il est forcément beaucoup plus petit.
    """
    from run_all import LAYER_SETS, filter_health, flag_set, load_findings

    health = load_findings(findings_path)
    tasks = gt["taches"]
    magnitude = {
        t["id"]
        for t in tasks
        if any(v["source"] == "magnitude" and v["action"] in ("modify", "remove") for v in t["verdicts"])
    }
    union6 = {t["id"] for t in tasks if t["accord"]["signalee_par"]}
    union_all = {
        t["id"]
        for t in tasks
        if any(v["action"] in ("modify", "remove") for v in t["verdicts"])
    }
    by_id = {t["id"]: t for t in tasks}
    sites = {t["id"]: t["site"] for t in tasks}

    out: dict[str, Any] = {
        "referentiels": {
            "magnitude_07_2025": len(magnitude),
            "union_6_annotateurs": len(union6),
            "union_8_sources_emergence_comprise": len(union_all),
        },
        "par_configuration": {},
    }

    # Les politiques d'ablation historiques sont mesurées en plus des six configurations
    # « couche × seuil » : c'est le détecteur naïf du 15/08 qui produisait le chiffre de
    # 41 tâches « hors patch-set » cité dans le cadrage, et il faut pouvoir montrer que ce
    # chiffre est un artefact de sa permissivité, pas une découverte.
    from benchmark_doctor.cli import ABLATIONS

    configurations: list[tuple[str, Any]] = []
    for layer_name in ("L1", "L1+L2", "L1+L2+L3"):
        sub = filter_health(health, LAYER_SETS[layer_name])
        for tname, threshold in (("high", Severity.HIGH), ("medium", Severity.MEDIUM)):
            configurations.append((f"{layer_name}/{tname}", flag_set(sub, threshold)))
    l1_only = filter_health(health, LAYER_SETS["L1"])
    for policy, (label, predicate) in ABLATIONS.items():
        configurations.append(
            (
                f"L1/{policy}",
                {v.task.task_id for v in l1_only.verdicts if predicate(v)},
            )
        )

    for conf_name, flagged in configurations:
        hors_magnitude = flagged - magnitude
        hors_union6 = flagged - union6
        hors_union_all = flagged - union_all
        out["par_configuration"][conf_name] = {
            "n_signalees": len(flagged),
            "hors_magnitude": {
                "n": len(hors_magnitude),
                "pct_corpus": round(100 * len(hors_magnitude) / len(tasks), 1),
                "par_site": dict(Counter(sites[i] for i in hors_magnitude).most_common()),
                "ids": sorted(hors_magnitude),
            },
            "hors_union_6": {
                "n": len(hors_union6),
                "pct_corpus": round(100 * len(hors_union6) / len(tasks), 1),
                "par_site": dict(Counter(sites[i] for i in hors_union6).most_common()),
                "ids": sorted(hors_union6),
            },
            "hors_union_8": {
                "n": len(hors_union_all),
                "ids": sorted(hors_union_all),
            },
        }

    v1 = out["par_configuration"]["L1/v1_naive"]
    v2 = out["par_configuration"]["L1/v2_contextual"]
    out["reproduction_du_chiffre_du_cadrage"] = {
        "chiffre_annonce_le_15_08_2026": 41,
        "politique_qui_le_produit": "L1 / v1 naïf (toute date passée ou tout effet de bord)",
        "recompte": v1["hors_magnitude"]["n"],
        "ecart_avec_le_chiffre_annonce": (
            "L'écart d'une unité vient de l'extracteur de dates, qui reconnaît désormais "
            "les mois abrégés (« Jan. 22 ») que le script exploratoire du 15/08 ratait."
        ),
        "meme_politique_hors_union_6": v1["hors_union_6"]["n"],
        "politique_retenue_v2_hors_magnitude": v2["hors_magnitude"]["n"],
        "politique_retenue_v2_hors_union_6": v2["hors_union_6"]["n"],
        "lecture": (
            "Le « decay accumulé » de 41 tâches annoncé dans le cadrage est un artefact de "
            "la politique naïve : elle signale toute date passée, y compris sur des "
            "requêtes archivistiques qui restent parfaitement exécutables. Sous la "
            "politique contextuelle, l'outil ne trouve presque rien que Magnitude n'ait "
            "déjà vu — et rien du tout que les six annotateurs réunis n'aient vu. C'est un "
            "résultat NÉGATIF, et il est important : sur le mode temporel, la détection "
            "statique n'a plus rien à apprendre aux praticiens ; ce qui reste à découvrir "
            "est côté site, donc en L2/L3."
        ),
    }

    sub = filter_health(health, LAYER_SETS["L1"])
    ref = sorted(flag_set(sub, Severity.MEDIUM) - magnitude)
    by_id_health = {v.task.task_id: v for v in sub.verdicts}
    out["exemples_hors_magnitude_L1_medium"] = [
        {
            "id": task_id,
            "site": sites[task_id],
            "question": by_id[task_id]["question_originale"],
            "signaux": sorted(
                {f"{f.detector}:{f.signal}" for f in by_id_health[task_id].findings if f.severity >= Severity.MEDIUM}
            ),
            "vu_ensuite_par": by_id[task_id]["accord"]["signalee_par"],
        }
        for task_id in ref[:25]
    ]
    return out


def forks_health() -> dict[str, Any]:
    """Chaque fork mesuré à sa propre date de gel, puis au 15/08/2026 : forker guérit-il ?

    Si la santé d'un fork à sa naissance est bonne et sa santé aujourd'hui mauvaise, alors
    le fork n'est pas une réparation mais un report d'échéance.

    Chaque fork est mesuré sur son corpus, exclusions comprises : un fichier de tâches qui
    contient encore les identifiants que le fork a publiquement retirés n'est pas son
    corpus. C'est le cas de browser-use (643 lignes, 55 exclusions déclarées, 588 tâches
    réelles) ; sans ce filtre, on lui impute des tâches qu'il ne fait pas tourner.
    """
    rows = []
    for label, filename, birth, exclusions_file in FORKS:
        path = RAW / filename
        if not path.exists():
            continue
        tasks = load_webvoyager(path)
        n_brut = len(tasks)
        excluded: set[str] = set()
        if exclusions_file:
            excl_path = RAW / exclusions_file
            if excl_path.exists():
                excluded = set(json.loads(excl_path.read_text(encoding="utf-8")))
                tasks = [t for t in tasks if t.task_id not in excluded]
        at_birth = run_l1(tasks, today=birth)
        now = run_l1(tasks, today=TODAY)
        n = len(tasks)
        b_high = len(at_birth.flagged(Severity.HIGH))
        n_high = len(now.flagged(Severity.HIGH))
        b_med = len(at_birth.flagged(Severity.MEDIUM))
        n_med = len(now.flagged(Severity.MEDIUM))
        age = months_between(birth, TODAY)
        rows.append(
            {
                "fork": label,
                "fichier": filename,
                "date_de_gel": birth.isoformat(),
                "n_taches": n,
                "n_lignes_du_fichier": n_brut,
                "n_exclusions_declarees_retirees": n_brut - n,
                "age_mois": round(age, 1),
                "signalees_a_sa_naissance_high": b_high,
                "signalees_a_sa_naissance_high_pct": round(100 * b_high / n, 1),
                "signalees_au_15_08_2026_high": n_high,
                "signalees_au_15_08_2026_high_pct": round(100 * n_high / n, 1),
                "nouvelles_morts_high": n_high - b_high,
                "signalees_a_sa_naissance_medium": b_med,
                "signalees_au_15_08_2026_medium": n_med,
                "risque_high": hazard(n_high - b_high, n - b_high, age) if age > 0 else None,
            }
        )
    return {
        "note": (
            "Mesure L1 uniquement : le seul mode de décadence visible ici est le temporel. "
            "Un fork qui supprime des tâches sans re-dater améliore mécaniquement son taux "
            "sans avoir traité la cause."
        ),
        "denominateur": (
            "Chaque fork est mesuré sur son corpus réel, exclusions déclarées retirées. "
            "browser-use : 588 tâches et non les 643 lignes de browseruse_tasks.jsonl, qui "
            "contient encore les 55 identifiants de WebVoyagerImpossibleTasks.json. Avant "
            "cette correction, 9 des 12 constats « à sa naissance » portaient sur des "
            "tâches déjà retirées et le taux publié (1,9 %) valait près de quatre fois le "
            "vrai (0,5 %)."
        ),
        "forks": rows,
    }


def om2w_control(gt: Mapping[str, Any]) -> dict[str, Any]:
    """Online-Mind2Web : décadence observée sous surveillance active.

    WebVoyager n'est pas maintenu, sa décadence n'est mesurée que quand un tiers décide de
    forker. Online-Mind2Web publie un journal de remplacement daté ; son taux est donc une
    mesure de ce qu'une équipe qui REGARDE trouve. S'il est supérieur au nôtre, ce n'est pas
    que le corpus se dégrade plus vite, c'est que le nôtre est sous-observé.
    """
    j = gt["om2w_journal"]
    n = j["taille_corpus"]
    waves = j["vagues"]
    first = _dt.date.fromisoformat(waves[0]["date"])
    last = _dt.date.fromisoformat(waves[-1]["date"])

    # Les identifiants de la dernière vague portent un suffixe de date (`..._051526`) :
    # c'est la MÊME tâche d'origine, remplacée une seconde fois. On compte donc les
    # identifiants de base, sinon une tâche re-remplacée compterait pour deux.
    def base(tid: str) -> str:
        return tid.split("_")[0]

    seen: set[str] = set()
    replaced_twice: Counter = Counter()
    cumul = []
    for w in waves:
        for tid in w["task_ids"]:
            replaced_twice[base(tid)] += 1
        seen.update(base(t) for t in w["task_ids"])
        cumul.append(
            {
                "date": w["date"],
                "n_remplacees": w["n_taches"],
                "cumul_distinctes": len(seen),
                "cumul_pct": round(100 * len(seen) / n, 1),
            }
        )
    repeats = {k: v for k, v in replaced_twice.items() if v > 1}
    span = months_between(first, last)
    return {
        "benchmark": "Online-Mind2Web",
        "n_taches": n,
        "n_vagues": len(waves),
        "premiere_vague": first.isoformat(),
        "derniere_vague": last.isoformat(),
        "duree_mois": round(span, 2),
        "remplacements_cumules": sum(w["n_taches"] for w in waves),
        "taches_distinctes_remplacees": len(seen),
        "identifiants_bruts_distincts": len({t for w in waves for t in w["task_ids"]}),
        "taches_remplacees_plusieurs_fois": {
            "n": len(repeats),
            "detail": dict(sorted(repeats.items(), key=lambda kv: -kv[1])),
            "lecture": (
                f"{len(repeats)} des {len(seen)} tâches remplacées ont dû l'être une "
                "seconde fois, et une une troisième. Remplacer n'est pas plus définitif "
                "que re-dater : c'est le même argument que la rouille des correctifs de "
                "Magnitude, observé cette fois sur un benchmark maintenu."
            ),
        },
        "cumul": cumul,
        "risque": hazard(len(seen), n, span),
        "lecture": (
            "Ce taux est celui d'un benchmark ACTIVEMENT maintenu : chaque remplacement "
            "est le fruit d'une vérification. Il borne par le haut ce qu'une surveillance "
            "peut voir, là où les patch-sets WebVoyager bornent par le bas ce qu'une "
            "observation opportuniste trouve."
        ),
    }


def summarise_rates(
    curve_a: Mapping[str, Any],
    curve_b: Mapping[str, Any],
    curve_b_patched: Mapping[str, Any],
    rot: Mapping[str, Any],
    om2w: Mapping[str, Any],
) -> dict[str, Any]:
    """Rassemble les estimateurs de taux de décadence et dit ce que chacun mesure."""
    jalons = [m for m in curve_a["jalons"] if m["annotateur_independant"]]
    first, last = jalons[0], jalons[-1]
    n_total = curve_a["n_taches"]
    span_all = months_between(T0, _dt.date.fromisoformat(last["date"]))
    span_post = months_between(
        _dt.date.fromisoformat(first["date"]), _dt.date.fromisoformat(last["date"])
    )
    survivors_after_first = n_total - first["cumul_independants"]
    new_after_first = last["cumul_independants"] - first["cumul_independants"]

    estimators = {
        "A1_cumul_brut_praticiens": {
            "question": "Quelle part du corpus a été signalée depuis la publication ?",
            **hazard(last["cumul_independants"], n_total, span_all),
            "biais": (
                "Censuré à gauche : les 121 tâches du premier audit peuvent être des "
                "défauts de construction et non de la décadence. Surestime le taux."
            ),
        },
        "A2_increments_post_premier_audit": {
            "question": (
                "Parmi les tâches qu'un premier auditeur avait jugées saines en 12/2024, "
                "combien un auditeur ultérieur a-t-il signalées ?"
            ),
            **hazard(new_after_first, survivors_after_first, span_post),
            "biais": (
                "Le seul estimateur non censuré à gauche, mais il dépend entièrement du "
                "zèle des annotateurs suivants : personne n'a re-examiné le corpus entre "
                "05/2026 et 08/2026. Sous-estime le taux."
            ),
        },
        "B_instrument_constant_L1_high": {
            "question": (
                "Parmi les tâches qu'un détecteur temporel constant jugeait valides à la "
                "publication, combien sont périmées au 15/08/2026 ?"
            ),
            **curve_b["seuils"]["high"]["risque_sur_les_vivantes"],
            "biais": (
                "Exact et reproductible, mais ne voit que la dérive temporelle (T1) : "
                "aveugle à la disparition de contenu, à l'anti-bot et à l'ambiguïté. "
                "Borne inférieure stricte."
            ),
        },
        "B_prime_instrument_sur_corpus_repare": {
            "question": (
                "Le même instrument, appliqué au corpus RÉPARÉ par Magnitude à partir du "
                "jour de la réparation : à quelle vitesse une réparation se défait-elle ?"
            ),
            **curve_b_patched["seuils"]["high"]["risque_sur_les_vivantes"],
            "biais": (
                "Mesure la durée de vie d'un corpus re-daté, pas celle d'un corpus "
                "d'origine. C'est pourtant le régime pertinent : tout benchmark web-live "
                "maintenu vit dans cet état, jamais dans celui d'un corpus figé dont les "
                "dates sont déjà toutes passées."
            ),
        },
        "C_rouille_des_correctifs": {
            "question": (
                "Parmi les correctifs datés publiés par un praticien en 07/2025, combien "
                "sont eux-mêmes périmés treize mois plus tard ?"
            ),
            **rot["risque"],
            "biais": (
                "Population très particulière : ce sont des tâches CHOISIES pour leur "
                "fragilité temporelle, re-datées à horizon court (janvier-mars 2026). Le "
                "taux n'est pas transposable au corpus entier ; il mesure la durée de vie "
                "d'un correctif, pas celle d'une tâche."
            ),
        },
        "D_controle_benchmark_maintenu": {
            "question": (
                "Quel taux mesure une équipe qui surveille activement son benchmark web-live ?"
            ),
            **om2w["risque"],
            "biais": (
                "Corpus, domaine et politique de remplacement différents. Comparable en "
                "ordre de grandeur, pas en valeur. Borne supérieure de ce qui est visible."
            ),
        },
    }
    values = [
        e["taux_annuel"]
        for k, e in estimators.items()
        if e.get("taux_annuel") is not None and k != "C_rouille_des_correctifs"
    ]
    n_est = len(values)
    headline = estimators["A2_increments_post_premier_audit"]
    return {
        "estimateurs": estimators,
        "fourchette_taux_annuel_hors_correctifs": [round(min(values), 4), round(max(values), 4)],
        "recommandation_pour_le_memoire": {
            "estimateur_a_citer": "A2_increments_post_premier_audit",
            "valeur": headline["taux_annuel"],
            "ic95": headline["taux_annuel_ic95"],
            "formulation": (
                "Entre décembre 2024 et mai 2026, "
                f"{headline['k']} des {headline['n']} tâches qu'un premier auditeur avait "
                "jugées saines ont été signalées par un auditeur ultérieur, soit un taux "
                f"annuel de {round(100 * headline['taux_annuel'], 1)} % "
                f"[IC 95 % : {round(100 * headline['taux_annuel_ic95'][0], 1)} – "
                f"{round(100 * headline['taux_annuel_ic95'][1], 1)} %]."
            ),
            "pourquoi_celui_la": (
                "C'est le seul estimateur qui ne soit pas censuré à gauche (il part de "
                "tâches déjà examinées et jugées saines) et qui porte sur TOUS les modes "
                "de décadence (il repose sur des observations humaines du site, pas sur un "
                "détecteur). Il faut le citer accompagné de sa limite : il ne voit que ce "
                "que des auditeurs bénévoles ont bien voulu regarder, donc il "
                "sous-estime."
            ),
            "a_ne_pas_citer_seul": (
                "Le taux de 100 % de la rouille des correctifs est spectaculaire et vrai, "
                "mais il porte sur 65 tâches choisies pour leur fragilité temporelle et "
                "re-datées à horizon court. Il répond à « combien de temps vit un "
                "correctif ? », pas à « à quelle vitesse un benchmark se dégrade ? »."
            ),
        },
        "conclusion": (
            f"{n_est} estimateurs indépendants placent le taux de décadence annuel de "
            f"WebVoyager entre {round(100 * min(values), 1)} % et "
            f"{round(100 * max(values), 1)} % des tâches encore valides. Aucun n'est "
            "l'estimateur juste : ils diffèrent par ce qu'ils observent (un mode de "
            "décadence contre tous) et par qui observe (un instrument constant contre un "
            "panel d'annotateurs changeant). L'écart entre eux mesure l'effort "
            "d'observation autant que la décadence elle-même — c'est le résultat "
            "méthodologique central de ce chapitre."
        ),
    }


BIASES = [
    "Les patch-sets ne sont pas des mesures indépendantes du même phénomène. Magnitude "
    "re-date par précaution des tâches encore exécutables ; Skyvern rafraîchit en masse "
    "sans motiver ; browser-use exclut sans réécrire. « Signalée » agrège trois "
    "intentions différentes.",
    "Le silence vaut conservation. Une source qui ne mentionne pas une tâche est comptée "
    "comme la conservant, alors qu'elle ne l'a peut-être jamais examinée. Tous les "
    "cumuls sont donc des bornes inférieures du nombre de tâches réellement défectueuses, "
    "et tous les accords des bornes supérieures.",
    "Censure à gauche : le premier audit disponible date de 12/2024, neuf mois et demi "
    "après la publication. Les 121 tâches qu'il signale n'ont pas de date de décès "
    "connue ; une partie est probablement défectueuse dès l'origine (défaut de "
    "construction), ce qui n'est pas de la décadence.",
    "Censure à droite : aucun annotateur n'a examiné le corpus entre 05/2026 et notre "
    "mesure. Le dernier segment de la courbe A est plat par absence d'observateur, pas "
    "par absence de décadence.",
    "L'instrument de la courbe B ne voit qu'un mode de décadence. Une tâche dont le site "
    "a changé de structure, dont le produit cité a disparu ou dont l'accès est bloqué "
    "reste « vivante » pour lui. Sa borne est stricte mais étroite.",
    "Les dates de décès de la courbe B sont connues au mois près (grille mensuelle) et "
    "sont des dates de PÉREMPTION TEXTUELLE, pas des dates d'échec d'exécution : la tâche "
    "meurt le jour où sa date interne passe, pas le jour où un agent échoue.",
    "Le corpus n'est pas homogène. Deux sites (Booking, Google Flights) portent une "
    "fraction énorme des décès temporels. Un taux moyen sur les 643 tâches masque une "
    "distribution bimodale : des sites presque intacts et des sites presque entièrement "
    "morts.",
    "Le contrôle Online-Mind2Web porte sur un autre corpus, un autre domaine et une autre "
    "politique de remplacement. Il sert d'ordre de grandeur et de démonstration qu'un "
    "benchmark surveillé produit un taux OBSERVÉ plus élevé — pas de valeur de référence.",
]


def _print(report: Mapping[str, Any]) -> None:
    a = report["courbe_A_praticiens"]
    print("\n=== COURBE A — mortalité vue par les praticiens ===")
    print(f"{'date':<12}{'source':<15}{'indép.':<8}{'mois':>6}{'nouv.':>7}{'cumul':>7}{'%':>7}")
    for m in a["jalons"]:
        print(
            f"{m['date']:<12}{m['source']:<15}{'oui' if m['annotateur_independant'] else 'non':<8}"
            f"{m['mois_depuis_publication']:>6.1f}{m['nouvelles_vs_cumul_independants']:>7}"
            f"{m['cumul_independants']:>7}{m['cumul_independants_pct']:>7.1f}"
        )
    print(f"  → {a['lecture']['censure_a_gauche']}")

    for key, title in (
        ("courbe_B_instrument", "COURBE B — instrument constant, corpus d'origine"),
        ("courbe_B_prime_corpus_repare", "COURBE B′ — même instrument, corpus réparé 07/2025"),
    ):
        b = report[key]
        h = b["seuils"]["high"]
        print(f"\n=== {title} (L1, seuil HIGH) ===")
        for row in h["courbe"]:
            bar = "#" * int(row["pct"] / 2)
            print(f"  {row['date']}  {row['n_signalees']:>4} ({row['pct']:>5.2f} %) {bar}")
        tb = b["bombes_a_retardement"]
        print(
            f"  à la naissance : {h['mortes_a_la_publication']} signalées "
            f"({h['mortes_a_la_publication_pct']} %), "
            f"{tb['bombes_a_retardement']} bombes à retardement "
            f"(horizon médian {tb['horizon_median_jours']} j), "
            f"{tb['deja_perimees_a_la_naissance']} déjà périmées"
        )
        print(f"  nouvelles morts depuis : {h['nouvelles_morts']} ; "
              f"décès par semestre : {h['deces_par_semestre']}")

    r = report["rouille_des_correctifs"]
    print("\n=== LES CORRECTIFS QUI POURRISSENT ===")
    for k, v in r["resultats"].items():
        print(f"  {k:<45} {v}")

    u = report["decadence_hors_patch_sets"]
    print("\n=== DÉCADENCE ACCUMULÉE HORS PATCH-SETS ===")
    print(f"{'configuration':<18}{'signalées':>10}{'hors Magnitude':>16}{'hors union 6':>14}")
    for conf, v in u["par_configuration"].items():
        print(
            f"{conf:<18}{v['n_signalees']:>10}{v['hors_magnitude']['n']:>16}"
            f"{v['hors_union_6']['n']:>14}"
        )

    f = report["sante_des_forks"]
    print("\n=== SANTÉ COMPARÉE DES FORKS (L1 seuil HIGH) ===")
    print(f"{'fork':<24}{'gel':<12}{'n':>5}{'à sa naissance':>16}{'au 15/08/2026':>16}")
    for row in f["forks"]:
        print(
            f"{row['fork']:<24}{row['date_de_gel']:<12}{row['n_taches']:>5}"
            f"{row['signalees_a_sa_naissance_high']:>8} ({row['signalees_a_sa_naissance_high_pct']:>4.1f} %)"
            f"{row['signalees_au_15_08_2026_high']:>8} ({row['signalees_au_15_08_2026_high_pct']:>4.1f} %)"
        )

    print("\n=== ESTIMATEURS DU TAUX DE DÉCADENCE ANNUEL ===")
    for name, e in report["taux_de_decadence"]["estimateurs"].items():
        if e.get("taux_annuel") is None:
            continue
        ic = e["taux_annuel_ic95"]
        print(
            f"  {name:<34} {100 * e['taux_annuel']:>5.1f} %  "
            f"[{100 * ic[0]:>4.1f} ; {100 * ic[1]:>4.1f}]  "
            f"(k={e['k']}/n={e['n']} sur {e['months']} mois)"
        )
    reco = report["taux_de_decadence"]["recommandation_pour_le_memoire"]
    print(f"  → à citer : {reco['formulation']}")
    print("  " + report["taux_de_decadence"]["conclusion"])

    print("\n=== BIAIS ASSUMÉS ===")
    for i, bias in enumerate(report["biais"], 1):
        print(f"  {i}. {bias}")


def _write_csv(report: Mapping[str, Any], path: Path) -> None:
    """Les deux courbes dans un CSV unique, prêt à tracer."""
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["courbe", "date", "mois_depuis_publication", "n_signalees", "pct", "n_corpus"])
        n = report["courbe_A_praticiens"]["n_taches"]
        for m in report["courbe_A_praticiens"]["jalons"]:
            if m["annotateur_independant"]:
                w.writerow(
                    ["A_praticiens", m["date"], m["mois_depuis_publication"],
                     m["cumul_independants"], m["cumul_independants_pct"], n]
                )
        for key, label in (
            ("courbe_B_instrument", "B_instrument"),
            ("courbe_B_prime_corpus_repare", "Bprime_corpus_repare"),
        ):
            for seuil in ("high", "medium"):
                for row in report[key]["seuils"][seuil]["courbe"]:
                    w.writerow(
                        [f"{label}_{seuil}", row["date"], row["mois"],
                         row["n_signalees"], row["pct"], report[key]["n_taches"]]
                    )
        for row in report["controle_online_mind2web"]["cumul"]:
            w.writerow(
                ["D_online_mind2web", row["date"],
                 round(months_between(_dt.date(2025, 4, 5), _dt.date.fromisoformat(row["date"])), 2),
                 row["cumul_distinctes"], row["cumul_pct"], 300]
            )


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="analysis_longitudinal.py",
        description="Courbes de mortalité et taux de décadence de WebVoyager (2024-2026).",
    )
    p.add_argument("--step", type=int, default=1, help="pas de la courbe B, en mois")
    p.add_argument(
        "--findings",
        default=str(RUNS / "health_20260815_findings.json"),
        help="journal des constats produit par run_all.py --phase audit",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    gt = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    tasks = load_webvoyager(RAW / "webvoyager_original.jsonl")

    curve_a = curve_annotators(gt)
    curve_b = curve_instrument(tasks, step_months=args.step)
    # Courbe B′ : le même instrument sur le corpus RÉPARÉ par Magnitude, à partir du jour
    # de la réparation. C'est là que l'instrument capte de la décadence en vol, parce que
    # le patcheur a introduit des dates futures, donc des échéances.
    curve_b_patched = curve_instrument(
        load_webvoyager(RAW / "magnitude_patched.jsonl"),
        start=_dt.date(2025, 7, 6),
        end=TODAY,
        step_months=args.step,
        corpus="magnitude_patched.jsonl",
    )
    rot = patch_rot()
    om2w = om2w_control(gt)
    unseen = unseen_decay(gt, Path(args.findings))
    forks = forks_health()

    report = {
        "meta": {
            "generated_by": f"analysis_longitudinal.py (benchmark-doctor {__version__})",
            "publication": T0.isoformat(),
            "date_de_mesure": TODAY.isoformat(),
            "mois_ecoules": round(months_between(T0, TODAY), 2),
            "corpus": "WebVoyager 643 tâches (MinorJerry/WebVoyager @ 0915445)",
        },
        "courbe_A_praticiens": curve_a,
        "courbe_B_instrument": curve_b,
        "courbe_B_prime_corpus_repare": curve_b_patched,
        "rouille_des_correctifs": rot,
        "decadence_hors_patch_sets": unseen,
        "sante_des_forks": forks,
        "controle_online_mind2web": om2w,
        "taux_de_decadence": summarise_rates(curve_a, curve_b, curve_b_patched, rot, om2w),
        "biais": BIASES,
    }

    RUNS.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_csv(report, OUT_CSV)
    _print(report)
    print(f"\nrapport : {OUT_JSON}")
    print(f"courbes : {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
