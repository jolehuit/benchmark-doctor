r"""Score de stabilité task-side d'une tâche de benchmark, et échelle A/B/C/D.

La question posée est : cette tâche mesure-t-elle encore, à la date :math:`t`, ce
qu'elle mesurait à sa publication ? Ce n'est pas la fiabilité *agent-side* des travaux
de reliability (HAL, Rabanser et al., ICML 2026), qui fixent la tâche et font varier
l'exécution d'un agent sur quelques heures. Ici aucun agent n'est exécuté : la tâche est
l'objet mesuré, le monde est ce qui varie, l'échelle de temps est le mois. Les deux
dimensions se composent, et le dépôt écrit « stabilité task-side » ou « validité
longitudinale », jamais « stabilité » seule.

Le score se lit comme une probabilité de survie, chaque constat comme une perte espérée.
Pour une tâche :math:`\tau` observée à la date :math:`t` :

.. math::

   S(\tau, t) = \prod_{g \in \mathcal{T}} \bigl(1 - \rho_g(\tau, t)\bigr), \quad
   \rho_g = \max\Bigl(\max_{f \in F_g(\tau)} w(\sigma_f)\, c_f\, \kappa(\gamma_f, g)\,
                      e^{-\lambda_f (t - t_f)},\; \pi_g(\tau)\Bigr)

:math:`\mathcal{T}` est la taxonomie T1..T8, :math:`w` le poids de sévérité, :math:`c`
la confiance du détecteur, :math:`\kappa` la crédibilité du canal d'accès,
:math:`\lambda` le taux de péremption de l'observation, :math:`\pi_g` l'a priori des
praticiens (fraction des annotateurs ayant supprimé ou réécrit la tâche, pondérée par
``prior_remove_weight`` et ``prior_modify_weight``). Le maximum à l'intérieur d'une
catégorie évite de compter deux fois un même défaut vu par deux détecteurs ; le produit
entre catégories suppose les modes de défaillance indépendants, hypothèse que
`compare_aggregations` chiffre et que ``aggregation="max"`` annule.

Chaque constante est mesurée et son origine est donnée à sa définition :
`SEVERITY_WEIGHTS` (échelle ordinale grossière, assumée), `CHANNEL_CREDIBILITY`,
`WORLD_DECAY_PER_MONTH`, et `GRADE_THRESHOLDS` dont chaque frontière vaut 1 − w(σ),
soit « un constat de cette sévérité tenu pour certain ». Aucun seuil n'est ajusté sur la
vérité terrain, qui sert déjà à l'évaluation. `calibrate_channel_credibility` et
`calibrate_world_decay` les recalculent depuis leurs journaux.

Le score est **ordinal avant d'être cardinal** : aucun détecteur n'a de courbe de
fiabilité, donc comparer deux tâches est légitime, lire 0,62 comme « 62 % de chances de
survie » ne l'est pas. Il ne dit pas qu'une tâche est morte, il dit ce que les
détecteurs, le canal et six praticiens en savent à une date donnée.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .models import (
    GRADE_THRESHOLDS,
    SEVERITY_WEIGHTS,
    BenchmarkHealth,
    Category,
    Channel,
    Finding,
    Severity,
    TaskVerdict,
)

__all__ = [
    "StabilityModel",
    "DEFAULT_MODEL",
    "CategoryRisk",
    "StabilityAssessment",
    "PriorEvidence",
    "PractitionerPrior",
    "CHANNEL_CREDIBILITY",
    "GRADE_THRESHOLDS",
    "WORLD_DECAY_PER_MONTH",
    "finding_risk",
    "score_verdict",
    "score_health",
    "grade_for",
    "calibrate_channel_credibility",
    "calibrate_world_decay",
    "compare_aggregations",
    "compare_grade_scales",
    "sensitivity_channel_credibility",
    "aggregate_scores",
]


# Constantes calibrées

#: Crédibilité d'un constat d'**accès refusé** selon le canal qui l'a produit.
#:
#: Provenance : ``runs/l2_probe_20260815.json``, campagne du 15/08/2026. Trois URL
#: bloquées en HTTP direct disposaient d'un second canal navigateur ; deux étaient
#: servies normalement au navigateur, la troisième renvoyait le même challenge mais
#: celui-ci a été résolu par le navigateur. Estimateur de Laplace (k+1)/(n+2) avec k = 1,
#: n = 3 (lecture la plus favorable au constat de blocage) → 0,40.
#: Recalculable par `calibrate_channel_credibility`.
CHANNEL_CREDIBILITY: dict[Channel, float] = {
    # Un constat statique n'a pas de canal à mettre en doute : sa confiance est déjà
    # dans `Finding.confidence`.
    Channel.STATIC: 1.0,
    # Le canal le plus filtré, et le seul qui tourne en CI sans coût.
    Channel.HTTP_DATACENTER: 0.40,
    # Jamais mesuré ici (pas de proxy résidentiel disponible). On applique par défaut la
    # remise du datacenter : cela sous-estime la décadence plutôt que de la surestimer,
    # comme partout ailleurs dans le score. À recalibrer dès qu'une mesure existe.
    Channel.HTTP_RESIDENTIAL: 0.40,
    # Canal de référence : dans les quatre divergences mesurées, le navigateur a toujours
    # vu *plus* du site que le HTTP direct, jamais moins. Un blocage qui résiste à un
    # vrai navigateur est imputable au site.
    Channel.BROWSER_LOCAL: 1.0,
    Channel.BROWSER_CLOUD: 1.0,
    # Les détecteurs L3 rabattent déjà leur propre confiance de 10 % parce qu'ils jugent
    # sans consulter le site (cf. `l3_solvability.verdict_to_findings`). Appliquer ici une
    # seconde remise reviendrait à compter deux fois la même réserve.
    Channel.LLM: 1.0,
}

#: Taux de décadence mensuel d'une observation *de l'état du monde*.
#:
#: Provenance : journal de remplacement d'Online-Mind2Web (benchmark maintenu),
#: 52 tâches distinctes sur 300 remplacées entre le 05/04/2025 et le 15/05/2026 (13,35
#: mois) → λ = −ln(1 − 52/300)/13,35 = 0,0143, soit une demi-vie de 48 mois.
#: Contre-vérification sur WebVoyager : 169/643 tâches signalées en 17 mois → λ = 0,0180
#: (demi-vie 39 mois). Recalculable par `calibrate_world_decay`.
WORLD_DECAY_PER_MONTH: float = 0.0143

#: Bornes des notes : **importées de `models`**, jamais redéfinies ici. Le dépôt a porté
#: deux échelles concurrentes jusqu'au 16 août 2026, 0,85 / 0,60 / 0,35 d'un côté et
#: 0,75 / 0,50 / 0,25 de l'autre ; appliquées aux scores de la carte canonique elles
#: déplacent la note de 118 tâches sur 643 (A 193 / B 124 / C 146 / D 180 contre
#: A 210 / B 138 / C 185 / D 110). Il n'en reste qu'une, et le seul moyen de garantir
#: qu'elle reste unique est qu'un seul fichier la définisse. Ce ré-export existe pour les
#: appelants historiques.

#: Catégories pour lesquelles la crédibilité du canal s'applique. Un canal filtrant peut
#: fabriquer un refus d'accès ; il ne fabrique pas un 404 ni un contenu supprimé.
CHANNEL_SENSITIVE_CATEGORIES: frozenset[Category] = frozenset({Category.ACCESS_DENIED})

#: Détecteurs dont les constats sont des *propriétés de l'énoncé* et non des observations
#: du monde : ils ne périment pas (λ = 0). Tout ce qui n'est pas dans cette liste et qui
#: n'est pas un constat d'accès est traité comme une observation périssable.
_STATIC_LAYERS: frozenset[str] = frozenset({"L1"})

_DAYS_PER_MONTH = 30.436875  # année julienne moyenne / 12, pour convertir un Δjours


# Le modèle


@dataclass(frozen=True, slots=True)
class StabilityModel:
    """Paramètres du score de stabilité, tous explicites et tous justifiés.

    Instancier un modèle plutôt que de cabler des constantes rend l'analyse de
    sensibilité triviale (``replace(DEFAULT_MODEL, channel_credibility=...)``) et oblige
    le rapport à publier les paramètres qui ont produit ses chiffres.

    Args:
        severity_weights: poids ``w(σ)``, par défaut ceux de `models.SEVERITY_WEIGHTS`.
        channel_credibility: facteurs ``κ(γ)`` pour les constats d'accès refusé.
        world_decay_per_month: ``λ`` des observations de l'état du monde.
        access_decay_per_month: ``λ`` des constats d'accès. Vaut 0 par défaut : nous
            n'avons pas de mesure de la volatilité hebdomadaire des signatures anti-bot,
            et l'âge de l'observation est affiché plutôt que décoté.
        prior_remove_weight: ``w_rm``, poids d'une suppression par un praticien.
        prior_modify_weight: ``w_md``, poids d'une réécriture par un praticien.
        aggregation: ``"noisy_or"`` (défaut) ou ``"max"``, la formule de départ
            ``1 − max_f w(σ_f)·c_f``, pour l'ablation.
        staleness_days: âge au-delà duquel une observation réseau est signalée comme
            à re-mesurer dans le rapport.
    """

    severity_weights: Mapping[str, float] = field(
        default_factory=lambda: dict(SEVERITY_WEIGHTS)
    )
    channel_credibility: Mapping[Channel, float] = field(
        default_factory=lambda: dict(CHANNEL_CREDIBILITY)
    )
    world_decay_per_month: float = WORLD_DECAY_PER_MONTH
    access_decay_per_month: float = 0.0
    prior_remove_weight: float = 1.0
    prior_modify_weight: float = 0.5
    aggregation: str = "noisy_or"
    staleness_days: int = 30

    def __post_init__(self) -> None:
        if self.aggregation not in ("noisy_or", "max"):
            raise ValueError(f"agrégation inconnue : {self.aggregation!r}")
        for name in ("world_decay_per_month", "access_decay_per_month"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} doit être positif ou nul")

    def weight(self, severity: Severity) -> float:
        """``w(σ)`` : poids de sévérité."""
        return float(self.severity_weights[severity.value])

    def credibility(self, finding: Finding) -> float:
        """``κ(γ, g)`` : crédibilité du canal pour ce constat.

        Deux règles, dans cet ordre :

        1. **Un détecteur qui déclare son constat non imputable au site le voit annulé.**
           La couche L2 publie ``details["is_site_verdict"]`` : il vaut ``False`` pour les
           signatures ``channel_blocked`` (réponse fabriquée par le proxy d'egress) et
           ``unreachable`` (aucune réponse HTTP). Ce sont des faits sur la mesure, pas sur
           la tâche ; les compter reviendrait à dégrader un benchmark parce que notre
           réseau va mal. C'est la règle « on n'impute jamais à la tâche ce qui peut
           l'être à la mesure », rendue exécutable, et c'est elle qui épargne aux
           41 tâches GitHub un faux verdict de mort.
        2. **La remise de canal ne s'applique qu'aux constats d'accès refusé** issus d'un
           canal réseau : c'est la seule assertion qu'un canal de mesure peut fabriquer à
           lui seul. Un 404 ou un contenu supprimé ne s'inventent pas.
        """
        if finding.details.get("is_site_verdict") is False:
            return 0.0
        if finding.category not in CHANNEL_SENSITIVE_CATEGORIES:
            return 1.0
        if not finding.channel.is_networked:
            return 1.0
        return float(self.channel_credibility.get(finding.channel, 1.0))

    def decay_rate(self, finding: Finding) -> float:
        """``λ`` applicable à ce constat, en mois⁻¹."""
        if finding.layer in _STATIC_LAYERS:
            return 0.0
        if finding.category in CHANNEL_SENSITIVE_CATEGORIES:
            return self.access_decay_per_month
        return self.world_decay_per_month

    def freshness(self, finding: Finding, today: _dt.date) -> float:
        """``φ(t − t_f; λ)`` : facteur de fraîcheur, dans ]0, 1]."""
        lam = self.decay_rate(finding)
        if lam <= 0:
            return 1.0
        age_days = max(0, (today - finding.observed_at).days)
        return math.exp(-lam * age_days / _DAYS_PER_MONTH)

    def provenance(self) -> dict[str, Any]:
        """Paramètres et leur origine, à recopier dans tout rapport publié."""
        return {
            "aggregation": self.aggregation,
            "severity_weights": dict(self.severity_weights),
            "channel_credibility": {
                c.value: v for c, v in self.channel_credibility.items()
            },
            "channel_credibility_source": (
                "runs/l2_probe_20260815.json — 3 URL bloquées en HTTP direct disposant "
                "d'un canal navigateur, 1 blocage confirmé ; Laplace (k+1)/(n+2) = 0,40"
            ),
            "channel_credibility_scope": (
                "appliquée aux seuls constats T3 (accès refusé) issus d'un canal réseau"
            ),
            "world_decay_per_month": self.world_decay_per_month,
            "world_decay_source": (
                "journal Online-Mind2Web : 52/300 tâches remplacées en 13,35 mois "
                "→ λ = 0,0143/mois (demi-vie 48 mois) ; contre-vérification WebVoyager "
                "169/643 en 17 mois → λ = 0,0180 (demi-vie 39 mois)"
            ),
            "access_decay_per_month": self.access_decay_per_month,
            "access_decay_source": (
                "aucune mesure disponible de la volatilité hebdomadaire des signatures "
                "anti-bot (répétabilité mesurée sur 3 minutes seulement) : λ = 0 et l'âge "
                "de l'observation est affiché au lieu d'être décoté"
            ),
            "prior_weights": {
                "remove": self.prior_remove_weight,
                "modify": self.prior_modify_weight,
            },
            "prior_weights_source": (
                "suppression = irrécupérable (poids critical) ; réécriture = poids medium "
                "car Magnitude re-date par précaution des tâches encore valides, ce qui "
                "confond « cassée » et « rafraîchie »"
            ),
            "grade_thresholds": dict(GRADE_THRESHOLDS),
            "grade_thresholds_source": (
                "1 − w(σ) : chaque frontière est « un constat de cette sévérité tenu pour "
                "certain » ; aucun ajustement sur les données"
            ),
            "staleness_days": self.staleness_days,
        }


#: Modèle de référence, celui dont les chiffres sont publiés.
DEFAULT_MODEL = StabilityModel()


# A priori des praticiens


@dataclass(frozen=True, slots=True)
class PriorEvidence:
    """Ce que les praticiens ont dit d'une tâche, réduit à ce dont le score a besoin."""

    task_id: str
    n_annotators: int
    n_remove: int
    n_modify: int
    category: Category | None
    contested: bool
    sources_flagging: tuple[str, ...] = ()

    def risk(self, model: StabilityModel = DEFAULT_MODEL) -> float:
        """``π(τ)`` : risque estimé par jugement humain, dans [0, 1]."""
        if self.n_annotators <= 0:
            return 0.0
        value = (
            model.prior_remove_weight * self.n_remove
            + model.prior_modify_weight * self.n_modify
        ) / self.n_annotators
        return min(1.0, max(0.0, value))

    def to_dict(self, model: StabilityModel = DEFAULT_MODEL) -> dict[str, Any]:
        return {
            "n_annotators": self.n_annotators,
            "n_remove": self.n_remove,
            "n_modify": self.n_modify,
            "category": self.category.value if self.category else None,
            "contested": self.contested,
            "sources_flagging": list(self.sources_flagging),
            "risk": round(self.risk(model), 4),
        }


