"""Ablation L3 rejouée à rubrique propre — correction du problème bloquant B1.

Ce banc reprend `experiments/ablation_ambiguity.py` (même jeu annoté, mêmes plis, mêmes
primitives de mesure, importées et non recopiées) et corrige les quatre défauts que la
vérification adverse du 16/08/2026 lui a trouvés :

**B1 — fuite du jeu de test dans le prompt du juge.** L'ancienne rubrique contenait des
énoncés du jeu évalué recopiés mot pour mot. Elle est réécrite avec des exemples
fabriqués (cf. le commentaire de ``_RUBRIC`` et `experiments/check_rubric_leak.py`), et
les deux versions sont mesurées côte à côte : *leaky* rejoue la rubrique du 15/08,
*clean* exécute la nouvelle. L'écart entre les deux est la valeur de la fuite.

**C1 — un maximum publié pour une moyenne.** Le F1 0,827 était le meilleur de quatre
exécutions. Chaque juge est ici exécuté ``JUDGE_RUNS`` fois (variantes de cache
indépendantes, même prompt, même température) et le tableau publie **moyenne et
écart-type inter-exécutions**, à côté — et jamais à la place — de l'écart-type
inter-plis. Les deux dispersions mesurent des choses différentes et portent des noms
différents.

**C2 — un seuil calibré qui dégénère.** La calibration par maximisation du F1 choisit la
ligne « tout positif » dès que les notes séparent mal les classes. Le tableau principal
est donc calibré sur le **J de Youden**, qui vaut 0 pour toute règle ignorant l'énoncé,
et le **seuil fixe 0,5** est publié en regard. Le seuil F1 reste calculé, comme témoin
de la dégénérescence.

**C13 — TF-IDF in-sample.** Aucune métrique in-sample n'est produite ici : toutes les
lignes sont hors plis. La précision apparente de 0,964 du backend ``tfidf`` entraîné sur
les 139 annotations puis appliqué à ces mêmes 139 tâches est recalculée **uniquement**
pour être publiée comme un artefact à ne pas citer (champ ``tfidf_in_sample_warning``).

Sorties : un JSON dans ``runs/`` et le tableau Markdown de `experiments/ABLATION_L3.md`.

    python experiments/ablation_l3_clean.py --offline    # (a), (b) et références, 0 $
    python experiments/ablation_l3_clean.py              # tout, coût réel relevé
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_doctor.detectors.l3_ambiguity import (  # noqa: E402
    AnnotatedSet,
    EmbeddingScorer,
    LlmJudgeScorer,
    MiniLmEmbedder,
    OpenRouterEmbedder,
    TfidfScorer,
    calibrate_threshold,
    calibrate_threshold_youden,
    load_annotations,
)
from benchmark_doctor.detectors.l3_client import (  # noqa: E402
    CHEAP_CHAT_MODEL,
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBED_MODEL,
    CostLedger,
    OpenRouterClient,
)

# Les primitives de mesure sont importées du banc d'origine : deux implémentations de
# McNemar ou de l'AUC dans le même dépôt, ce serait deux occasions de diverger.
from experiments.ablation_ambiguity import (  # noqa: E402
    CV_SEED,
    N_SPLITS,
    _HeuristicScorer,
    _SiteMajorityScorer,
    mcnemar_exact,
    prf,
    roc_auc,
    stratified_folds,
)
from experiments.check_rubric_leak import LEAKY_RUBRIC  # noqa: E402

ANNOTATIONS = ROOT / "data" / "annotations_ambiguity.json"

#: Nombre d'exécutions indépendantes de chaque juge. Quatre suffisaient à montrer que le
#: chiffre publié était un maximum ; cinq est le minimum honnête pour publier un σ.
JUDGE_RUNS = 5

#: Étiquettes de cache des exécutions. Les quatre premières de la rubrique fuitée
#: existent déjà (``None``, ``v1``, ``v2``, ``v3``) : elles sont resservies à 0 $, ce qui
#: rend la comparaison avant/après gratuite pour sa moitié.
LEAKY_VARIANTS = [None, "v1", "v2", "v3", "v4"]
CLEAN_VARIANTS = ["c1", "c2", "c3", "c4", "c5"]
PLAIN_VARIANTS = [None, "p2", "p3", "p4", "p5"]

#: Les cinq items du jeu annoté dont une formulation figurait dans l'ancienne rubrique.
#: Quatre positifs (relevés par la vérification adverse) **et un négatif** — GitHub--28,
#: dont « most starred » était le contre-exemple négatif de la rubrique — que la
#: vérification avait manqué. Retirer les cinq donne le F1 « hors fuite ».
LEAKED_TASK_IDS = ["Apple--11", "Coursera--0", "GitHub--5", "Huggingface--23", "GitHub--28"]


# Validation croisée


def cv_from_scores(
    scores: Sequence[float],
    labels: Sequence[int],
    folds: Sequence[Sequence[int]],
    calibrator: Callable[[Sequence[float], Sequence[int]], float],
) -> dict[str, Any]:
    """Validation croisée d'un vecteur de notes fixe (juge, ou scorer déjà appliqué).

    Le juge ne s'entraîne pas : ses notes ne dépendent pas du pli. Seul le **seuil** est
    appris, sur les plis d'entraînement, puis appliqué au pli de test — exactement le
    protocole du banc d'origine, mais avec un calibrateur enfichable.
    """
    n = len(labels)
    oof_pred = [0] * n
    thresholds: list[float] = []
    per_fold: list[dict[str, float]] = []
    for fold_id, test_idx in enumerate(folds):
        test = set(test_idx)
        train_idx = [i for i in range(n) if i not in test]
        t = calibrator([scores[i] for i in train_idx], [labels[i] for i in train_idx])
        for i in test_idx:
            oof_pred[i] = 1 if scores[i] >= t else 0
        thresholds.append(t)
        m = prf([labels[i] for i in test_idx], [oof_pred[i] for i in test_idx])
        m["fold"], m["threshold"], m["n_test"] = fold_id, t, len(test_idx)
        per_fold.append(m)
    return _package(labels, list(scores), oof_pred, thresholds, per_fold)


def cv_refit(
    factory: Callable[[Sequence[str], Sequence[int]], Any],
    data: AnnotatedSet,
    folds: Sequence[Sequence[int]],
    calibrator: Callable[[Sequence[float], Sequence[int]], float],
) -> dict[str, Any]:
    """Validation croisée d'un classifieur réentraîné à chaque pli (TF-IDF, embeddings)."""
    n = len(data)
    oof_pred = [0] * n
    oof_score = [0.0] * n
    thresholds: list[float] = []
    per_fold: list[dict[str, float]] = []
    for fold_id, test_idx in enumerate(folds):
        test = set(test_idx)
        train_idx = [i for i in range(n) if i not in test]
        scorer = factory([data.texts[i] for i in train_idx], [data.labels[i] for i in train_idx])
        t = calibrator(
            scorer.score([data.texts[i] for i in train_idx]),
            [data.labels[i] for i in train_idx],
        )
        scores = scorer.score([data.texts[i] for i in test_idx])
        for i, s in zip(test_idx, scores):
            oof_score[i] = float(s)
            oof_pred[i] = 1 if s >= t else 0
        thresholds.append(t)
        m = prf([data.labels[i] for i in test_idx], [oof_pred[i] for i in test_idx])
        m["fold"], m["threshold"], m["n_test"] = fold_id, t, len(test_idx)
        per_fold.append(m)
    return _package(data.labels, oof_score, oof_pred, thresholds, per_fold)


