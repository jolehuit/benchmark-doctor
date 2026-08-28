#!/usr/bin/env python3
"""Campagne complète de `benchmark-doctor` sur WebVoyager, et sa validation.

Point d'entrée reproductible de la campagne, en trois phases exécutables séparément :

1. ``audit`` : une passe L1 + L2 + L3 sur les 643 tâches, à date de référence fixée,
   produisant la carte de santé (JSON + HTML) et le journal brut des constats ;
2. ``validate`` : précision, rappel et F1 contre la base de verdicts réconciliée des six
   annotateurs indépendants, globalement et par catégorie, avec l'ablation par couche ;
3. ``export`` : le sous-ensemble WebVoyager-Verified v0.1 et son README.

Quatre décisions de méthode portent le reste. Les trois couches sont exécutées une seule
fois, et l'ablation « L1 seul / L1+L2 / L1+L2+L3 » se fait ensuite en filtrant les constats
par couche : ré-exécuter la campagne pour chaque niveau introduirait une variation de
mesure, le web changeant entre deux passes, là où l'on veut mesurer une variation de
méthode. C'est pourquoi `TaskVerdict` ne stocke aucun verdict binaire.

La validation porte sur les constats, jamais sur le score publié. Le score de stabilité de
la carte de santé intègre un a priori tiré de `data/ground_truth.json`, la vérité terrain
elle-même : le valider contre cette base mesurerait la capacité de l'outil à recopier ce
qu'on lui a donné. Précision et rappel sont calculés sur les constats des détecteurs, et
les métriques d'ordonnancement sur le score détecteurs seuls (`prior` vide).

Il n'y a pas une vérité terrain mais cinq, « tâche défectueuse » n'ayant pas de définition
unique : les six annotateurs signalent 169 tâches, dont 68 seulement font l'unanimité et 78
sont supprimées par au moins un. Publier un seul couple (P, R) choisirait silencieusement
une définition ; les cinq sont mesurées côte à côte, et leur écart est un résultat.

Le seuil de décision est explicite et varié : la couche L3 (ambiguïté) n'émet que des
constats MEDIUM par construction, une tâche ambiguë s'exécute, et mesurer son apport au
seuil HIGH donnerait zéro. Chaque tableau est produit aux deux seuils, HIGH et MEDIUM.

Usage :

    python3 run_all.py                      # les trois phases
    python3 run_all.py --phase audit --l3-backend llm
    python3 run_all.py --phase validate     # relit runs/health_20260815_findings.json
    python3 run_all.py --phase export

Toutes les sorties sont écrites dans ``runs/`` et ``exports/``.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from benchmark_doctor import __version__  # noqa: E402
from benchmark_doctor.models import (  # noqa: E402
    BenchmarkHealth,
    Channel,
    Finding,
    Severity,
    Task,
    TaskVerdict,
)

# Constantes de la campagne

#: Date de référence de toutes les mesures publiées. Elle est **gelée** et non déduite de
#: l'horloge : les détecteurs temporels en dépendent, et un chiffre de mémoire dont la
#: valeur change selon le jour où l'on relance le script n'est pas un chiffre.
REFERENCE_DATE = _dt.date(2026, 8, 15)

CORPUS = ROOT / "data" / "raw" / "webvoyager_original.jsonl"

#: Le chemin du corpus tel qu'il est publié. `CORPUS` sert à ouvrir le fichier et à en
#: calculer l'empreinte, ce qui exige un chemin absolu ; l'étiquette écrite dans la carte
#: et dans le journal des constats est relative à la racine, pour qu'un artefact versionné
#: ne nomme pas le poste de travail qui l'a produit.
CORPUS_LABEL = str(CORPUS.relative_to(ROOT))

GROUND_TRUTH = ROOT / "data" / "ground_truth.json"
RUNS = ROOT / "runs"
EXPORTS = ROOT / "exports"

CARD_JSON = RUNS / "health_20260815.json"
CARD_HTML = RUNS / "health_20260815.html"
FINDINGS_JSON = RUNS / "health_20260815_findings.json"
VALIDATION_JSON = RUNS / "validation_ablation_20260815.json"

#: Les six annotateurs retenus comme indépendants (cf. rapport de réconciliation) :
#: Skyvern compte deux instantanés mais un seul annotateur, et Emergence est écarté de
#: l'accord parce que ses exclusions sont confondues avec un rééchantillonnage.
INDEPENDENT_SOURCES = (
    "browseruse",
    "convergence",
    "magnitude",
    "fara",
    "alumnium",
    "skyvern_2026",
)

LAYER_SETS: dict[str, tuple[str, ...]] = {
    "L1": ("L1",),
    "L2": ("L2",),
    "L3": ("L3",),
    "L1+L2": ("L1", "L2"),
    "L1+L3": ("L1", "L3"),
    "L1+L2+L3": ("L1", "L2", "L3"),
}

THRESHOLDS = {"high": Severity.HIGH, "medium": Severity.MEDIUM}


# Phase 1 — l'audit


def _audit_namespace(args: argparse.Namespace) -> argparse.Namespace:
    """Fabrique l'espace de noms attendu par `cli._run_layers`.

    On réutilise l'orchestration de la ligne de commande plutôt que de la réécrire : la
    campagne publiée doit être exactement celle que produit `bdoctor audit`, sinon le
    lecteur ne peut pas la rejouer.
    """
    return argparse.Namespace(
        corpus=str(CORPUS),
        format="webvoyager",
        benchmark="webvoyager",
        layers=args.layers,
        channel=args.channel,
        recorded=args.recorded,
        l2_content=True,
        l3_backend=args.l3_backend,
        l3_solvability=not args.no_solvability,
        limit=args.limit,
        today=args.today,
        no_prior=False,
        prior=None,
    )


def phase_audit(args: argparse.Namespace) -> dict[str, Any]:
    """Exécute la campagne multi-couches et écrit la carte de santé."""
    from benchmark_doctor.cli import _run_layers
    from benchmark_doctor.report import build_card, write_card
    from benchmark_doctor.scoring import DEFAULT_MODEL, PractitionerPrior, score_health

    today = _dt.date.fromisoformat(args.today)
    ns = _audit_namespace(args)

    started = time.perf_counter()
    health, cost, notes, executed, protocol = _run_layers(ns, today)
    prior = PractitionerPrior.load(None)
    assessments = score_health(health, model=DEFAULT_MODEL, prior=prior, today=today)

    card = build_card(
        health,
        model=DEFAULT_MODEL,
        prior=prior,
        assessments=assessments,
        today=today,
        layers=executed or ["(aucune)"],
        cost=cost,
        notes=notes
        + [
            "Campagne produite par run_all.py (phase « audit ») : une seule passe de "
            "mesure, dont l'ablation par couche est ensuite dérivée par filtrage des "
            "constats. Le score publié intègre l'a priori des praticiens ; la validation "
            "du chapitre 4 n'utilise, elle, que les constats des détecteurs.",
        ],
        protocol=protocol,
    )
    # `_run_layers` étiquette le bulletin avec le chemin qu'on lui a passé, et `build_card`
    # a besoin de ce chemin absolu pour calculer l'empreinte du corpus. Une fois l'empreinte
    # prise, l'étiquette repasse en relatif dans les deux artefacts écrits ci-dessous.
    card.corpus_path = CORPUS_LABEL
    health.source = CORPUS_LABEL

    RUNS.mkdir(parents=True, exist_ok=True)
    write_card(card, json_path=str(CARD_JSON), html_path=str(CARD_HTML))

    # Journal brut des constats : c'est LUI qui rend la phase `validate` rejouable sans
    # réseau ni clé d'API. La carte de santé ne conserve que le risque agrégé par
    # catégorie, ce qui suffit à lire un rapport mais pas à refaire une ablation.
    raw = health.to_dict()
    raw["meta"] = {
        "generated_by": f"run_all.py (benchmark-doctor {__version__})",
        "reference_date": today.isoformat(),
        "corpus": CORPUS_LABEL,
        "layers_executed": executed,
        "protocol": protocol,
        "cost": cost.to_dict(len(health)),
        "wall_seconds": round(time.perf_counter() - started, 2),
    }
    FINDINGS_JSON.write_text(
        json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    summary = card.summary()
    print()
    print(f"carte de santé      : {CARD_JSON}")
    print(f"rapport HTML        : {CARD_HTML}")
    print(f"journal des constats: {FINDINGS_JSON}")
    print(
        f"stabilité moyenne   : {summary['mean_stability']:.3f} "
        f"(détecteurs seuls {summary['mean_stability_detector_only']:.3f})"
    )
    print(
        "notes               : "
        + "  ".join(f"{g} {summary['grades'][g]}" for g in ("A", "B", "C", "D"))
    )
    print(
        f"coût réel           : {cost.total_usd:.5f} $ "
        f"({cost.total_calls} appels, {cost.total_seconds:.1f} s)"
    )
    return raw


# Phase 2 — la validation


def load_findings(path: Path = FINDINGS_JSON) -> BenchmarkHealth:
    """Relit le journal brut des constats en objets du domaine."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    health = BenchmarkHealth(
        benchmark=payload["summary"]["benchmark"],
        generated_at=_dt.date.fromisoformat(payload["summary"]["generated_at"]),
        source=payload["summary"].get("source"),
        tool_version=payload["summary"].get("tool_version", __version__),
    )
    for row in payload["tasks"]:
        task = Task(
            task_id=row["task_id"],
            question=row["question"],
            site=row.get("site"),
            start_url=row.get("start_url"),
            benchmark=row.get("benchmark", "webvoyager"),
        )
        verdict = TaskVerdict(
            task=task,
            evaluated_at=_dt.date.fromisoformat(row["evaluated_at"]),
            channels=[Channel(c) for c in row.get("channels", ["static"])],
        )
        for f in row["findings"]:
            verdict.findings.append(Finding.from_dict(f))
        health.verdicts.append(verdict)
    return health


