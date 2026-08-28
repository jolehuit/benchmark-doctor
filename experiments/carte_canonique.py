#!/usr/bin/env python3
"""Carte de santé CANONIQUE du mémoire : rejeu hors ligne, à coût nul.

Pourquoi ce script existe
-------------------------
Trois cartes de santé aux chiffres différents circulaient dans le dossier
(cf. `VERIFICATION.md` §C8). Elles ne sont pas fausses : ce sont trois
*configurations* différentes du même outil. Le problème est qu'aucune n'était
déclarée comme la référence, et que les tables de sensibilité publiées à côté du
README étaient calculées dans une AUTRE configuration que le README lui-même.

Ce script fait deux choses et rien d'autre :

1. il **rejoue** la campagne canonique à partir du journal de constats gelé
   ``runs/health_20260815_findings.json`` — donc sans un seul appel réseau et
   sans un centime d'API : les constats sont des faits datés du 15/08/2026, pas
   quelque chose qu'on recalcule ;
2. il produit **dans cette configuration et dans elle seule** la carte, les
   tables de sensibilité (κ, agrégation, échelle de notes) et le journal
   canonique ``runs/carte_canonique_20260815.json``.

Configuration canonique (une seule, nommée, opposable)
------------------------------------------------------
======================  ==================================================
Corpus                  ``data/raw/webvoyager_original.jsonl`` (643 tâches)
                        sha256 69b19fd8…c488
Date de référence       **2026-08-15**, gelée (``run_all.REFERENCE_DATE``)
Couches                 **L1 + L2 + L3**, solvabilité **incluse**
Canal L2                ``direct_http:browser`` (kind ``http_datacenter``)
Contenus L2             vérifiés (``--l2-content``)
Backend L3 ambiguïté    ``llm-judge:gemini-2.5-flash:rubric``, seuil 0,5
Backend L3 solvabilité  ``google/gemini-2.5-flash``
A priori praticiens     ``data/ground_truth.json`` (inclus dans le score publié)
Échelle de notes        1 − w(σ) : A > 0,75 · B > 0,50 · C > 0,25 · D ≤ 0,25
======================  ==================================================

Le choix est justifié dans ``CARTE_CANONIQUE.md``. Les autres cartes de
``runs/`` restent sur le disque mais sont marquées « configuration
exploratoire, non citée ».

Usage :
    python3 experiments/carte_canonique.py            # rejeu + écriture
    python3 experiments/carte_canonique.py --check    # rejeu + contrôle seul
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmark_doctor import __version__  # noqa: E402
from benchmark_doctor.models import (  # noqa: E402
    BenchmarkHealth,
    Channel,
    Finding,
    Task,
    TaskVerdict,
)
from benchmark_doctor.scoring import (  # noqa: E402
    CHANNEL_CREDIBILITY,
    DEFAULT_MODEL,
    GRADE_THRESHOLDS,
    PractitionerPrior,
    grade_for,
    score_health,
)

REFERENCE_DATE = _dt.date(2026, 8, 15)
RUNS = ROOT / "runs"

#: Le journal de constats gelé. C'est la **mesure** ; tout le reste en est dérivé.
JOURNAL = RUNS / "health_20260815_findings.json"
#: La carte de référence produite le 15/08 par `run_all.py --phase audit`.
CARTE_PUBLIEE = RUNS / "health_20260815.json"
#: Le rejeu canonique écrit par ce script.
SORTIE = RUNS / "carte_canonique_20260815.json"

CONFIG_CANONIQUE: dict[str, Any] = {
    "nom": "canonique-20260815",
    "corpus": "data/raw/webvoyager_original.jsonl",
    "corpus_sha256": "69b19fd86c23f1a500244a3724e039aa7ca6a1223d03e11eb10e308d4f11c488",
    "n_tasks": 643,
    "date_de_reference": "2026-08-15",
    "couches": ["L1", "L2", "L3"],
    "l3_solvabilite": True,
    "l2_canal": "direct_http:browser",
    "l2_canal_kind": "http_datacenter",
    "l2_content_checks": True,
    "l3_ambiguity_backend": "llm-judge:gemini-2.5-flash:rubric",
    "l3_ambiguity_threshold": 0.5,
    "l3_solvability_model": "google/gemini-2.5-flash",
    "a_priori_praticiens": "data/ground_truth.json",
    "echelle_de_notes": dict(GRADE_THRESHOLDS),
    "kappa": CHANNEL_CREDIBILITY[Channel.HTTP_DATACENTER],
    "commande_de_production": (
        "python3 run_all.py --phase audit --l3-backend llm   "
        "# 15/08/2026, 0,26 $ (servi par runs/l3_cache ensuite)"
    ),
    "commande_de_rejeu": "python3 experiments/carte_canonique.py --check",
}


# Rejeu du journal


def charge_journal(path: Path = JOURNAL) -> BenchmarkHealth:
    """Reconstruit le bulletin de santé à partir du journal de constats gelé.

    Le journal contient chaque constat avec sa catégorie, sa sévérité, sa confiance,
    son canal et sa date d'observation : tout ce dont le modèle de score a besoin.
    Rien n'est recalculé, rien n'est appelé.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta = raw["meta"]
    health = BenchmarkHealth(
        benchmark="webvoyager",
        generated_at=_dt.date.fromisoformat(meta["reference_date"]),
        source=meta["corpus"],
        tool_version=meta.get("tool_version", __version__),
    )
    for row in raw["tasks"]:
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
        for f in row.get("findings", []):
            verdict.findings.append(
                Finding(
                    category=f["category"],
                    severity=f["severity"],
                    confidence=f["confidence"],
                    evidence=f.get("evidence", ""),
                    detector=f["detector"],
                    channel=f.get("channel", "static"),
                    task_id=f.get("task_id") or row["task_id"],
                    signal=f.get("signal"),
                    details=f.get("details", {}),
                    observed_at=f.get("observed_at", row["evaluated_at"]),
                )
            )
        health.verdicts.append(verdict)
    return health