def _package(labels, oof_score, oof_pred, thresholds, per_fold) -> dict[str, Any]:
    def agg(key: str) -> tuple[float, float]:
        v = [m[key] for m in per_fold]
        return statistics.mean(v), (statistics.stdev(v) if len(v) > 1 else 0.0)

    f1_mean, f1_std = agg("f1")
    p_mean, _ = agg("precision")
    r_mean, _ = agg("recall")
    return {
        "pooled": prf(labels, oof_pred),
        "fixed_0_5": prf(labels, [1 if s >= 0.5 else 0 for s in oof_score]),
        "auc": roc_auc(labels, oof_score),
        "f1_mean_folds": f1_mean,
        # Nommé sans équivoque : c'est la dispersion ENTRE PLIS, pas entre exécutions.
        "f1_std_between_folds": f1_std,
        "precision_mean_folds": p_mean,
        "recall_mean_folds": r_mean,
        "thresholds": thresholds,
        "per_fold": per_fold,
        "oof_pred": oof_pred,
        "oof_score": [round(float(s), 4) for s in oof_score],
    }


def subset_metrics(labels: Sequence[int], preds: Sequence[int], keep: Sequence[bool]) -> dict[str, float]:
    """Métriques restreintes à un sous-ensemble (ici : hors items fuités)."""
    y = [l for l, k in zip(labels, keep) if k]
    p = [q for q, k in zip(preds, keep) if k]
    return prf(y, p)