def filter_health(health: BenchmarkHealth, layers: Sequence[str]) -> BenchmarkHealth:
    """Copie du bulletin ne conservant que les constats des couches demandées."""
    keep = set(layers)
    out = BenchmarkHealth(
        benchmark=health.benchmark,
        generated_at=health.generated_at,
        source=health.source,
        tool_version=health.tool_version,
    )
    for v in health.verdicts:
        clone = TaskVerdict(task=v.task, evaluated_at=v.evaluated_at, channels=[Channel.STATIC])
        clone.findings = [f for f in v.findings if f.layer in keep]
        for f in clone.findings:
            if f.channel not in clone.channels:
                clone.channels.append(f.channel)
        out.verdicts.append(clone)
    return out


# ---- définitions de la vérité terrain ---------------------------------------------------


def build_ground_truths(gt: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Cinq lectures défendables de « cette tâche est défectueuse ».

    Aucune n'est la bonne : elles bornent le problème. La plus permissive (`signalee_1`)
    inclut les patches de précaution — Magnitude re-date des tâches encore valides ; la
    plus stricte (`unanime_6`) ne retient que ce sur quoi six équipes indépendantes se
    sont accordées sans se concerter.
    """
    tasks = gt["taches"]
    defs: dict[str, dict[str, Any]] = {}

    def collect(name: str, predicate, description: str) -> None:
        ids = {t["id"] for t in tasks if predicate(t)}
        defs[name] = {"ids": ids, "n": len(ids), "description": description}

    collect(
        "signalee_1",
        lambda t: len(t["accord"]["signalee_par"]) >= 1,
        "signalée (réécrite ou supprimée) par au moins 1 des 6 annotateurs indépendants",
    )
    collect(
        "signalee_3",
        lambda t: len(t["accord"]["signalee_par"]) >= 3,
        "signalée par au moins 3 des 6 annotateurs (majorité)",
    )
    collect(
        "unanime_6",
        lambda t: len(t["accord"]["signalee_par"]) == 6,
        "signalée par les 6 annotateurs indépendants (accord parfait)",
    )
    collect(
        "supprimee_1",
        lambda t: any(
            v["action"] == "remove" and v["source"] in INDEPENDENT_SOURCES
            for v in t["verdicts"]
        ),
        "supprimée du corpus par au moins 1 des 6 annotateurs",
    )
    collect(
        "magnitude",
        lambda t: any(
            v["source"] == "magnitude" and v["action"] in ("remove", "modify")
            for v in t["verdicts"]
        ),
        "patchée par Magnitude au 06/07/2025 (la ground truth historique du 15/08)",
    )
    return defs


def prf(predicted: set[str], truth: set[str]) -> dict[str, Any]:
    """Précision, rappel, F1 et matrice de confusion d'un ensemble de tâches signalées."""
    tp = len(predicted & truth)
    fp = len(predicted - truth)
    fn = len(truth - predicted)
    p = tp / len(predicted) if predicted else 0.0
    r = tp / len(truth) if truth else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {
        "n_flagged": len(predicted),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f1, 4),
    }


# ---- métriques d'ordonnancement (sans seuil) ---------------------------------------------


