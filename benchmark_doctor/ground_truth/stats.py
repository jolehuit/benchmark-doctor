#!/usr/bin/env python3
"""Statistiques de désaccord entre patch-sets — résultat central du chapitre 4.

Ce que le module calcule, et pourquoi :

- **Effectifs par source** : combien de tâches chaque acteur conserve, réécrit, supprime.
  C'est la mesure de la fragmentation (586/590/595/601/619/635/643).
- **Matrice de désaccord** : pour chaque couple d'annotateurs, le nombre de tâches que
  l'un supprime et que l'autre conserve intactes. C'est le désaccord qui coûte cher :
  deux laboratoires publient un score sur « WebVoyager » sans parler du même corpus.
- **Accord inter-annotateurs** : kappa de Fleiss (plus de deux juges, même nombre de juges
  par item, catégories nominales) sur trois codages, plus la matrice des kappas de Cohen
  par couple, plus l'AC1 de Gwet pour contourner le paradoxe de prévalence.
- **Divergence des correctifs** : parmi les tâches que plusieurs annotateurs réécrivent,
  combien reçoivent des correctifs différents. S'accorder sur le défaut n'est pas
  s'accorder sur la réparation.
- **Vérification du chiffre Alumnium** : « Alumnium restaure ~30 tâches supprimées par
  Magnitude » — vérifié sur les données, et corrigé sur un point de fond.
- **Prévalence par catégorie** : les 121 raisons de Magnitude relues à la main, comparées
  au classement par mots-clés qu'elles remplacent.
- **Courbe longitudinale** : nombre cumulé de tâches distinctes signalées au fil des huit
  observations datées (2024-12 → 2026-05), et le contrepoint Online-Mind2Web.

Usage :
    python3 -m benchmark_doctor.ground_truth.stats            # rapport texte
    python3 -m benchmark_doctor.ground_truth.stats --json out.json
    python3 -m benchmark_doctor.ground_truth.stats --embed    # écrit dans ground_truth.json
"""

from __future__ import annotations

import argparse
import collections
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

if __package__ in (None, ""):  # exécution directe du fichier
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from benchmark_doctor.ground_truth import loaders, reconcile, sources, taxonomy
else:
    from . import loaders, reconcile, sources, taxonomy

KEEP, MODIFY, REMOVE = loaders.KEEP, loaders.MODIFY, loaders.REMOVE
ACTIONS = (KEEP, MODIFY, REMOVE)

__all__ = [
    "fleiss_kappa",
    "gwet_ac1",
    "cohen_kappa",
    "interpret_kappa",
    "compute_stats",
    "format_report",
    "main",
]


# Mesures d'accord


def _counts_matrix(ratings: Sequence[Sequence[str]], categories: Sequence[str]) -> list[list[int]]:
    """Matrice item × catégorie du nombre de juges, à partir des jugements bruts."""
    index = {c: i for i, c in enumerate(categories)}
    matrix = []
    for item in ratings:
        row = [0] * len(categories)
        for value in item:
            row[index[value]] += 1
        matrix.append(row)
    return matrix


def fleiss_kappa(ratings: Sequence[Sequence[str]], categories: Sequence[str]) -> dict[str, float]:
    """Kappa de Fleiss pour un nombre constant de juges par item.

    Applicable ici parce que les huit patch-sets se prononcent chacun sur les 643 tâches
    (le silence d'une source valant conservation), donc *n* est constant — condition que
    le kappa de Cohen, limité à deux juges, ne permettrait pas de couvrir.

    Returns:
        ``{"kappa", "p_observe", "p_attendu", "n_items", "n_juges"}``.
    """
    matrix = _counts_matrix(ratings, categories)
    n_items = len(matrix)
    n_raters = sum(matrix[0])
    if n_items == 0 or n_raters < 2:
        raise ValueError("il faut au moins 2 juges et 1 item")
    p_items = [
        (sum(cell * cell for cell in row) - n_raters) / (n_raters * (n_raters - 1)) for row in matrix
    ]
    p_observed = sum(p_items) / n_items
    totals = [sum(row[j] for row in matrix) / (n_items * n_raters) for j in range(len(categories))]
    p_expected = sum(p * p for p in totals)
    kappa = (p_observed - p_expected) / (1 - p_expected) if p_expected < 1 else 1.0
    return {
        "kappa": round(kappa, 4),
        "p_observe": round(p_observed, 4),
        "p_attendu": round(p_expected, 4),
        "n_items": n_items,
        "n_juges": n_raters,
    }


