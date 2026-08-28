"""L3 — solvabilité : la tâche est-elle réalisable *en principe* sur ce site ?

La couche L1 sait repérer qu'un énoncé demande de se connecter ou de payer, parce que
c'est écrit dans la phrase. Elle ne sait pas qu'« Apple ne vend plus le HomePod
d'origine », que « la saison NBA n'a pas commencé » ou que « GitHub Pro n'existe plus
sous ce nom » : ces verdicts demandent une connaissance du monde. C'est ce que ce
détecteur va chercher dans un modèle de langage — et c'est aussi sa limite, qu'il faut
énoncer avant les résultats :

    **Le modèle ne consulte pas le site.** Le canal est ``Channel.LLM``. Ce qu'il rend
    est un *a priori* de faisabilité, daté de sa coupure d'entraînement, pas une
    observation. Un tel constat sert à *prioriser* une vérification L2, jamais à
    conclure seul qu'une tâche est morte.

Le détecteur produit, par tâche, un verdict ``yes`` / ``no`` / ``unclear``, un motif de
blocage typé et une confiance. Le motif est ce qui rend le constat exploitable : il se
mappe sur la taxonomie (accès → T3, contenu disparu → T2, date révolue → T1) et il
oriente la sonde suivante.

Évaluation. Il n'existe pas de vérité terrain de solvabilité pour WebVoyager. On utilise
un **substitut** : les tâches que les praticiens ont retirées de leur fork — les 53
suppressions de Magnitude et les 55 identifiants de ``WebVoyagerImpossibleTasks.json``
de browser-use, soit 59 tâches en union (49 en commun). Ce substitut est imparfait et il
faut le dire : on y trouve des tâches retirées pour dérive de contenu ou obsolescence de
date, pas seulement pour infaisabilité de principe. Les chiffres produits mesurent donc
« l'accord avec le jugement de retrait d'un praticien », ce qui est déjà la question
utile pour un outil de maintenance.

Exécution :

    python -m benchmark_doctor.detectors.l3_solvability --n-per-site 4 \\
        --model google/gemini-2.5-flash --out runs/solvability_20260815.json
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import random
import re
import time
from pathlib import Path
from typing import Any, Sequence

from ..models import Category, Channel, Finding, Severity, Task
from ..parsers.webvoyager import load_webvoyager
from .l3_client import DEFAULT_CHAT_MODEL, CostLedger, OpenRouterClient

__all__ = [
    "SolvabilityVerdict",
    "SolvabilityChecker",
    "detect_solvability",
    "run_solvability",
    "BLOCKER_TO_CATEGORY",
    "SOLVABILITY_PROMPT",
]

DETECTOR_NAME = "l3_solvability"

ROOT = Path(__file__).resolve().parents[2]

#: Motif de blocage → catégorie de la taxonomie. Le motif « other » est rattaché à la
#: dérive de contenu, cause la plus fréquente après l'accès dans les patch-sets réels.
BLOCKER_TO_CATEGORY: dict[str, Category] = {
    "auth": Category.ACCESS_DENIED,
    "payment": Category.ACCESS_DENIED,
    "side_effect": Category.ACCESS_DENIED,
    "content_missing": Category.CONTENT_DRIFT,
    "site_capability": Category.CONTENT_DRIFT,
    "temporal": Category.TEMPORAL,
    "other": Category.CONTENT_DRIFT,
    "none": Category.CONTENT_DRIFT,
}

SOLVABILITY_PROMPT = """You audit web-agent benchmark tasks for feasibility.

Decide whether the task below could still be completed IN PRINCIPLE by a competent
agent driving a normal browser on the given website, at the given date. Judge
feasibility, not difficulty, and not whether the answer is easy to grade.

Answer "no" when the task cannot be completed as written, for instance:
- auth: it needs an account, credentials or a logged-in session;
- payment: it needs a real payment or a real booking to be confirmed;
- side_effect: it would write to a third-party site (post, upload, delete, subscribe);
- content_missing: the product, page, section or entity it names no longer exists;
- site_capability: the site does not offer that feature or that filter at all;
- temporal: the date it names is in the past, and the action is only meaningful in the
  future (booking a flight, reserving a room).