class PractitionerPrior:
    """Index des verdicts multi-annotateurs, chargé depuis ``data/ground_truth.json``.

    La base est produite par `benchmark_doctor.ground_truth.reconcile` : 643 tâches,
    8 sources datées dont 6 comptées dans l'accord (Skyvern figure deux fois comme jalon
    longitudinal mais une seule fois comme annotateur ; Emergence est écarté parce que ses
    exclusions se confondent avec un rééchantillonnage).

    L'objet est volontairement tolérant : si le fichier n'existe pas, l'index est vide et
    le score se calcule sans a priori. C'est le cas nominal pour un benchmark autre que
    WebVoyager : l'outil doit rester utilisable sans vérité terrain.
    """

    def __init__(self, entries: Mapping[str, PriorEvidence] | None = None,
                 *, source: str | None = None) -> None:
        self._entries: dict[str, PriorEvidence] = dict(entries or {})
        self.source = source

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, task_id: object) -> bool:
        return task_id in self._entries

    def get(self, task_id: str) -> PriorEvidence | None:
        return self._entries.get(task_id)

    @classmethod
    def empty(cls) -> "PractitionerPrior":
        return cls({}, source=None)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "PractitionerPrior":
        """Charge la base de verdicts ; renvoie un index vide si elle est absente."""
        target = Path(path) if path else _default_ground_truth_path()
        if not target.exists():
            return cls.empty()
        payload = json.loads(target.read_text(encoding="utf-8"))
        entries: dict[str, PriorEvidence] = {}
        for row in payload.get("taches", []):
            accord = row.get("accord") or {}
            actions = accord.get("actions") or {}
            taxo = row.get("taxonomie") or {}
            code = taxo.get("categorie")
            try:
                category = Category.from_code(code) if code else None
            except ValueError:  # pragma: no cover - étiquette hors taxonomie
                category = None
            entries[row["id"]] = PriorEvidence(
                task_id=row["id"],
                n_annotators=int(accord.get("n_annotateurs", 0)),
                n_remove=int(actions.get("remove", 0)),
                n_modify=int(actions.get("modify", 0)),
                category=category,
                contested=bool(accord.get("desaccord_exclusion", False)),
                sources_flagging=tuple(accord.get("signalee_par", []) or ()),
            )
        return cls(entries, source=_display_path(target))

    def describe(self) -> dict[str, Any]:
        flagged = [e for e in self._entries.values() if e.n_remove or e.n_modify]
        return {
            "source": self.source,
            "n_tasks": len(self._entries),
            "n_flagged_by_at_least_one": len(flagged),
            "n_contested": sum(1 for e in self._entries.values() if e.contested),
            "n_with_category_label": sum(
                1 for e in self._entries.values() if e.category is not None
            ),
        }