# Approches


def judge_scores(
    texts: Sequence[str],
    *,
    model: str,
    prompt: str,
    system: str | None,
    variant: str | None,
    workers: int,
    label: str,
) -> tuple[list[float], CostLedger, float]:
    ledger = CostLedger(label=label)
    client = OpenRouterClient(ledger=ledger)
    try:
        judge = LlmJudgeScorer(
            client, model=model, prompt=prompt, system=system, variant=variant, max_workers=workers
        )
        t0 = time.perf_counter()
        scores = judge.score(list(texts))
        elapsed = time.perf_counter() - t0
        if judge.unparsed:
            print(f"    {judge.unparsed} réponses illisibles (0,5 imputé)")
    finally:
        client.close()
    return scores, ledger, elapsed


def run_judge_family(
    key: str,
    label: str,
    *,
    data: AnnotatedSet,
    folds: Sequence[Sequence[int]],
    model: str,
    prompt: str,
    system: str | None,
    variants: Sequence[str | None],
    workers: int,
    budget: float,
    spent: list[float],
) -> dict[str, Any]:
    """Exécute un juge ``len(variants)`` fois et agrège moyenne et σ INTER-EXÉCUTIONS."""
    runs: list[dict[str, Any]] = []
    all_scores: list[list[float]] = []
    ledgers: list[dict[str, Any]] = []
    print(f"  {label}")
    for variant in variants:
        scores, ledger, elapsed = judge_scores(
            data.texts, model=model, prompt=prompt, system=system, variant=variant,
            workers=workers, label=f"{key}-{variant}",
        )
        spent[0] += ledger.cost_usd
        if spent[0] > budget:
            raise SystemExit(
                f"budget dépassé : {spent[0]:.4f} $ > {budget:.4f} $ — exécution interrompue"
            )
        all_scores.append(scores)
        ledgers.append(ledger.to_dict())
        runs.append(
            {
                "variant": str(variant),
                "youden": cv_from_scores(scores, data.labels, folds, calibrate_threshold_youden),
                "f1max": cv_from_scores(scores, data.labels, folds, calibrate_threshold),
            }
        )
        y = runs[-1]["youden"]
        print(f"    {str(variant):5s} : F1 hors plis {y['pooled']['f1']:.3f} "
              f"(seuil J {statistics.mean(y['thresholds']):.2f}) · "
              f"F1@0,5 {y['fixed_0_5']['f1']:.3f} · AUC {y['auc']:.3f} · "
              f"{ledger.calls} appels, {ledger.cost_usd:.5f} $ "
              f"({ledger.cached_calls} en cache)")

    def across(path: Callable[[dict[str, Any]], float]) -> dict[str, float]:
        v = [path(r) for r in runs]
        return {
            "mean": statistics.mean(v),
            # Dispersion ENTRE EXÉCUTIONS du même prompt à température 0. C'est elle que
            # le tableau du 15/08 n'avait jamais mesurée.
            "std_between_runs": statistics.stdev(v) if len(v) > 1 else 0.0,
            "min": min(v),
            "max": max(v),
            "values": [round(x, 4) for x in v],
        }

    keep = [t not in set(LEAKED_TASK_IDS) for t in data.task_ids]
    return {
        "key": key,
        "label": label,
        "n_runs": len(runs),
        "runs": runs,
        "youden_pooled_f1": across(lambda r: r["youden"]["pooled"]["f1"]),
        "youden_pooled_precision": across(lambda r: r["youden"]["pooled"]["precision"]),
        "youden_pooled_recall": across(lambda r: r["youden"]["pooled"]["recall"]),
        "fixed_f1": across(lambda r: r["youden"]["fixed_0_5"]["f1"]),
        "fixed_precision": across(lambda r: r["youden"]["fixed_0_5"]["precision"]),
        "fixed_recall": across(lambda r: r["youden"]["fixed_0_5"]["recall"]),
        "f1max_pooled_f1": across(lambda r: r["f1max"]["pooled"]["f1"]),
        "auc": across(lambda r: r["youden"]["auc"]),
        "f1_std_between_folds": across(lambda r: r["youden"]["f1_std_between_folds"]),
        # F1 hors plis calculé sans les cinq items dont une formulation figurait dans
        # l'ancienne rubrique : la mesure comparable entre les deux versions du prompt.
        "youden_f1_excluding_leaked": across(
            lambda r: subset_metrics(data.labels, r["youden"]["oof_pred"], keep)["f1"]
        ),
        "score_histogram": dict(sorted(collections.Counter(round(s, 1) for s in all_scores[0]).items())),
        "verdict_flip_rate_at_0_5": round(
            sum(1 for i in range(len(data)) if len({1 if r[i] >= 0.5 else 0 for r in all_scores}) > 1)
            / len(data),
            4,
        ),
        "ledgers": ledgers,
        "cost_first_run_usd": round(sum(l["first_run_cost_usd"] for l in ledgers), 6),
        "cost_spent_usd": round(sum(l["cost_usd"] for l in ledgers), 6),
    }


