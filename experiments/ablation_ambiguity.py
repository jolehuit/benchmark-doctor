"""Banc d'ablation : quatre approches de détection d'ambiguïté, à coût croissant.

Question posée : **à partir de quel budget la détection d'ambiguïté devient-elle
meilleure ?** L'architecture de `benchmark-doctor` postule une hiérarchie par coût (L1
statique gratuit → L2 sondes web → L3 modèles). Si un sac de mots gratuit égale un juge
payant sur la même tâche, la couche L3 ne se justifie pas pour l'ambiguïté.

Les quatre approches, sur le même jeu annoté et la même validation croisée :

  (a) ``tfidf``      TF-IDF (1-2 grammes) + régression logistique   — hors ligne, 0 $
  (b) ``minilm``     all-MiniLM-L6-v2 (384 dim) + régression log.   — hors ligne, 0 $
  (c) ``openrouter`` text-embedding-3-small (1536 dim) + rég. log.  — API, coût mesuré
  (d) ``llm``        juge gemini-2.5-flash-lite, note 0-1 + seuil   — API, coût mesuré

Trois lignes de référence les encadrent : « tout positif » (plancher trivial), « majorité
par site » (combien de signal n'est que l'identité du site, question sérieuse ici, les
positifs se concentrant sur Allrecipes, Amazon et Coursera) et une règle lexicale écrite à
la main (ce que coûte zéro apprentissage).

Protocole identique pour tous, sans exception :

- validation croisée stratifiée à 5 plis, mêmes plis pour toutes les approches
  (``random_state=42``) ;
- le seuil de décision est calibré sur les plis d'entraînement (maximisation du F1) puis
  appliqué au pli de test, y compris pour les classifieurs, qui pourraient se contenter de
  0,5 : sans cette symétrie, on comparerait des conventions de décision autant que des
  représentations ;
- ce qui n'est pas appris sur les données (encodeurs figés, juge) est calculé une fois pour
  les 139 énoncés, hors de la boucle de validation : un encodeur pré-entraîné ne voit pas
  les étiquettes, il n'y a donc pas de fuite ;
- précision, rappel et F1 de la classe positive sont calculés par pli ; le tableau publie la
  moyenne et l'écart-type entre plis, plus la valeur agrégée hors plis, seule directement
  comparable à une exploitation réelle ;
- les différences entre approches sont testées par un test de McNemar exact sur les
  prédictions hors plis : avec 139 exemples, quelques points de F1 ne prouvent rien.

    python experiments/ablation_ambiguity.py sample            # revérifie le tirage
    python experiments/ablation_ambiguity.py run --offline     # (a), (b) et références
    python experiments/ablation_ambiguity.py run               # les quatre approches
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import random
import re
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
    load_annotations,
)
from benchmark_doctor.detectors.l3_client import (  # noqa: E402
    CHEAP_CHAT_MODEL,
    DEFAULT_EMBED_MODEL,
    CostLedger,
    OpenRouterClient,
)

CORPUS = ROOT / "data" / "raw" / "webvoyager_original.jsonl"
ANNOTATIONS = ROOT / "data" / "annotations_ambiguity.json"

N_SPLITS = 5
CV_SEED = 42
#: Graine et quota du tirage stratifié — doivent rester identiques à ceux consignés
#: dans ``data/annotations_ambiguity.json`` (vérifié par la sous-commande ``sample``).
SAMPLE_SEED = 20260815
PER_SITE = 9
FORCED_IDS = ["Apple--14", "Apple--42", "Google Search--15", "Huggingface--23"]

#: Nombre de tirages indépendants du juge, pour mesurer sa variance d'une exécution à
#: l'autre à température 0 (cf. browser-use, « The Benchmark Behind the Benchmark »).
JUDGE_REPEATS = 3


# Échantillonnage (reproductibilité du jeu annoté)


def build_sample(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tirage stratifié par site, déterministe : 9 tâches par site + positifs certains.

    La graine dépend du nom du site (``random.Random(f"{seed}:{site}")``) : ajouter un
    site au corpus ne redistribue pas l'échantillon des autres, ce qui permet d'étendre
    le jeu annoté sans invalider les étiquettes déjà posées.
    """
    by_site: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        by_site[row["web_name"]].append(row)
    sample: list[dict[str, Any]] = []
    for site in sorted(by_site):
        pool = sorted(by_site[site], key=lambda r: r["id"])
        rng = random.Random(f"{SAMPLE_SEED}:{site}")
        sample.extend(rng.sample(pool, PER_SITE))
    index = {r["id"]: r for r in rows}
    seen = {r["id"] for r in sample}
    sample.extend(index[i] for i in FORCED_IDS if i not in seen)
    return sorted(sample, key=lambda r: (r["web_name"], int(r["id"].split("--")[1])))