def _default_ground_truth_path() -> Path:
    """``<racine du dépôt>/data/ground_truth.json``, sans dépendre du répertoire courant."""
    return Path(__file__).resolve().parent.parent / "data" / "ground_truth.json"


def _display_path(target: Path) -> str:
    """Chemin relatif à la racine du dépôt s'il y est, absolu sinon.

    Les cartes de santé sont des artefacts versionnés : y écrire le chemin de la machine
    qui les a produites les rend inutilement dépendantes d'elle.
    """
    root = Path(__file__).resolve().parent.parent
    try:
        return str(Path(target).resolve().relative_to(root))
    except ValueError:
        return str(target)


# Résultat du calcul


@dataclass(frozen=True, slots=True)
class CategoryRisk:
    """Risque porté par une catégorie de la taxonomie, et sa preuve."""

    category: Category
    risk: float
    origin: str  # "detector" | "prior" | "detector+prior"
    driver: Finding | None = None
    explanation: str = ""

    def to_dict(self, *, include_driver: bool = True) -> dict[str, Any]:
        """Sérialise le risque.

        ``include_driver=False`` omet le constat brut. Ce n'est pas un détail : sur
        WebVoyager, le constat L2 d'un site est identique pour ses 45 tâches (une seule
        URL de départ par site), et le sérialiser à chaque tâche multiplie la taille du
        rapport par vingt sans ajouter une seule information. Les constats complets
        restent publiés dans la section « tâches les plus dégradées ».
        """
        out: dict[str, Any] = {
            "category": self.category.value,
            "risk": round(self.risk, 4),
            "origin": self.origin,
            "explanation": self.explanation,
        }
        if include_driver:
            out["driver"] = self.driver.to_dict() if self.driver else None
        elif self.driver is not None:
            out["driver_ref"] = {
                "detector": self.driver.detector,
                "signal": self.driver.signal,
                "severity": self.driver.severity.value,
                "confidence": round(self.driver.confidence, 3),
                "channel": self.driver.channel.value,
                "observed_at": self.driver.observed_at.isoformat(),
            }
        return out


