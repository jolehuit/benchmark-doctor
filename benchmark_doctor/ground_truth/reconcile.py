#!/usr/bin/env python3
"""Fusionne les patch-sets en une base unifiée de verdicts : `data/ground_truth.json`.

Le produit est une ligne par tâche du corpus d'origine (643), portant la liste datée des
verdicts de chaque source et une synthèse d'accord :

```json
{
  "id": "Booking--8",
  "site": "Booking",
  "question_originale": "...",
  "verdicts": [{"source": "magnitude", "date": "2025-07-06", "action": "modify",
                "raison": "The booking date '20/12/2023' is explicitly in the past…",
                "nouvelle_question": "..."}],
  "accord": {"consensus": "modify", "unanime": false, "taux": 0.71, ...}
}
```

Deux partis pris, qui déterminent tout ce qui se calcule ensuite :

- **Le silence vaut conservation.** Une source qui publie un fichier de tâches sans
  mentionner une tâche l'a de fait conservée : c'est ce qui rend le nombre d'annotateurs
  constant et le kappa calculable. La limite est réelle — un patcheur peut n'avoir jamais
  examiné une tâche qu'il conserve.
- **Une réécriture n'est pas une suppression.** `modify` dit « défectueuse mais
  réparable », `remove` dit « à sortir du corpus ». Le désaccord dur, celui que les
  statistiques isolent, oppose `remove` chez l'un à `keep` chez l'autre.

Usage :
    python3 -m benchmark_doctor.ground_truth.reconcile [-o data/ground_truth.json]
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # exécution directe du fichier
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from benchmark_doctor.ground_truth import loaders, sources, taxonomy
else:
    from . import loaders, sources, taxonomy

KEEP, MODIFY, REMOVE = loaders.KEEP, loaders.MODIFY, loaders.REMOVE
DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "data" / "ground_truth.json"

__all__ = ["reconcile", "agreement_summary", "build_database", "main"]


def agreement_summary(
    verdicts: list[loaders.Verdict], annotator_keys: set[str]
) -> dict[str, Any]:
    """Synthétise l'accord des sources sur une tâche.

    Args:
        verdicts: tous les verdicts portés sur la tâche, y compris les sources de faible
            confiance.
        annotator_keys: clés des sources retenues pour l'accord (une par annotateur).

    Returns:
        ``consensus`` (action majoritaire, ``"conflit"`` en cas d'égalité stricte),
        ``unanime``, ``taux`` (part des annotateurs sur l'action majoritaire),
        ``n_annotateurs``, le décompte par action, et deux drapeaux de lecture :
        ``desaccord_exclusion`` (au moins un `remove` et au moins un `keep`) et
        ``jamais_signalee`` (aucune source n'a rien trouvé à redire).
    """
    retained = [v for v in verdicts if v.source in annotator_keys]
    counts = collections.Counter(v.action for v in retained)
    total = sum(counts.values())
    if not total:
        return {"consensus": None, "unanime": None, "taux": None, "n_annotateurs": 0}
    top = counts.most_common()
    majority_action, majority_n = top[0]
    tie = len(top) > 1 and top[1][1] == majority_n
    return {
        "consensus": "conflit" if tie else majority_action,
        "unanime": len(counts) == 1,
        "taux": round(majority_n / total, 3),
        "n_annotateurs": total,
        "actions": {a: counts.get(a, 0) for a in (KEEP, MODIFY, REMOVE)},
        "desaccord_exclusion": bool(counts.get(REMOVE) and counts.get(KEEP)),
        "signalee_par": sorted(v.source for v in retained if v.action != KEEP),
        "jamais_signalee": counts.get(KEEP, 0) == total,
    }


def reconcile(raw_dir: Path | None = None) -> dict[str, Any]:
    """Construit la base unifiée en mémoire.

    Returns:
        Le dictionnaire complet (métadonnées, tâches, journal Online-Mind2Web), prêt à
        être sérialisé.
    """
    original, per_source, reports = loaders.load_all(raw_dir)
    annotator_keys = set(sources.ANNOTATORS)
    order = [spec.key for spec in sources.SOURCES]
    labels = taxonomy.load_manual_labels()

    tasks: list[dict[str, Any]] = []
    for tid, task in original.items():
        task_verdicts = [per_source[key][tid] for key in order if tid in per_source[key]]
        record: dict[str, Any] = {
            "id": tid,
            "site": task.site,
            "question_originale": task.question,
            "url": task.url,
            "verdicts": [v.to_dict() for v in task_verdicts],
            "accord": agreement_summary(task_verdicts, annotator_keys),
        }
        label = labels.get(tid)
        if label:
            record["taxonomie"] = {
                "categorie": label["categorie"],
                "categorie_secondaire": label["categorie_secondaire"],
                "limite": label["limite"],
                "source_etiquette": "relecture manuelle des raisons Magnitude",
            }
        tasks.append(record)

    tasks.sort(key=lambda r: (r["site"], int(r["id"].rsplit("--", 1)[1])))

    return {
        "meta": {
            "benchmark": "WebVoyager",
            "corpus": "MinorJerry/WebVoyager @ 0915445 (2024-03-02), 643 tâches",
            "genere_le": dt.date.today().isoformat(),
            "outil": "benchmark-doctor / ground_truth.reconcile",
            "n_taches": len(tasks),
            "n_sources": len(order),
            "sources": [
                {
                    "cle": s.key,
                    "libelle": s.label,
                    "annotateur": s.annotator,
                    "date": s.date,
                    "depot": s.repo,
                    "commit": s.commit,
                    "exprime": s.expresses,
                    "confiance": s.confidence,
                    "compte_dans_accord": s.counted_in_agreement,
                    "reserve": s.note,
                    "effectifs": reports["effectifs"][s.key],
                }
                for s in sources.SOURCES
            ],
            "conventions": {
                "actions": {
                    "keep": "tâche conservée telle quelle par la source",
                    "modify": "énoncé réécrit par la source (défaut jugé réparable)",
                    "remove": "tâche exclue du corpus par la source",
                },
                "silence_vaut_conservation": (
                    "une source qui ne mentionne pas une tâche est comptée `keep` : ses "
                    "fichiers la conservent de fait"
                ),
                "accord": (
                    f"calculé sur les {len(annotator_keys)} sources à annotateur distinct "
                    f"({', '.join(sorted(annotator_keys))}) ; skyvern_2025 et emergence en sont "
                    "exclus (annotateur dupliqué, exclusions non attribuables au decay)"
                ),
                "regle_arbitrage_taxonomie": taxonomy.ARBITRATION_RULE,
            },
            "appariement_emergence": reports.get("emergence"),
        },
        "taxonomie": [
            {"code": c.code, "libelle": c.label, "definition": c.definition, "exemple": c.exemple}
            for c in taxonomy.CATEGORIES
        ],
        "taches": tasks,
        "om2w_journal": loaders.load_om2w_journal(raw_dir),
    }


def build_database(output: Path | None = None, raw_dir: Path | None = None) -> Path:
    """Écrit `data/ground_truth.json` et renvoie son chemin."""
    database = reconcile(raw_dir)
    path = output or DEFAULT_OUTPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(database, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fusionne les patch-sets WebVoyager.")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    path = build_database(args.output, args.raw_dir)
    database = json.loads(path.read_text(encoding="utf-8"))
    tasks = database["taches"]
    never = sum(1 for t in tasks if t["accord"]["jamais_signalee"])
    conflict = sum(1 for t in tasks if t["accord"]["desaccord_exclusion"])
    unanimous = sum(1 for t in tasks if t["accord"]["unanime"])
    print(f"Écrit {path} ({path.stat().st_size // 1024} Kio)")
    print(f"  {len(tasks)} tâches × {database['meta']['n_sources']} sources")
    print(f"  jamais signalée par aucun annotateur : {never} ({100 * never / len(tasks):.1f} %)")
    print(f"  verdict unanime : {unanimous} ({100 * unanimous / len(tasks):.1f} %)")
    print(f"  désaccord d'exclusion (remove chez l'un, keep chez l'autre) : {conflict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
