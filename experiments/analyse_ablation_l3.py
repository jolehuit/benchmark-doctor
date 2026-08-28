"""Analyses complémentaires de l'ablation L3 : significativité, rappel par critère, fuite.

Le banc `ablation_l3_clean.py` produit les prédictions ; ce script en tire trois lectures que
le tableau ne porte pas.

Significativité entre exécutions. Le McNemar du banc oppose *une* exécution de chaque juge,
ce qui est le pire cas de puissance : cinq exécutions à température 0 donnent cinq
échantillons appariés. On publie ici un test exact de Mann-Whitney sur les cinq F1 de chaque
famille, où deux étendues disjointes ne laissent qu'une valeur de p possible, 2/C(10,5) =
0,0079, et un McNemar sur le verdict majoritaire des cinq exécutions, qui a plus de puissance
qu'un McNemar sur un tirage.

Rappel par critère d'ambiguïté (A1-A4). C'est là que la fuite était censée payer : les quatre
énoncés recopiés couvraient A2 et A3, et la mesure initiale y donnait le juge supérieur. La
question est de savoir si cette supériorité survit à une rubrique propre.

Où passent les cinq items dont une formulation figurait dans l'ancienne rubrique. Le juge
fuité les reconnaît-il mieux que le juge propre, et de combien ?

    python experiments/analyse_ablation_l3.py [runs/ablation_l3_clean_20260816.json]
"""

from __future__ import annotations

import itertools
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.ablation_ambiguity import mcnemar_exact, prf  # noqa: E402

ANNOTATIONS = ROOT / "data" / "annotations_ambiguity.json"


def mann_whitney_exact(a: list[float], b: list[float]) -> float:
    """p bilatéral exact du test de Mann-Whitney (petits échantillons, ex æquo à 0,5)."""
    n, m = len(a), len(b)
    observed = sum(1.0 if x > y else 0.5 if x == y else 0.0 for x in a for y in b)
    pool = a + b
    extreme = 0
    total = 0
    for combo in itertools.combinations(range(n + m), n):
        left = [pool[i] for i in combo]
        right = [pool[i] for i in range(n + m) if i not in set(combo)]
        u = sum(1.0 if x > y else 0.5 if x == y else 0.0 for x in left for y in right)
        total += 1
        if abs(u - n * m / 2) >= abs(observed - n * m / 2) - 1e-9:
            extreme += 1
    return extreme / total