def distribution(assessments) -> dict[str, int]:
    counts = {g: 0 for g in ("A", "B", "C", "D")}
    for a in assessments:
        counts[a.grade] += 1
    return counts


def moyenne(assessments) -> float:
    return round(sum(a.score for a in assessments) / len(assessments), 4)


# Tables de sensibilité — DANS LA CONFIGURATION CANONIQUE


def sensibilite_kappa(health: BenchmarkHealth, prior: PractitionerPrior) -> list[dict[str, Any]]:
    """Effet de κ (crédibilité du canal HTTP datacenter) sur la distribution des notes.

    C'est la table que le rapport 5 publiait **sans la couche solvabilité** alors que le
    README publiait la carte **avec**. Elle est ici recalculée dans la configuration
    canonique : les deux chiffres sont désormais collables dans le même paragraphe.
    """
    from dataclasses import replace as _replace

    rows: list[dict[str, Any]] = []
    for kappa in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        cred = dict(DEFAULT_MODEL.channel_credibility)
        cred[Channel.HTTP_DATACENTER] = kappa
        cred[Channel.HTTP_RESIDENTIAL] = kappa
        model = _replace(DEFAULT_MODEL, channel_credibility=cred)
        a = score_health(health, model=model, prior=prior, today=REFERENCE_DATE)
        d = distribution(a)
        rows.append(
            {
                "kappa": kappa,
                "stabilite_moyenne": moyenne(a),
                **{f"note_{g}": d[g] for g in ("A", "B", "C", "D")},
                "retenu": kappa == CHANNEL_CREDIBILITY[Channel.HTTP_DATACENTER],
            }
        )
    return rows


def sensibilite_agregation(
    health: BenchmarkHealth, prior: PractitionerPrior
) -> dict[str, Any]:
    """OU bruité (retenu) contre maximum (référence) : combien de notes changent."""
    from dataclasses import replace as _replace

    noisy = score_health(health, model=DEFAULT_MODEL, prior=prior, today=REFERENCE_DATE)
    plain = score_health(
        health,
        model=_replace(DEFAULT_MODEL, aggregation="max"),
        prior=prior,
        today=REFERENCE_DATE,
    )
    changed = [
        {"task_id": n.task_id, "ou_bruite": n.grade, "maximum": p.grade}
        for n, p in zip(noisy, plain)
        if n.grade != p.grade
    ]
    multi = sum(1 for a in noisy if len(a.category_risks) > 1)
    return {
        "n_taches_multi_categories": multi,
        "taux_multi_categories": round(multi / len(noisy), 4),
        "n_changements_de_note": len(changed),
        "distribution_ou_bruite": distribution(noisy),
        "distribution_maximum": distribution(plain),
        "exemples": changed[:15],
    }


def sensibilite_echelle(health: BenchmarkHealth, prior: PractitionerPrior) -> dict[str, Any]:
    """Échelle retenue (1 − w(σ)) contre l'ancienne échelle 0,85 / 0,60 / 0,35.

    Publiée pour mémoire : l'échelle héritée n'est plus dans le code depuis la
    correction C8, cette table dit ce qu'elle aurait donné.
    """
    a = score_health(health, model=DEFAULT_MODEL, prior=prior, today=REFERENCE_DATE)
    heritee = {"A": 0.85, "B": 0.60, "C": 0.35, "D": 0.0}
    d_new = {g: 0 for g in "ABCD"}
    d_old = {g: 0 for g in "ABCD"}
    migrations: dict[str, int] = {}
    for x in a:
        n, o = grade_for(x.score), grade_for(x.score, heritee)
        d_new[n] += 1
        d_old[o] += 1
        if n != o:
            migrations[f"{o}->{n}"] = migrations.get(f"{o}->{n}", 0) + 1
    return {
        "seuils_retenus": dict(GRADE_THRESHOLDS),
        "seuils_herites_abandonnes": heritee,
        "distribution_retenue": d_new,
        "distribution_heritee": d_old,
        "migrations": dict(sorted(migrations.items(), key=lambda kv: -kv[1])),
    }