def roc_auc(scores: Sequence[float], labels: Sequence[int]) -> float:
    """AUC par la statistique de Mann-Whitney (moyenne des rangs, ex æquo à 0,5).

    Implémentée à la main : `run_all.py` doit rester exécutable dans un environnement
    où seule la bibliothèque standard est garantie, comme la couche L1 du paquet.
    """
    pairs = sorted(zip(scores, labels))
    n = len(pairs)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        mean_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = mean_rank
        i = j + 1
    n_pos = sum(l for _, l in pairs)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    sum_pos = sum(rank for rank, (_, label) in zip(ranks, pairs) if label == 1)
    return (sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def average_precision(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Précision moyenne (aire sous la courbe précision/rappel), ordre décroissant."""
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    n_pos = sum(labels)
    if n_pos == 0:
        return float("nan")
    tp = 0
    total = 0.0
    for rank, idx in enumerate(order, start=1):
        if labels[idx] == 1:
            tp += 1
            total += tp / rank
    return total / n_pos


# ---- la phase proprement dite ------------------------------------------------------------


def flag_set(health: BenchmarkHealth, threshold: Severity) -> set[str]:
    return {v.task.task_id for v in health.verdicts if v.is_flagged(threshold)}


def detector_scores(health: BenchmarkHealth, today: _dt.date) -> dict[str, float]:
    """Score de stabilité **détecteurs seuls** de chaque tâche (a priori vide)."""
    from benchmark_doctor.scoring import DEFAULT_MODEL, PractitionerPrior, score_health

    assessments = score_health(
        health, model=DEFAULT_MODEL, prior=PractitionerPrior.empty(), today=today
    )
    return {a.task_id: a.score_detector for a in assessments}


def phase_validate(args: argparse.Namespace) -> dict[str, Any]:
    """Précision / rappel / F1 contre la base réconciliée, avec ablation par couche."""
    today = _dt.date.fromisoformat(args.today)
    health = load_findings()
    gt = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    truths = build_ground_truths(gt)
    all_ids = [v.task.task_id for v in health.verdicts]

    # Étiquettes de taxonomie : disponibles pour les 121 tâches patchées par Magnitude,
    # relues une à une (rapport de réconciliation). C'est la seule source d'étiquettes
    # de CATÉGORIE ; les autres annotateurs ne motivent pas leurs retraits.
    gt_category = {
        t["id"]: t["taxonomie"]["categorie"]
        for t in gt["taches"]
        if t.get("taxonomie")
    }

    report: dict[str, Any] = {
        "meta": {
            "generated_by": f"run_all.py --phase validate (benchmark-doctor {__version__})",
            "reference_date": today.isoformat(),
            "findings_source": str(FINDINGS_JSON.relative_to(ROOT)),
            "ground_truth": str(GROUND_TRUTH.relative_to(ROOT)),
            "n_tasks": len(all_ids),
            "avertissement": (
                "Les mesures portent sur les CONSTATS des détecteurs, jamais sur le score "
                "publié : celui-ci intègre un a priori tiré de la même base de vérité "
                "terrain, et le valider contre elle serait circulaire."
            ),
        },
        "ground_truths": {
            k: {"n": v["n"], "description": v["description"]} for k, v in truths.items()
        },
        "ablation": {},
        "par_categorie": {},
        "ordonnancement": {},
        "diagnostic": {},
    }

    # ---- tableau d'ablation ------------------------------------------------------------
    for layer_name, layers in LAYER_SETS.items():
        sub = filter_health(health, layers)
        entry: dict[str, Any] = {
            "layers": list(layers),
            "n_findings": sum(len(v.findings) for v in sub.verdicts),
            "n_tasks_with_finding": sum(1 for v in sub.verdicts if v.findings),
            "seuils": {},
        }
        for tname, threshold in THRESHOLDS.items():
            flagged = flag_set(sub, threshold)
            entry["seuils"][tname] = {
                "n_flagged": len(flagged),
                "flag_rate": round(len(flagged) / len(all_ids), 4),
                "contre": {
                    gt_name: prf(flagged, truth["ids"]) for gt_name, truth in truths.items()
                },
            }
        report["ablation"][layer_name] = entry

    # ---- rappel par catégorie de la taxonomie -------------------------------------------
    # Deux lectures : (a) le rappel brut — la tâche est-elle signalée, quelle que soit la
    # catégorie invoquée ; (b) le rappel « avec la bonne raison » — la tâche est-elle
    # signalée PAR un constat de la même catégorie que l'étiquette. (b) est la mesure
    # exigeante : un outil qui signale une tâche de dérive de contenu parce qu'elle
    # contient une date a raison par accident.
    by_cat_truth: dict[str, set[str]] = defaultdict(set)
    for task_id, code in gt_category.items():
        by_cat_truth[code].add(task_id)

    for layer_name, layers in LAYER_SETS.items():
        sub = filter_health(health, layers)
        by_id = {v.task.task_id: v for v in sub.verdicts}
        block: dict[str, Any] = {}
        for tname, threshold in THRESHOLDS.items():
            rows: dict[str, Any] = {}
            for code in sorted(by_cat_truth):
                ids = by_cat_truth[code]
                hit_any = 0
                hit_same = 0
                for task_id in ids:
                    v = by_id[task_id]
                    fs = [f for f in v.findings if f.severity >= threshold]
                    if fs:
                        hit_any += 1
                    if any(f.category.code == code for f in fs):
                        hit_same += 1
                rows[code] = {
                    "n_verite": len(ids),
                    "rappel_brut": round(hit_any / len(ids), 4),
                    "n_rappel_brut": hit_any,
                    "rappel_bonne_categorie": round(hit_same / len(ids), 4),
                    "n_rappel_bonne_categorie": hit_same,
                }
            block[tname] = rows
        report["par_categorie"][layer_name] = block

    # Précision de la catégorie annoncée, sur les seules tâches étiquetées : quand l'outil
    # invoque Tk sur une tâche dont on connaît la vraie catégorie, a-t-il raison ?
    sub_all = filter_health(health, LAYER_SETS["L1+L2+L3"])
    by_id_all = {v.task.task_id: v for v in sub_all.verdicts}
    confusion: dict[str, Counter] = defaultdict(Counter)
    for task_id, code in gt_category.items():
        cats = {f.category.code for f in by_id_all[task_id].findings if f.severity >= Severity.MEDIUM}
        if not cats:
            confusion[code]["(aucun constat)"] += 1
        for c in sorted(cats):
            confusion[code][c] += 1
    report["par_categorie"]["confusion_categorie_L1+L2+L3_medium"] = {
        "_note": (
            "Ligne = catégorie de vérité (relecture manuelle des raisons Magnitude), "
            "colonne = catégorie invoquée par un constat de l'outil. Une tâche compte "
            "dans plusieurs colonnes si l'outil invoque plusieurs catégories : les lignes "
            "ne somment donc pas à l'effectif. À lire comme « quand la vérité est Tk, que "
            "dit l'outil ? », jamais comme une matrice de classification à une étiquette."
        ),
        **{code: dict(counter) for code, counter in sorted(confusion.items())},
    }

    # ---- apport marginal de chaque détecteur ---------------------------------------------
    # Le tableau d'ablation par couche masque une asymétrie : la couche L2 contient deux
    # détecteurs de nature très différente — une sonde d'accès mesurée par SITE et propagée
    # à ses tâches, et une vérification de contenu mesurée PAR TÂCHE. Les agréger fait
    # disparaître la seule mesure fine de la couche. On mesure donc chaque détecteur seul,
    # puis son apport quand on le retire de la campagne complète.
    detectors = sorted({f.detector for v in health.verdicts for f in v.findings})
    per_detector: dict[str, Any] = {}
    truth_ref = truths["signalee_1"]["ids"]
    full_ids_by_threshold = {}
    for tname, threshold in THRESHOLDS.items():
        full_ids_by_threshold[tname] = {
            v.task.task_id for v in health.verdicts if v.is_flagged(threshold)
        }
    for det in detectors:
        entry: dict[str, Any] = {"n_findings": 0, "seuils": {}}
        entry["n_findings"] = sum(
            1 for v in health.verdicts for f in v.findings if f.detector == det
        )
        for tname, threshold in THRESHOLDS.items():
            alone = {
                v.task.task_id
                for v in health.verdicts
                if any(f.detector == det and f.severity >= threshold for f in v.findings)
            }
            without = {
                v.task.task_id
                for v in health.verdicts
                if any(f.detector != det and f.severity >= threshold for f in v.findings)
            }
            full = full_ids_by_threshold[tname]
            entry["seuils"][tname] = {
                "seul": prf(alone, truth_ref),
                "campagne_sans_lui": prf(without, truth_ref),
                "taches_qu_il_est_seul_a_signaler": len(full - without),
                "vrais_positifs_exclusifs": len((full - without) & truth_ref),
            }
        per_detector[det] = entry
    report["par_detecteur"] = {
        "verite_de_reference": "signalee_1",
        "detecteurs": per_detector,
    }

    # ---- métriques d'ordonnancement ------------------------------------------------------
    for layer_name, layers in LAYER_SETS.items():
        sub = filter_health(health, layers)
        scores = detector_scores(sub, today)
        # Le risque est 1 − stabilité : plus il est grand, plus la tâche devrait être
        # signalée. AUC et précision moyenne sont indépendantes du seuil et donc
        # comparables entre couches sans arbitrage de politique.
        risk = [1.0 - scores[i] for i in all_ids]
        block = {}
        for gt_name, truth in truths.items():
            labels = [1 if i in truth["ids"] else 0 for i in all_ids]
            block[gt_name] = {
                "auc": round(roc_auc(risk, labels), 4),
                "average_precision": round(average_precision(risk, labels), 4),
                "base_rate": round(sum(labels) / len(labels), 4),
            }
        report["ordonnancement"][layer_name] = block

    # ---- diagnostic : d'où viennent les faux positifs ? -----------------------------------
    truth_any = truths["signalee_1"]["ids"]
    full = filter_health(health, LAYER_SETS["L1+L2+L3"])
    flagged_high = flag_set(full, Severity.HIGH)
    fp_ids = flagged_high - truth_any
    fp_detectors = Counter()
    fp_sites = Counter()
    # Le parcours est trié : `most_common()` départage les ex æquo par ordre d'insertion,
    # et un ensemble ne s'itère pas deux fois dans le même ordre d'un processus à l'autre.
    # Sans ce tri, deux exécutions du même script écrivent des octets différents.
    for task_id in sorted(fp_ids):
        v = by_id_all[task_id]
        for f in v.findings:
            if f.severity >= Severity.HIGH:
                fp_detectors[f"{f.detector}:{f.signal}"] += 1
        fp_sites[v.task.site or "?"] += 1
    fn_ids = truth_any - flagged_high
    fn_sites = Counter()
    for task_id in sorted(fn_ids):
        fn_sites[by_id_all[task_id].task.site or "?"] += 1

    # Effet de la granularité de L2 : une sonde par site, propagée à toutes ses tâches.
    l2_sites = Counter()
    for v in health.verdicts:
        for f in v.findings:
            if f.layer == "L2" and f.severity >= Severity.HIGH:
                l2_sites[v.task.site or "?"] += 1
                break
    report["diagnostic"] = {
        "faux_positifs_L1+L2+L3_high_vs_signalee_1": {
            "n": len(fp_ids),
            "par_detecteur_signal": dict(fp_detectors.most_common()),
            "par_site": dict(fp_sites.most_common()),
        },
        "faux_negatifs_L1+L2+L3_high_vs_signalee_1": {
            "n": len(fn_ids),
            "par_site": dict(fn_sites.most_common()),
        },
        "granularite_L2": {
            "note": (
                "La sonde d'accès est faite sur l'URL de départ du site puis propagée à "
                "toutes ses tâches : L2 ne peut pas distinguer deux tâches du même site. "
                "Son apport en rappel se paie donc mécaniquement en précision."
            ),
            "taches_signalees_par_site": dict(l2_sites.most_common()),
        },
    }

    VALIDATION_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    _print_validation(report)
    print(f"\nrapport de validation : {VALIDATION_JSON}")
    return report


def _print_validation(report: Mapping[str, Any]) -> None:
    print("\n=== VÉRITÉS TERRAIN ===")
    for name, meta in report["ground_truths"].items():
        print(f"  {name:<13} n={meta['n']:>3}  {meta['description']}")

    for tname in ("high", "medium"):
        print(f"\n=== ABLATION — seuil {tname.upper()} ===")
        header = f"{'couche':<10} {'flags':>6}"
        for gt_name in report["ground_truths"]:
            header += f" | {gt_name:^20}"
        print(header)
        print(f"{'':<10} {'':>6}" + " | " + " | ".join(f"{'P     R     F1':^20}" for _ in report["ground_truths"]))
        for layer_name, entry in report["ablation"].items():
            block = entry["seuils"][tname]
            line = f"{layer_name:<10} {block['n_flagged']:>6}"
            for gt_name in report["ground_truths"]:
                m = block["contre"][gt_name]
                line += f" | {m['precision']:>5.3f} {m['recall']:>5.3f} {m['f1']:>5.3f}  "
            print(line)

    for tname in ("high", "medium"):
        print(
            f"\n=== RAPPEL PAR CATÉGORIE (étiquettes Magnitude relues, n=121) — seuil "
            f"{tname.upper()} ===\n"
            "    format « signalée / vérité (dont par un constat de LA BONNE catégorie) »"
        )
        codes = sorted(report["par_categorie"]["L1"][tname])
        print(f"{'couche':<10}" + "".join(f"{c:>17}" for c in codes))
        for layer_name in LAYER_SETS:
            rows = report["par_categorie"][layer_name][tname]
            line = f"{layer_name:<10}"
            for c in codes:
                r = rows[c]
                line += (
                    f"{r['n_rappel_brut']:>4}/{r['n_verite']:<3}"
                    f"({r['n_rappel_bonne_categorie']:>2}) "
                )
            print(line)

    print("\n=== APPORT MARGINAL DE CHAQUE DÉTECTEUR (vérité : signalee_1, seuil MEDIUM) ===")
    print(f"{'détecteur':<16}{'constats':>9}{'seul: P':>9}{'R':>7}{'F1':>7}"
          f"{'exclusif':>10}{'dont VP':>9}")
    for det, entry in report["par_detecteur"]["detecteurs"].items():
        m = entry["seuils"]["medium"]
        print(
            f"{det:<16}{entry['n_findings']:>9}{m['seul']['precision']:>9.3f}"
            f"{m['seul']['recall']:>7.3f}{m['seul']['f1']:>7.3f}"
            f"{m['taches_qu_il_est_seul_a_signaler']:>10}{m['vrais_positifs_exclusifs']:>9}"
        )

    print("\n=== ORDONNANCEMENT (AUC du risque détecteurs seuls) ===")
    print(f"{'couche':<10}" + "".join(f"{g:>16}" for g in report["ground_truths"]))
    for layer_name, block in report["ordonnancement"].items():
        print(f"{layer_name:<10}" + "".join(f"{block[g]['auc']:>16.3f}" for g in report["ground_truths"]))


# Phase 3 — l'export WebVoyager-Verified v0.1

#: Ordre de préférence des annotateurs pour choisir le patch canonique d'une tâche
#: réécrite : le plus récent d'abord. Justification : 87 des 87 tâches réécrites par au
#: moins deux annotateurs reçoivent des énoncés textuellement différents, et 76 d'entre
#: elles divergent jusque sur l'année cible. Aucune règle de vote ne peut réconcilier des
#: dates différentes ; la seule qui ait un sens pour un défaut temporel est la fraîcheur.
PATCH_PREFERENCE = ("skyvern_2026", "alumnium", "fara", "magnitude", "convergence", "browseruse")


def _past_date_in(text: str, today: _dt.date) -> list[str]:
    """Dates certainement révolues présentes dans un énoncé (extracteur L1 réutilisé).

    On ne compte que les mentions dont le millésime est explicite : « December 25-26 »
    n'est pas révolu (le prochain 25 décembre existe), seule sa réponse de référence
    l'est. Cette convention est la même que celle du détecteur temporel, sans quoi le
    nombre de patches périmés dépendrait de la définition retenue plutôt que du monde.
    """
    from benchmark_doctor.detectors.l1_temporal import extract_date_mentions

    return [m.text for m in extract_date_mentions(text) if m.is_past(today)]


def phase_export(args: argparse.Namespace) -> dict[str, Any]:
    """Écrit `exports/webvoyager_verified_v0.1.jsonl` et son README."""
    today = _dt.date.fromisoformat(args.today)
    gt = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    card = json.loads(CARD_JSON.read_text(encoding="utf-8"))
    scores = {t["task_id"]: t for t in card["tasks"]}

    EXPORTS.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    counts = Counter()

    for t in gt["taches"]:
        acc = t["accord"]
        verdicts = {v["source"]: v for v in t["verdicts"] if v["source"] in INDEPENDENT_SOURCES}
        n_flag = len(acc["signalee_par"])
        card_row = scores.get(t["id"], {})

        # -- statut d'inclusion ------------------------------------------------------------
        if acc["consensus"] == "conflit" or acc["desaccord_exclusion"]:
            statut = "conteste"
        elif acc["consensus"] == "remove":
            statut = "retirer"
        elif acc["consensus"] == "modify":
            statut = "corriger"
        elif n_flag == 0:
            statut = "noyau"
        else:
            statut = "surveiller"
        counts[statut] += 1

        # -- patch canonique proposé --------------------------------------------------------
        variants = {
            src: v["nouvelle_question"]
            for src, v in verdicts.items()
            if v.get("nouvelle_question")
        }
        patch = None
        if variants:
            for src in PATCH_PREFERENCE:
                if src in variants:
                    stale = _past_date_in(variants[src], today)
                    patch = {
                        "source": src,
                        "date_source": verdicts[src]["date"],
                        "question": variants[src],
                        "n_variantes_publiees": len(variants),
                        "variantes_divergentes": len(set(variants.values())) > 1,
                        "deja_perime_au": today.isoformat() if stale else None,
                        "dates_passees_restantes": stale or None,
                    }
                    break

        # -- péremption de l'ÉNONCÉ lui-même -------------------------------------------------
        # Le champ `question` conserve l'énoncé d'origine (le patch vit à côté). Un
        # sous-ensemble qui s'appelle « Verified » ne peut pas laisser croire que ces
        # énoncés sont exécutables tels quels : 84 des 563 tâches du sous-ensemble dit
        # exécutable portent une date déjà révolue à la date de mesure, dont 14 dans le
        # noyau. Nous les **marquons** plutôt que de les retirer, pour
        # trois raisons : (a) le fichier est une photographie à 643 lignes, une par tâche,
        # et retirer des lignes casserait l'invariant qui le rend comparable dans le temps ;
        # (b) la péremption est datée — elle sera vraie de plus de tâches dans six mois, et
        # un champ se recalcule là qu'une suppression est irréversible ; (c) c'est un
        # résultat du mémoire, pas un déchet à cacher.
        enonce_stale = _past_date_in(t["question_originale"], today)
        patch_ok = bool(patch) and not patch["deja_perime_au"]
        enonce_perime = {
            "perime_au": today.isoformat() if enonce_stale else None,
            "dates_passees": enonce_stale or None,
            "patch_disponible": bool(patch),
            "patch_lui_meme_perime": bool(patch and patch["deja_perime_au"]),
            # Vrai ssi la tâche peut être lancée sans retouche humaine : soit l'énoncé est
            # sain, soit il existe un patch canonique qui, lui, ne l'est pas.
            "executable_sans_retouche": (not enonce_stale) or patch_ok,
        }

        rows.append(
            {
                "id": t["id"],
                "site": t["site"],
                "url": t["url"],
                "question": t["question_originale"],
                "enonce_perime": enonce_perime,
                "statut": statut,
                "verdict_consensuel": acc["consensus"],
                "accord": {
                    "n_annotateurs": acc["n_annotateurs"],
                    "n_signalants": n_flag,
                    "taux": acc["taux"],
                    "unanime": acc["unanime"],
                    "conteste": acc["desaccord_exclusion"],
                    "signalee_par": acc["signalee_par"],
                    "actions": acc["actions"],
                },
                "stabilite": {
                    "score": card_row.get("stability_score"),
                    "note": card_row.get("grade"),
                    "score_detecteurs_seuls": card_row.get("stability_score_detector_only"),
                    "note_detecteurs_seuls": card_row.get("grade_detector_only"),
                    "categorie_dominante": card_row.get("top_category"),
                    "explication": card_row.get("headline_explanation"),
                    "mesure_le": card_row.get("evaluated_at"),
                    "canal": card_row.get("channels"),
                },
                "taxonomie": (t.get("taxonomie") or {}).get("categorie"),
                "taxonomie_source": (t.get("taxonomie") or {}).get("source_etiquette"),
                "patch_canonique": patch,
                "raisons_publiees": {
                    src: v["raison"] for src, v in verdicts.items() if v.get("raison")
                },
            }
        )

    path = EXPORTS / "webvoyager_verified_v0.1.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    stats = _export_stats(rows, counts, gt, today)
    (EXPORTS / "README.md").write_text(_export_readme(stats), encoding="utf-8")
    (EXPORTS / "webvoyager_verified_v0.1.stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\nexport : {path} ({len(rows)} lignes)")
    for statut, n in counts.most_common():
        print(f"  {statut:<12} {n:>4}")
    print(f"README : {EXPORTS / 'README.md'}")
    return stats


def _export_stats(
    rows: Sequence[Mapping[str, Any]],
    counts: Counter,
    gt: Mapping[str, Any],
    today: _dt.date,
) -> dict[str, Any]:
    grades = Counter(r["stabilite"]["note"] for r in rows)
    core = [r for r in rows if r["statut"] == "noyau"]
    core_grades = Counter(r["stabilite"]["note_detecteurs_seuls"] for r in core)
    patched = [r for r in rows if r["patch_canonique"]]
    rotten = [r for r in patched if r["patch_canonique"]["deja_perime_au"]]
    divergent = [r for r in patched if r["patch_canonique"]["variantes_divergentes"]]
    runnable = [r for r in rows if r["statut"] in ("noyau", "surveiller", "corriger")]

    # Tableau croisé « ce que disent les praticiens » × « ce que mesure l'outil ». C'est la
    # vue qui compte : les deux ne sont d'accord ni sur le nombre ni sur les tâches, et
    # publier l'un sans l'autre donnerait l'illusion d'un verdict unique.
    crosstab: dict[str, dict[str, int]] = {}
    for r in rows:
        crosstab.setdefault(r["statut"], Counter())[r["stabilite"]["note_detecteurs_seuls"]] += 1
    crosstab = {k: dict(sorted(v.items())) for k, v in crosstab.items()}

    rot_by_status = Counter(r["statut"] for r in rotten)

    # -- péremption des énoncés du sous-ensemble exécutable ---------------------------------
    # « 563 tâches exécutables » était faux : 84 d'entre elles portent un énoncé déjà
    # révolu. Le chiffre honnête est double, et il se publie tel quel.
    stale_run = [r for r in runnable if r["enonce_perime"]["perime_au"]]
    stale_run_by_status = Counter(r["statut"] for r in stale_run)
    stale_run_patch_rotten = [r for r in stale_run if r["enonce_perime"]["patch_lui_meme_perime"]]
    stale_run_no_patch = [r for r in stale_run if not r["enonce_perime"]["patch_disponible"]]
    # Deux dénombrements voisins qu'il ne faut pas confondre — l'un compte les patches
    # périmés *parmi les énoncés déjà périmés*, l'autre *dans tout le sous-ensemble*. Ils
    # diffèrent d'une unité (Google Flights--9 : énoncé sain, patch périmé) et cette unité
    # a déjà produit une divergence entre deux rapports.
    run_patch_rotten = [
        r for r in runnable if r["patch_canonique"] and r["patch_canonique"]["deja_perime_au"]
    ]
    clean_run = [r for r in runnable if not r["enonce_perime"]["perime_au"]]
    fixable_run = [r for r in runnable if r["enonce_perime"]["executable_sans_retouche"]]

    return {
        "version": "0.1",
        "date": today.isoformat(),
        "benchmark": "WebVoyager (MinorJerry/WebVoyager @ 0915445, 2024-03-02)",
        "n_taches": len(rows),
        "statuts": dict(counts),
        "notes_avec_a_priori": dict(grades),
        "noyau_notes_detecteurs_seuls": dict(core_grades),
        "croisement_statut_x_note_detecteurs_seuls": crosstab,
        "desaccord_outil_praticiens": {
            "noyau_note_D": crosstab.get("noyau", {}).get("D", 0),
            "noyau_sous_A": sum(
                v for k, v in crosstab.get("noyau", {}).items() if k != "A"
            ),
            "retirer_note_A": crosstab.get("retirer", {}).get("A", 0),
            "lecture": (
                "L'outil et les praticiens ne signalent pas les mêmes tâches. Les tâches "
                "du noyau notées sous A sont, soit des faux positifs de l'outil (sondes "
                "d'accès propagées par site, ambiguïté jugée par un modèle), soit des "
                "défauts que personne n'a encore regardés. Rien dans ce fichier ne permet "
                "de trancher : il faudrait ouvrir le site."
            ),
        },
        "n_sous_ensemble_executable": len(runnable),
        "enonces_perimes": {
            "n_corpus_entier": sum(1 for r in rows if r["enonce_perime"]["perime_au"]),
            "n_sous_ensemble_executable": len(runnable),
            "n_enonces_perimes": len(stale_run),
            "taux_enonces_perimes": round(len(stale_run) / max(1, len(runnable)), 4),
            "perimes_par_statut": dict(stale_run_by_status),
            "dont_patch_lui_meme_perime": len(stale_run_patch_rotten),
            "dont_aucun_patch_publie": len(stale_run_no_patch),
            "n_patches_perimes_dans_le_sous_ensemble": len(run_patch_rotten),
            "n_enonce_original_sain": len(clean_run),
            "n_lancable_apres_patch_valide": len(fixable_run),
            "ids_perimes": sorted(r["id"] for r in stale_run),
            "lecture": (
                "Le sous-ensemble « exécutable » est défini par le vote des praticiens "
                "(noyau ∪ surveiller ∪ corriger), pas par l'état de l'énoncé. Ces deux "
                "définitions ne coïncident pas : à la date de mesure, "
                f"{len(stale_run)} de ses {len(runnable)} énoncés portent une date "
                "révolue. Trois chiffres, et il faut dire lequel on cite : le "
                f"sous-ensemble consensuel ({len(runnable)}), les énoncés d'origine encore "
                f"sains ({len(clean_run)}), et ceux qu'un patch canonique lui-même non "
                f"périmé rend lançables ({len(fixable_run)}). Le chiffre de référence du "
                f"mémoire est {len(clean_run)} : il ne suppose rien du travail d'autrui. "
                "Aucune ligne n'est retirée du fichier : la péremption est marquée dans le "
                "champ `enonce_perime`, elle est datée, et elle se recalcule à toute date "
                "ultérieure. Attention enfin à deux dénombrements voisins : "
                f"{len(stale_run_patch_rotten)} patches périmés parmi les énoncés déjà "
                f"périmés, {len(run_patch_rotten)} dans tout le sous-ensemble — l'écart est "
                "Google Flights--9, énoncé sain et patch périmé."
            ),
        },
        "patches": {
            "n_taches_avec_patch_publie": len(patched),
            "n_patches_divergents": len(divergent),
            "n_patches_deja_perimes": len(rotten),
            "perimes_par_statut": dict(rot_by_status),
            "ids_perimes": sorted(r["id"] for r in rotten),
        },
        "avertissement": (
            "Ce sous-ensemble n'est pas une réparation du benchmark : c'est une "
            "réconciliation datée de verdicts publiés, augmentée de métadonnées de "
            "stabilité mesurées."
        ),
    }


def _export_readme(s: Mapping[str, Any]) -> str:
    st = s["statuts"]
    p = s["patches"]
    sp = s["enonces_perimes"]
    ct = s["croisement_statut_x_note_detecteurs_seuls"]
    d = s["desaccord_outil_praticiens"]
    grades = ("A", "B", "C", "D")
    crosstab_rows = "\n".join(
        "| `" + statut + "` | " + " | ".join(str(ct.get(statut, {}).get(g, 0)) for g in grades) + " |"
        for statut in ("noyau", "surveiller", "corriger", "retirer", "conteste")
        if statut in ct
    )
    return f"""# WebVoyager-Verified v0.1

**Date de la mesure : {s['date']}** · benchmark d'origine : {s['benchmark']} · produit par
`benchmark-doctor` ({__version__}), script `run_all.py --phase export`.

Un fichier : `webvoyager_verified_v0.1.jsonl`, **{s['n_taches']} lignes** — une par tâche de
WebVoyager, dans l'ordre du corpus d'origine. Les statistiques agrégées sont dans
`webvoyager_verified_v0.1.stats.json`.

## Ce que ce fichier est

Une **réconciliation datée** de six audits publics de WebVoyager, augmentée de
métadonnées de stabilité mesurées le {s['date']}. Chaque ligne porte :

| Champ | Contenu |
|---|---|
| `statut` | la recommandation d'usage (voir plus bas) |
| `verdict_consensuel` | `keep` / `modify` / `remove` / `conflit`, majorité des 6 annotateurs |
| `accord` | qui a signalé la tâche, combien, avec quelle action, et s'il y a désaccord dur |
| `stabilite` | score task-side, note A–D, catégorie dominante et **l'explication du calcul** |
| `taxonomie` | catégorie T1–T8 du défaut, pour les 121 tâches dont un patch-set motive le retrait |
| `patch_canonique` | l'énoncé corrigé retenu, sa source, sa date, ses variantes concurrentes, et s'il est **lui-même déjà périmé** |
| `enonce_perime` | si l'énoncé d'origine porte une date **déjà révolue** à la date de mesure, lesquelles, et si la tâche reste lançable sans retouche |
| `raisons_publiees` | les motifs bruts des annotateurs, tels qu'ils les ont écrits |

### Les cinq statuts

| Statut | n | Définition | Usage recommandé |
|---|---:|---|---|
| `noyau` | {st.get('noyau', 0)} | aucun des 6 annotateurs ne l'a jamais signalée | à exécuter |
| `surveiller` | {st.get('surveiller', 0)} | consensus « conserver », mais au moins un annotateur l'a signalée | à exécuter, et à re-mesurer |
| `corriger` | {st.get('corriger', 0)} | consensus « réécrire » | à exécuter avec `patch_canonique` |
| `retirer` | {st.get('retirer', 0)} | consensus « supprimer » | à exclure du score |
| `conteste` | {st.get('conteste', 0)} | supprimée par au moins un annotateur ET conservée intacte par au moins un autre | **à ne pas trancher automatiquement** |

### Le sous-ensemble exécutable : quel chiffre citer

Le sous-ensemble consensuel (`noyau` ∪ `surveiller` ∪ `corriger`) compte
**{s['n_sous_ensemble_executable']} tâches**. Ce n'est **pas** le nombre de tâches
lançables : le statut vient du vote des praticiens, pas de l'état de l'énoncé. À la date
de mesure, **{sp['n_enonces_perimes']} de ces {sp['n_sous_ensemble_executable']} énoncés
({100 * sp['taux_enonces_perimes']:.1f} %) portent une date déjà révolue** — dont
{sp['perimes_par_statut'].get('noyau', 0)} dans le `noyau`, c'est-à-dire parmi les tâches
que personne n'a jamais signalées. Sur ces {sp['n_enonces_perimes']},
{sp['dont_patch_lui_meme_perime']} disposent d'un patch canonique **lui-même périmé** et
{sp['dont_aucun_patch_publie']} n'ont aucun patch publié.

**Il y a donc trois chiffres, et il faut dire lequel on cite :**

| Lecture | n | Définition |
|---|---:|---|
| sous-ensemble consensuel | {s['n_sous_ensemble_executable']} | les praticiens ne demandent ni retrait ni arbitrage |
| **énoncé d'origine encore sain** | **{sp['n_enonce_original_sain']}** | et l'énoncé ne porte aucune date révolue au {s['date']} |
| lançable après patch valide | {sp['n_lancable_apres_patch_valide']} | ou un patch canonique non périmé le répare |

Le chiffre de référence est **{sp['n_enonce_original_sain']}** : c'est le seul qui ne
suppose rien du travail d'autrui. Les {sp['n_lancable_apres_patch_valide']} supposent en
plus que le patch d'un annotateur tiers est bon — or {p['n_patches_deja_perimes']} des
{p['n_taches_avec_patch_publie']} patches recopiés ici sont eux-mêmes déjà périmés.

Aucune ligne n'est retirée du fichier pour autant. La péremption est **marquée**, dans le
champ `enonce_perime` de chaque ligne, avec les dates fautives et la date d'évaluation.
Trois raisons : le fichier est une photographie à {s['n_taches']} lignes — une par tâche —
et retirer des lignes casserait l'invariant qui le rend comparable dans le temps ; la
péremption est **datée**, elle sera vraie de plus de tâches dans six mois, et un champ se
recalcule là où une suppression est irréversible ; et c'est un résultat, pas un déchet.
Un utilisateur qui veut la liste courte l'obtient en une ligne :

```
jq -c 'select(.statut != "retirer" and .statut != "conteste"
       and .enonce_perime.executable_sans_retouche)' webvoyager_verified_v0.1.jsonl
```

Le statut `conteste` est le résultat, pas un déchet : {st.get('conteste', 0)} tâches sur
{s['n_taches']} sont l'objet d'un désaccord dur entre praticiens. Aucun agrégat de
verdicts ne peut le résoudre ; il faudrait ouvrir le site et arbitrer à la main. C'est ce
que nous n'avons pas fait, et c'est écrit ici plutôt que masqué par un vote.

Le champ `patch_canonique` est renseigné dès qu'un annotateur a publié une réécriture,
**y compris sur des tâches de statut `retirer` ou `conteste`** : cela signale précisément
les tâches qu'un praticien a réparées là où un autre les a supprimées.

### Ce que l'outil en pense, statut par statut

Note de stabilité **détecteurs seuls** (sans l'a priori des praticiens, donc sans
circularité) croisée avec le statut issu du vote des praticiens :

| Statut \\ Note | A | B | C | D |
|---|---:|---:|---:|---:|
{crosstab_rows}

À lire dans les deux sens. {d['noyau_sous_A']} tâches que **personne** n'a jamais
signalées reçoivent une note inférieure à A, dont {d['noyau_note_D']} en D ; et
{d['retirer_note_A']} tâche{'s' if d['retirer_note_A'] > 1 else ''} que les
praticiens veulent supprimer {'sont notées' if d['retirer_note_A'] > 1 else 'est notée'} A
par l'outil. {d['lecture']}

## Ce que ce fichier n'est PAS

1. **Ce n'est pas un audit manuel des 643 tâches, et nous ne prétendons pas être les
   premiers.** Emergence AI a publié en mars 2026 un audit humain de WebVoyager et une
   version corrigée de **535 tâches templatées** (`EmergenceAI/EmergenceWebVoyager`).
   Microsoft Fara publie un sous-ensemble de 595 tâches, Convergence de 601, Alumnium de
   619, Skyvern de 635. Ce dépôt apporte la réconciliation multi-annotateurs, la mesure
   longitudinale et les métadonnées de stabilité par tâche, qui ne sont publiées nulle
   part ailleurs.

2. **Ce n'est pas une réparation exhaustive du benchmark.** Aucune tâche n'a été
   ré-exécutée par un agent, aucun énoncé n'a été réécrit par nous. Les patches proposés
   sont ceux des annotateurs, recopiés et datés.

3. **Ce n'est pas un verdict de vérité.** Le champ `verdict_consensuel` est un décompte
   de majorité sur six sources qui n'ont ni le même but ni le même seuil : Magnitude
   re-date par précaution, Skyvern rafraîchit en masse, browser-use exclut. Une tâche
   « conservée » par une source peut simplement n'avoir jamais été examinée par elle —
   le silence y vaut conservation. L'accord publié est donc une **borne haute**.

4. **Ce n'est pas stable dans le temps — par construction, et ce n'est pas non plus un
   sous-ensemble propre.** {p['n_patches_deja_perimes']} des
   {p['n_taches_avec_patch_publie']} patches recopiés ici sont **déjà périmés** à la date
   de la mesure : ils contiennent encore une date passée. Et surtout, l'énoncé d'origine
   lui-même est déjà révolu pour **{sp['n_enonces_perimes']} des
   {sp['n_sous_ensemble_executable']} tâches du sous-ensemble consensuel
   ({100 * sp['taux_enonces_perimes']:.1f} %)**. Le mot *Verified* de ce fichier porte sur
   la **réconciliation des verdicts** et sur la **datation des mesures** — jamais sur
   l'exécutabilité d'une tâche. Chaque ligne dit elle-même dans quel état elle est
   (`enonce_perime`) ; c'est le seul sens dans lequel ce fichier est vérifié.
   {p['n_patches_divergents']} tâches reçoivent par ailleurs des correctifs textuellement
   différents selon l'annotateur. Un sous-ensemble « vérifié » est une photographie, pas
   un état.

5. **Ce n'est pas une mesure de la fiabilité des agents.** Le score de stabilité porte sur
   la *tâche* (mesure-t-elle encore ce qu'elle mesurait ?), pas sur l'agent (donne-t-il le
   même résultat d'un run à l'autre). Les deux se composent mais ne se confondent pas.

## Limites de mesure à connaître avant de citer un chiffre

- Les sondes réseau sont parties d'une **IP de datacenter**. Sur les trois sites bloqués
  que nous avons pu recouper avec un navigateur, deux répondaient normalement à
  celui-ci : les constats d'accès sont pondérés par une crédibilité de canal κ = 0,40 et
  ne doivent jamais être lus comme « tâche morte ».
- Les sondes ne portent que sur **l'URL de départ** de chaque tâche : WebVoyager n'en
  fournit pas d'autre. Le verdict d'accès d'un site est propagé à toutes ses tâches. Les
  taux bornent la décadence **par le bas**.
- Le score est **ordinal avant d'être cardinal**. Comparer deux tâches est légitime ; lire
  un score comme une probabilité ne l'est pas.

## Reproduire ce fichier

```
python3 run_all.py --phase audit     # mesure L1+L2+L3 sur les 643 tâches
python3 run_all.py --phase export    # ce fichier
python3 analysis_longitudinal.py     # les courbes de mortalité qui l'accompagnent
```

La base de verdicts réconciliée dont dérivent les champs `accord`, `taxonomie` et
`patch_canonique` se reconstruit par
`python3 -m benchmark_doctor.ground_truth.fetch_sources` puis `.reconcile`.

## Licence et citation

Le fichier dérive de corpus publics : WebVoyager (MIT, He et al. 2024) et des six
patch-sets cités, chacun sous sa propre licence. Les champs ajoutés par nous
(`statut`, `stabilite`, `taxonomie`, `accord`) sont publiés sous MIT.
"""


# Point d'entrée


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_all.py",
        description="Campagne complète benchmark-doctor sur WebVoyager (chapitre 4).",
    )
    p.add_argument(
        "--phase",
        default="all",
        choices=["all", "audit", "validate", "export"],
        help="phase à exécuter (défaut : les trois, dans l'ordre)",
    )
    p.add_argument("--today", default=REFERENCE_DATE.isoformat(),
                   help="date de référence des détecteurs (défaut : 2026-08-15, gelée)")
    p.add_argument("--layers", default="l1,l2,l3", help="couches de l'audit")
    p.add_argument("--channel", default="direct",
                   choices=["direct", "direct-minimal", "browser-local", "recorded", "none"])
    p.add_argument("--recorded", default=None, help="observations à rejouer (canal recorded)")
    p.add_argument("--l3-backend", default="llm",
                   help="backend d'ambiguïté : tfidf | minilm | openrouter | llm (défaut)")
    p.add_argument("--no-solvability", action="store_true",
                   help="ne pas exécuter le vérificateur de solvabilité (économise ~0,13 $)")
    p.add_argument("--limit", type=int, default=0, help="sous-échantillon (essais seulement)")
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.phase in ("all", "audit"):
        phase_audit(args)
    if args.phase in ("all", "validate"):
        phase_validate(args)
    if args.phase in ("all", "export"):
        phase_export(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
