"""Validation **hors échantillon** des détecteurs de `benchmark-doctor`.

La grille de validation publiée (`run_all.py --phase validate`,
`runs/validation_ablation_20260815.json`) annonce pour la couche L1 au seuil HIGH une
précision de 0,986 contre la vérité `signalee_1`. Ce chiffre est intégralement in-sample :
sur les 72 vrais positifs, 71 sont des tâches du patch-set Magnitude, exactement le corpus
sur lequel les détecteurs L1 ont été réglés, et l'apport des cinq autres annotateurs se
réduit à une tâche. Mesurer un détecteur sur son propre jeu de réglage mesure sa capacité à
mémoriser, pas à généraliser.

D'où la scission : jeu d'ajustement A = les 121 tâches que Magnitude a patchées, jeu de
validation V = les 522 restantes, disjonction vérifiée à l'exécution. Une tâche de V est
défectueuse si elle a été signalée par au moins un des cinq annotateurs autres que
Magnitude, qui n'intervient jamais dans l'étiquetage de V. Chaque ligne de la grille porte
sa ligne de base : précision au hasard (la prévalence dans V, sans laquelle « précision
0,33 » ne dit ni bien ni mal), lift, et test binomial unilatéral.

Le binomial suppose des signalements indépendants, ce qu'ils ne sont pas : la couche L2
mesure l'accès par site et propage un constat unique aux 8 à 46 tâches du site. Dans V,
L2/HIGH signale 126 tâches, mais ce sont quatre décisions (Allrecipes 40/40, Amazon 38/38,
Booking 11/11, ESPN 37/37). Trois lectures sont donc calculées et nommées : ``p_binomial``,
le test naïf, publié comme borne optimiste ; ``p_intra_site``, exact et stratifié par site ;
``p_site``, permutation exacte au niveau site quand l'ensemble signalé est une réunion de
sites entiers. Chacune est justifiée à sa fonction, la règle de choix dans `_retained_p`.
S'y ajoute un intervalle de confiance rééchantillonnant les 15 sites, non les tâches, et
deux contrôles de robustesse, `leave_one_site_out` et `per_annotator`.

Ce que le protocole ne corrige pas : la scission est disjointe sur les positifs, pas sur les
négatifs, puisque régler les détecteurs a consisté pour partie à supprimer des faux positifs,
donc à regarder des tâches non patchées, ce qui laisse le chiffre hors échantillon en borne
haute. Et la vérité de validation reste le jugement d'autres praticiens, faillible et non
motivé pour la plupart des sources.

Aucun appel réseau : tout est relu dans les constats déjà journalisés.

    python experiments/validation_hors_echantillon.py                  # grille complète
    python experiments/validation_hors_echantillon.py --bootstrap 0    # sans bootstrap
    python experiments/validation_hors_echantillon.py --out chemin.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.stats import binomtest, fisher_exact, hypergeom

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_all as _ra  # noqa: E402
from benchmark_doctor.models import BenchmarkHealth, Severity  # noqa: E402

RUNS = ROOT / "runs"
DATA = ROOT / "data"
RAW = DATA / "raw"
GROUND_TRUTH = DATA / "ground_truth.json"
FINDINGS = RUNS / "health_20260815_findings.json"
OUT_JSON = RUNS / "validation_hors_echantillon_20260816.json"

#: Date de mesure, gelée comme dans `run_all.py` et `analysis_longitudinal.py`.
TODAY = _dt.date(2026, 8, 15)

#: Le patch-set qui a servi à régler les détecteurs L1.
TUNING_SOURCE = "magnitude"

#: Les six annotateurs comptés dans l'accord (`run_all.INDEPENDENT_SOURCES`). Le mot
#: « indépendants » est retiré : Convergence et Magnitude partagent 56 de leurs 60
#: réécritures communes au caractère près.
ANNOTATORS = tuple(_ra.INDEPENDENT_SOURCES)

#: Convergence appartient à la même lignée que Magnitude : une vérité qui l'exclut est
#: la lecture la plus sévère du hors-échantillon.
SAME_LINEAGE_AS_TUNING = ("convergence",)

LAYER_SETS = dict(_ra.LAYER_SETS)
THRESHOLDS = dict(_ra.THRESHOLDS)

BOOTSTRAP_DEFAULT = 20_000
SEED_DEFAULT = 20260816


# 1. La scission


def load_corpus() -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Renvoie les 643 tâches réconciliées et la table tâche → site."""
    gt = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    tasks = gt["taches"]
    sites = {t["id"]: t["site"] for t in tasks}
    return tasks, sites


def flagged_by(tasks: Sequence[Mapping[str, Any]], source: str) -> set[str]:
    """Tâches qu'une source a signalées : réécrites (`modify`) **ou** supprimées."""
    return {
        t["id"]
        for t in tasks
        if any(v["source"] == source and v["action"] in ("remove", "modify") for v in t["verdicts"])
    }