# Commande


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="approches gratuites seulement")
    parser.add_argument("--no-local", action="store_true", help="saute MiniLM")
    parser.add_argument("--chat-model", default=DEFAULT_CHAT_MODEL)
    parser.add_argument("--cheap-model", default=CHEAP_CHAT_MODEL)
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--budget-usd", type=float, default=0.42,
                        help="plafond de dépense réelle ; l'exécution s'interrompt au-delà")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    data = load_annotations(ANNOTATIONS)
    folds = stratified_folds(data.labels, N_SPLITS, CV_SEED)
    site_of = {t: s for t, s in zip(data.texts, data.sites)}
    keep = [t not in set(LEAKED_TASK_IDS) for t in data.task_ids]
    spent = [0.0]

    print(f"jeu annoté : {len(data)} tâches, {sum(data.labels)} positives "
          f"({data.positive_rate:.1%}) · {N_SPLITS} plis stratifiés, graine {CV_SEED}")
    print(f"items fuités retirés pour la mesure « hors fuite » : {LEAKED_TASK_IDS}")
    print()

    classical: list[dict[str, Any]] = []

    def add(key: str, label: str, factory, *, note: str = "", ledger: CostLedger | None = None) -> None:
        y = cv_refit(factory, data, folds, calibrate_threshold_youden)
        f = cv_refit(factory, data, folds, calibrate_threshold)
        entry = {
            "key": key, "label": label, "note": note,
            "youden": y, "f1max": f,
            "f1_excluding_leaked": subset_metrics(data.labels, y["oof_pred"], keep),
            "cost_first_run_usd": round(ledger.first_run_cost_usd, 6) if ledger else 0.0,
            "cost_spent_usd": round(ledger.cost_usd, 6) if ledger else 0.0,
        }
        classical.append(entry)
        print(f"  {label}\n    F1 hors plis {y['pooled']['f1']:.3f} (J) · "
              f"{f['pooled']['f1']:.3f} (F1max) · {y['fixed_0_5']['f1']:.3f} (@0,5) · "
              f"AUC {y['auc']:.3f}")

    print("références")
    add("always_positive", "référence — tout positif",
        lambda t, y: _ConstantScorer(), note="plancher trivial : J = 0 par construction")
    add("site_majority", "référence — majorité par site",
        lambda t, y: _SiteMajorityScorer(site_of).fit(t, y),
        note="n'utilise que le nom du site, jamais l'énoncé")
    add("heuristic", "référence — règle lexicale écrite à la main",
        lambda t, y: _HeuristicScorer().fit(t, y), note="aucun apprentissage")

    print("approches")
    add("a_tfidf", "(a) TF-IDF 1-2 grammes + régression logistique",
        lambda t, y: TfidfScorer().fit(t, y), note="hors ligne, 0 $")

    if not args.no_local:
        embedder = MiniLmEmbedder()
        scorer_b = EmbeddingScorer(embedder)
        t0 = time.perf_counter()
        scorer_b.embed(data.texts)
        print(f"  (vectorisation MiniLM : {time.perf_counter() - t0:.1f} s)")
        add("b_minilm", "(b) all-MiniLM-L6-v2 (384 dim) + régression logistique",
            lambda t, y: scorer_b.fit(t, y), note="modèle local, 0 $", ledger=embedder.ledger)

    judges: list[dict[str, Any]] = []
    if not args.offline:
        embed_ledger = CostLedger(label="embed-openrouter")
        embed_client = OpenRouterClient(ledger=embed_ledger)
        scorer_c = EmbeddingScorer(OpenRouterEmbedder(embed_client, model=args.embed_model))
        scorer_c.embed(data.texts)
        spent[0] += embed_ledger.cost_usd
        add("c_openrouter_embed", f"(c) {args.embed_model} (1536 dim) + régression logistique",
            lambda t, y: scorer_c.fit(t, y), note="API d'embeddings", ledger=embed_ledger)
        embed_client.close()

        # Cinq familles de juge, toutes à cinq exécutions. Les trois premières isolent ce
        # que vaut le prompt (fuité → propre → aucune rubrique) à modèle constant ; les
        # deux dernières refont la même mesure sur le modèle bon marché, dont le dossier
        # du 15/08 affirmait qu'il « s'effondre au niveau du hasard ».
        print("juges (5 exécutions chacun)")
        plan = [
            ("d_judge_clean", f"(d) juge {short(args.chat_model)} — rubrique PROPRE",
             args.chat_model, "rubric", None, CLEAN_VARIANTS),
            ("d_judge_leaky", f"(d⁻) juge {short(args.chat_model)} — rubrique FUITÉE (15/08)",
             args.chat_model, "rubric", LEAKY_RUBRIC_PROMPT, LEAKY_VARIANTS),
            ("d_judge_plain", f"(d⁰) juge {short(args.chat_model)} — sans rubrique",
             args.chat_model, "plain", None, PLAIN_VARIANTS),
            ("d_lite_clean", f"(e) juge {short(args.cheap_model)} — rubrique PROPRE",
             args.cheap_model, "rubric", None, CLEAN_VARIANTS),
            ("d_lite_leaky", f"(e⁻) juge {short(args.cheap_model)} — rubrique FUITÉE (15/08)",
             args.cheap_model, "rubric", LEAKY_RUBRIC_PROMPT, LEAKY_VARIANTS),
        ]
        for key, label, model, prompt, system, variants in plan:
            judges.append(run_judge_family(
                key, label, data=data, folds=folds, model=model, prompt=prompt,
                system=system, variants=variants, workers=args.workers,
                budget=args.budget_usd, spent=spent))
            print(f"    (cumul dépensé : {spent[0]:.5f} $)")

    # -- C13 : ce que vaut vraiment la précision in-sample du backend tfidf --------------
    tfidf_full = TfidfScorer().fit(data.texts, data.labels)
    in_sample = prf(data.labels, [1 if s >= 0.5 else 0 for s in tfidf_full.score(data.texts)])
    oof_tfidf = next(r for r in classical if r["key"] == "a_tfidf")["youden"]["pooled"]

    # -- McNemar sur les prédictions hors plis --------------------------------------------
    pool = {r["key"]: r["youden"]["oof_pred"] for r in classical}
    for j in judges:
        pool[j["key"]] = j["runs"][0]["youden"]["oof_pred"]
    keys = list(pool)
    comparisons = [
        {"a": a, "b": b, **mcnemar_exact(data.labels, pool[a], pool[b])}
        for i, a in enumerate(keys) for b in keys[i + 1 :]
    ]

    payload = {
        "generated_at": dt.date.today().isoformat(),
        "supersedes": "runs/ablation_ambiguity_20260815.json",
        "corrects": ["B1 (fuite de rubrique)", "C1 (maximum publié pour une moyenne)",
                     "C2 (seuil dégénéré)", "C13 (métrique in-sample)"],
        "annotations": {
            "path": str(ANNOTATIONS.relative_to(ROOT)), "n": len(data),
            "n_positive": sum(data.labels), "positive_rate": round(data.positive_rate, 4),
            "annotator": data.meta.get("annotator"), "limits": data.meta.get("limits"),
        },
        "protocol": {
            "cv": f"{N_SPLITS} plis stratifiés, graine {CV_SEED} (identiques au banc du 15/08)",
            "threshold_primary": "J de Youden, calibré sur les plis d'entraînement",
            "threshold_secondary": "seuil fixe 0,5, sans calibration",
            "threshold_witness": "maximisation du F1 (l'ancien critère), conservé comme témoin",
            "judge_runs": JUDGE_RUNS,
            "chat_model": args.chat_model,
            "embed_model": args.embed_model,
            "leaked_task_ids": LEAKED_TASK_IDS,
        },
        "classical": classical,
        "judges": judges,
        "tfidf_in_sample_warning": {
            "in_sample_precision": round(in_sample["precision"], 4),
            "in_sample_flags": in_sample["tp"] + in_sample["fp"],
            "out_of_fold_precision": round(oof_tfidf["precision"], 4),
            "comment": (
                "build_scorer(fit=True) entraîne le classifieur sur les 139 annotations puis "
                "l'applique aux 643 tâches, dont ces 139 : la précision in-sample n'est pas "
                "publiable. Seule la ligne hors plis l'est."
            ),
        },
        "mcnemar": comparisons,
        "cost_usd_this_run": round(spent[0], 6),
    }

    out = Path(args.out) if args.out else ROOT / "runs" / f"ablation_l3_clean_{dt.date.today():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"TF-IDF : précision in-sample {in_sample['precision']:.3f} "
          f"contre {oof_tfidf['precision']:.3f} hors plis — seule la seconde est publiable")
    print(f"coût réel de cette exécution : {spent[0]:.5f} $")
    print(f"rapport écrit : {out}")
    return 0


def short(model: str) -> str:
    return model.split("/")[-1]


class _ConstantScorer:
    """Prédit toujours la classe positive (plancher trivial, J = 0)."""

    def score(self, texts: Sequence[str]) -> list[float]:
        return [1.0] * len(texts)


#: Le prompt complet du 15/08 : préambule d'origine + rubrique fuitée. Reconstruit ici et
#: pas importé, parce que le module de l'outil ne doit plus contenir la rubrique fuitée.
LEAKY_RUBRIC_PROMPT = (
    "You rate web-agent benchmark tasks against the rubric below.\n\n"
    + LEAKY_RUBRIC
    + "\n\nRate the task statement from 0.0 (clearly not ambiguous) to 1.0 (clearly "
    "ambiguous).\n"
    'Answer with strict JSON only: {"score": <float 0-1>, "reason": "<12 words max>"}'
)


if __name__ == "__main__":
    raise SystemExit(main())