@dataclass(frozen=True, slots=True)
class StabilityAssessment:
    """Score de stabilité task-side d'une tâche, avec tout ce qui l'explique.

    Deux scores sont toujours produits, parce qu'ils répondent à deux questions
    différentes et que les confondre serait malhonnête :

    - ``score_detector`` : ce que l'outil sait **seul**, aujourd'hui. C'est le chiffre
      reproductible et transposable à un autre benchmark.
    - ``score`` : le meilleur état des connaissances, a priori des praticiens compris.
      C'est le chiffre à publier dans un sous-ensemble « vérifié », mais il n'est
      disponible que là où une vérité terrain existe.
    """

    task_id: str
    site: str | None
    score: float
    grade: str
    score_detector: float
    grade_detector: str
    category_risks: tuple[CategoryRisk, ...]
    prior: PriorEvidence | None
    #: Risque venu d'un a priori praticien **sans étiquette de catégorie**. Il ne peut
    #: figurer dans `category_risks` (on ignore de quel mode de défaillance il relève),
    #: mais il porte le score : sans ce champ, une tâche notée D n'afficherait aucune
    #: explication, ce qui est exactement le défaut que l'outil reproche aux patch-sets.
    unlabelled_prior_risk: float
    prior_explanation: str
    worst_severity: Severity
    n_findings: int
    layers: tuple[str, ...]
    channels: tuple[Channel, ...]
    max_observation_age_days: int | None
    stale: bool
    evaluated_at: _dt.date
    notes: tuple[str, ...] = ()

    @property
    def top_risk(self) -> CategoryRisk | None:
        """Catégorie la plus risquée, celle à montrer dans une liste de tâches."""
        return max(self.category_risks, key=lambda r: r.risk, default=None)

    @property
    def headline_explanation(self) -> str:
        """La phrase à afficher : ce qui porte réellement le score de cette tâche.

        Un a priori praticien non étiqueté n'apparaît dans aucune catégorie ; s'il domine,
        c'est lui qu'il faut montrer, sinon le rapport afficherait un mauvais score sans
        aucune justification visible.
        """
        top = self.top_risk
        if top is not None and top.risk >= self.unlabelled_prior_risk:
            return top.explanation
        if self.prior_explanation:
            return self.prior_explanation
        return top.explanation if top else "aucun constat"

    @property
    def headline_category(self) -> str:
        """Code de catégorie à afficher, ou ``"?"`` pour un a priori non étiqueté."""
        top = self.top_risk
        if top is not None and top.risk >= self.unlabelled_prior_risk:
            return top.category.code
        return "?" if self.unlabelled_prior_risk > 0 else "—"

    @property
    def prior_delta(self) -> float:
        """Écart de score apporté par l'a priori des praticiens (≤ 0)."""
        return round(self.score - self.score_detector, 4)

    def to_dict(self, *, include_drivers: bool = True) -> dict[str, Any]:
        top = self.top_risk
        return {
            "task_id": self.task_id,
            "site": self.site,
            "stability_score": round(self.score, 4),
            "grade": self.grade,
            "stability_score_detector_only": round(self.score_detector, 4),
            "grade_detector_only": self.grade_detector,
            "prior_delta": self.prior_delta,
            "top_category": top.category.value if top else None,
            "top_risk": round(top.risk, 4) if top else 0.0,
            "headline_category": self.headline_category,
            "headline_explanation": self.headline_explanation,
            "unlabelled_prior_risk": round(self.unlabelled_prior_risk, 4),
            "worst_severity": self.worst_severity.value,
            "n_findings": self.n_findings,
            "layers": list(self.layers),
            "channels": [c.value for c in self.channels],
            "max_observation_age_days": self.max_observation_age_days,
            "stale": self.stale,
            "evaluated_at": self.evaluated_at.isoformat(),
            "category_risks": [
                r.to_dict(include_driver=include_drivers) for r in self.category_risks
            ],
            "prior": self.prior.to_dict() if self.prior else None,
            "notes": list(self.notes),
        }