Answer "yes" when a browsing agent could carry it out today, even if the answer has
changed since the task was written. Answer "unclear" only when you genuinely cannot
tell.

Reply with strict JSON only:
{"solvable": "yes|no|unclear", "blocker": "none|auth|payment|side_effect|content_missing|site_capability|temporal|other", "confidence": <float 0-1>, "reason": "<15 words max>"}"""

_JSON_RE = re.compile(r"\{.*?\}", re.S)


class SolvabilityVerdict:
    """Verdict de solvabilité d'une tâche : décision, motif, confiance, justification."""

    __slots__ = ("task_id", "solvable", "blocker", "confidence", "reason", "raw")

    def __init__(
        self,
        task_id: str,
        solvable: str,
        blocker: str,
        confidence: float,
        reason: str,
        raw: str = "",
    ) -> None:
        self.task_id = task_id
        self.solvable = solvable if solvable in ("yes", "no", "unclear") else "unclear"
        self.blocker = blocker if blocker in BLOCKER_TO_CATEGORY else "other"
        self.confidence = max(0.0, min(1.0, float(confidence)))
        self.reason = reason
        self.raw = raw

    @property
    def is_blocked(self) -> bool:
        """Vrai si le modèle refuse la tâche (``no``) — ``unclear`` ne compte pas."""
        return self.solvable == "no"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "solvable": self.solvable,
            "blocker": self.blocker,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
        }


