"""Met en forme les tableaux de l'ablation L3 depuis le JSON produit par le banc.

Les tableaux partent sur la sortie standard, prêts à coller : ce sont eux que publie
`experiments/CONTRE_VERIFICATION.md`. Aucun chiffre n'est recopié à la main, de sorte
qu'une ré-exécution du banc et un `python experiments/render_ablation_l3.py` suffisent à
republier des tableaux cohérents avec l'artefact.

    python experiments/render_ablation_l3.py [runs/ablation_l3_clean_20260816.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fmt(x: float, n: int = 3) -> str:
    return f"{x:.{n}f}".replace(".", ",")


def pm(block: dict, n: int = 3) -> str:
    return f"{fmt(block['mean'], n)} ± {fmt(block['std_between_runs'], n)}"


def span(block: dict, n: int = 3) -> str:
    return f"{fmt(block['min'], n)}–{fmt(block['max'], n)}"


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else ROOT / "runs" / "ablation_l3_clean_20260816.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    classical = {r["key"]: r for r in d["classical"]}
    judges = {j["key"]: j for j in d["judges"]}

    print("### Tableau 1 — les quatre approches, seuil J de Youden (hors plis)\n")
    print("| Approche | P | R | F1 | AUC | σ inter-plis | σ inter-exéc. | Coût / 139 |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    order = ["always_positive", "site_majority", "heuristic", "a_tfidf", "b_minilm", "c_openrouter_embed"]
    for k in order:
        r = classical.get(k)
        if not r:
            continue
        y = r["youden"]["pooled"]
        cost = f"{r['cost_usd']:.5f} $".replace(".", ",") if r["cost_usd"] else "0 $"
        print(f"| {r['label']} | {fmt(y['precision'])} | {fmt(y['recall'])} | **{fmt(y['f1'])}** | "
              f"{fmt(r['youden']['auc'])} | {fmt(r['youden']['f1_std_between_folds'])} | — | {cost} |")
    for k, j in judges.items():
        cost = f"{j['cost_usd']:.5f} $".replace(".", ",")
        print(f"| {j['label']} | {pm(j['youden_pooled_precision'])} | {pm(j['youden_pooled_recall'])} | "
              f"**{pm(j['youden_pooled_f1'])}** | {pm(j['auc'])} | "
              f"{fmt(j['f1_std_between_folds']['mean'])} | {fmt(j['youden_pooled_f1']['std_between_runs'])} | {cost} |")

    print("\n### Tableau 2 — le même jeu de notes au seuil fixe 0,5 (aucune calibration)\n")
    print("| Approche | P | R | F1 |")
    print("|---|---:|---:|---:|")
    for k in order:
        r = classical.get(k)
        if not r:
            continue
        f = r["youden"]["fixed_0_5"]
        print(f"| {r['label']} | {fmt(f['precision'])} | {fmt(f['recall'])} | **{fmt(f['f1'])}** |")
    for k, j in judges.items():
        print(f"| {j['label']} | {pm(j['fixed_precision'])} | {pm(j['fixed_recall'])} | "
              f"**{pm(j['fixed_f1'])}** |")

    print("\n### Tableau 3 — ce que change le critère de calibration (F1 hors plis)\n")
    print("| Approche | seuil J (publié) | seuil fixe 0,5 | seuil max-F1 (ancien critère) |")
    print("|---|---:|---:|---:|")
    for k in order:
        r = classical.get(k)
        if not r:
            continue
        print(f"| {r['label']} | {fmt(r['youden']['pooled']['f1'])} | "
              f"{fmt(r['youden']['fixed_0_5']['f1'])} | {fmt(r['f1max']['pooled']['f1'])} |")
    for k, j in judges.items():
        print(f"| {j['label']} | {pm(j['youden_pooled_f1'])} | {pm(j['fixed_f1'])} | "
              f"{pm(j['f1max_pooled_f1'])} |")

    print("\n### Tableau 4 — les cinq exécutions de chaque juge, une par une (F1 hors plis, seuil J)\n")
    heads = " | ".join(f"exéc. {i + 1}" for i in range(max(j["n_runs"] for j in judges.values())))
    print(f"| Juge | {heads} | moyenne | σ | étendue |")
    print("|---" * (2 + max(j["n_runs"] for j in judges.values()) + 3 - 1) + "|")
    for k, j in judges.items():
        vals = " | ".join(fmt(v) for v in j["youden_pooled_f1"]["values"])
        print(f"| {j['label']} | {vals} | **{fmt(j['youden_pooled_f1']['mean'])}** | "
              f"{fmt(j['youden_pooled_f1']['std_between_runs'])} | {span(j['youden_pooled_f1'])} |")

    print("\n### Tableau 5 — effet de la fuite : F1 avec et sans les cinq items fuités\n")
    print("| Approche | F1 sur les 139 | F1 sur les 134 (hors items fuités) | écart |")
    print("|---|---:|---:|---:|")
    for k in order:
        r = classical.get(k)
        if not r:
            continue
        a, b = r["youden"]["pooled"]["f1"], r["f1_excluding_leaked"]["f1"]
        print(f"| {r['label']} | {fmt(a)} | {fmt(b)} | {fmt(b - a, 3)} |")
    for k, j in judges.items():
        a, b = j["youden_pooled_f1"]["mean"], j["youden_f1_excluding_leaked"]["mean"]
        print(f"| {j['label']} | {pm(j['youden_pooled_f1'])} | {pm(j['youden_f1_excluding_leaked'])} | "
              f"{fmt(b - a, 3)} |")

    print("\n### McNemar (exécution 1 de chaque juge, prédictions hors plis)\n")
    print("| A | B | A seul correct | B seul correct | p |")
    print("|---|---|---:|---:|---:|")
    interesting = {("d_judge_clean", "d_judge_leaky"), ("d_judge_clean", "a_tfidf"),
                   ("a_tfidf", "d_judge_clean"), ("d_judge_clean", "d_judge_plain"),
                   ("a_tfidf", "b_minilm"), ("a_tfidf", "c_openrouter_embed"),
                   ("d_judge_clean", "c_openrouter_embed"), ("d_judge_clean", "site_majority"),
                   ("d_judge_leaky", "d_judge_plain"), ("d_lite_clean", "d_lite_leaky"),
                   ("d_judge_clean", "d_lite_clean")}
    for c in d["mcnemar"]:
        if (c["a"], c["b"]) in interesting or (c["b"], c["a"]) in interesting:
            print(f"| {c['a']} | {c['b']} | {c['a_only_correct']} | {c['b_only_correct']} | "
                  f"{fmt(c['p_value'], 4)} |")

    print("\n### Histogrammes de notes (exécution 1)\n")
    for k, j in judges.items():
        print(f"- `{k}` : {j['score_histogram']} · taux de bascule à 0,5 sur 5 exécutions : "
              f"{fmt(j['verdict_flip_rate_at_0_5'] * 100, 1)} %")

    print(f"\nTF-IDF : précision in-sample {d['tfidf_in_sample_warning']['in_sample_precision']} "
          f"contre {d['tfidf_in_sample_warning']['out_of_fold_precision']} hors plis")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