def load_corpus() -> list[dict[str, Any]]:
    return [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]


def cmd_sample(_: argparse.Namespace) -> int:
    """Rejoue le tirage et vérifie qu'il coïncide exactement avec le jeu annoté."""
    sample_ids = [r["id"] for r in build_sample(load_corpus())]
    annotated = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))
    annotated_ids = [i["task_id"] for i in annotated["items"]]
    ok = sample_ids == annotated_ids
    print(f"tirage rejoué : {len(sample_ids)} tâches")
    print(f"jeu annoté    : {len(annotated_ids)} tâches")
    print("identique     :", "oui" if ok else "NON")
    if not ok:
        missing = sorted(set(sample_ids) - set(annotated_ids))
        extra = sorted(set(annotated_ids) - set(sample_ids))
        print("  absentes du jeu annoté :", missing[:10])
        print("  en trop dans le jeu    :", extra[:10])
        return 1
    positives = sum(i["label"] for i in annotated["items"])
    print(f"positives     : {positives}/{len(annotated_ids)} ({positives / len(annotated_ids):.1%})")
    return 0


# Métriques


def prf(y_true: Sequence[int], y_pred: Sequence[int]) -> dict[str, float]:
    """Précision, rappel et F1 de la classe positive, plus les effectifs bruts."""
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / len(y_true) if y_true else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def mcnemar_exact(y_true: Sequence[int], pred_a: Sequence[int], pred_b: Sequence[int]) -> dict[str, float]:
    """Test de McNemar exact (binomial bilatéral) entre deux jeux de prédictions.

    Ne comptent que les cas où les deux approches divergent : ``b`` = A a raison et B a
    tort, ``c`` = l'inverse. Sous l'hypothèse nulle, chaque discordance est un tirage à
    pile ou face. C'est le test adapté à des prédictions appariées sur le même
    échantillon — et à 139 exemples, il dira le plus souvent « pas de différence ».
    """
    b = sum(1 for t, a, bb in zip(y_true, pred_a, pred_b) if a == t and bb != t)
    c = sum(1 for t, a, bb in zip(y_true, pred_a, pred_b) if a != t and bb == t)
    n = b + c
    if n == 0:
        return {"a_only_correct": 0, "b_only_correct": 0, "p_value": 1.0}
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return {"a_only_correct": b, "b_only_correct": c, "p_value": min(1.0, 2 * tail)}


def roc_auc(y_true: Sequence[int], scores: Sequence[float]) -> float:
    """Aire sous la courbe ROC, par la statistique de Mann-Whitney.

    C'est la seule mesure du tableau qui ne dépende d'aucun seuil : elle départage des
    approches dont la calibration diffère, et elle survit au fait que le juge LLM
    concentre ses notes sur quelques valeurs. Les ex æquo comptent une demi-victoire.
    """
    positives = [s for s, y in zip(scores, y_true) if y == 1]
    negatives = [s for s, y in zip(scores, y_true) if y == 0]
    if not positives or not negatives:
        return 0.5
    wins = sum(
        1.0 if p > n else 0.5 if p == n else 0.0 for p in positives for n in negatives
    )
    return wins / (len(positives) * len(negatives))


