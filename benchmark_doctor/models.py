"""Vocabulaire commun aux trois couches de détection (L1 statique, L2 sondes web,
L3 sondes LLM) : la tâche analysée, le constat élémentaire, le verdict par tâche et le
bulletin de santé du benchmark.

Trois choix de conception, parce qu'ils ne vont pas de soi :

1. Le canal d'accès (`Channel`) est un attribut de premier plan du constat. Une même
   URL renvoie 402 depuis une IP de datacenter et 200 depuis un navigateur cloud : un
   verdict qui tait le canal de l'observation est irreproductible. Toute observation
   est donc datée et canalisée.

2. Sévérité et confiance sont séparées : la première dit à quel point la tâche est
   cassée si le constat est vrai, la seconde à quel point le détecteur est sûr de son
   constat. `Finding.risk` combine les deux.

3. Aucun verdict binaire n'est stocké. `TaskVerdict` garde la liste des constats et le
   caractère « signalé » est calculé à la demande depuis un seuil explicite, ce qui
   permet l'ablation de détecteurs sans réexécuter l'analyse.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Protocol,
    Sequence,
    runtime_checkable,
)

__all__ = [
    "Category",
    "Severity",
    "Channel",
    "Task",
    "Finding",
    "TaskVerdict",
    "BenchmarkHealth",
    "Detector",
    "SEVERITY_WEIGHTS",
    "GRADE_THRESHOLDS",
]


class Category(str, Enum):
    """Les 8 catégories de la taxonomie du decay des benchmarks web-live.

    Le code (T1..T8) est stable et sert de clé de mapping vers les taxonomies
    antérieures (Emergence-11, ABC task/outcome validity, codebook 2607.28367).
    """

    TEMPORAL = "T1_temporal"
    CONTENT_DRIFT = "T2_content_drift"
    ACCESS_DENIED = "T3_access_denied"
    UI_INSTABILITY = "T4_ui_instability"
    AMBIGUITY = "T5_ambiguity"
    MULTIPLE_SOLUTIONS = "T6_multiple_solutions"
    EVAL_BRITTLENESS = "T7_eval_brittleness"
    TIMING = "T8_timing"

    @property
    def code(self) -> str:
        """Code court de la catégorie, p. ex. ``"T1"``."""
        return self.value.split("_", 1)[0]

    @property
    def slug(self) -> str:
        """Nom lisible de la catégorie, p. ex. ``"temporal"``."""
        return self.value.split("_", 1)[1]

    @classmethod
    def from_code(cls, code: str) -> "Category":
        """Retrouve une catégorie depuis ``"T1"``, ``"t1"``, ``"temporal"`` ou sa valeur pleine."""
        needle = code.strip().lower()
        for member in cls:
            if needle in (member.value.lower(), member.code.lower(), member.slug.lower()):
                return member
        raise ValueError(f"catégorie inconnue : {code!r}")


#: Poids numérique de chaque sévérité, utilisé par le score de stabilité.
#: L'échelle est volontairement grossière : elle n'a pas vocation à être calibrée
#: finement, seulement à ordonner les constats de façon défendable.
SEVERITY_WEIGHTS: dict[str, float] = {
    "info": 0.0,
    "low": 0.25,
    "medium": 0.50,
    "high": 0.75,
    "critical": 1.0,
}

#: Unique échelle de notes du dépôt : `TaskVerdict.grade` et `scoring.grade_for` lisent
#: cette table et aucune autre. Chaque frontière vaut ``1 - w(sigma)``, soit « un constat
#: de cette sévérité tenu pour certain » ; aucun seuil n'est ajusté sur la vérité terrain,
#: qui sert déjà à l'évaluation.
#:
#: Une échelle 0,85 / 0,60 / 0,35 a coexisté avec celle-ci jusqu'au 16 août 2026, la
#: première ici, la seconde dans `scoring`. Sur la carte canonique elles donnaient
#: A 193 / B 124 / C 146 / D 180 contre A 210 / B 138 / C 185 / D 110, soit 118 tâches
#: sur 643 dont la note dépendait de l'échelle appliquée ; sur la carte statique, D 65
#: contre D 0. L'échelle héritée est abandonnée ; `scoring.compare_grade_scales` en
#: publie la correspondance, pour que les distributions publiées avant cette date restent
#: lisibles.
#:
#: Conséquence, avec le score de référence ``1 - max(risque)`` : aucune tâche analysée
#: par la seule couche L1 n'atteint la note D, aucun détecteur statique n'annonçant une
#: confiance de 1,0. La carte statique du 15 août 2026 donne A 509 / B 61 / C 73 / D 0.
GRADE_THRESHOLDS: dict[str, float] = {
    "A": 1.0 - SEVERITY_WEIGHTS["low"],  # 0,75
    "B": 1.0 - SEVERITY_WEIGHTS["medium"],  # 0,50
    "C": 1.0 - SEVERITY_WEIGHTS["high"],  # 0,25
    "D": 0.0,
}


class Severity(str, Enum):
    """Gravité du constat *si celui-ci est avéré* (indépendante de la confiance).

    - ``INFO``     : observation consignée, pas un défaut (p. ex. date future encore valide).
    - ``LOW``      : la tâche vieillit mais reste exécutable (requête archivistique datée).
    - ``MEDIUM``   : la tâche est probablement dégradée ou son attendu a bougé.
    - ``HIGH``     : la tâche est très probablement inexécutable telle quelle.
    - ``CRITICAL`` : inexécutabilité confirmée par observation directe (couche L2/L3).
    """

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def weight(self) -> float:
        """Poids dans [0, 1] utilisé par le score de stabilité."""
        return SEVERITY_WEIGHTS[self.value]

    @property
    def rank(self) -> int:
        """Rang ordinal (0 = info … 4 = critical), pour comparer et trier."""
        return list(SEVERITY_WEIGHTS).index(self.value)

    # Les comparaisons permettent d'écrire `if finding.severity >= Severity.HIGH`.
    def __lt__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, Severity):
            return self.rank < other.rank
        return NotImplemented

    def __le__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, Severity):
            return self.rank <= other.rank
        return NotImplemented

    def __gt__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, Severity):
            return self.rank > other.rank
        return NotImplemented

    def __ge__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, Severity):
            return self.rank >= other.rank
        return NotImplemented


class Channel(str, Enum):
    """Canal depuis lequel une observation a été faite.

    Mesuré le 15/08/2026 : une même URL renvoie 402 depuis une IP de datacenter et 200
    depuis un navigateur cloud. Le statut d'une tâche est donc une propriété du couple
    (tâche, canal), et un rapport qui omet le canal surestime le decay en comptant
    comme mortes des tâches simplement inaccessibles depuis l'infrastructure de mesure.
    """

    #: Analyse hors ligne : les constats L1 sont toujours sur ce canal.
    STATIC = "static"
    #: Requête HTTP depuis une IP de datacenter (CI, cloud), le canal le plus filtré.
    HTTP_DATACENTER = "http_datacenter"
    #: Requête HTTP depuis une IP résidentielle / proxy résidentiel.
    HTTP_RESIDENTIAL = "http_residential"
    #: Navigateur piloté localement (Playwright sur poste de travail).
    BROWSER_LOCAL = "browser_local"
    #: Navigateur piloté dans un service cloud (Browserbase & co.).
    BROWSER_CLOUD = "browser_cloud"
    #: Jugement produit par un modèle de langage, sans accès au site.
    LLM = "llm"

    @property
    def is_networked(self) -> bool:
        """Vrai si le canal implique un accès réseau au site cible."""
        return self not in (Channel.STATIC, Channel.LLM)


@dataclass(frozen=True, slots=True)
class Task:
    """Une tâche de benchmark, normalisée depuis son format d'origine.

    Les champs sont génériques parce que les corpus ne s'accordent pas sur les noms :
    WebVoyager publie (``id``, ``ques``, ``web_name``, ``web``), Online-Mind2Web
    d'autres. Le dictionnaire d'origine est conservé dans ``raw``.
    """

    task_id: str
    question: str
    site: str | None = None
    start_url: str | None = None
    benchmark: str = "unknown"
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id vide")
        if not isinstance(self.question, str):
            raise TypeError("question doit être une chaîne")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "question": self.question,
            "site": self.site,
            "start_url": self.start_url,
            "benchmark": self.benchmark,
        }


def _today() -> _dt.date:
    return _dt.date.today()


@dataclass(frozen=True, slots=True)
class Finding:
    """Un constat élémentaire produit par un détecteur sur une tâche.

    ``evidence`` cite l'extrait qui justifie le constat : jamais de verdict sans preuve.
    ``signal`` est le sous-motif interne du détecteur (``"past_date_transactional"``),
    granularité à laquelle se fait l'ablation. ``observed_at`` porte la date de
    l'observation, celle du jour à défaut, parce qu'une observation sans date ne dit rien
    d'un objet qui se dégrade dans le temps.

    ``channel`` vaut `Channel.STATIC` par défaut, ce qui convient aux détecteurs hors
    ligne, les seuls à pouvoir se passer d'un canal. Tout détecteur qui touche le réseau
    ou interroge un modèle renseigne le sien : laisser la valeur par défaut rendrait son
    constat irreproductible et lui vaudrait la crédibilité pleine accordée au statique
    par `scoring.StabilityModel.credibility`.
    """

    category: Category
    severity: Severity
    confidence: float
    evidence: str
    detector: str
    channel: Channel = Channel.STATIC
    task_id: str | None = None
    signal: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    observed_at: _dt.date = field(default_factory=_today)

    def __post_init__(self) -> None:
        # Coercition douce : accepter les chaînes facilite la relecture JSON et les tests.
        object.__setattr__(self, "category", Category(self.category))
        object.__setattr__(self, "severity", Severity(self.severity))
        object.__setattr__(self, "channel", Channel(self.channel))
        if isinstance(self.observed_at, str):
            object.__setattr__(self, "observed_at", _dt.date.fromisoformat(self.observed_at))
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError(f"confidence hors de [0, 1] : {self.confidence!r}")
        object.__setattr__(self, "confidence", float(self.confidence))
        if not self.detector:
            raise ValueError("detector vide : un constat doit être traçable")

    @property
    def risk(self) -> float:
        """Risque porté par le constat : ``severity.weight * confidence`` dans [0, 1]."""
        return self.severity.weight * self.confidence

    @property
    def layer(self) -> str:
        """Couche du détecteur (``"L1"``, ``"L2"``, ``"L3"``) déduite de son nom."""
        prefix = self.detector.split("_", 1)[0].upper()
        return prefix if prefix in ("L1", "L2", "L3") else "L?"

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
            "detector": self.detector,
            "channel": self.channel.value,
            "task_id": self.task_id,
            "signal": self.signal,
            "details": dict(self.details),
            "observed_at": self.observed_at.isoformat(),
            "risk": round(self.risk, 3),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Finding":
        data = dict(payload)
        data.pop("risk", None)
        data.pop("layer", None)
        return cls(**data)


#: Seuil de sévérité à partir duquel une tâche est considérée « signalée » (flag dur).
#: Exposé comme constante parce qu'un taux de tâches signalées dépend de ce seuil autant
#: que des détecteurs : le publier sans lui le rendrait ininterprétable.
DEFAULT_FLAG_THRESHOLD = Severity.HIGH


@dataclass(slots=True)
class TaskVerdict:
    """Ce que l'outil sait d'une tâche à un instant donné : la liste de ses constats.

    Non binaire par construction : `is_flagged` applique un seuil de sévérité explicite,
    ce qui permet de rejouer plusieurs politiques de décision sur la même analyse.
    """

    task: Task
    findings: list[Finding] = field(default_factory=list)
    evaluated_at: _dt.date = field(default_factory=_today)
    channels: list[Channel] = field(default_factory=lambda: [Channel.STATIC])

    def add(self, finding: Finding) -> "TaskVerdict":
        """Ajoute un constat, en propageant l'identifiant de tâche s'il manque."""
        if finding.task_id is None:
            finding = Finding(
                category=finding.category,
                severity=finding.severity,
                confidence=finding.confidence,
                evidence=finding.evidence,
                detector=finding.detector,
                channel=finding.channel,
                task_id=self.task.task_id,
                signal=finding.signal,
                details=finding.details,
                observed_at=finding.observed_at,
            )
        self.findings.append(finding)
        if finding.channel not in self.channels:
            self.channels.append(finding.channel)
        return self

    def extend(self, findings: Iterable[Finding]) -> "TaskVerdict":
        for f in findings:
            self.add(f)
        return self

    @property
    def worst_severity(self) -> Severity:
        """Sévérité maximale observée (``INFO`` si aucun constat)."""
        return max((f.severity for f in self.findings), default=Severity.INFO)

    @property
    def risk(self) -> float:
        """Risque de la tâche : le maximum des risques de ses constats."""
        return max((f.risk for f in self.findings), default=0.0)

    @property
    def stability_score(self) -> float:
        """Score de stabilité par défaut : ``1 - max(risque des constats)``.

        Le module ``scoring`` en propose une version enrichie (historique, accord
        inter-patch-sets) ; celle-ci reste la référence sans dépendance externe.
        """
        return round(1.0 - self.risk, 3)

    @property
    def grade(self) -> str:
        """Note A/B/C/D dérivée du score de stabilité (A = sain, D = probablement mort).

        La comparaison est stricte : la frontière appartient à la note inférieure. Un
        constat ``low`` tenu pour certain produit exactement 0,75 et doit faire perdre
        la note A, sans quoi « A = rien au-delà du niveau low » serait faux au point
        précis où la phrase se joue.
        """
        s = self.stability_score
        for letter in ("A", "B", "C"):
            if s > GRADE_THRESHOLDS[letter]:
                return letter
        return "D"

    @property
    def categories(self) -> list[Category]:
        """Catégories distinctes présentes dans les constats, dans l'ordre T1..T8."""
        present = {f.category for f in self.findings}
        return [c for c in Category if c in present]

    def is_flagged(self, threshold: Severity = DEFAULT_FLAG_THRESHOLD) -> bool:
        """Vrai si au moins un constat atteint le seuil de sévérité donné."""
        return any(f.severity >= threshold for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.task.to_dict(),
            "evaluated_at": self.evaluated_at.isoformat(),
            "channels": [c.value for c in self.channels],
            "stability_score": self.stability_score,
            "grade": self.grade,
            "worst_severity": self.worst_severity.value,
            "categories": [c.value for c in self.categories],
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(slots=True)
class BenchmarkHealth:
    """Bulletin de santé d'un benchmark entier : l'objet sérialisé par le rapport.

    Les agrégations sont calculées à la demande depuis les verdicts, pour qu'un rapport
    ne puisse pas afficher un total incohérent avec son détail.
    """

    benchmark: str
    verdicts: list[TaskVerdict] = field(default_factory=list)
    generated_at: _dt.date = field(default_factory=_today)
    source: str | None = None
    tool_version: str = "0.1.0"
    notes: list[str] = field(default_factory=list)

    def __iter__(self) -> Iterator[TaskVerdict]:
        return iter(self.verdicts)

    def __len__(self) -> int:
        return len(self.verdicts)

    @property
    def n_tasks(self) -> int:
        return len(self.verdicts)

    @property
    def channels(self) -> list[Channel]:
        """Canaux effectivement utilisés dans ce bulletin (traçabilité de la mesure)."""
        seen: list[Channel] = []
        for v in self.verdicts:
            for c in v.channels:
                if c not in seen:
                    seen.append(c)
        return seen

    def flagged(
        self,
        threshold: Severity = DEFAULT_FLAG_THRESHOLD,
        predicate: "Callable[[TaskVerdict], bool] | None" = None,
    ) -> list[TaskVerdict]:
        """Tâches signalées, par seuil de sévérité ou par une politique explicite.

        ``predicate`` rejoue une politique de décision arbitraire sur une analyse déjà
        calculée, ce qui rend l'ablation gratuite.
        """
        test = predicate or (lambda v: v.is_flagged(threshold))
        return [v for v in self.verdicts if test(v)]

    def flag_rate(
        self,
        threshold: Severity = DEFAULT_FLAG_THRESHOLD,
        predicate: "Callable[[TaskVerdict], bool] | None" = None,
    ) -> float:
        """Part des tâches signalées, dans [0, 1]."""
        if not self.verdicts:
            return 0.0
        return len(self.flagged(threshold, predicate)) / len(self.verdicts)

    def category_prevalence(self) -> dict[str, int]:
        """Nombre de tâches concernées par catégorie (une tâche peut compter plusieurs fois)."""
        counts = {c.value: 0 for c in Category}
        for v in self.verdicts:
            for c in v.categories:
                counts[c.value] += 1
        return counts

    def signal_counts(self) -> dict[str, int]:
        """Nombre de tâches touchées par sous-motif de détecteur (granularité d'ablation)."""
        counts: dict[str, int] = {}
        for v in self.verdicts:
            for signal in {f.signal for f in v.findings if f.signal}:
                counts[signal] = counts.get(signal, 0) + 1  # type: ignore[index]
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def grade_distribution(self) -> dict[str, int]:
        counts = {g: 0 for g in ("A", "B", "C", "D")}
        for v in self.verdicts:
            counts[v.grade] += 1
        return counts

    def by_site(
        self,
        threshold: Severity = DEFAULT_FLAG_THRESHOLD,
        predicate: "Callable[[TaskVerdict], bool] | None" = None,
    ) -> dict[str, dict[str, Any]]:
        """Ventilation par site : effectif, tâches signalées, taux, stabilité moyenne."""
        test = predicate or (lambda v: v.is_flagged(threshold))
        buckets: dict[str, list[TaskVerdict]] = {}
        for v in self.verdicts:
            buckets.setdefault(v.task.site or "unknown", []).append(v)
        out: dict[str, dict[str, Any]] = {}
        for site, vs in buckets.items():
            flagged = sum(1 for v in vs if test(v))
            out[site] = {
                "n": len(vs),
                "flagged": flagged,
                "flag_rate": round(flagged / len(vs), 3),
                "mean_stability": round(sum(v.stability_score for v in vs) / len(vs), 3),
            }
        return dict(sorted(out.items(), key=lambda kv: -kv[1]["flag_rate"]))

    @property
    def mean_stability(self) -> float:
        if not self.verdicts:
            return 1.0
        return round(sum(v.stability_score for v in self.verdicts) / len(self.verdicts), 3)

    def summary(
        self,
        threshold: Severity = DEFAULT_FLAG_THRESHOLD,
        predicate: "Callable[[TaskVerdict], bool] | None" = None,
        policy: str | None = None,
    ) -> dict[str, Any]:
        """Résumé compact, l'en-tête du rapport de santé.

        ``policy`` est un libellé consigné tel quel : un taux de tâches signalées n'a de
        sens qu'accompagné de la règle qui l'a produit.
        """
        flagged = self.flagged(threshold, predicate)
        return {
            "benchmark": self.benchmark,
            "generated_at": self.generated_at.isoformat(),
            "source": self.source,
            "tool_version": self.tool_version,
            "channels": [c.value for c in self.channels],
            "flag_threshold": threshold.value,
            "flag_policy": policy or f"severity>={threshold.value}",
            "n_tasks": self.n_tasks,
            "n_flagged": len(flagged),
            "flag_rate": round(self.flag_rate(threshold, predicate), 4),
            "mean_stability": self.mean_stability,
            "grades": self.grade_distribution(),
            "categories": self.category_prevalence(),
        }

    def to_dict(
        self,
        threshold: Severity = DEFAULT_FLAG_THRESHOLD,
        predicate: "Callable[[TaskVerdict], bool] | None" = None,
        policy: str | None = None,
    ) -> dict[str, Any]:
        return {
            "summary": self.summary(threshold, predicate, policy),
            "signals": self.signal_counts(),
            "by_site": self.by_site(threshold, predicate),
            "notes": self.notes,
            "tasks": [v.to_dict() for v in self.verdicts],
        }


@runtime_checkable
class Detector(Protocol):
    """Contrat minimal d'un détecteur : une fonction de la tâche vers des constats.

    Les détecteurs L2/L3 ajoutent leurs propres paramètres (client HTTP, modèle) mais
    exposent la même signature d'appel.
    """

    name: str

    def __call__(self, task: Task) -> Sequence[Finding]: ...