# Le calcul


def finding_risk(
    finding: Finding,
    *,
    model: StabilityModel = DEFAULT_MODEL,
    today: _dt.date | None = None,
) -> float:
    """Risque effectif d'un constat : ``w(σ) · c · κ(γ) · φ(t − t_f)``.

    C'est la brique élémentaire de la formule ; tout le reste n'est que de l'agrégation.
    """
    day = today or finding.observed_at
    return (
        model.weight(finding.severity)
        * float(finding.confidence)
        * model.credibility(finding)
        * model.freshness(finding, day)
    )


def grade_for(score: float, thresholds: Mapping[str, float] | None = None) -> str:
    """Note A/B/C/D d'un score, selon les seuils du modèle.

    La comparaison est **stricte**, et ce n'est pas un détail d'implémentation : la
    frontière appartient à la note inférieure. Un constat de sévérité ``low`` tenu pour
    certain produit un risque de 0,25 exactement, donc un score de 0,75 exactement, et
    il doit faire perdre la note A, sans quoi la phrase « A = rien au-delà du niveau
    low » serait fausse au point précis où elle se joue. Avec ``>=``, une tâche portant
    un défaut certain serait déclarée saine.
    """
    table = thresholds or GRADE_THRESHOLDS
    for letter in ("A", "B", "C"):
        if score > table[letter]:
            return letter
    return "D"


def _combine(risks: Sequence[float], aggregation: str) -> float:
    """Agrège des risques indépendants : OU bruité (défaut) ou maximum (référence)."""
    if not risks:
        return 0.0
    if aggregation == "max":
        return max(risks)
    survival = 1.0
    for r in risks:
        survival *= 1.0 - min(1.0, max(0.0, r))
    return 1.0 - survival


def score_verdict(
    verdict: TaskVerdict,
    *,
    model: StabilityModel = DEFAULT_MODEL,
    prior: PriorEvidence | None = None,
    today: _dt.date | None = None,
) -> StabilityAssessment:
    """Calcule le score de stabilité task-side d'une tâche.

    Args:
        verdict: la tâche et ses constats, toutes couches confondues.
        model: paramètres du score (cf. `StabilityModel`).
        prior: verdicts des praticiens sur cette tâche, si disponibles.
        today: date de référence de l'évaluation. **Toujours la passer pour un chiffre
            publié** : la fraîcheur des observations en dépend.
    """
    day = today or verdict.evaluated_at
    notes: list[str] = []

    # 1. risque par catégorie, côté détecteurs
    per_category: dict[Category, tuple[float, Finding]] = {}
    for f in verdict.findings:
        r = finding_risk(f, model=model, today=day)
        current = per_category.get(f.category)
        if current is None or r > current[0]:
            per_category[f.category] = (r, f)

    detector_risks: dict[Category, CategoryRisk] = {}
    for category, (risk, driver) in per_category.items():
        detector_risks[category] = CategoryRisk(
            category=category,
            risk=risk,
            origin="detector",
            driver=driver,
            explanation=_explain(driver, risk, model, day),
        )

    score_detector = 1.0 - _combine(
        [r.risk for r in detector_risks.values()], model.aggregation
    )

    # 2. a priori des praticiens
    combined: dict[Category, CategoryRisk] = dict(detector_risks)
    prior_risk = prior.risk(model) if prior else 0.0
    unlabelled_prior = 0.0

    if prior is not None and prior_risk > 0:
        if prior.category is not None:
            # Étiquette de catégorie disponible : l'a priori entre dans la bonne case et
            # se combine par maximum avec le détecteur : pas de double comptage du même
            # mode de défaillance.
            existing = combined.get(prior.category)
            if existing is None or prior_risk > existing.risk:
                combined[prior.category] = CategoryRisk(
                    category=prior.category,
                    risk=prior_risk,
                    origin="detector+prior" if existing else "prior",
                    driver=existing.driver if existing else None,
                    explanation=_explain_prior(prior, prior_risk),
                )
            elif existing is not None:
                combined[prior.category] = replace(
                    existing,
                    origin="detector+prior",
                    explanation=existing.explanation
                    + " — "
                    + _explain_prior(prior, prior_risk),
                )
        else:
            # Sans étiquette, on ignore quel mode de défaillance les praticiens ont vu :
            # combiner par OU bruité risquerait de compter deux fois le même défaut. On
            # se rabat sur le maximum, plus conservateur.
            unlabelled_prior = prior_risk
            notes.append(
                "a priori praticiens sans étiquette de catégorie : combiné par maximum "
                "et non par OU bruité, pour ne pas compter deux fois le même défaut"
            )

    risk_combined = _combine([r.risk for r in combined.values()], model.aggregation)
    risk_combined = max(risk_combined, unlabelled_prior)
    score = 1.0 - risk_combined

    # 3. fraîcheur et traçabilité
    network_findings = [f for f in verdict.findings if f.channel.is_networked]
    ages = [max(0, (day - f.observed_at).days) for f in network_findings]
    max_age = max(ages) if ages else None
    stale = max_age is not None and max_age > model.staleness_days
    if stale:
        notes.append(
            f"observation réseau vieille de {max_age} jours (seuil {model.staleness_days}) : "
            "à re-mesurer avant publication — aucune décote n'est appliquée faute de taux "
            "mesuré pour la volatilité des signatures d'accès"
        )

    ordered = tuple(
        sorted(combined.values(), key=lambda r: (-r.risk, r.category.value))
    )
    layers = tuple(sorted({f.layer for f in verdict.findings}))
    return StabilityAssessment(
        task_id=verdict.task.task_id,
        site=verdict.task.site,
        score=round(score, 4),
        grade=grade_for(score),
        score_detector=round(score_detector, 4),
        grade_detector=grade_for(score_detector),
        category_risks=ordered,
        prior=prior,
        unlabelled_prior_risk=round(unlabelled_prior, 4),
        prior_explanation=_explain_prior(prior, prior_risk) if prior and prior_risk > 0 else "",
        worst_severity=verdict.worst_severity,
        n_findings=len(verdict.findings),
        layers=layers,
        channels=tuple(verdict.channels),
        max_observation_age_days=max_age,
        stale=stale,
        evaluated_at=day,
        notes=tuple(notes),
    )