def stratified_folds(labels: Sequence[int], n_splits: int = N_SPLITS, seed: int = CV_SEED) -> list[list[int]]:
    """Indices de test de chaque pli, stratifiés sur l'étiquette (sans dépendance externe).

    Reproduit le comportement de ``StratifiedKFold(shuffle=True)`` : les positifs et les
    négatifs sont mélangés séparément puis distribués à tour de rôle, de sorte que le
    taux de positifs de chaque pli soit celui du jeu complet à une unité près.
    """
    rng = random.Random(seed)
    folds: list[list[int]] = [[] for _ in range(n_splits)]
    for target in (1, 0):
        idx = [i for i, y in enumerate(labels) if y == target]
        rng.shuffle(idx)
        for position, i in enumerate(idx):
            folds[position % n_splits].append(i)
    return [sorted(f) for f in folds]


# Évaluation d'une approche


class Approach:
    """Une approche évaluable : un nom, un coût, une fabrique de scorer par pli.

    ``factory(train_texts, train_labels)`` doit renvoyer un objet exposant
    ``score(texts)`` déjà entraîné. Le seuil est calibré par le banc, identiquement
    pour toutes les approches.
    """

    def __init__(
        self,
        key: str,
        label: str,
        factory: Callable[[Sequence[str], Sequence[int]], Any],
        *,
        ledger: CostLedger | None = None,
        inference_time_s: float = 0.0,
        note: str = "",
    ) -> None:
        self.key = key
        self.label = label
        self.factory = factory
        self.ledger = ledger
        self.inference_time_s = inference_time_s
        self.note = note


def evaluate(approach: Approach, data: AnnotatedSet, folds: Sequence[Sequence[int]]) -> dict[str, Any]:
    """Validation croisée d'une approche : métriques par pli, agrégées et hors plis."""
    per_fold: list[dict[str, float]] = []
    oof_pred = [0] * len(data)
    oof_score = [0.0] * len(data)
    thresholds: list[float] = []
    train_time = 0.0
    predict_time = 0.0

    for fold_id, test_idx in enumerate(folds):
        test_set = set(test_idx)
        train_idx = [i for i in range(len(data)) if i not in test_set]
        train_texts = [data.texts[i] for i in train_idx]
        train_labels = [data.labels[i] for i in train_idx]
        test_texts = [data.texts[i] for i in test_idx]
        test_labels = [data.labels[i] for i in test_idx]

        t0 = time.perf_counter()
        scorer = approach.factory(train_texts, train_labels)
        threshold = calibrate_threshold(scorer.score(train_texts), train_labels)
        train_time += time.perf_counter() - t0

        t1 = time.perf_counter()
        scores = scorer.score(test_texts)
        predict_time += time.perf_counter() - t1

        preds = [1 if s >= threshold else 0 for s in scores]
        thresholds.append(threshold)
        for i, p, s in zip(test_idx, preds, scores):
            oof_pred[i] = p
            oof_score[i] = float(s)
        metrics = prf(test_labels, preds)
        metrics["fold"] = fold_id
        metrics["threshold"] = threshold
        metrics["n_test"] = len(test_idx)
        per_fold.append(metrics)

    def agg(key: str) -> tuple[float, float]:
        values = [m[key] for m in per_fold]
        return statistics.mean(values), (statistics.stdev(values) if len(values) > 1 else 0.0)

    precision_mean, precision_std = agg("precision")
    recall_mean, recall_std = agg("recall")
    f1_mean, f1_std = agg("f1")
    accuracy_mean, accuracy_std = agg("accuracy")
    pooled = prf(data.labels, oof_pred)

    ledger = approach.ledger.to_dict() if approach.ledger else None
    model_time = ledger["model_time_s"] if ledger else approach.inference_time_s
    # Deux lectures complémentaires du même jeu de notes : le seuil calibré (ce que
    # publie le tableau) et le seuil fixe 0,5 (ce qu'un praticien appliquerait sans
    # jeu annoté). L'écart entre les deux dit ce que la calibration apporte — ou, pour
    # le juge LLM, à quel point la maximisation du F1 dégénère.
    fixed = prf(data.labels, [1 if s >= 0.5 else 0 for s in oof_score])
    return {
        "key": approach.key,
        "label": approach.label,
        "note": approach.note,
        "auc": roc_auc(data.labels, oof_score),
        "fixed_threshold_0_5": fixed,
        "precision_mean": precision_mean,
        "precision_std": precision_std,
        "recall_mean": recall_mean,
        "recall_std": recall_std,
        "f1_mean": f1_mean,
        "f1_std": f1_std,
        "accuracy_mean": accuracy_mean,
        "accuracy_std": accuracy_std,
        "pooled": pooled,
        "thresholds": thresholds,
        "per_fold": per_fold,
        "oof_pred": oof_pred,
        "oof_score": [round(s, 4) for s in oof_score],
        "train_time_s": round(train_time, 4),
        "predict_time_s": round(predict_time, 4),
        # Temps de paroi de cette exécution (≈ 0 quand le cache sert) et temps de modèle
        # cumulé, relu dans le cache : c'est le second qui figure dans le tableau, parce
        # qu'il ne dépend ni du parallélisme choisi ni de l'état du cache.
        "inference_wall_time_s": round(approach.inference_time_s, 3),
        "inference_time_s": round(model_time, 3),
        "total_time_s": round(train_time + predict_time + model_time, 3),
        "cost": ledger,
        "cost_usd": round(ledger["cost_usd"], 6) if ledger else 0.0,
    }


