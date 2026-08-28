"""benchmark-doctor — surveillance continue de la santé des benchmarks d'agents web.

L'outil applique à un corpus de tâches trois couches de détection, ordonnées par coût :

- **L1 statique** (ce paquet, sans réseau, coût nul) : dérive temporelle, effets de bord,
  références nommées ;
- **L2 sondes web** : liveness des URL, anti-bot/CAPTCHA, existence des contenus cités ;
- **L3 sondes LLM** : ambiguïté, solvabilité, fragilité de l'évaluation.

Le résultat est un `BenchmarkHealth` : un verdict par tâche, assorti d'un score de
stabilité, de la catégorie de decay et — point central — du **canal d'accès** depuis
lequel l'observation a été faite.

Utilisation typique :

    from benchmark_doctor import load_webvoyager, run_l1
    health = run_l1(load_webvoyager("data/raw/webvoyager_original.jsonl"))
    print(health.summary())
"""

from __future__ import annotations

import datetime as _dt
from typing import Iterable, Sequence

from .models import (
    BenchmarkHealth,
    Category,
    Channel,
    Detector,
    Finding,
    Severity,
    Task,
    TaskVerdict,
)
from .parsers.webvoyager import load_webvoyager, parse_webvoyager_record
from .detectors.l1_reference import detect_named_references
from .detectors.l1_sideeffect import detect_side_effects
from .detectors.l1_temporal import detect_temporal_decay

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "BenchmarkHealth",
    "Category",
    "Channel",
    "Detector",
    "Finding",
    "Severity",
    "Task",
    "TaskVerdict",
    "load_webvoyager",
    "parse_webvoyager_record",
    "detect_temporal_decay",
    "detect_side_effects",
    "detect_named_references",
    "L1_DETECTORS",
    "run_l1",
]

#: Les trois détecteurs de la couche statique, dans l'ordre du rapport.
L1_DETECTORS = (detect_temporal_decay, detect_side_effects, detect_named_references)


def run_l1(
    tasks: Iterable[Task],
    *,
    today: _dt.date | None = None,
    benchmark: str = "webvoyager",
    source: str | None = None,
    detectors: Sequence[Detector] | None = None,
) -> BenchmarkHealth:
    """Applique la couche L1 à un corpus et renvoie le bulletin de santé.

    Args:
        tasks: les tâches à analyser.
        today: date de référence de l'analyse. **Toujours la passer explicitement pour
            un chiffre publié** : les détecteurs temporels dépendent du jour de mesure,
            c'est précisément le propos du mémoire.
        benchmark: nom du benchmark analysé (figure dans le rapport).
        source: chemin ou URL du corpus, pour la traçabilité.
        detectors: détecteurs à appliquer ; par défaut les trois détecteurs L1.
    """
    day = today or _dt.date.today()
    dets = tuple(detectors) if detectors is not None else L1_DETECTORS
    health = BenchmarkHealth(
        benchmark=benchmark,
        generated_at=day,
        source=source,
        tool_version=__version__,
    )
    for task in tasks:
        verdict = TaskVerdict(task=task, evaluated_at=day, channels=[Channel.STATIC])
        for detector in dets:
            verdict.extend(detector(task, today=day))  # type: ignore[call-arg]
        health.verdicts.append(verdict)
    return health