def gwet_ac1(ratings: Sequence[Sequence[str]], categories: Sequence[str]) -> dict[str, float]:
    """AC1 de Gwet — même accord observé que Fleiss, hasard estimé autrement.

    Le kappa de Fleiss s'effondre quand une catégorie domine (ici « keep » représente ~90 %
    des jugements) : il attribue alors presque tout l'accord au hasard. C'est le *paradoxe
    de prévalence*. L'AC1 corrige ce biais et se lit sur la même échelle ; les deux sont
    reportés côte à côte plutôt que de choisir celui qui arrange.
    """
    matrix = _counts_matrix(ratings, categories)
    n_items = len(matrix)
    n_raters = sum(matrix[0])
    p_items = [
        (sum(cell * cell for cell in row) - n_raters) / (n_raters * (n_raters - 1)) for row in matrix
    ]
    p_observed = sum(p_items) / n_items
    totals = [sum(row[j] for row in matrix) / (n_items * n_raters) for j in range(len(categories))]
    k = len(categories)
    p_expected = sum(p * (1 - p) for p in totals) / (k - 1)
    ac1 = (p_observed - p_expected) / (1 - p_expected) if p_expected < 1 else 1.0
    return {"ac1": round(ac1, 4), "p_observe": round(p_observed, 4), "p_attendu": round(p_expected, 4)}


def cohen_kappa(a: Sequence[str], b: Sequence[str], categories: Sequence[str]) -> float:
    """Kappa de Cohen entre deux juges — utilisé pour la matrice par couple.

    Fleiss donne un chiffre global, Cohen dit *quels* couples se disputent : c'est le
    couple qui intéresse le mémoire (Magnitude contre Alumnium, par exemple).
    """
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = collections.Counter(a), collections.Counter(b)
    expected = sum((ca[c] / n) * (cb[c] / n) for c in categories)
    return round((observed - expected) / (1 - expected), 4) if expected < 1 else 1.0


def interpret_kappa(value: float) -> str:
    """Échelle de Landis & Koch (1977), citée telle quelle dans le mémoire."""
    if value < 0:
        return "désaccord (pire que le hasard)"
    if value < 0.21:
        return "faible (slight)"
    if value < 0.41:
        return "passable (fair)"
    if value < 0.61:
        return "modéré (moderate)"
    if value < 0.81:
        return "substantiel (substantial)"
    return "presque parfait (almost perfect)"


# Statistiques


def _collapse_exclusion(action: str) -> str:
    """Codage binaire « la tâche sort-elle du corpus ? »."""
    return "exclue" if action == REMOVE else "retenue"


def _collapse_defect(action: str) -> str:
    """Codage binaire « la tâche est-elle jugée défectueuse ? » (réécrite ou supprimée)."""
    return "intacte" if action == KEEP else "defectueuse"