# Lignes de référence


class _ConstantScorer:
    """Prédit toujours la classe positive (plancher trivial)."""

    def fit(self, texts: Sequence[str], labels: Sequence[int]) -> "_ConstantScorer":
        return self

    def score(self, texts: Sequence[str]) -> list[float]:
        return [1.0] * len(texts)


class _SiteMajorityScorer:
    """Prédit la classe majoritaire du site, apprise sur les plis d'entraînement.

    N'utilise **que** l'identité du site, jamais l'énoncé : mesure la part de la
    performance qui n'est qu'un effet de corpus (« tout Allrecipes est ambigu »).
    """

    def __init__(self, site_of: dict[str, str]) -> None:
        self._site_of = site_of
        self._rate: dict[str, float] = {}
        self._global = 0.0

    def fit(self, texts: Sequence[str], labels: Sequence[int]) -> "_SiteMajorityScorer":
        buckets: dict[str, list[int]] = collections.defaultdict(list)
        for text, label in zip(texts, labels):
            buckets[self._site_of[text]].append(label)
        self._rate = {site: sum(v) / len(v) for site, v in buckets.items()}
        self._global = sum(labels) / len(labels) if labels else 0.0
        return self

    def score(self, texts: Sequence[str]) -> list[float]:
        return [self._rate.get(self._site_of[t], self._global) for t in texts]


#: Règle lexicale écrite à la main : cible indéfinie (« find a … ») ou critère subjectif.
#: Écrite d'après la rubrique d'étiquetage, pas ajustée sur les scores : c'est ce que
#: donne un détecteur L1 de quinze lignes, à comparer à ce que coûte un modèle.
_INDEFINITE_TARGET = re.compile(
    r"\b(?:find|search for|look for|locate|identify|provide|browse|show me|get|pick|choose)\s+"
    r"(?:me\s+)?(?:an?|one|some|any|\d+|three|five)\b",
    re.I,
)
_SUBJECTIVE = re.compile(
    r"\b(?:best|popular|renowned|innovative|widely recognized|interesting|good|nice|"
    r"main|top\s+\d|suitable|appropriate|relevant|notable|famous|reputable)\b",
    re.I,
)
_DETERMINISTIC = re.compile(
    r"\b(?:cheapest|lowest[- ]priced|most\s+\w+|least\s+\w+|highest|closest|nearest|"
    r"how many|number of|the first|latest|most recent)\b",
    re.I,
)