def parse_verdict(task_id: str, text: str) -> SolvabilityVerdict:
    """Lit la réponse du modèle ; toute réponse illisible devient ``unclear``."""
    match = _JSON_RE.search(text or "")
    if match:
        try:
            payload = json.loads(match.group(0))
            return SolvabilityVerdict(
                task_id,
                str(payload.get("solvable", "unclear")).lower().strip(),
                str(payload.get("blocker", "other")).lower().strip(),
                float(payload.get("confidence", 0.5)),
                str(payload.get("reason", ""))[:200],
                raw=text[:400],
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return SolvabilityVerdict(task_id, "unclear", "other", 0.0, "(réponse illisible)", raw=text[:400])


class SolvabilityChecker:
    """Interroge un modèle sur la faisabilité de chaque tâche, coût mesuré."""

    def __init__(
        self,
        client: OpenRouterClient | None = None,
        *,
        model: str = DEFAULT_CHAT_MODEL,
        today: _dt.date | None = None,
        max_workers: int = 8,
    ) -> None:
        self._client = client or OpenRouterClient(ledger=CostLedger(label="solvability"))
        self._model = model
        self._today = today or _dt.date.today()
        self._max_workers = max_workers
        self.name = f"solvability:{model.split('/')[-1]}"

    @property
    def ledger(self) -> CostLedger:
        return self._client.ledger

    def _check_one(self, task: Task) -> SolvabilityVerdict:
        user = (
            f"Date: {self._today.isoformat()}\n"
            f"Website: {task.site or 'unknown'} ({task.start_url or 'unknown URL'})\n"
            f"Task: {task.question}"
        )
        result = self._client.chat(
            [{"role": "system", "content": SOLVABILITY_PROMPT}, {"role": "user", "content": user}],
            model=self._model,
            temperature=0.0,
            max_tokens=160,
        )
        return parse_verdict(task.task_id, result.text)

    def check(self, tasks: Sequence[Task]) -> list[SolvabilityVerdict]:
        if self._max_workers > 1 and len(tasks) > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                return list(pool.map(self._check_one, tasks))
        return [self._check_one(t) for t in tasks]


def verdict_to_findings(
    task: Task, verdict: SolvabilityVerdict, *, today: _dt.date | None = None
) -> list[Finding]:
    """Traduit un verdict en constats de la taxonomie (aucun si la tâche passe)."""
    if verdict.solvable == "yes":
        return []
    day = today or _dt.date.today()
    if verdict.solvable == "no":
        severity = Severity.HIGH if verdict.confidence >= 0.7 else Severity.MEDIUM
    else:
        severity = Severity.LOW
    return [
        Finding(
            category=BLOCKER_TO_CATEGORY.get(verdict.blocker, Category.CONTENT_DRIFT),
            severity=severity,
            # La confiance annoncée par le modèle est rabattue de 10 % : elle porte sur un
            # jugement sans accès au site, jamais sur une observation.
            confidence=round(verdict.confidence * 0.9, 3),
            evidence=verdict.reason or task.question[:160],
            detector=DETECTOR_NAME,
            channel=Channel.LLM,
            task_id=task.task_id,
            signal=f"solvability:{verdict.solvable}:{verdict.blocker}",
            details={
                "solvable": verdict.solvable,
                "blocker": verdict.blocker,
                "model_confidence": round(verdict.confidence, 3),
                "rationale": (
                    "jugement de faisabilité produit sans consulter le site : à confirmer "
                    "par une sonde L2 avant toute conclusion"
                ),
            },
            observed_at=day,
        )
    ]


def run_solvability(
    tasks: Sequence[Task],
    *,
    checker: SolvabilityChecker | None = None,
    today: _dt.date | None = None,
) -> tuple[list[SolvabilityVerdict], list[list[Finding]], CostLedger]:
    """Vérifie un lot de tâches ; renvoie verdicts, constats et comptabilité."""
    engine = checker or SolvabilityChecker(today=today)
    verdicts = engine.check(tasks)
    findings = [verdict_to_findings(t, v, today=today) for t, v in zip(tasks, verdicts)]
    return verdicts, findings, engine.ledger


def detect_solvability(
    task: Task, *, today: _dt.date | None = None, checker: SolvabilityChecker | None = None
) -> list[Finding]:
    """Interface détecteur : les constats de solvabilité d'une tâche unique."""
    _, findings, _ = run_solvability([task], checker=checker, today=today)
    return findings[0]


detect_solvability.name = DETECTOR_NAME  # type: ignore[attr-defined]


# Évaluation contre le substitut de vérité terrain


def load_removal_ground_truth() -> dict[str, set[str]]:
    """Identifiants retirés par les praticiens : Magnitude (suppressions) et browser-use."""
    patches = json.loads((ROOT / "data" / "raw" / "magnitude_patches.json").read_text(encoding="utf-8"))
    magnitude = {k for k, v in patches.items() if v.get("new") is None}
    browseruse = set(
        json.loads((ROOT / "data" / "raw" / "browseruse_impossible.json").read_text(encoding="utf-8"))
    )
    modified = {k for k, v in patches.items() if v.get("new") is not None}
    return {
        "magnitude_deleted": magnitude,
        "magnitude_modified": modified,
        "browseruse_impossible": browseruse,
        # « retirée » : le praticien a jugé la tâche irrécupérable.
        "union": magnitude | browseruse,
        "intersection": magnitude & browseruse,
        # « touchée » : le praticien est intervenu, par retrait OU par correction. C'est
        # le substitut pertinent pour un outil de maintenance, dont la question n'est pas
        # « faut-il supprimer ? » mais « faut-il intervenir ? ».
        "touched": magnitude | modified | browseruse,
    }


def sample_tasks(tasks: Sequence[Task], *, per_site: int, seed: int) -> list[Task]:
    """Échantillon stratifié par site, déterministe (même principe que le jeu annoté)."""
    by_site: dict[str, list[Task]] = collections.defaultdict(list)
    for task in tasks:
        by_site[task.site or "unknown"].append(task)
    picked: list[Task] = []
    for site in sorted(by_site):
        pool = sorted(by_site[site], key=lambda t: t.task_id)
        rng = random.Random(f"{seed}:{site}")
        picked.extend(rng.sample(pool, min(per_site, len(pool))))
    return sorted(picked, key=lambda t: (t.site or "", int(t.task_id.split("--")[1])))


def _prf(y_true: Sequence[int], y_pred: Sequence[int]) -> dict[str, float]:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Vérificateur de solvabilité L3 sur un échantillon de tâches WebVoyager.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--corpus", default=str(ROOT / "data" / "raw" / "webvoyager_original.jsonl"))
    parser.add_argument("--per-site", type=int, default=4, help="tâches tirées par site")
    parser.add_argument("--seed", type=int, default=20260816)
    parser.add_argument("--model", default="google/gemini-2.5-flash")
    parser.add_argument("--today", default="2026-08-15")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--audit-removed",
        action="store_true",
        help="évalue aussi toutes les tâches retirées par les praticiens (mesure du rappel)",
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    today = _dt.date.fromisoformat(args.today)
    tasks = list(load_webvoyager(args.corpus))
    sample = sample_tasks(tasks, per_site=args.per_site, seed=args.seed)
    truth = load_removal_ground_truth()

    ledger = CostLedger(label=f"solvability-{args.model.split('/')[-1]}")
    client = OpenRouterClient(ledger=ledger)
    checker = SolvabilityChecker(client, model=args.model, today=today, max_workers=args.workers)

    started = time.perf_counter()
    verdicts, findings, _ = run_solvability(sample, checker=checker, today=today)
    wall = time.perf_counter() - started

    # Le tirage aléatoire ne contient qu'une poignée de tâches retirées (≈ 9 % du corpus) :
    # il mesure bien le taux de fausse alerte en exploitation, mais pas le rappel. Le
    # rappel se mesure sur l'ensemble des tâches retirées, évalué à part — mélanger les
    # deux populations produirait une « précision » sans signification.
    removed_tasks = [t for t in tasks if t.task_id in truth["union"]]
    removed_extra = [t for t in removed_tasks if t.task_id not in {x.task_id for x in sample}]
    removed_verdicts: list[SolvabilityVerdict] = []
    if args.audit_removed and removed_extra:
        removed_verdicts = checker.check(removed_extra)
    all_removed_verdicts = removed_verdicts + [
        v for t, v in zip(sample, verdicts) if t.task_id in truth["union"]
    ]

    y_true = [1 if t.task_id in truth["union"] else 0 for t in sample]
    y_pred = [1 if v.is_blocked else 0 for v in verdicts]
    # Variante indulgente : « unclear » compte comme un signalement, ce qui est la
    # politique raisonnable pour une file de vérification L2 (on préfère vérifier une
    # tâche saine que rater une tâche morte).
    y_pred_lenient = [1 if v.solvable in ("no", "unclear") else 0 for v in verdicts]

    client.close()
    strict = _prf(y_true, y_pred)
    lenient = _prf(y_true, y_pred_lenient)
    # Second substitut, moins sévère : « le praticien est intervenu » (retrait ou
    # correction). Plusieurs « fausses alertes » du premier substitut sont en réalité des
    # tâches que Magnitude a re-datées plutôt que supprimées — le modèle avait raison,
    # c'est la vérité terrain qui était trop étroite.
    y_touched = [1 if t.task_id in truth["touched"] else 0 for t in sample]
    touched_metrics = _prf(y_touched, y_pred)
    by_blocker = collections.Counter(v.blocker for v in verdicts if v.is_blocked)
    by_verdict = collections.Counter(v.solvable for v in verdicts)

    payload = {
        "generated_at": _dt.date.today().isoformat(),
        "reference_date": today.isoformat(),
        "model": args.model,
        "sample": {
            "n": len(sample),
            "per_site": args.per_site,
            "seed": args.seed,
            "task_ids": [t.task_id for t in sample],
        },
        "ground_truth": {
            "definition": (
                "substitut : union des 53 suppressions de Magnitude et des 55 identifiants "
                "de WebVoyagerImpossibleTasks.json (browser-use) — 59 tâches, 49 en commun"
            ),
            "n_union": len(truth["union"]),
            "n_in_sample": sum(y_true),
            "limits": [
                "un retrait de praticien n'est pas toujours une infaisabilité de principe : "
                "certaines tâches ont été retirées pour dérive de contenu ou date périmée",
                "les deux listes se recouvrent à 49/59 : ce sont deux annotateurs très "
                "corrélés, pas deux mesures indépendantes",
                "le modèle juge sans consulter le site : le verdict est un a priori daté "
                "de sa coupure d'entraînement, à confirmer par une sonde L2",
            ],
        },
        "verdicts": [v.to_dict() for v in verdicts],
        "distribution": {"solvable": dict(by_verdict), "blockers": dict(by_blocker)},
        "agreement_with_any_practitioner_edit": {
            "definition": "retraits ∪ corrections (127 tâches sur 643)",
            "n_in_sample": sum(y_touched),
            "strict_no_only": touched_metrics,
        },
        "agreement_with_removals": {
            "strict_no_only": strict,
            "lenient_no_or_unclear": lenient,
            "false_alarm_rate_on_kept_tasks": round(
                sum(1 for t, v in zip(sample, verdicts) if v.is_blocked and t.task_id not in truth["union"])
                / max(1, sum(1 for t in sample if t.task_id not in truth["union"])),
                4,
            ),
        },
        "recall_on_removed_tasks": {
            "n": len(all_removed_verdicts),
            "audited": bool(args.audit_removed),
            "flagged_no": sum(1 for v in all_removed_verdicts if v.is_blocked),
            "flagged_no_or_unclear": sum(
                1 for v in all_removed_verdicts if v.solvable in ("no", "unclear")
            ),
            "recall": round(
                sum(1 for v in all_removed_verdicts if v.is_blocked) / max(1, len(all_removed_verdicts)),
                4,
            ),
            "blockers": dict(collections.Counter(v.blocker for v in all_removed_verdicts if v.is_blocked)),
            "verdicts": [v.to_dict() for v in all_removed_verdicts],
        },
        "cost": ledger.to_dict(),
        "wall_time_s": round(wall, 2),
        "findings_emitted": sum(len(f) for f in findings),
    }

    out = Path(args.out) if args.out else ROOT / "runs" / f"solvability_{_dt.date.today():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"modèle {args.model} — {len(sample)} tâches, {ledger.first_run_cost_usd:.5f} $ "
          f"({ledger.calls} appels facturés, {ledger.cached_calls} en cache), {wall:.1f} s")
    print(f"verdicts : {dict(by_verdict)}")
    print(f"motifs de blocage : {dict(by_blocker)}")
    print(f"accord avec les retraits de praticiens ({sum(y_true)}/{len(sample)} tâches retirées) :")
    print(f"  strict  (« no »)            P={strict['precision']:.3f} R={strict['recall']:.3f} F1={strict['f1']:.3f}")
    print(f"  indulgent (« no » ou « unclear ») P={lenient['precision']:.3f} R={lenient['recall']:.3f} F1={lenient['f1']:.3f}")
    if payload["recall_on_removed_tasks"]["n"]:
        rec = payload["recall_on_removed_tasks"]
        print(f"rappel sur les {rec['n']} tâches retirées par les praticiens : "
              f"{rec['flagged_no']}/{rec['n']} = {rec['recall']:.1%} — motifs {rec['blockers']}")
    print(f"accord avec « le praticien est intervenu » ({sum(y_touched)}/{len(sample)}) : "
          f"P={touched_metrics['precision']:.3f} R={touched_metrics['recall']:.3f} "
          f"F1={touched_metrics['f1']:.3f}")
    print(f"taux de fausse alerte sur les tâches conservées du tirage : "
          f"{payload['agreement_with_removals']['false_alarm_rate_on_kept_tasks']:.1%}")
    print(f"coût total (tirage + audit) : {ledger.first_run_cost_usd:.5f} $")
    print(f"rapport écrit : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