def compute_stats(raw_dir: Path | None = None) -> dict[str, Any]:
    """Calcule toutes les statistiques de réconciliation.

    Returns:
        Un dictionnaire sérialisable, structuré par section (effectifs, désaccord,
        accord, alumnium_vs_magnitude, taxonomie, longitudinal, om2w).
    """
    original, per_source, reports = loaders.load_all(raw_dir)
    task_ids = list(original)
    annotators = [s.key for s in sources.annotator_sources()]
    labels = taxonomy.load_manual_labels()

    def actions(key: str) -> list[str]:
        return [per_source[key][tid].action for tid in task_ids]

    # -- effectifs ----------------------------------------------------------------------
    effectifs = {
        s.key: {
            "libelle": s.label,
            "date": s.date,
            "annotateur": s.annotator,
            **reports["effectifs"][s.key],
            "taille_corpus_retenu": sum(
                1 for v in per_source[s.key].values() if v.action != REMOVE
            ),
            "compte_dans_accord": s.counted_in_agreement,
        }
        for s in sources.SOURCES
    }

    # -- couverture ---------------------------------------------------------------------
    flagged_by = {
        tid: [k for k in annotators if per_source[k][tid].action != KEEP] for tid in task_ids
    }
    removed_by = {
        tid: [k for k in annotators if per_source[k][tid].action == REMOVE] for tid in task_ids
    }
    consensus_curve = collections.Counter(len(v) for v in flagged_by.values())
    removal_curve = collections.Counter(len(v) for v in removed_by.values())

    # -- matrice de désaccord -----------------------------------------------------------
    disagreement: dict[str, dict[str, Any]] = {}
    for a, b in itertools.permutations(annotators, 2):
        pairs = [(per_source[a][tid].action, per_source[b][tid].action) for tid in task_ids]
        disagreement[f"{a}|{b}"] = {
            "supprimee_par_a_conservee_intacte_par_b": sum(
                1 for x, y in pairs if x == REMOVE and y == KEEP
            ),
            "supprimee_par_a_reecrite_par_b": sum(1 for x, y in pairs if x == REMOVE and y == MODIFY),
        }
    pair_matrix: dict[str, dict[str, Any]] = {}
    for a, b in itertools.combinations(annotators, 2):
        va, vb = actions(a), actions(b)
        contingency = collections.Counter(zip(va, vb))
        pair_matrix[f"{a}|{b}"] = {
            "accord_brut": round(sum(1 for x, y in zip(va, vb) if x == y) / len(task_ids), 4),
            "kappa_cohen_3cat": cohen_kappa(va, vb, ACTIONS),
            "kappa_cohen_exclusion": cohen_kappa(
                [_collapse_exclusion(x) for x in va],
                [_collapse_exclusion(y) for y in vb],
                ("exclue", "retenue"),
            ),
            "contingence": {f"{x}/{y}": n for (x, y), n in sorted(contingency.items())},
            "desaccord_dur": sum(
                1
                for x, y in zip(va, vb)
                if {x, y} == {REMOVE, KEEP}
            ),
        }

    # -- accord global ------------------------------------------------------------------
    def ratings(
        keys: Iterable[str],
        collapse: Callable[[str], str] | None = None,
        subset: Sequence[str] | None = None,
    ) -> list[list[str]]:
        keys = list(keys)
        return [
            [collapse(per_source[k][tid].action) if collapse else per_source[k][tid].action for k in keys]
            for tid in (subset if subset is not None else task_ids)
        ]

    contested = [tid for tid in task_ids if flagged_by[tid]]

    accord = {
        "annotateurs_retenus": annotators,
        "exclus": [
            {"cle": s.key, "motif": s.note}
            for s in sources.SOURCES
            if not s.counted_in_agreement
        ],
        "fleiss_3categories": fleiss_kappa(ratings(annotators), ACTIONS),
        "fleiss_exclusion": fleiss_kappa(
            ratings(annotators, _collapse_exclusion), ("exclue", "retenue")
        ),
        "fleiss_defaut": fleiss_kappa(
            ratings(annotators, _collapse_defect), ("intacte", "defectueuse")
        ),
        "gwet_ac1_3categories": gwet_ac1(ratings(annotators), ACTIONS),
        "gwet_ac1_exclusion": gwet_ac1(
            ratings(annotators, _collapse_exclusion), ("exclue", "retenue")
        ),
        "matrice_cohen": pair_matrix,
    }
    accord["fleiss_3categories"]["lecture"] = interpret_kappa(accord["fleiss_3categories"]["kappa"])
    accord["fleiss_exclusion"]["lecture"] = interpret_kappa(accord["fleiss_exclusion"]["kappa"])
    accord["fleiss_defaut"]["lecture"] = interpret_kappa(accord["fleiss_defaut"]["kappa"])
    # sensibilité : que devient l'accord si l'on réintègre les sources écartées ?
    configurations = {
        "6 annotateurs (référence)": annotators,
        "+ skyvern_2025 (annotateur dupliqué)": annotators + ["skyvern_2025"],
        "+ emergence (confiance faible)": annotators + ["emergence"],
        "les 8 sources": [s.key for s in sources.SOURCES],
    }
    accord["sensibilite"] = {
        name: {
            "n_sources": len(keys),
            "fleiss_3categories": fleiss_kappa(ratings(keys), ACTIONS)["kappa"],
            "fleiss_exclusion": fleiss_kappa(
                ratings(keys, _collapse_exclusion), ("exclue", "retenue")
            )["kappa"],
        }
        for name, keys in configurations.items()
    }
    # accord conditionnel : sur les seules tâches qu'au moins un annotateur a signalées.
    # Retirer les tâches sur lesquelles tout le monde se tait supprime l'accord trivial
    # et donne la mesure la plus informative — celle qui répond à « une fois qu'un
    # patcheur a vu un problème, les autres le voient-ils pareil ? ».
    accord["conditionnel_taches_signalees"] = {
        "n_taches": len(contested),
        "fleiss_3categories": fleiss_kappa(ratings(annotators, subset=contested), ACTIONS),
        "fleiss_exclusion": fleiss_kappa(
            ratings(annotators, _collapse_exclusion, subset=contested), ("exclue", "retenue")
        ),
    }
    accord["conditionnel_taches_signalees"]["lecture_3cat"] = interpret_kappa(
        accord["conditionnel_taches_signalees"]["fleiss_3categories"]["kappa"]
    )

    # -- divergence des réparations -----------------------------------------------------
    # S'accorder sur le défaut ne veut pas dire s'accorder sur le correctif : `Booking--8`
    # est réécrite par les six annotateurs, qui la datent de quatre années différentes.
    repairs: list[dict[str, Any]] = []
    for tid in task_ids:
        variants: dict[str, list[str]] = collections.defaultdict(list)
        for key in annotators:
            verdict = per_source[key][tid]
            if verdict.action == MODIFY and verdict.new_question:
                variants[loaders.normalize_question(verdict.new_question)].append(key)
        n_modifiers = sum(len(v) for v in variants.values())
        if n_modifiers >= 2:
            texts = {per_source[keys[0]][tid].new_question: keys for keys in variants.values()}
            years = {
                tuple(sorted(set(re.findall(r"\b20\d{2}\b", text or "")))) for text in texts
            }
            repairs.append(
                {
                    "id": tid,
                    "n_reecritures": n_modifiers,
                    "n_variantes_distinctes": len(variants),
                    "n_millesimes_distincts": len(years),
                    "variantes": texts,
                }
            )
    multi = [r for r in repairs if r["n_variantes_distinctes"] > 1]
    multi_years = [r for r in repairs if r["n_millesimes_distincts"] > 1]
    reparations = {
        "definition": (
            "parmi les tâches réécrites par au moins deux annotateurs, combien reçoivent des "
            "correctifs textuellement différents"
        ),
        "taches_reecrites_par_2_annotateurs_ou_plus": len(repairs),
        "dont_correctifs_divergents": len(multi),
        "part_divergente": round(len(multi) / len(repairs), 3) if repairs else None,
        "dont_millesimes_divergents": len(multi_years),
        "part_millesimes_divergents": round(len(multi_years) / len(repairs), 3) if repairs else None,
        "lecture_millesimes": (
            "mesure plus exigeante que la divergence textuelle : deux correctifs peuvent "
            "différer par « Feb » contre « February » sans désaccord de fond. Ici les "
            "annotateurs ne s'accordent même pas sur l'année vers laquelle décaler la tâche."
        ),
        "variantes_moyennes": (
            round(sum(r["n_variantes_distinctes"] for r in repairs) / len(repairs), 2)
            if repairs
            else None
        ),
        "distribution_variantes": dict(
            sorted(collections.Counter(r["n_variantes_distinctes"] for r in repairs).items())
        ),
        "exemples": sorted(repairs, key=lambda r: -r["n_variantes_distinctes"])[:5],
    }

    # -- Alumnium vs Magnitude ----------------------------------------------------------
    mag, alu = per_source["magnitude"], per_source["alumnium"]
    mag_removed = {t for t in task_ids if mag[t].action == REMOVE}
    alu_removed = {t for t in task_ids if alu[t].action == REMOVE}
    restored = sorted(mag_removed - alu_removed)
    restored_verbatim = [t for t in restored if alu[t].action == KEEP]
    restored_modified = [t for t in restored if alu[t].action == MODIFY]
    alumnium_vs_magnitude = {
        "affirmation_verifiee": "Alumnium (03/2026) restaurerait ~30 tâches supprimées par Magnitude (07/2025)",
        "magnitude_supprime": len(mag_removed),
        "alumnium_supprime": len(alu_removed),
        "suppressions_communes": len(mag_removed & alu_removed),
        "restaurees_par_alumnium": len(restored),
        "dont_conservees_telles_quelles": len(restored_verbatim),
        "dont_reecrites": len(restored_modified),
        "supprimees_par_alumnium_conservees_intactes_par_magnitude": sorted(
            t for t in alu_removed - mag_removed if mag[t].action == KEEP
        ),
        "liste_restaurees": restored,
        "verdict": (
            f"chiffre confirmé : {len(restored)} des {len(mag_removed)} suppressions de Magnitude "
            f"sont conservées par Alumnium ({len(restored_verbatim)} à l'identique, "
            f"{len(restored_modified)} après réécriture)"
        ),
        "correction_de_fond": (
            "Alumnium n'a pas « re-audité Magnitude » : son dépôt part du commit d'origine de "
            "MinorJerry (2024-03-02) et non du fork Magnitude. Les deux audits sont indépendants, "
            "ce qui rend le désaccord d'autant plus significatif — il ne s'agit pas d'un "
            "réviseur contredisant un premier passage, mais de deux équipes regardant le même "
            "corpus et n'en tirant pas les mêmes conclusions."
        ),
        "categories_des_restaurees": collections.Counter(
            labels[t]["categorie"] for t in restored if t in labels
        ),
    }

    # -- taxonomie ----------------------------------------------------------------------
    manual = taxonomy.prevalence(labels)
    with_secondary = taxonomy.prevalence(labels, secondary=True)
    keyword = collections.Counter(
        taxonomy.classify_reason_keywords(entry["raison_publiee"]) for entry in labels.values()
    )
    confusion = collections.Counter(
        (taxonomy.classify_reason_keywords(entry["raison_publiee"]), entry["categorie"])
        for entry in labels.values()
    )
    keyword_agreement = sum(
        n
        for (kw, manual_code), n in confusion.items()
        if taxonomy.KEYWORD_TO_TAXONOMY.get(kw) == manual_code
    )
    taxonomie = {
        "corpus": "les 121 raisons publiées par Magnitude, relues une à une",
        "regle_arbitrage": taxonomy.ARBITRATION_RULE,
        "prevalence_principale": manual,
        "prevalence_avec_secondaire": with_secondary,
        "part_du_corpus_643": {k: round(100 * v / len(task_ids), 1) for k, v in manual.items()},
        "part_des_121": {k: round(100 * v / len(labels), 1) for k, v in manual.items()},
        "cas_limites": sum(1 for e in labels.values() if e["limite"]),
        "par_action": {
            action: collections.Counter(
                e["categorie"] for e in labels.values() if e["action"] == action
            )
            for action in (MODIFY, REMOVE)
        },
        "reference_mots_cles": dict(keyword),
        "accord_mots_cles_vs_manuel": {
            "n_identiques": keyword_agreement,
            "taux": round(keyword_agreement / len(labels), 3),
            "confusion": {f"{kw}->{code}": n for (kw, code), n in sorted(confusion.items())},
        },
    }

    # -- longitudinal -------------------------------------------------------------------
    # Deux cumuls : l'un sur toutes les sources, l'autre sur les seules sources de confiance
    # haute. Emergence réécrit *tous* les énoncés en gabarits ; l'inclure ferait bondir le
    # cumul de 147 à 445 sans qu'aucune tâche supplémentaire n'ait été jugée défectueuse.
    seen_flagged: set[str] = set()
    seen_flagged_hc: set[str] = set()
    seen_removed: set[str] = set()
    timeline = []
    for spec in sorted(sources.SOURCES, key=lambda s: s.date):
        flagged = {t for t in task_ids if per_source[spec.key][t].action != KEEP}
        removed = {t for t in task_ids if per_source[spec.key][t].action == REMOVE}
        new_flags = flagged - seen_flagged
        new_flags_hc = (flagged - seen_flagged_hc) if spec.confidence == "haute" else set()
        seen_flagged |= flagged
        seen_removed |= removed
        if spec.confidence == "haute":
            seen_flagged_hc |= flagged
        timeline.append(
            {
                "date": spec.date,
                "source": spec.key,
                "signalees_par_cette_source": len(flagged),
                "nouvelles_par_rapport_au_cumul": len(new_flags),
                "nouvelles_confiance_haute": len(new_flags_hc),
                "cumul_signalees": len(seen_flagged),
                "cumul_signalees_pct": round(100 * len(seen_flagged) / len(task_ids), 1),
                "cumul_confiance_haute": len(seen_flagged_hc),
                "cumul_confiance_haute_pct": round(100 * len(seen_flagged_hc) / len(task_ids), 1),
                "cumul_supprimees_au_moins_une_fois": len(seen_removed),
                "confiance": spec.confidence,
            }
        )

    return {
        "meta": {
            "n_taches": len(task_ids),
            "n_sources": len(sources.SOURCES),
            "n_annotateurs_distincts": len(annotators),
            "appariement_emergence": reports.get("emergence"),
        },
        "effectifs": effectifs,
        "couverture": {
            "jamais_signalee": sum(1 for v in flagged_by.values() if not v),
            "signalee_par_au_moins_1": sum(1 for v in flagged_by.values() if v),
            "signalee_par_tous": sum(1 for v in flagged_by.values() if len(v) == len(annotators)),
            "distribution_nb_annotateurs_signalant": dict(sorted(consensus_curve.items())),
            "distribution_nb_annotateurs_supprimant": dict(sorted(removal_curve.items())),
            "supprimee_par_au_moins_1": sum(1 for v in removed_by.values() if v),
            "supprimee_par_tous": sum(1 for v in removed_by.values() if len(v) == len(annotators)),
        },
        "desaccord": {
            "definition": (
                "une tâche supprimée par un annotateur et conservée sans modification par un "
                "autre : les deux ne mesurent pas le même benchmark"
            ),
            "taches_en_desaccord_dur": sum(
                1
                for tid in task_ids
                if removed_by[tid]
                and any(per_source[k][tid].action == KEEP for k in annotators)
            ),
            "matrice_orientee": disagreement,
            "supprimee_par_tous_les_annotateurs": [
                {"id": tid, "question": original[tid].question}
                for tid in task_ids
                if len(removed_by[tid]) == len(annotators)
            ],
            "taches_les_plus_disputees": [
                {
                    "id": tid,
                    "site": original[tid].site,
                    "supprimee_par": removed_by[tid],
                    "conservee_intacte_par": [
                        k for k in annotators if per_source[k][tid].action == KEEP
                    ],
                    "categorie": (labels.get(tid) or {}).get("categorie"),
                    "question": original[tid].question,
                }
                for tid in sorted(
                    task_ids,
                    key=lambda t: (
                        -len(removed_by[t])
                        * sum(1 for k in annotators if per_source[k][t].action == KEEP),
                        t,
                    ),
                )[:15]
            ],
        },
        "accord": accord,
        "reparations": reparations,
        "alumnium_vs_magnitude": alumnium_vs_magnitude,
        "taxonomie": taxonomie,
        "longitudinal": timeline,
        "om2w": loaders.load_om2w_journal(raw_dir),
    }