class _HeuristicScorer:
    """Règle lexicale sans apprentissage (référence « coût zéro, effort zéro »)."""

    def fit(self, texts: Sequence[str], labels: Sequence[int]) -> "_HeuristicScorer":
        return self

    def score(self, texts: Sequence[str]) -> list[float]:
        out = []
        for text in texts:
            hit = bool(_INDEFINITE_TARGET.search(text)) or bool(_SUBJECTIVE.search(text))
            if hit and _DETERMINISTIC.search(text) and not _SUBJECTIVE.search(text):
                hit = False
            out.append(1.0 if hit else 0.0)
        return out


# Stabilité du juge


def judge_stability(runs: Sequence[Sequence[float]], threshold: float) -> dict[str, Any]:
    """Variance du juge entre exécutions indépendantes du même prompt.

    Deux quantités : la dispersion des notes (écart-type moyen par énoncé) et surtout le
    **taux de bascule de verdict** — la part des énoncés dont la décision binaire change
    d'une exécution à l'autre. C'est la version « task-side » du résultat de browser-use
    sur les juges : à température 0, un juge n'est pas une fonction.
    """
    if len(runs) < 2:
        return {}
    n = len(runs[0])
    per_task_std = [statistics.stdev([r[i] for r in runs]) for i in range(n)]
    max_gap = [max(r[i] for r in runs) - min(r[i] for r in runs) for i in range(n)]

    def flips_at(cut: float) -> int:
        return sum(1 for i in range(n) if len({1 if r[i] >= cut else 0 for r in runs}) > 1)

    # Le taux de bascule doit être lu à un seuil qui sépare réellement les deux classes :
    # mesuré au seuil calibré du juge le plus dégénéré (0,0), il vaut zéro par
    # construction puisque tout est déclaré positif dans les trois exécutions.
    flips_calibrated = flips_at(threshold)
    flips_half = flips_at(0.5)
    return {
        "n_runs": len(runs),
        "mean_score_std": round(statistics.mean(per_task_std), 4),
        "max_score_std": round(max(per_task_std), 4),
        "mean_max_gap": round(statistics.mean(max_gap), 4),
        "n_tasks_scored_differently": sum(1 for g in max_gap if g > 0),
        "verdict_flip_rate_at_0_5": round(flips_half / n, 4),
        "n_flipped_at_0_5": flips_half,
        "verdict_flip_rate_at_calibrated": round(flips_calibrated / n, 4),
        "n_flipped_at_calibrated": flips_calibrated,
        "calibrated_threshold": threshold,
    }


# Commande principale