def majority(preds: list[list[int]]) -> list[int]:
    """Verdict majoritaire de plusieurs exécutions, item par item."""
    return [1 if sum(col) * 2 > len(col) else 0 for col in zip(*preds)]


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else ROOT / "runs" / "ablation_l3_clean_20260816.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    items = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))["items"]
    labels = [int(i["label"]) for i in items]
    task_ids = [i["task_id"] for i in items]
    criteria = [set(i["criteria"]) for i in items]
    leaked = set(d["protocol"]["leaked_task_ids"])

    judges = {j["key"]: j for j in d["judges"]}
    classical = {r["key"]: r for r in d["classical"]}
    verdicts: dict[str, list[int]] = {k: r["youden"]["oof_pred"] for k, r in classical.items()}
    for k, j in judges.items():
        verdicts[k] = majority([r["youden"]["oof_pred"] for r in j["runs"]])
    f1s = {k: j["youden_pooled_f1"]["values"] for k, j in judges.items()}

    print("=== 1a. Mann-Whitney exact sur les 5 F1 de chaque famille de juge ===")
    pairs = [("d_judge_clean", "d_judge_leaky"), ("d_judge_clean", "d_judge_plain"),
             ("d_judge_clean", "d_lite_clean"), ("d_lite_clean", "d_lite_leaky"),
             ("d_judge_leaky", "d_judge_plain")]
    for a, b in pairs:
        p = mann_whitney_exact(f1s[a], f1s[b])
        print(f"  {a:16s} {statistics.mean(f1s[a]):.3f} vs {b:16s} "
              f"{statistics.mean(f1s[b]):.3f}  p = {p:.4f}"
              f"{'  (étendues disjointes)' if max(f1s[a]) < min(f1s[b]) or max(f1s[b]) < min(f1s[a]) else ''}")

    print("\n=== 1b. McNemar sur le VERDICT MAJORITAIRE des 5 exécutions ===")
    duels = [("d_judge_clean", "a_tfidf"), ("d_judge_clean", "c_openrouter_embed"),
             ("d_judge_clean", "b_minilm"), ("d_judge_clean", "site_majority"),
             ("d_judge_clean", "heuristic"), ("d_judge_clean", "always_positive"),
             ("d_judge_clean", "d_judge_leaky"), ("d_judge_clean", "d_judge_plain"),
             ("a_tfidf", "c_openrouter_embed"), ("a_tfidf", "b_minilm"),
             ("a_tfidf", "site_majority"), ("a_tfidf", "always_positive")]
    for a, b in duels:
        t = mcnemar_exact(labels, verdicts[a], verdicts[b])
        fa, fb = prf(labels, verdicts[a])["f1"], prf(labels, verdicts[b])["f1"]
        star = "  ***" if t["p_value"] < 0.01 else ("  *" if t["p_value"] < 0.05 else "")
        print(f"  {a:20s} (F1 {fa:.3f}) vs {b:20s} (F1 {fb:.3f}) : "
              f"{t['a_only_correct']:3d} / {t['b_only_correct']:3d}  p = {t['p_value']:.4f}{star}")

    print("\n=== 1c. McNemar restreint aux positifs / aux négatifs ===")
    # Le McNemar global mêle deux questions : « qui trouve plus de positifs ? » et « qui
    # se trompe moins sur les négatifs ? ». Quand deux approches ont le même rappel, seule
    # la seconde a un sens, et c'est elle qui porte le résultat du juge propre.
    pos = [i for i, y in enumerate(labels) if y == 1]
    neg = [i for i, y in enumerate(labels) if y == 0]
    for a, b in [("d_judge_clean", "a_tfidf"), ("d_judge_clean", "c_openrouter_embed"),
                 ("d_judge_clean", "d_judge_leaky")]:
        for name, idx in (("55 positifs", pos), ("84 négatifs", neg)):
            t = mcnemar_exact([labels[i] for i in idx],
                              [verdicts[a][i] for i in idx], [verdicts[b][i] for i in idx])
            star = "  ***" if t["p_value"] < 0.01 else ("  *" if t["p_value"] < 0.05 else "")
            print(f"  {a:16s} vs {b:20s} sur les {name:12s} : "
                  f"{t['a_only_correct']:3d} / {t['b_only_correct']:3d}  "
                  f"p = {t['p_value']:.4f}{star}")

    print("\n=== 2. Rappel par critère d'ambiguïté (verdict majoritaire) ===")
    codes = sorted({c for s in criteria for c in s})
    cols = ["a_tfidf", "c_openrouter_embed", "d_judge_clean", "d_judge_leaky", "d_judge_plain"]
    print("| critère | n | " + " | ".join(cols) + " |")
    print("|---|---:|" + "---:|" * len(cols))
    for code in codes:
        idx = [i for i, s in enumerate(criteria) if code in s]
        cells = []
        for k in cols:
            hit = sum(1 for i in idx if verdicts[k][i] == 1)
            cells.append(f"{hit}/{len(idx)} ({hit / len(idx):.0%})")
        print(f"| {code} | {len(idx)} | " + " | ".join(cells) + " |")
    # Les négatifs : combien chaque approche en signale à tort.
    neg = [i for i, y in enumerate(labels) if y == 0]
    cells = [f"{sum(1 for i in neg if verdicts[k][i] == 1)}/{len(neg)}" for k in cols]
    print(f"| faux positifs | {len(neg)} | " + " | ".join(cells) + " |")

    print("\n=== 3. Les cinq items dont une formulation figurait dans l'ancienne rubrique ===")
    print("| item | label | " + " | ".join(cols) + " |")
    print("|---|---:|" + "---:|" * len(cols))
    for t in d["protocol"]["leaked_task_ids"]:
        i = task_ids.index(t)
        cells = ["oui" if verdicts[k][i] == labels[i] else "non" for k in cols]
        print(f"| {t} | {labels[i]} | " + " | ".join(cells) + " |")
    keep = [t not in leaked for t in task_ids]
    print()
    for k in cols:
        full = prf(labels, verdicts[k])
        sub = prf([l for l, m in zip(labels, keep) if m], [p for p, m in zip(verdicts[k], keep) if m])
        print(f"  {k:20s} F1 139 items {full['f1']:.3f} → 134 items {sub['f1']:.3f} "
              f"(écart {sub['f1'] - full['f1']:+.3f})")

    print("\n=== 4. Point de fonctionnement : ce que le juge propre achète ===")
    for k in cols:
        m = prf(labels, verdicts[k])
        print(f"  {k:20s} P {m['precision']:.3f} R {m['recall']:.3f} F1 {m['f1']:.3f} "
              f"· signale {m['tp'] + m['fp']:3d}/139 · VP {m['tp']:2d} FP {m['fp']:2d} FN {m['fn']:2d}")

    print("\n=== 5. Intervalle de confiance binomial (Wilson 95 %) sur la précision ===")
    for k in ("a_tfidf", "d_judge_clean", "d_judge_leaky"):
        m = prf(labels, verdicts[k])
        n, x = m["tp"] + m["fp"], m["tp"]
        if n:
            p = x / n
            z = 1.96
            centre = (p + z * z / (2 * n)) / (1 + z * z / n)
            half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
            print(f"  {k:20s} P = {p:.3f}  IC95 [{centre - half:.3f} ; {centre + half:.3f}]  (n = {n})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