# Rapport texte


def _table(rows: Sequence[Sequence[Any]], headers: Sequence[str]) -> str:
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    line = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    out = [line, "  ".join("-" * w for w in widths)]
    for row in rows:
        out.append("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(out)


def format_report(stats: dict[str, Any]) -> str:
    """Met en forme les statistiques pour la console (et pour copie dans le mémoire)."""
    out: list[str] = []
    add = out.append
    n = stats["meta"]["n_taches"]

    add("=" * 100)
    add("RÉCONCILIATION DES PATCH-SETS WEBVOYAGER — statistiques de désaccord")
    add("=" * 100)

    add("\n## 1. Effectifs par source (643 tâches d'origine)\n")
    rows = [
        [
            key,
            v["date"],
            v.get("keep", 0),
            v.get("modify", 0),
            v.get("remove", 0),
            v["taille_corpus_retenu"],
            "oui" if v["compte_dans_accord"] else "non",
        ]
        for key, v in sorted(stats["effectifs"].items(), key=lambda kv: kv[1]["date"])
    ]
    add(_table(rows, ["source", "date", "keep", "modify", "remove", "corpus", "accord"]))

    cov = stats["couverture"]
    add("\n## 2. Couverture et consensus\n")
    add(f"  jamais signalée par aucun annotateur : {cov['jamais_signalee']} "
        f"({100 * cov['jamais_signalee'] / n:.1f} %)")
    add(f"  signalée par au moins un annotateur  : {cov['signalee_par_au_moins_1']} "
        f"({100 * cov['signalee_par_au_moins_1'] / n:.1f} %)")
    add(f"  signalée par les six annotateurs     : {cov['signalee_par_tous']}")
    add(f"  supprimée par au moins un annotateur : {cov['supprimee_par_au_moins_1']}")
    add(f"  supprimée par les six annotateurs    : {cov['supprimee_par_tous']}")
    add("  distribution (nb d'annotateurs signalant → nb de tâches) : "
        + ", ".join(f"{k}→{v}" for k, v in cov["distribution_nb_annotateurs_signalant"].items()))
    add("  distribution (nb d'annotateurs supprimant → nb de tâches) : "
        + ", ".join(f"{k}→{v}" for k, v in cov["distribution_nb_annotateurs_supprimant"].items()))

    add("\n## 3. Matrice de désaccord — « A supprime, B conserve intacte »\n")
    keys = stats["accord"]["annotateurs_retenus"]
    header = ["A \\ B"] + keys
    rows = []
    for a in keys:
        row = [a]
        for b in keys:
            row.append("·" if a == b else stats["desaccord"]["matrice_orientee"][f"{a}|{b}"][
                "supprimee_par_a_conservee_intacte_par_b"
            ])
        rows.append(row)
    add(_table(rows, header))
    add(f"\n  tâches en désaccord dur (supprimée par ≥1, conservée intacte par ≥1) : "
        f"{stats['desaccord']['taches_en_desaccord_dur']} "
        f"({100 * stats['desaccord']['taches_en_desaccord_dur'] / n:.1f} % du corpus)")
    unanimes = stats["desaccord"]["supprimee_par_tous_les_annotateurs"]
    add(f"  tâches supprimées par les six annotateurs : {len(unanimes)}")
    for item in unanimes:
        add(f"    {item['id']} — {item['question'][:90]}")
    add("\n  Les quinze tâches les plus disputées (produit suppressions × conservations) :\n")
    rows = [
        [
            t["id"],
            len(t["supprimee_par"]),
            len(t["conservee_intacte_par"]),
            t["categorie"] or "—",
            t["question"][:58],
        ]
        for t in stats["desaccord"]["taches_les_plus_disputees"]
    ]
    add(_table(rows, ["tâche", "suppr.", "conserv.", "cat.", "énoncé"]))

    acc = stats["accord"]
    add("\n## 4. Accord inter-annotateurs\n")
    add(f"  annotateurs retenus ({len(keys)}) : {', '.join(keys)}")
    for spec in acc["exclus"]:
        add(f"  exclu : {spec['cle']} — {spec['motif']}")
    add("")
    rows = [
        ["Fleiss κ — 3 catégories (keep/modify/remove)", acc["fleiss_3categories"]["kappa"],
         acc["fleiss_3categories"]["p_observe"], acc["fleiss_3categories"]["p_attendu"],
         acc["fleiss_3categories"]["lecture"]],
        ["Fleiss κ — binaire exclusion (remove vs reste)", acc["fleiss_exclusion"]["kappa"],
         acc["fleiss_exclusion"]["p_observe"], acc["fleiss_exclusion"]["p_attendu"],
         acc["fleiss_exclusion"]["lecture"]],
        ["Fleiss κ — binaire défaut (keep vs reste)", acc["fleiss_defaut"]["kappa"],
         acc["fleiss_defaut"]["p_observe"], acc["fleiss_defaut"]["p_attendu"],
         acc["fleiss_defaut"]["lecture"]],
        ["Gwet AC1 — 3 catégories", acc["gwet_ac1_3categories"]["ac1"],
         acc["gwet_ac1_3categories"]["p_observe"], acc["gwet_ac1_3categories"]["p_attendu"], ""],
        ["Gwet AC1 — binaire exclusion", acc["gwet_ac1_exclusion"]["ac1"],
         acc["gwet_ac1_exclusion"]["p_observe"], acc["gwet_ac1_exclusion"]["p_attendu"], ""],
    ]
    add(_table(rows, ["mesure", "valeur", "P_obs", "P_att", "lecture"]))

    cond = acc["conditionnel_taches_signalees"]
    add(f"\n  Accord conditionnel, sur les {cond['n_taches']} tâches signalées par au moins un "
        f"annotateur (sans l'accord trivial des tâches que personne ne conteste) :")
    add(f"    Fleiss κ 3 catégories = {cond['fleiss_3categories']['kappa']} "
        f"({cond['lecture_3cat']}), P_obs = {cond['fleiss_3categories']['p_observe']}")
    add(f"    Fleiss κ exclusion    = {cond['fleiss_exclusion']['kappa']}")

    add("\n  Sensibilité au périmètre des sources :\n")
    rows = [
        [name, v["n_sources"], v["fleiss_3categories"], v["fleiss_exclusion"]]
        for name, v in acc["sensibilite"].items()
    ]
    add(_table(rows, ["configuration", "n", "κ 3cat", "κ exclusion"]))

    add("\n  Kappa de Cohen par couple (3 catégories / exclusion / désaccord dur) :\n")
    rows = [
        [pair, v["accord_brut"], v["kappa_cohen_3cat"], v["kappa_cohen_exclusion"], v["desaccord_dur"]]
        for pair, v in sorted(acc["matrice_cohen"].items(), key=lambda kv: -kv[1]["kappa_cohen_3cat"])
    ]
    add(_table(rows, ["couple", "accord brut", "κ 3cat", "κ exclusion", "désaccord dur"]))

    rep = stats["reparations"]
    add("\n## 5. Le désaccord ne porte pas que sur le diagnostic, mais sur le correctif\n")
    add(f"  tâches réécrites par au moins deux annotateurs : {rep['taches_reecrites_par_2_annotateurs_ou_plus']}")
    add(f"  dont correctifs textuellement divergents      : {rep['dont_correctifs_divergents']} "
        f"({100 * (rep['part_divergente'] or 0):.1f} %)")
    add(f"  dont millésimes divergents (année du correctif) : {rep['dont_millesimes_divergents']} "
        f"({100 * (rep['part_millesimes_divergents'] or 0):.1f} %)")
    add(f"  nombre moyen de variantes par tâche réécrite  : {rep['variantes_moyennes']}")
    add("  distribution (nb de variantes → nb de tâches) : "
        + ", ".join(f"{k}→{v}" for k, v in rep["distribution_variantes"].items()))
    if rep["exemples"]:
        worst = rep["exemples"][0]
        add(f"\n  exemple — {worst['id']} : {worst['n_reecritures']} réécritures, "
            f"{worst['n_variantes_distinctes']} énoncés distincts")
        for text, keys in list(worst["variantes"].items())[:6]:
            add(f"    [{', '.join(keys)}] {text[:96]}")

    avm = stats["alumnium_vs_magnitude"]
    add("\n## 6. Vérification : Alumnium restaure-t-il ~30 tâches supprimées par Magnitude ?\n")
    add(f"  Magnitude supprime {avm['magnitude_supprime']} tâches, Alumnium {avm['alumnium_supprime']}.")
    add(f"  suppressions communes aux deux : {avm['suppressions_communes']}")
    add(f"  → {avm['verdict']}")
    add(f"  inversement, supprimées par Alumnium et conservées intactes par Magnitude : "
        f"{len(avm['supprimees_par_alumnium_conservees_intactes_par_magnitude'])} "
        f"{avm['supprimees_par_alumnium_conservees_intactes_par_magnitude']}")
    add(f"  catégories des restaurées : {dict(avm['categories_des_restaurees'])}")
    add(f"\n  {avm['correction_de_fond']}")

    tax = stats["taxonomie"]
    add("\n## 7. Prévalence par catégorie (121 raisons Magnitude relues à la main)\n")
    rows = []
    for cat in taxonomy.CATEGORIES:
        rows.append([
            cat.code,
            cat.label,
            tax["prevalence_principale"][cat.code],
            f"{tax['part_des_121'][cat.code]} %",
            f"{tax['part_du_corpus_643'][cat.code]} %",
            tax["prevalence_avec_secondaire"][cat.code],
        ])
    add(_table(rows, ["code", "catégorie", "n", "% des 121", "% des 643", "n (+ secondaires)"]))
    add(f"\n  cas frontaliers signalés `limite: true` : {tax['cas_limites']}/121")
    add(f"  répartition par action : réécritures {dict(tax['par_action']['modify'])}")
    add(f"                           suppressions {dict(tax['par_action']['remove'])}")
    add(f"\n  référence basse (classement par mots-clés) : {tax['reference_mots_cles']}")
    add(f"  accord mots-clés / relecture manuelle : {tax['accord_mots_cles_vs_manuel']['n_identiques']}/121 "
        f"({100 * tax['accord_mots_cles_vs_manuel']['taux']:.0f} %)")

    add("\n## 8. Courbe longitudinale — tâches signalées au fil des observations\n")
    add("  Les colonnes de droite ne comptent que les sources de confiance haute : Emergence "
        "réécrit\n  tous les énoncés en gabarits, sa présence gonflerait le cumul sans nouveau "
        "défaut constaté.\n")
    rows = [
        [t["date"], t["source"], t["signalees_par_cette_source"],
         t["nouvelles_confiance_haute"] if t["confiance"] == "haute" else "—",
         t["cumul_confiance_haute"], f"{t['cumul_confiance_haute_pct']} %", t["confiance"]]
        for t in stats["longitudinal"]
    ]
    add(_table(rows, ["date", "source", "signalées", "nouvelles", "cumul", "% du corpus",
                      "confiance"]))

    om = stats["om2w"]
    add("\n## 9. Contrepoint : Online-Mind2Web, benchmark maintenu\n")
    add(f"  {om['n_vagues']} vagues de remplacement du {om['premiere_vague']} au {om['derniere_vague']} ; "
        f"{om['remplacements_cumules']} remplacements cumulés portant sur "
        f"{om['taches_distinctes_remplacees']} tâches distinctes sur {om['taille_corpus']} "
        f"({100 * om['taches_distinctes_remplacees'] / om['taille_corpus']:.1f} % du corpus)")
    for wave in om["vagues"]:
        add(f"    {wave['date']} : {wave['n_taches']} tâche(s)")
    add("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Statistiques de désaccord entre patch-sets.")
    parser.add_argument("--json", type=Path, default=None, help="écrit les statistiques en JSON")
    parser.add_argument(
        "--embed",
        action="store_true",
        help="ajoute les statistiques à data/ground_truth.json sous la clé `statistiques`",
    )
    parser.add_argument("--raw-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    stats = compute_stats(args.raw_dir)
    print(format_report(stats))

    if args.json:
        args.json.write_text(json.dumps(stats, ensure_ascii=False, indent=1, default=dict) + "\n", "utf-8")
        print(f"→ {args.json}")
    if args.embed:
        path = reconcile.DEFAULT_OUTPUT
        database = json.loads(path.read_text(encoding="utf-8"))
        database["statistiques"] = json.loads(json.dumps(stats, default=dict))
        path.write_text(json.dumps(database, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"→ statistiques intégrées à {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