def cmd_run(args: argparse.Namespace) -> int:
    data = load_annotations(ANNOTATIONS)
    folds = stratified_folds(data.labels, N_SPLITS, CV_SEED)
    site_of = {text: site for text, site in zip(data.texts, data.sites)}
    results: list[dict[str, Any]] = []
    extras: dict[str, Any] = {}
    #: Comptabilités hors tableau (tirages de contrôle du juge) : jamais évaluées comme
    #: des approches, mais bien facturées.
    side_ledgers: list[dict[str, Any]] = []

    print(f"jeu annoté : {len(data)} tâches, {sum(data.labels)} positives "
          f"({data.positive_rate:.1%}), {N_SPLITS} plis stratifiés (graine {CV_SEED})")

    # -- lignes de référence -----------------------------------------------------------
    results.append(
        evaluate(
            Approach("always_positive", "référence — tout positif",
                     lambda t, y: _ConstantScorer().fit(t, y),
                     note="plancher trivial : rappel 100 %, précision = taux de positifs"),
            data, folds,
        )
    )
    results.append(
        evaluate(
            Approach("site_majority", "référence — majorité par site",
                     lambda t, y: _SiteMajorityScorer(site_of).fit(t, y),
                     note="n'utilise que le nom du site, jamais l'énoncé"),
            data, folds,
        )
    )
    results.append(
        evaluate(
            Approach("heuristic", "référence — règle lexicale écrite à la main",
                     lambda t, y: _HeuristicScorer().fit(t, y),
                     note="aucun apprentissage ; écrite d'après la rubrique d'étiquetage"),
            data, folds,
        )
    )

    # -- (a) TF-IDF --------------------------------------------------------------------
    results.append(
        evaluate(
            Approach("a_tfidf", "(a) TF-IDF 1-2 grammes + régression logistique",
                     lambda t, y: TfidfScorer().fit(t, y),
                     note="hors ligne, aucune dépendance réseau"),
            data, folds,
        )
    )
    tfidf_full = TfidfScorer().fit(data.texts, data.labels)
    extras["tfidf_top_features"] = tfidf_full.top_features(20)

    # -- (b) MiniLM local --------------------------------------------------------------
    if not args.no_local:
        embedder = MiniLmEmbedder()
        scorer_b = EmbeddingScorer(embedder)
        t0 = time.perf_counter()
        scorer_b.embed(data.texts)  # vectorisation unique, hors boucle de validation
        embed_time = time.perf_counter() - t0
        results.append(
            evaluate(
                Approach("b_minilm", "(b) all-MiniLM-L6-v2 (384 dim) + régression logistique",
                         lambda t, y: scorer_b.fit(t, y),
                         ledger=embedder.ledger, inference_time_s=embed_time,
                         note="modèle local, 22 M paramètres, aucun appel réseau"),
                data, folds,
            )
        )

    # -- (c) et (d) : approches payantes ------------------------------------------------
    if not args.offline:
        embed_ledger = CostLedger(label="embed-openrouter")
        embed_client = OpenRouterClient(ledger=embed_ledger)
        remote_embedder = OpenRouterEmbedder(embed_client, model=args.embed_model)
        scorer_c = EmbeddingScorer(remote_embedder)
        t0 = time.perf_counter()
        scorer_c.embed(data.texts)
        remote_embed_time = time.perf_counter() - t0
        results.append(
            evaluate(
                Approach("c_openrouter_embed",
                         f"(c) {args.embed_model} (1536 dim) + régression logistique",
                         lambda t, y: scorer_c.fit(t, y),
                         ledger=embed_ledger, inference_time_s=remote_embed_time,
                         note="API d'embeddings, coût réel relevé dans usage.cost"),
                data, folds,
            )
        )

        judge_runs: dict[str, list[list[float]]] = {}
        for prompt in ("rubric", "plain"):
            runs: list[list[float]] = []
            for repeat in range(1, JUDGE_REPEATS + 1):
                ledger = CostLedger(label=f"judge-{prompt}-v{repeat}")
                judge_client = OpenRouterClient(ledger=ledger)
                judge = LlmJudgeScorer(
                    judge_client, model=args.chat_model, prompt=prompt,
                    variant=f"v{repeat}", max_workers=args.workers,
                )
                t0 = time.perf_counter()
                scores = judge.score(data.texts)
                elapsed = time.perf_counter() - t0
                runs.append(scores)
                if repeat == 1:
                    results.append(
                        evaluate(
                            Approach(
                                f"d_llm_judge_{prompt}",
                                f"(d) juge {args.chat_model.split('/')[-1]} — prompt « {prompt} »",
                                lambda t, y, j=judge: j.fit(t, y),
                                ledger=ledger, inference_time_s=elapsed,
                                note=("prompt porteur de la rubrique d'étiquetage"
                                      if prompt == "rubric"
                                      else "prompt minimal, sans rubrique"),
                            ),
                            data, folds,
                        )
                    )
                    if judge.unparsed:
                        print(f"  {judge.unparsed} réponses illisibles (note neutre 0,5 imputée)")
                print(f"  juge {prompt} v{repeat} : {elapsed:.1f} s, "
                      f"{ledger.calls + ledger.cached_calls} appels, "
                      f"{ledger.first_run_cost_usd:.5f} $")
            judge_runs[prompt] = runs

        # Le juge le moins cher échoue-t-il parce qu'il est bon marché, ou parce que la
        # tâche résiste au juge ? Un modèle plus coûteux, même prompt, même jeu :
        # c'est la seule façon de ne pas confondre « juge faible » et « approche faible ».
        for model in args.judge_models:
            slug = model.split("/")[-1].replace(".", "_")
            ledger = CostLedger(label=f"judge-{slug}")
            judge_client = OpenRouterClient(ledger=ledger)
            judge = LlmJudgeScorer(
                judge_client, model=model, prompt="rubric", variant="v1", max_workers=args.workers
            )
            t0 = time.perf_counter()
            first_run = judge.score(data.texts)
            elapsed = time.perf_counter() - t0
            if model in args.stability_models:
                extra_runs = [first_run]
                for repeat in range(2, JUDGE_REPEATS + 1):
                    twin_ledger = CostLedger(label=f"judge-{slug}-v{repeat}")
                    twin = LlmJudgeScorer(
                        OpenRouterClient(ledger=twin_ledger),
                        model=model, prompt="rubric", variant=f"v{repeat}", max_workers=args.workers,
                    )
                    extra_runs.append(twin.score(data.texts))
                    # Les tirages de contrôle sont facturés comme les autres : leur coût
                    # doit apparaître au total, sinon la campagne dépense sans le dire.
                    side_ledgers.append(twin_ledger.to_dict())
                judge_runs[slug] = extra_runs
            results.append(
                evaluate(
                    Approach(
                        f"d_llm_judge_{slug}",
                        f"(d′) juge {model.split('/')[-1]} — prompt « rubric »",
                        lambda t, y, j=judge: j.fit(t, y),
                        ledger=ledger, inference_time_s=elapsed,
                        note="modèle plus coûteux, prompt et protocole identiques",
                    ),
                    data, folds,
                )
            )
            print(f"  juge {model} : {elapsed:.1f} s, {ledger.calls} appels, {ledger.cost_usd:.5f} $")
            judge_client.close()

        extras["judge_stability"] = {
            prompt: judge_stability(
                runs,
                threshold=next(
                    (statistics.mean(r["thresholds"]) for r in results
                     if r["key"] == f"d_llm_judge_{prompt}"),
                    0.5,
                ),
            )
            for prompt, runs in judge_runs.items()
        }
        extras["judge_score_histogram"] = {
            prompt: dict(sorted(collections.Counter(round(s, 1) for s in runs[0]).items()))
            for prompt, runs in judge_runs.items()
        }
        embed_client.close()

    # -- comparaisons appariées ---------------------------------------------------------
    keys = [r["key"] for r in results]
    by_key = {r["key"]: r for r in results}
    comparisons = []
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            test = mcnemar_exact(data.labels, by_key[a]["oof_pred"], by_key[b]["oof_pred"])
            comparisons.append({"a": a, "b": b, **test})
    extras["mcnemar"] = comparisons

    # -- ce que chaque approche voit, par type d'ambiguïté -------------------------------
    # Une moyenne de rappel cache l'essentiel : les positifs de ce jeu relèvent de quatre
    # motifs très différents (multiplicité, subjectivité, référent flou, sortie libre).
    # Savoir lequel résiste dit plus qu'un point de F1 moyen.
    raw_items = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))["items"]
    criteria_of = [set(item["criteria"]) for item in raw_items]
    codes = sorted({c for s in criteria_of for c in s})
    extras["recall_by_criterion"] = {
        r["key"]: {
            code: {
                "n": sum(1 for i, s in enumerate(criteria_of) if code in s),
                "recall": round(
                    _safe_ratio(
                        sum(1 for i, s in enumerate(criteria_of) if code in s and r["oof_pred"][i] == 1),
                        sum(1 for s in criteria_of if code in s),
                    ),
                    3,
                ),
            }
            for code in codes
        }
        for r in results
    }
    extras["recall_multiplicity_only"] = {
        r["key"]: round(
            _safe_ratio(
                sum(
                    1
                    for i, s in enumerate(criteria_of)
                    if s == {"A1"} and r["oof_pred"][i] == 1
                ),
                sum(1 for s in criteria_of if s == {"A1"}),
            ),
            3,
        )
        for r in results
    }

    # -- coût extrapolé ------------------------------------------------------------------
    extras["side_ledgers"] = side_ledgers
    extras["cost_projection"] = {
        r["key"]: {
            "measured_usd": r["cost_usd"],
            "tasks_measured": len(data),
            "usd_per_task": round(r["cost_usd"] / len(data), 8),
            "usd_for_643_tasks": round(r["cost_usd"] * 643 / len(data), 5),
            "usd_per_year_weekly_643": round(r["cost_usd"] * 643 / len(data) * 52, 4),
        }
        for r in results
    }

    payload = {
        "generated_at": dt.date.today().isoformat(),
        "annotations": {
            "path": str(ANNOTATIONS.relative_to(ROOT)),
            "n": len(data),
            "n_positive": sum(data.labels),
            "positive_rate": round(data.positive_rate, 4),
            "annotator": data.meta.get("annotator"),
            "limits": data.meta.get("limits"),
        },
        "protocol": {
            "cv": f"{N_SPLITS} plis stratifiés, graine {CV_SEED}",
            "threshold": "calibré par maximisation du F1 sur les plis d'entraînement",
            "chat_model": args.chat_model,
            "embed_model": args.embed_model,
            "judge_repeats": JUDGE_REPEATS,
        },
        "results": results,
        **extras,
    }

    out = Path(args.out) if args.out else ROOT / "runs" / f"ablation_ambiguity_{dt.date.today():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print()
    print(markdown_table(results))
    print()
    total_cost = sum(r["cost_usd"] for r in results) + sum(
        l["cost_usd"] for l in side_ledgers
    )
    print(f"coût de la mesure : {total_cost:.5f} $")
    print(f"rapport écrit : {out}")
    return 0