def _explain(finding: Finding, risk: float, model: StabilityModel, day: _dt.date) -> str:
    """Phrase française expliquant d'où vient le risque."""
    parts = [
        f"{finding.detector} ({finding.signal or 'sans sous-motif'})",
        f"sévérité {finding.severity.value} (w={model.weight(finding.severity):.2f})",
        f"confiance {finding.confidence:.2f}",
    ]
    kappa = model.credibility(finding)
    if kappa < 1.0:
        parts.append(
            f"crédibilité du canal {finding.channel.value} κ={kappa:.2f} "
            "(un blocage vu depuis ce canal n'a pas résisté au navigateur dans nos mesures)"
        )
    phi = model.freshness(finding, day)
    if phi < 0.999:
        age = (day - finding.observed_at).days
        parts.append(f"fraîcheur φ={phi:.3f} (observation vieille de {age} j)")
    return " × ".join(parts) + f" → risque {risk:.3f}"


def _explain_prior(prior: PriorEvidence, risk: float) -> str:
    bits = []
    if prior.n_remove:
        bits.append(f"{prior.n_remove}/{prior.n_annotators} praticiens l'ont supprimée")
    if prior.n_modify:
        bits.append(f"{prior.n_modify}/{prior.n_annotators} l'ont réécrite")
    text = ", ".join(bits) or "aucun signalement"
    if prior.contested:
        text += " (désaccord dur : supprimée par au moins un, conservée intacte par un autre)"
    return f"a priori praticiens : {text} → risque {risk:.3f}"


# Agrégation au niveau du benchmark


def score_health(
    health: BenchmarkHealth,
    *,
    model: StabilityModel = DEFAULT_MODEL,
    prior: PractitionerPrior | None = None,
    today: _dt.date | None = None,
) -> list[StabilityAssessment]:
    """Score toutes les tâches d'un bulletin de santé, dans l'ordre du corpus."""
    day = today or health.generated_at
    index = prior or PractitionerPrior.empty()
    return [
        score_verdict(v, model=model, prior=index.get(v.task.task_id), today=day)
        for v in health.verdicts
    ]