def sensibilite_couches(health: BenchmarkHealth, prior: PractitionerPrior) -> dict[str, Any]:
    """Distribution des notes quand on retire une couche du calcul du score.

    Ablation par **filtrage des constats** : une seule passe de mesure, comme dans
    `run_all.py`. Aucune re-mesure, donc aucune variation du monde entre deux lignes.
    """
    out: dict[str, Any] = {}
    for nom, couches in (
        ("L1", ("L1",)),
        ("L1+L2", ("L1", "L2")),
        ("L1+L3", ("L1", "L3")),
        ("L1+L2+L3 (canonique)", ("L1", "L2", "L3")),
    ):
        sous = BenchmarkHealth(
            benchmark=health.benchmark,
            generated_at=health.generated_at,
            source=health.source,
            tool_version=health.tool_version,
        )
        for v in health.verdicts:
            w = TaskVerdict(task=v.task, evaluated_at=v.evaluated_at, channels=list(v.channels))
            w.findings.extend([f for f in v.findings if f.layer in couches])
            sous.verdicts.append(w)
        a = score_health(sous, model=DEFAULT_MODEL, prior=prior, today=REFERENCE_DATE)
        out[nom] = {"stabilite_moyenne": moyenne(a), **distribution(a)}
    return out


# Contrôle : le rejeu doit reproduire la carte publiée


def controle(assessments) -> dict[str, Any]:
    publiee = json.loads(CARTE_PUBLIEE.read_text(encoding="utf-8"))["summary"]
    rejeu = {"grades": distribution(assessments), "mean_stability": moyenne(assessments)}
    ecarts = {
        g: rejeu["grades"][g] - publiee["grades"][g] for g in "ABCD"
        if rejeu["grades"][g] != publiee["grades"][g]
    }
    return {
        "carte_publiee": {"grades": publiee["grades"], "mean_stability": publiee["mean_stability"]},
        "rejeu_hors_ligne": rejeu,
        "ecarts_de_notes": ecarts,
        "identique": not ecarts
        and abs(rejeu["mean_stability"] - publiee["mean_stability"]) < 5e-4,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="contrôle seul, aucune écriture")
    args = ap.parse_args(argv)

    health = charge_journal()
    prior = PractitionerPrior.load(str(ROOT / "data" / "ground_truth.json"))
    assessments = score_health(health, model=DEFAULT_MODEL, prior=prior, today=REFERENCE_DATE)

    ctrl = controle(assessments)
    print("Carte canonique — rejeu hors ligne du journal du 15/08/2026")
    print(f"  journal   : {JOURNAL.relative_to(ROOT)}")
    print(f"  tâches    : {len(assessments)}")
    print(f"  notes     : {distribution(assessments)}")
    print(f"  stabilité : {moyenne(assessments)}")
    print(f"  contrôle contre la carte publiée : "
          f"{'IDENTIQUE' if ctrl['identique'] else 'ÉCART ' + json.dumps(ctrl['ecarts_de_notes'])}")

    if args.check:
        return 0 if ctrl["identique"] else 1

    payload = {
        "schema": "benchmark-doctor/carte-canonique/1",
        "genere_par": f"experiments/carte_canonique.py (benchmark-doctor {__version__})",
        "genere_le": _dt.date.today().isoformat(),
        "configuration_canonique": CONFIG_CANONIQUE,
        "source_de_verite": {
            "journal_de_constats": str(JOURNAL.relative_to(ROOT)),
            "carte_publiee": str(CARTE_PUBLIEE.relative_to(ROOT)),
            "appels_reseau": 0,
            "cout_usd": 0.0,
        },
        "controle_de_rejeu": ctrl,
        "resume": {
            "n_tasks": len(assessments),
            "stabilite_moyenne": moyenne(assessments),
            "notes": distribution(assessments),
            "taux_sous_A": round(
                sum(1 for a in assessments if a.grade != "A") / len(assessments), 4
            ),
        },
        "sensibilite_kappa": sensibilite_kappa(health, prior),
        "sensibilite_agregation": sensibilite_agregation(health, prior),
        "sensibilite_echelle_de_notes": sensibilite_echelle(health, prior),
        "sensibilite_couches": sensibilite_couches(health, prior),
    }
    SORTIE.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nÉcrit : {SORTIE.relative_to(ROOT)}")

    print("\nSensibilité à κ (configuration canonique, AVEC solvabilité) :")
    print("      κ   stabilité ⌀     A     B     C     D")
    for r in payload["sensibilite_kappa"]:
        mark = "   <-- retenu" if r["retenu"] else ""
        print(f"  {r['kappa']:.3f}      {r['stabilite_moyenne']:.4f}  "
              f"{r['note_A']:4d}  {r['note_B']:4d}  {r['note_C']:4d}  {r['note_D']:4d}{mark}")

    ag = payload["sensibilite_agregation"]
    print(f"\nAgrégation : {ag['n_taches_multi_categories']} tâches multi-catégories "
          f"({100 * ag['taux_multi_categories']:.1f} %), "
          f"{ag['n_changements_de_note']} changements de note / {len(assessments)}")
    return 0 if ctrl["identique"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