def _safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def markdown_table(results: Sequence[dict[str, Any]]) -> str:
    """Le tableau du mémoire : performance, dispersion, temps et coût réel."""
    head = (
        "| Approche | P | R | F1 (moy ± σ entre plis) | F1 hors plis | AUC | Temps | Coût réel |\n"
        "|---|---|---|---|---|---|---|---|"
    )
    lines = [head]
    for r in results:
        cost = f"{r['cost_usd']:.5f} $" if r["cost_usd"] else "0 $"
        lines.append(
            f"| {r['label']} | {r['precision_mean']:.3f} | {r['recall_mean']:.3f} | "
            f"{r['f1_mean']:.3f} ± {r['f1_std']:.3f} | {r['pooled']['f1']:.3f} | "
            f"{r['auc']:.3f} | {r['total_time_s']:.2f} s | {cost} |"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sample = sub.add_parser("sample", help="rejoue le tirage stratifié et le compare au jeu annoté")
    p_sample.set_defaults(func=cmd_sample)

    p_run = sub.add_parser("run", help="exécute l'ablation des quatre approches")
    p_run.add_argument("--offline", action="store_true", help="n'exécute que les approches gratuites")
    p_run.add_argument("--no-local", action="store_true", help="saute le modèle local MiniLM")
    # L'approche (d) du mémoire est épinglée au modèle le moins cher, indépendamment du
    # défaut de la bibliothèque : l'expérience doit rester reproductible même après que
    # ses résultats ont fait changer ce défaut.
    p_run.add_argument("--chat-model", default=CHEAP_CHAT_MODEL)
    p_run.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    p_run.add_argument("--workers", type=int, default=8, help="appels de juge en parallèle")
    p_run.add_argument(
        "--stability-models",
        nargs="*",
        default=[],
        help="modèles de juge à exécuter plusieurs fois pour mesurer leur variance",
    )
    p_run.add_argument(
        "--judge-models",
        nargs="*",
        default=[],
        help="modèles de juge supplémentaires à évaluer (même prompt, même protocole)",
    )
    p_run.add_argument("--out", default=None, help="chemin du rapport JSON")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