def aggregate_scores(
    assessments: Sequence[StabilityAssessment],
    *,
    model: StabilityModel = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Agrégats publiables d'une liste de scores.

    Le score global d'un benchmark est la **moyenne** des scores de tâches, et non leur
    produit : un benchmark n'est pas « cassé » parce qu'une tâche l'est, il est dégradé
    en proportion. Le rapport publie aussi la médiane et la part de tâches sous chaque
    note, parce qu'une moyenne de 0,86 masque 65 tâches en D.
    """
    if not assessments:
        # Un résumé vide garde la même forme qu'un résumé plein : tout consommateur
        # (rapport HTML, différentiel) doit pouvoir lire les mêmes clés sans test préalable.
        return {
            "n_tasks": 0,
            "mean_stability": 1.0,
            "median_stability": 1.0,
            "min_stability": 1.0,
            "p10_stability": 1.0,
            "mean_stability_detector_only": 1.0,
            "grades": {g: 0 for g in ("A", "B", "C", "D")},
            "grade_rates": {g: 0.0 for g in ("A", "B", "C", "D")},
            "n_below_A": 0,
            "rate_below_A": 0.0,
            "n_D": 0,
            "rate_D": 0.0,
            "n_stale_observations": 0,
            "aggregation": model.aggregation,
        }
    scores = sorted(a.score for a in assessments)
    n = len(scores)
    grades = {g: 0 for g in ("A", "B", "C", "D")}
    for a in assessments:
        grades[a.grade] += 1
    detector_scores = [a.score_detector for a in assessments]
    return {
        "n_tasks": n,
        "mean_stability": round(sum(scores) / n, 4),
        "median_stability": round(scores[n // 2] if n % 2 else (scores[n // 2 - 1] + scores[n // 2]) / 2, 4),
        "min_stability": round(scores[0], 4),
        "p10_stability": round(scores[max(0, int(0.10 * n) - 1)], 4),
        "mean_stability_detector_only": round(sum(detector_scores) / n, 4),
        "grades": grades,
        "grade_rates": {g: round(c / n, 4) for g, c in grades.items()},
        "n_below_A": sum(1 for a in assessments if a.grade != "A"),
        "rate_below_A": round(sum(1 for a in assessments if a.grade != "A") / n, 4),
        "n_D": grades["D"],
        "rate_D": round(grades["D"] / n, 4),
        "n_stale_observations": sum(1 for a in assessments if a.stale),
        "aggregation": model.aggregation,
    }


# Calibration


def calibrate_channel_credibility(probe_report: str | Path) -> dict[str, Any]:
    """Recalcule ``κ`` depuis un rapport de sondes L2.

    Méthode : parmi les URL dont **un canal a rendu un verdict de blocage imputable au
    site**, ne garder que celles disposant d'un second canal *navigateur* ; compter
    combien de fois le blocage est confirmé. La crédibilité est l'estimateur de Laplace
    :math:`(k+1)/(n+2)`, qui évite de publier 0 ou 1 sur trois observations.

    Returns:
        dict avec ``n_checkable``, ``n_confirmed``, ``kappa_laplace``, ``kappa_naive``
        et le détail par URL.
    """
    payload = json.loads(Path(probe_report).read_text(encoding="utf-8"))
    per_url = payload.get("channel_dependence", {}).get("per_url", [])
    blocking = {"paywall_402", "forbidden_403", "antibot_challenge", "captcha",
                "rate_limited_429"}
    rows: list[dict[str, Any]] = []
    for entry in per_url:
        sigs: dict[str, str] = entry.get("signatures", {})
        direct = {k: v for k, v in sigs.items() if k.startswith("direct_http")}
        browser = {k: v for k, v in sigs.items()
                   if k.startswith("browser_cloud") or k.startswith("browser_local")}
        if not browser:
            continue
        if not any(v in blocking for v in direct.values()):
            continue
        confirmed = any(v in blocking for v in browser.values())
        rows.append({
            "url": entry.get("url"),
            "direct": direct,
            "browser": browser,
            "blocking_confirmed_by_browser": confirmed,
        })
    n = len(rows)
    k = sum(1 for r in rows if r["blocking_confirmed_by_browser"])
    return {
        "source": str(probe_report),
        "n_checkable": n,
        "n_confirmed": k,
        "kappa_naive": round(k / n, 4) if n else None,
        "kappa_laplace": round((k + 1) / (n + 2), 4) if n >= 0 else None,
        "detail": rows,
        "caveat": (
            "n très petit ; l'estimateur de Laplace est là pour ne pas publier 0 ou 1. "
            "Booking compte comme « confirmé » parce que la signature reste un challenge, "
            "alors que le navigateur l'a en fait résolu : c'est la lecture la plus "
            "favorable au constat de blocage, donc la plus prudente pour le score."
        ),
    }


def calibrate_world_decay(
    ground_truth: str | Path | None = None,
) -> dict[str, Any]:
    """Recalcule ``λ`` depuis les journaux de décadence disponibles.

    Deux estimations indépendantes :

    - **Online-Mind2Web** : benchmark *maintenu*, dont le journal de remplacement donne
      directement le nombre de tâches invalidées et la fenêtre d'observation. C'est
      l'estimation de référence.
    - **WebVoyager** : cumul des tâches signalées par au moins un annotateur, du premier
      au dernier jalon. Estimation de contrôle ; elle mesure autant l'attention des
      patcheurs que la décadence réelle.
    """
    target = Path(ground_truth) if ground_truth else _default_ground_truth_path()
    out: dict[str, Any] = {"source": str(target)}
    if not target.exists():
        out["error"] = "base de verdicts absente"
        return out
    payload = json.loads(target.read_text(encoding="utf-8"))
    stats = payload.get("statistiques", {})

    om2w = stats.get("om2w", {})
    if om2w:
        size = int(om2w.get("taille_corpus", 0))
        replaced = int(om2w.get("taches_distinctes_remplacees", 0))
        first = _dt.date.fromisoformat(om2w["premiere_vague"])
        last = _dt.date.fromisoformat(om2w["derniere_vague"])
        months = (last - first).days / _DAYS_PER_MONTH
        lam = -math.log(1 - replaced / size) / months if size and months else 0.0
        out["online_mind2web"] = {
            "corpus": size,
            "replaced": replaced,
            "window_months": round(months, 2),
            "lambda_per_month": round(lam, 5),
            "half_life_months": round(math.log(2) / lam, 1) if lam else None,
        }

    longitudinal = stats.get("longitudinal") or []
    coverage = stats.get("couverture", {})
    if longitudinal and coverage:
        first = _dt.date.fromisoformat(longitudinal[0]["date"])
        last = _dt.date.fromisoformat(longitudinal[-1]["date"])
        months = (last - first).days / _DAYS_PER_MONTH
        size = int(payload.get("meta", {}).get("n_taches", 0))
        flagged = int(coverage.get("signalee_par_au_moins_1", 0))
        lam = -math.log(1 - flagged / size) / months if size and months else 0.0
        out["webvoyager_control"] = {
            "corpus": size,
            "flagged": flagged,
            "window_months": round(months, 2),
            "lambda_per_month": round(lam, 5),
            "half_life_months": round(math.log(2) / lam, 1) if lam else None,
            "caveat": (
                "mesure l'attention cumulée de six patcheurs autant que la décadence : "
                "borne haute"
            ),
        }
    out["retained"] = WORLD_DECAY_PER_MONTH
    out["retained_source"] = "online_mind2web (benchmark maintenu, journal explicite)"
    return out


# Ablations et analyses de sensibilité


def compare_aggregations(
    health: BenchmarkHealth,
    *,
    prior: PractitionerPrior | None = None,
    today: _dt.date | None = None,
    model: StabilityModel = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Chiffre l'effet de l'hypothèse d'indépendance des catégories de la taxonomie.

    Compare l'agrégation par OU bruité (retenue) à l'agrégation par maximum, la formule
    de départ. L'effet dépend du nombre de couches exécutées : il reste faible tant
    qu'une seule facette du problème est instrumentée, peu de tâches cumulant alors
    plusieurs modes de défaillance, et il devient structurant quand les trois couches
    tournent ensemble. Sont renvoyés le nombre de tâches multi-catégories, l'écart absolu
    moyen des scores et la liste des notes déplacées, de quoi vérifier l'hypothèse au
    lieu de la supposer.
    """
    noisy = score_health(health, model=replace(model, aggregation="noisy_or"),
                         prior=prior, today=today)
    plain = score_health(health, model=replace(model, aggregation="max"),
                         prior=prior, today=today)
    deltas = [n.score - p.score for n, p in zip(noisy, plain)]
    changed = [
        {"task_id": n.task_id, "noisy_or": n.grade, "max": p.grade,
         "score_noisy_or": n.score, "score_max": p.score}
        for n, p in zip(noisy, plain) if n.grade != p.grade
    ]
    multi = sum(1 for a in noisy if len([r for r in a.category_risks if r.risk > 0]) > 1)
    return {
        "n_tasks": len(noisy),
        "n_tasks_multi_category": multi,
        "rate_multi_category": round(multi / len(noisy), 4) if noisy else 0.0,
        "mean_score_noisy_or": round(sum(a.score for a in noisy) / len(noisy), 4) if noisy else None,
        "mean_score_max": round(sum(a.score for a in plain) / len(plain), 4) if plain else None,
        "mean_abs_delta": round(sum(abs(d) for d in deltas) / len(deltas), 4) if deltas else 0.0,
        "max_abs_delta": round(max((abs(d) for d in deltas), default=0.0), 4),
        "n_grade_changes": len(changed),
        "grade_changes": changed[:25],
        "reading": (
            "Un écart faible signifie que l'hypothèse d'indépendance entre catégories ne "
            "porte pas les résultats : peu de tâches cumulent plusieurs modes de "
            "défaillance."
        ),
    }


def sensitivity_channel_credibility(
    health: BenchmarkHealth,
    *,
    values: Sequence[float] = (0.0, 0.20, 0.40, 0.714, 1.0),
    prior: PractitionerPrior | None = None,
    today: _dt.date | None = None,
    model: StabilityModel = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Effet du choix de ``κ`` sur les agrégats, le paramètre le moins bien estimé.

    ``0,714`` correspond à la lecture alternative (1 − 4/14, le taux de divergence de
    canal publié tous verdicts confondus) ; ``1,0`` à l'absence de remise, c'est-à-dire à
    un outil qui croirait son canal sur parole.
    """
    rows = []
    for kappa in values:
        credibility = dict(model.channel_credibility)
        credibility[Channel.HTTP_DATACENTER] = kappa
        credibility[Channel.HTTP_RESIDENTIAL] = kappa
        variant = replace(model, channel_credibility=credibility)
        assessments = score_health(health, model=variant, prior=prior, today=today)
        agg = aggregate_scores(assessments, model=variant)
        rows.append({
            "kappa": kappa,
            "mean_stability": agg["mean_stability"],
            "grades": agg["grades"],
            "n_D": agg["n_D"],
            "rate_below_A": agg["rate_below_A"],
        })
    return {
        "retained": model.channel_credibility.get(Channel.HTTP_DATACENTER),
        "rows": rows,
        "reading": (
            "κ = 1 revient à croire le canal de mesure sur parole : les tâches des sites "
            "protégés par un anti-bot basculent en D alors que nos mesures montrent que "
            "le site répond normalement à un navigateur. C'est l'erreur que le terme κ "
            "existe pour empêcher."
        ),
    }


def compare_grade_scales(
    assessments: Sequence[StabilityAssessment],
    *,
    legacy_thresholds: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Compare l'échelle en vigueur (1 − w(σ)) à l'échelle héritée, abandonnée.

    Depuis le 16 août 2026 le dépôt n'a plus qu'une échelle. Cette fonction ne compare
    donc plus deux conventions vivantes, elle **traduit les distributions publiées avant
    cette date** avec les seuils 0,85 / 0,60 / 0,35, pour qu'un lecteur puisse les
    rapprocher de la carte canonique sans croire à une erreur de mesure.
    """
    legacy = dict(legacy_thresholds or {"A": 0.85, "B": 0.60, "C": 0.35, "D": 0.0})
    new_counts = {g: 0 for g in ("A", "B", "C", "D")}
    old_counts = {g: 0 for g in ("A", "B", "C", "D")}
    migration: dict[str, int] = {}
    for a in assessments:
        new = grade_for(a.score)
        old = grade_for(a.score, legacy)
        new_counts[new] += 1
        old_counts[old] += 1
        if new != old:
            migration[f"{old}->{new}"] = migration.get(f"{old}->{new}", 0) + 1
    return {
        "thresholds_retained": dict(GRADE_THRESHOLDS),
        "thresholds_legacy": legacy,
        "distribution_retained": new_counts,
        "distribution_legacy": old_counts,
        "migrations": dict(sorted(migration.items(), key=lambda kv: -kv[1])),
        "justification_retained": (
            "chaque frontière vaut 1 − w(σ) : « un constat de cette sévérité tenu pour "
            "certain ». Aucun seuil n'est ajusté sur la vérité terrain, qui sert déjà à "
            "l'évaluation — l'ajuster serait circulaire."
        ),
    }


def most_degraded(
    assessments: Iterable[StabilityAssessment], *, limit: int = 25
) -> list[StabilityAssessment]:
    """Les tâches les plus dégradées, du pire score au meilleur."""
    return sorted(assessments, key=lambda a: (a.score, a.task_id))[:limit]


def by_site(assessments: Sequence[StabilityAssessment]) -> dict[str, dict[str, Any]]:
    """Ventilation par site : effectif, stabilité moyenne, notes, catégorie dominante."""
    buckets: dict[str, list[StabilityAssessment]] = {}
    for a in assessments:
        buckets.setdefault(a.site or "unknown", []).append(a)
    out: dict[str, dict[str, Any]] = {}
    for site, rows in buckets.items():
        grades = {g: 0 for g in ("A", "B", "C", "D")}
        categories: dict[str, int] = {}
        for a in rows:
            grades[a.grade] += 1
            top = a.top_risk
            if top and top.risk > 0:
                categories[top.category.value] = categories.get(top.category.value, 0) + 1
        dominant = max(categories.items(), key=lambda kv: kv[1])[0] if categories else None
        out[site] = {
            "n": len(rows),
            "mean_stability": round(sum(a.score for a in rows) / len(rows), 4),
            "min_stability": round(min(a.score for a in rows), 4),
            "grades": grades,
            "n_below_A": sum(1 for a in rows if a.grade != "A"),
            "rate_below_A": round(sum(1 for a in rows if a.grade != "A") / len(rows), 4),
            "dominant_category": dominant,
        }
    return dict(sorted(out.items(), key=lambda kv: kv[1]["mean_stability"]))


def by_category(assessments: Sequence[StabilityAssessment]) -> dict[str, dict[str, Any]]:
    """Ventilation par catégorie de la taxonomie : combien de tâches, quel risque moyen."""
    out: dict[str, dict[str, Any]] = {}
    for category in Category:
        rows = [
            r for a in assessments for r in a.category_risks
            if r.category is category and r.risk > 0
        ]
        n = len(rows)
        out[category.value] = {
            "code": category.code,
            "n_tasks": n,
            "rate": round(n / len(assessments), 4) if assessments else 0.0,
            "mean_risk": round(sum(r.risk for r in rows) / n, 4) if n else 0.0,
            "max_risk": round(max((r.risk for r in rows), default=0.0), 4),
            "origins": {
                origin: sum(1 for r in rows if r.origin == origin)
                for origin in ("detector", "prior", "detector+prior")
            },
        }
    return out