def removed_by(tasks: Sequence[Mapping[str, Any]], source: str) -> set[str]:
    return {
        t["id"]
        for t in tasks
        if any(v["source"] == source and v["action"] == "remove" for v in t["verdicts"])
    }


def split_corpus(tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Jeu d'ajustement (patch-set de réglage) contre jeu de validation, disjoints."""
    adjust = flagged_by(tasks, TUNING_SOURCE)
    every = {t["id"] for t in tasks}
    validate = every - adjust
    assert not (adjust & validate), "la scission doit être disjointe"
    assert adjust | validate == every, "la scission doit être exhaustive"
    return {
        "source_d_ajustement": TUNING_SOURCE,
        "n_corpus": len(every),
        "jeu_d_ajustement": sorted(adjust),
        "n_jeu_d_ajustement": len(adjust),
        "jeu_de_validation": sorted(validate),
        "n_jeu_de_validation": len(validate),
        "disjonction_verifiee": True,
        "note": (
            "Le jeu d'ajustement est l'ensemble des tâches patchées par Magnitude au "
            "06/07/2025 : c'est sur elles que les détecteurs L1 ont été réglés. Aucune "
            "décision de Magnitude ne porte sur le jeu de validation."
        ),
    }


def build_validation_truths(
    tasks: Sequence[Mapping[str, Any]], validate: set[str]
) -> dict[str, dict[str, Any]]:
    """Les vérités de validation, toutes construites **sans** l'annotateur d'ajustement."""
    others = [s for s in ANNOTATORS if s != TUNING_SOURCE]
    strict = [s for s in others if s not in SAME_LINEAGE_AS_TUNING]

    def n_signalers(t: Mapping[str, Any], sources: Iterable[str]) -> int:
        allowed = set(sources)
        return len(
            {
                v["source"]
                for v in t["verdicts"]
                if v["source"] in allowed and v["action"] in ("remove", "modify")
            }
        )

    truths: dict[str, dict[str, Any]] = {}

    def add(key: str, ids: set[str], description: str) -> None:
        ids = ids & validate
        truths[key] = {
            "ids": ids,
            "n": len(ids),
            "prevalence": len(ids) / len(validate),
            "description": description,
        }

    add(
        "autres_1",
        {t["id"] for t in tasks if n_signalers(t, others) >= 1},
        f"signalée par au moins 1 des {len(others)} annotateurs autres que Magnitude "
        "(vérité de référence)",
    )
    add(
        "autres_2",
        {t["id"] for t in tasks if n_signalers(t, others) >= 2},
        f"signalée par au moins 2 des {len(others)} annotateurs autres que Magnitude "
        "(lecture plus exigeante)",
    )
    add(
        "hors_lignee_1",
        {t["id"] for t in tasks if n_signalers(t, strict) >= 1},
        f"signalée par au moins 1 des {len(strict)} annotateurs sans filiation connue "
        "avec Magnitude (Convergence exclue : 56/60 réécritures identiques)",
    )
    add(
        "supprimee_autres_1",
        {
            t["id"]
            for t in tasks
            if any(v["source"] in others and v["action"] == "remove" for v in t["verdicts"])
        },
        f"retirée du corpus par au moins 1 des {len(others)} annotateurs autres que "
        "Magnitude (la vérité la plus proche de « la tâche est morte »)",
    )
    return truths


# 2. L'appareil statistique


def site_table(
    universe: set[str], flags: set[str], truth: set[str], sites: Mapping[str, str]
) -> list[tuple[str, int, int, int]]:
    """Par site : (nom, n tâches, n positifs, n signalées). L'unité de dépendance."""
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for task_id in universe:
        row = agg[sites[task_id]]
        row[0] += 1
        if task_id in truth:
            row[1] += 1
        if task_id in flags:
            row[2] += 1
    return [(s, *agg[s]) for s in sorted(agg)]


def p_stratified_by_site(
    universe: set[str], flags: set[str], truth: set[str], sites: Mapping[str, str]
) -> float:
    """Test exact conditionnel stratifié par site — :math:`P(TP' \\ge TP)` sous H0.

    Sous l'hypothèse nulle, à l'intérieur de chaque site :math:`s` les :math:`f_s`
    constats du détecteur sont placés au hasard parmi les :math:`n_s` tâches, dont
    :math:`c_s` sont positives. Le nombre de vrais positifs du site suit alors
    :math:`\\mathrm{Hypergeom}(n_s, c_s, f_s)`, et le total suit la convolution de ces
    lois indépendantes — calculée exactement, sans simulation.

    Ce test est le remède direct à la propagation par site : il ne récompense jamais le
    fait d'avoir désigné le bon **site**, uniquement le fait d'avoir désigné les bonnes
    **tâches** dans un site. Un détecteur qui signale des sites entiers obtient
    :math:`p = 1{,}0` exactement, la distribution étant dégénérée.
    """
    dist = np.array([1.0])
    for _site, n_s, c_s, f_s in site_table(universe, flags, truth, sites):
        if f_s == 0:
            continue
        support = np.arange(0, min(c_s, f_s) + 1)
        pmf = hypergeom.pmf(support, n_s, c_s, f_s)
        dist = np.convolve(dist, pmf)
    observed = len(flags & truth)
    if observed >= len(dist):
        return 0.0
    return float(dist[observed:].sum())


def is_site_uniform(
    universe: set[str], flags: set[str], truth: set[str], sites: Mapping[str, str]
) -> bool:
    """Vrai si chaque site est signalé en entier ou pas du tout (constat propagé)."""
    return all(f_s in (0, n_s) for _s, n_s, _c, f_s in site_table(universe, flags, truth, sites))


def p_site_permutation(
    universe: set[str], flags: set[str], truth: set[str], sites: Mapping[str, str]
) -> dict[str, Any] | None:
    """Permutation **exacte** au niveau site, quand l'ensemble signalé est site-uniforme.

    L'unité d'observation est le site, pas la tâche : le détecteur a pris :math:`k`
    décisions, pas :math:`n` ; on énumère les :math:`\\binom{S}{k}` façons de choisir
    :math:`k` sites parmi les :math:`S` du corpus et l'on compte celles qui atteignent au
    moins la précision observée. Aucune approximation, aucun tirage.
    """
    rows = site_table(universe, flags, truth, sites)
    if not is_site_uniform(universe, flags, truth, sites):
        return None
    if not flags:
        return None
    chosen = [r for r in rows if r[3] > 0]
    k = len(chosen)
    observed = len(flags & truth) / len(flags)
    at_least = 0
    total = 0
    for combo in itertools.combinations(rows, k):
        n = sum(r[1] for r in combo)
        c = sum(r[2] for r in combo)
        total += 1
        if c / n >= observed - 1e-12:
            at_least += 1
    return {
        "n_sites_corpus": len(rows),
        "n_sites_signales": k,
        "n_permutations": total,
        "p": at_least / total,
        "sites_signales": [r[0] for r in chosen],
    }


def cluster_bootstrap(
    universe: set[str],
    flags: set[str],
    truth: set[str],
    sites: Mapping[str, str],
    *,
    n_boot: int,
    seed: int,
) -> dict[str, Any] | None:
    """IC 95 % en clusters : rééchantillonnage **des sites** avec remise.

    Le bootstrap ordinaire (tâche par tâche) casserait la structure de dépendance qu'on
    cherche justement à respecter. On tire donc :math:`S` sites avec remise et l'on
    recalcule précision, prévalence et lift sur le corpus reconstitué. Avec 15 clusters
    seulement, l'intervalle est large et grossier : c'est une information honnête, pas une
    précision retrouvée.
    """
    if n_boot <= 0 or not flags:
        return None
    rows = site_table(universe, flags, truth, sites)
    n = np.array([r[1] for r in rows], dtype=float)
    c = np.array([r[2] for r in rows], dtype=float)
    tp = np.array(
        [
            len({t for t in universe if sites[t] == r[0]} & flags & truth)
            for r in rows
        ],
        dtype=float,
    )
    f = np.array([r[3] for r in rows], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(rows), size=(n_boot, len(rows)))
    tot_f = f[idx].sum(axis=1)
    tot_tp = tp[idx].sum(axis=1)
    tot_n = n[idx].sum(axis=1)
    tot_c = c[idx].sum(axis=1)
    ok = (tot_f > 0) & (tot_c > 0)
    if ok.sum() < n_boot // 4:
        # trop de réplicats dégénérés (détecteur quasi muet) : l'IC n'a pas de sens
        return {
            "n_replicats": int(n_boot),
            "n_replicats_valides": int(ok.sum()),
            "exploitable": False,
            "note": (
                "moins d'un quart des réplicats contiennent au moins un constat : le "
                "détecteur signale trop peu de tâches pour qu'un intervalle soit calculable"
            ),
        }
    prec = tot_tp[ok] / tot_f[ok]
    prev = tot_c[ok] / tot_n[ok]
    lift = prec / prev
    return {
        "n_replicats": int(n_boot),
        "n_replicats_valides": int(ok.sum()),
        "exploitable": True,
        "precision_ic95": [float(np.percentile(prec, 2.5)), float(np.percentile(prec, 97.5))],
        "lift_ic95": [float(np.percentile(lift, 2.5)), float(np.percentile(lift, 97.5))],
        "p_bootstrap_lift_le_1": float((lift <= 1.0).mean()),
    }


def evaluate(
    universe: set[str],
    flags: set[str],
    truth: set[str],
    sites: Mapping[str, str],
    *,
    n_boot: int,
    seed: int,
) -> dict[str, Any]:
    """Une ligne complète de grille. **Jamais** de précision sans sa ligne de base."""
    flags = flags & universe
    truth = truth & universe
    n_flag = len(flags)
    tp = len(flags & truth)
    prevalence = len(truth) / len(universe) if universe else float("nan")
    precision = tp / n_flag if n_flag else float("nan")
    recall = tp / len(truth) if truth else float("nan")
    f1 = (
        2 * precision * recall / (precision + recall)
        if n_flag and truth and (precision + recall) > 0
        else 0.0
    )
    row: dict[str, Any] = {
        "n_univers": len(universe),
        "n_signalees": n_flag,
        "taux_de_signalement": round(n_flag / len(universe), 4) if universe else None,
        "vrais_positifs": tp,
        "faux_positifs": n_flag - tp,
        "n_verite": len(truth),
        "precision": round(precision, 4) if n_flag else None,
        "precision_au_hasard": round(prevalence, 4),
        "lift": round(precision / prevalence, 3) if n_flag and prevalence else None,
        "rappel": round(recall, 4) if truth else None,
        "f1": round(f1, 4),
    }
    # --- les trois tests ---------------------------------------------------------------
    row["p_binomial"] = (
        float(binomtest(tp, n_flag, prevalence, alternative="greater").pvalue) if n_flag else None
    )
    a = tp
    b = n_flag - tp
    c = len(truth) - tp
    d = len(universe) - n_flag - c
    row["p_fisher"] = (
        float(fisher_exact([[a, b], [c, d]], alternative="greater")[1]) if n_flag else None
    )
    row["p_intra_site"] = (
        round(p_stratified_by_site(universe, flags, truth, sites), 6) if n_flag else None
    )
    row["signalement_par_site_entier"] = is_site_uniform(universe, flags, truth, sites)
    row["test_site"] = p_site_permutation(universe, flags, truth, sites)
    row["n_sites_touches"] = len({sites[t] for t in flags})
    row["ic95_cluster_site"] = cluster_bootstrap(
        universe, flags, truth, sites, n_boot=n_boot, seed=seed
    )
    # --- verdict lisible ---------------------------------------------------------------
    row["p_retenue"] = _retained_p(row)
    row["significatif_5pct"] = bool(row["p_retenue"] is not None and row["p_retenue"] < 0.05)
    return row


def _retained_p(row: Mapping[str, Any]) -> float | None:
    """La p-value à publier : la plus défendable, pas la plus flatteuse.

    Règle, appliquée sans exception : si l'ensemble signalé est une réunion de sites
    entiers, c'est le test de permutation au niveau site qui fait foi (le détecteur a pris
    :math:`k` décisions, pas :math:`n`). Sinon, c'est le test stratifié intra-site, qui
    n'attribue jamais au détecteur le mérite d'avoir deviné le bon site. Le test binomial
    reste dans le rapport, nommé pour ce qu'il est : la borne optimiste.
    """
    if row["n_signalees"] == 0:
        return None
    if row["signalement_par_site_entier"] and row["test_site"]:
        return float(row["test_site"]["p"])
    return row["p_intra_site"]


# 3. Les grilles


def flags_for(health: BenchmarkHealth, layer_name: str, threshold_name: str) -> set[str]:
    sub = _ra.filter_health(health, LAYER_SETS[layer_name])
    return _ra.flag_set(sub, THRESHOLDS[threshold_name])


def grid(
    health: BenchmarkHealth,
    universe: set[str],
    truths: Mapping[str, Mapping[str, Any]],
    sites: Mapping[str, str],
    *,
    n_boot: int,
    seed: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for layer_name in LAYER_SETS:
        for threshold_name in THRESHOLDS:
            flags = flags_for(health, layer_name, threshold_name)
            key = f"{layer_name}|{threshold_name}"
            out[key] = {
                truth_name: evaluate(
                    universe, flags, truth["ids"], sites, n_boot=n_boot, seed=seed
                )
                for truth_name, truth in truths.items()
            }
    return out


def holm_bonferroni(pvalues: Mapping[str, float], alpha: float = 0.05) -> dict[str, Any]:
    """Contrôle du risque de première espèce sur la **famille** de la grille.

    Douze configurations sont testées contre la même vérité : à 5 % par test, on attend
    une ligne significative par pur hasard tous les vingt tests. La procédure de Holm
    (descendante, uniformément plus puissante que Bonferroni et valide sans hypothèse
    d'indépendance) répond à la seule question qui compte : y a-t-il un résultat, ou une
    collection de coïncidences ?
    """
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(ordered)
    rows = []
    still_rejecting = True
    for rank, (name, p) in enumerate(ordered, start=1):
        seuil = alpha / (m - rank + 1)
        if still_rejecting and p > seuil:
            still_rejecting = False
        rows.append(
            {
                "configuration": name,
                "p": round(p, 6),
                "rang": rank,
                "seuil_holm": round(seuil, 6),
                "rejetee": bool(still_rejecting),
            }
        )
    return {
        "alpha": alpha,
        "n_tests": m,
        "procedure": "Holm-Bonferroni descendante sur les p-values retenues",
        "survivantes": [r["configuration"] for r in rows if r["rejetee"]],
        "lignes": rows,
    }


def leave_one_site_out(
    health: BenchmarkHealth,
    universe: set[str],
    truth: set[str],
    sites: Mapping[str, str],
    layer_name: str,
    threshold_name: str,
) -> list[dict[str, Any]]:
    """La ligne de tête survit-elle au retrait de n'importe quel site ?"""
    flags = flags_for(health, layer_name, threshold_name)
    rows = []
    for dropped in sorted({sites[t] for t in universe}):
        sub_universe = {t for t in universe if sites[t] != dropped}
        row = evaluate(sub_universe, flags, truth, sites, n_boot=0, seed=0)
        rows.append(
            {
                "site_retire": dropped,
                "n_univers": row["n_univers"],
                "n_signalees": row["n_signalees"],
                "vrais_positifs": row["vrais_positifs"],
                "precision": row["precision"],
                "precision_au_hasard": row["precision_au_hasard"],
                "lift": row["lift"],
                "p_binomial": row["p_binomial"],
                "p_intra_site": row["p_intra_site"],
            }
        )
    return rows


def per_annotator(
    health: BenchmarkHealth,
    tasks: Sequence[Mapping[str, Any]],
    universe: set[str],
    sites: Mapping[str, str],
    layers: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    """L1 contre **chaque** annotateur pris seul : cinq validations indépendantes.

    C'est la mesure la plus décontaminée de la grille : Fara (08/2025) et Alumnium (03/2026)
    n'ont aucune filiation connue avec Magnitude ni entre eux, et leurs verdicts portent
    sur des tâches que Magnitude n'a jamais touchées.
    """
    out: dict[str, Any] = {}
    for source in [s for s in ANNOTATORS if s != TUNING_SOURCE]:
        truth = flagged_by(tasks, source) & universe
        block: dict[str, Any] = {
            "n_verite": len(truth),
            "prevalence": round(len(truth) / len(universe), 4),
            "meme_lignee_que_magnitude": source in SAME_LINEAGE_AS_TUNING,
        }
        for layer_name, threshold_name in layers:
            flags = flags_for(health, layer_name, threshold_name)
            row = evaluate(universe, flags, truth, sites, n_boot=0, seed=0)
            block[f"{layer_name}|{threshold_name}"] = {
                k: row[k]
                for k in (
                    "n_signalees",
                    "vrais_positifs",
                    "precision",
                    "precision_au_hasard",
                    "lift",
                    "rappel",
                    "p_binomial",
                    "p_intra_site",
                    "p_retenue",
                )
            }
        out[source] = block
    return out


def in_sample_mirror(
    health: BenchmarkHealth,
    tasks: Sequence[Mapping[str, Any]],
    adjust: set[str],
    sites: Mapping[str, str],
) -> dict[str, Any]:
    """Ce que la précision de 0,986 mesure réellement, décomposé.

    On refait la mesure publiée sur les 643 tâches contre `signalee_1`, puis on la
    décompose : combien de ses vrais positifs tombent dans le jeu d'ajustement, combien
    au-dehors. C'est la ligne « avant » de la grille avant/après.
    """
    every = {t["id"] for t in tasks}
    signalee_1 = {t["id"] for t in tasks if len(t["accord"]["signalee_par"]) >= 1}
    out: dict[str, Any] = {}
    for layer_name in ("L1", "L1+L2+L3"):
        for threshold_name in THRESHOLDS:
            flags = flags_for(health, layer_name, threshold_name)
            tp = flags & signalee_1
            out[f"{layer_name}|{threshold_name}"] = {
                "n_signalees": len(flags),
                "vrais_positifs": len(tp),
                "precision_publiee": round(len(tp) / len(flags), 4) if flags else None,
                "precision_au_hasard": round(len(signalee_1) / len(every), 4),
                "lift": (
                    round((len(tp) / len(flags)) / (len(signalee_1) / len(every)), 3)
                    if flags
                    else None
                ),
                "vrais_positifs_dans_le_jeu_d_ajustement": len(tp & adjust),
                "vrais_positifs_hors_jeu_d_ajustement": len(tp - adjust),
                "part_in_sample_des_vrais_positifs": (
                    round(len(tp & adjust) / len(tp), 4) if tp else None
                ),
                "signalees_dans_le_jeu_d_ajustement": len(flags & adjust),
            }
    return out


# 4. Le dénominateur browser-use


def browseruse_denominator() -> dict[str, Any]:
    """Recompte la ligne browser-use de la table des forks sur son **corpus réel**.

    `browseruse_tasks.jsonl` contient encore les 55 tâches que browser-use a lui-même
    déclarées impossibles (`WebVoyagerImpossibleTasks.json`). Le corpus effectivement
    évalué par browser-use est donc de 588 tâches, pas 643 — et **neuf des douze constats
    « à sa naissance » portent sur des tâches qu'il avait déjà retirées**.
    """
    from benchmark_doctor.parsers.webvoyager import load_webvoyager

    from analysis_longitudinal import run_l1  # import tardif : script lourd

    birth = _dt.date(2024, 12, 15)
    raw = load_webvoyager(RAW / "browseruse_tasks.jsonl")
    impossible = set(json.loads((RAW / "browseruse_impossible.json").read_text(encoding="utf-8")))
    real = [t for t in raw if t.task_id not in impossible]

    def measure(tasks, label: str) -> dict[str, Any]:
        at_birth = run_l1(tasks, today=birth)
        now = run_l1(tasks, today=TODAY)
        b_high = at_birth.flagged(Severity.HIGH)
        n_high = now.flagged(Severity.HIGH)
        return {
            "lecture": label,
            "n_taches": len(tasks),
            "signalees_a_sa_naissance_high": len(b_high),
            "signalees_a_sa_naissance_high_pct": round(100 * len(b_high) / len(tasks), 1),
            "signalees_au_15_08_2026_high": len(n_high),
            "signalees_au_15_08_2026_high_pct": round(100 * len(n_high) / len(tasks), 1),
            "ids_a_sa_naissance": sorted(v.task.task_id for v in b_high),
        }

    published = measure(raw, "publiée (fichier brut, 643)")
    corrected = measure(real, "corrigée (corpus réel, 588)")
    contaminated = sorted(set(published["ids_a_sa_naissance"]) & impossible)
    return {
        "n_exclusions_declarees": len(impossible),
        "n_exclusions_encore_dans_le_fichier": sum(1 for t in raw if t.task_id in impossible),
        "publiee": published,
        "corrigee": corrected,
        "constats_de_naissance_portant_sur_une_tache_deja_retiree": contaminated,
        "n_contamines": len(contaminated),
        "ligne_a_publier": (
            f"| browser-use | 2024-12-15 | {corrected['n_taches']} | "
            f"{corrected['signalees_a_sa_naissance_high']} "
            f"({corrected['signalees_a_sa_naissance_high_pct']:.1f} %) | "
            f"{corrected['signalees_au_15_08_2026_high']} "
            f"({corrected['signalees_au_15_08_2026_high_pct']:.1f} %) |"
        ),
        "note": (
            "Le chiffre publié à la naissance (1,9 %) vaut près de quatre fois le vrai "
            "(0,5 %). La correction affaiblit l'argument « un fork naît sain puis se "
            "dégrade » côté numérateur et le renforce côté conclusion : browser-use naît "
            "presque parfaitement sain (3/588) et revient à 10,5 % en vingt mois."
        ),
    }


# 5. Affichage


def _fmt(value: Any, spec: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return format(value, spec) if spec else f"{value:.3f}"
    return str(value)


def print_grid(title: str, block: Mapping[str, Any], truth_name: str) -> None:
    print(f"\n=== {title} ===")
    header = (
        f"{'config':10s} {'seuil':7s} {'flags':>5s} {'VP':>4s} {'P':>7s} {'P_hasard':>9s} "
        f"{'lift':>6s} {'R':>6s} {'p_binom':>10s} {'p_site*':>10s} {'IC95 lift':>16s}"
    )
    print(header)
    print("-" * len(header))
    for key, per_truth in block.items():
        layer, threshold = key.split("|")
        row = per_truth[truth_name]
        ic = row.get("ic95_cluster_site") or {}
        ic_txt = (
            f"[{ic['lift_ic95'][0]:.2f} ; {ic['lift_ic95'][1]:.2f}]"
            if ic.get("exploitable")
            else "non calculable"
        )
        star = "S" if row["signalement_par_site_entier"] else "s"
        print(
            f"{layer:10s} {threshold:7s} {row['n_signalees']:5d} {row['vrais_positifs']:4d} "
            f"{_fmt(row['precision']):>7s} {_fmt(row['precision_au_hasard']):>9s} "
            f"{_fmt(row['lift'], '.2f'):>6s} {_fmt(row['rappel']):>6s} "
            f"{_fmt(row['p_binomial'], '.3g'):>10s} "
            f"{_fmt(row['p_retenue'], '.3g'):>9s}{star} {ic_txt:>16s}"
        )
    print(
        "  p_binom = test binomial unilatéral i.i.d. (borne optimiste). "
        "p_site* = p retenue : 'S' test de permutation au niveau site (constats propagés "
        "par site entier), 's' test exact stratifié intra-site."
    )


# 6. Point d'entrée


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    tasks, sites = load_corpus()
    health = _ra.load_findings(FINDINGS)
    split = split_corpus(tasks)
    adjust = set(split["jeu_d_ajustement"])
    validate = set(split["jeu_de_validation"])
    truths = build_validation_truths(tasks, validate)
    reference = "autres_1"

    report: dict[str, Any] = {
        "meta": {
            "genere_par": "experiments/validation_hors_echantillon.py",
            "date_de_reference": TODAY.isoformat(),
            "constats": str(FINDINGS.relative_to(ROOT)),
            "verite_terrain": str(GROUND_TRUTH.relative_to(ROOT)),
            "graine": args.seed,
            "n_replicats_bootstrap": args.bootstrap,
            "cout_api_usd": 0.0,
            "motif_de_la_mesure": (
                "La précision de 0,986 publiée pour L1 au seuil HIGH est intégralement "
                "in-sample : 71 de ses 72 vrais positifs sont des tâches du patch-set qui "
                "a servi à régler les détecteurs."
            ),
            "avertissement": (
                "Les mesures portent sur les CONSTATS des détecteurs, jamais sur le score "
                "publié : celui-ci intègre un a priori tiré de la même base de vérité, et "
                "le valider contre elle serait circulaire."
            ),
        },
        "scission": {k: v for k, v in split.items() if not k.startswith("jeu_")}
        | {
            "n_jeu_d_ajustement": split["n_jeu_d_ajustement"],
            "n_jeu_de_validation": split["n_jeu_de_validation"],
        },
        "verites_de_validation": {
            k: {"n": v["n"], "prevalence": round(v["prevalence"], 4), "description": v["description"]}
            for k, v in truths.items()
        },
        "verite_de_reference": reference,
    }

    report["sites"] = [
        {"site": s, "n_taches": n, "n_positifs": c, "n_signalees_L2_high": f}
        for s, n, c, f in site_table(
            validate, flags_for(health, "L2", "high"), truths[reference]["ids"], sites
        )
    ]

    report["avant__grille_publiee_643_in_sample"] = in_sample_mirror(health, tasks, adjust, sites)
    report["apres__grille_hors_echantillon_522"] = grid(
        health, validate, truths, sites, n_boot=args.bootstrap, seed=args.seed
    )
    report["controle_de_multiplicite"] = {
        truth_name: holm_bonferroni(
            {
                key: block[truth_name]["p_retenue"]
                for key, block in report["apres__grille_hors_echantillon_522"].items()
                if block[truth_name]["p_retenue"] is not None
            }
        )
        for truth_name in truths
    }
    report["robustesse_leave_one_site_out"] = {
        "configuration": "L1|medium",
        "verite": reference,
        "lignes": leave_one_site_out(
            health, validate, truths[reference]["ids"], sites, "L1", "medium"
        ),
    }
    report["par_annotateur"] = per_annotator(
        health,
        tasks,
        validate,
        sites,
        [("L1", "high"), ("L1", "medium"), ("L1+L2+L3", "medium")],
    )
    report["denominateur_browseruse"] = browseruse_denominator()

    # --- ce que l'on peut encore affirmer ------------------------------------------------
    ref_grid = report["apres__grille_hors_echantillon_522"]
    l1_high = ref_grid["L1|high"][reference]
    l1_med = ref_grid["L1|medium"][reference]
    l2_high = ref_grid["L2|high"][reference]
    full_med = ref_grid["L1+L2+L3|medium"][reference]
    report["conclusions"] = {
        "L1_high": {
            "verdict": "non validable hors échantillon",
            "detail": (
                f"{l1_high['n_signalees']} tâches signalées sur "
                f"{l1_high['n_univers']}, {l1_high['vrais_positifs']} vrai positif, "
                f"rappel {l1_high['rappel']}. Le test n'est pas sans puissance : un score "
                "parfait de 2/2 aurait donné p = 0,0085. C'est le détecteur qui est muet, "
                "pas le test qui est aveugle."
            ),
        },
        "L1_medium": {
            "verdict": "tient hors échantillon, y compris après correction du groupement par site",
            "detail": (
                f"précision {l1_med['precision']} contre {l1_med['precision_au_hasard']} "
                f"au hasard, lift {l1_med['lift']}, p binomial {l1_med['p_binomial']:.3g}, "
                f"p stratifiée intra-site {l1_med['p_intra_site']:.3g}."
            ),
        },
        "L2_high": {
            "verdict": "résultat nul une fois le groupement par site corrigé",
            "detail": (
                f"p binomial {l2_high['p_binomial']:.3g} (i.i.d.) mais les "
                f"{l2_high['n_signalees']} tâches signalées sont "
                f"{l2_high['test_site']['n_sites_signales'] if l2_high['test_site'] else '?'} "
                "sites entiers : test de permutation au niveau site "
                f"p = {l2_high['p_retenue']:.3g}."
            ),
        },
        "campagne_complete_medium": {
            "verdict": "significative mais de faible lift",
            "detail": (
                f"{full_med['n_signalees']} tâches signalées sur {full_med['n_univers']} "
                f"({full_med['taux_de_signalement']:.0%}), rappel {full_med['rappel']}, "
                f"lift {full_med['lift']}, p retenue {full_med['p_retenue']:.3g}."
            ),
        },
    }
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--bootstrap", type=int, default=BOOTSTRAP_DEFAULT)
    parser.add_argument("--seed", type=int, default=SEED_DEFAULT)
    parser.add_argument("--out", default=str(OUT_JSON))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(args)

    if not args.quiet:
        s = report["scission"]
        print("=== SCISSION ===")
        print(
            f"corpus {s['n_corpus']} = jeu d'ajustement {s['n_jeu_d_ajustement']} "
            f"(patch-set {s['source_d_ajustement']}) + jeu de validation "
            f"{s['n_jeu_de_validation']} — disjoints"
        )
        print("\n=== VÉRITÉS DE VALIDATION (aucune ne fait intervenir Magnitude) ===")
        for name, t in report["verites_de_validation"].items():
            print(f"  {name:20s} n={t['n']:3d}  prévalence={t['prevalence']:.4f}  {t['description']}")

        print("\n=== AVANT — la grille publiée, sur les 643, contre signalee_1 ===")
        for key, row in report["avant__grille_publiee_643_in_sample"].items():
            print(
                f"  {key:18s} flags {row['n_signalees']:3d}  P {row['precision_publiee']:.4f}  "
                f"P_hasard {row['precision_au_hasard']:.4f}  lift {row['lift']:.2f}  "
                f"VP in-sample {row['vrais_positifs_dans_le_jeu_d_ajustement']}/"
                f"{row['vrais_positifs']} "
                f"({row['part_in_sample_des_vrais_positifs']:.1%})"
            )

        ref = report["verite_de_reference"]
        print_grid(
            f"APRÈS — hors échantillon, {report['scission']['n_jeu_de_validation']} tâches, "
            f"vérité « {ref} »",
            report["apres__grille_hors_echantillon_522"],
            ref,
        )
        for other in report["verites_de_validation"]:
            if other == ref:
                continue
            print_grid(
                f"HORS ÉCHANTILLON — vérité « {other} »",
                report["apres__grille_hors_echantillon_522"],
                other,
            )

        print("\n=== CONTRÔLE DE MULTIPLICITÉ (Holm, α = 5 %, vérité de référence) ===")
        holm = report["controle_de_multiplicite"][report["verite_de_reference"]]
        for row in holm["lignes"]:
            mark = "REJETÉE H0" if row["rejetee"] else "—"
            print(
                f"  {row['rang']:2d}. {row['configuration']:18s} p={row['p']:<10.6g} "
                f"seuil={row['seuil_holm']:<10.6g} {mark}"
            )
        print(f"  survivantes : {holm['survivantes'] or 'aucune'}")

        print("\n=== ROBUSTESSE — L1/MEDIUM, retrait d'un site à la fois ===")
        for row in report["robustesse_leave_one_site_out"]["lignes"]:
            print(
                f"  sans {row['site_retire']:22s} n={row['n_univers']:3d} flags "
                f"{row['n_signalees']:3d} VP {row['vrais_positifs']:2d} P {row['precision']:.3f} "
                f"lift {row['lift']:.2f} p_binom {row['p_binomial']:.3g} "
                f"p_intra_site {row['p_intra_site']:.3g}"
            )

        print("\n=== L1 CONTRE CHAQUE ANNOTATEUR, PRIS SÉPARÉMENT (hors échantillon) ===")
        for source, block in report["par_annotateur"].items():
            lineage = " [même lignée que Magnitude]" if block["meme_lignee_que_magnitude"] else ""
            print(f"  {source}{lineage} : n={block['n_verite']} prévalence={block['prevalence']:.4f}")
            for key in ("L1|high", "L1|medium", "L1+L2+L3|medium"):
                r = block[key]
                print(
                    f"      {key:16s} flags {r['n_signalees']:3d} VP {r['vrais_positifs']:2d} "
                    f"P {_fmt(r['precision']):>6s} lift {_fmt(r['lift'], '.2f'):>6s} "
                    f"p_binom {_fmt(r['p_binomial'], '.3g'):>9s} "
                    f"p_retenue {_fmt(r['p_retenue'], '.3g'):>9s}"
                )

        b = report["denominateur_browseruse"]
        print("\n=== DÉNOMINATEUR browser-use ===")
        for key in ("publiee", "corrigee"):
            r = b[key]
            print(
                f"  {r['lecture']:28s} n={r['n_taches']:3d}  naissance "
                f"{r['signalees_a_sa_naissance_high']:2d} "
                f"({r['signalees_a_sa_naissance_high_pct']:.1f} %)  15/08/2026 "
                f"{r['signalees_au_15_08_2026_high']:2d} "
                f"({r['signalees_au_15_08_2026_high_pct']:.1f} %)"
            )
        print(
            f"  {b['n_contamines']} des {b['publiee']['signalees_a_sa_naissance_high']} constats "
            "de naissance portent sur une tâche que browser-use avait déjà retirée : "
            f"{', '.join(b['constats_de_naissance_portant_sur_une_tache_deja_retiree'])}"
        )
        print(f"  ligne à publier : {b['ligne_a_publier']}")

        print("\n=== CE QUE L'ON PEUT ENCORE AFFIRMER ===")
        for key, c in report["conclusions"].items():
            print(f"  {key:26s} {c['verdict']}\n      {c['detail']}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.quiet:
        print(f"\nrapport écrit : {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
