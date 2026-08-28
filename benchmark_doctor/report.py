"""Carte de santé d'un benchmark : sérialisation JSON et rendu HTML autonome.

Quatre règles ont guidé la conception du rapport, qui doit résister à la question
« d'où sort ce chiffre ? ».

1. Aucun chiffre sans sa provenance : l'en-tête porte la date de mesure, le corpus et
   son empreinte, les couches exécutées, les canaux, les paramètres du score et le coût
   réel. Un taux de tâches dégradées est une propriété du couple (benchmark, mesure),
   pas du benchmark.

2. Aucun verdict sans sa preuve : chaque tâche listée montre le constat qui porte son
   risque et la décomposition du calcul (sévérité, confiance, canal, fraîcheur).

3. Le HTML est autonome : CSS inlinée, aucune police distante, aucun script, aucune
   image externe. Un rapport qui exige un CDN pourrit avant le benchmark qu'il
   surveille, ce qui est exactement le mode de défaillance étudié ici.

4. `compare_cards` produit le différentiel entre deux mesures datées. C'est cette vue,
   pas la carte isolée, qui distingue une surveillance continue d'un audit ponctuel.

Le gabarit HTML et la feuille de style vivent dans ``templates/`` à la racine du dépôt,
résolus dans l'ordre : argument explicite, variable d'environnement
``BDOCTOR_TEMPLATES``, ``templates/`` relatif au paquet, puis gabarit minimal embarqué
pour qu'une installation en wheel sans données de paquet produise tout de même un
rapport lisible.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import html
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import BenchmarkHealth, Category, Channel
from .scoring import (
    DEFAULT_MODEL,
    GRADE_THRESHOLDS,
    PractitionerPrior,
    StabilityAssessment,
    StabilityModel,
    aggregate_scores,
    by_category,
    by_site,
    most_degraded,
)

__all__ = [
    "MeasurementCost",
    "HealthCard",
    "build_card",
    "render_html",
    "write_card",
    "CardDiff",
    "compare_cards",
    "render_diff_html",
    "write_diff",
    "TERMINOLOGY_NOTE",
]

SCHEMA_VERSION = "bdoctor-health-card/1"


@dataclass(slots=True)
class MeasurementCost:
    """Coût réel d'une campagne de mesure, ventilé par couche.

    Les montants viennent du champ ``usage.cost`` d'OpenRouter, donc facturés et non
    estimés. L1 et L2 sont gratuites en argent et se paient en temps et en requêtes
    réseau, comptés séparément pour ne pas les faire passer pour sans coût.
    """

    usd_by_layer: dict[str, float] = field(default_factory=dict)
    calls_by_layer: dict[str, int] = field(default_factory=dict)
    seconds_by_layer: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(self, layer: str, *, usd: float = 0.0, calls: int = 0, seconds: float = 0.0) -> None:
        self.usd_by_layer[layer] = self.usd_by_layer.get(layer, 0.0) + float(usd)
        self.calls_by_layer[layer] = self.calls_by_layer.get(layer, 0) + int(calls)
        self.seconds_by_layer[layer] = self.seconds_by_layer.get(layer, 0.0) + float(seconds)

    @property
    def total_usd(self) -> float:
        return round(sum(self.usd_by_layer.values()), 6)

    @property
    def total_calls(self) -> int:
        return sum(self.calls_by_layer.values())

    @property
    def total_seconds(self) -> float:
        return round(sum(self.seconds_by_layer.values()), 2)

    def per_task(self, n_tasks: int) -> float:
        return round(self.total_usd / n_tasks, 8) if n_tasks else 0.0

    def to_dict(self, n_tasks: int = 0) -> dict[str, Any]:
        return {
            "total_usd": self.total_usd,
            "total_calls": self.total_calls,
            "total_seconds": self.total_seconds,
            "usd_per_task": self.per_task(n_tasks),
            "by_layer": {
                layer: {
                    "usd": round(self.usd_by_layer.get(layer, 0.0), 6),
                    "calls": self.calls_by_layer.get(layer, 0),
                    "seconds": round(self.seconds_by_layer.get(layer, 0.0), 2),
                }
                for layer in sorted(
                    set(self.usd_by_layer) | set(self.calls_by_layer) | set(self.seconds_by_layer)
                )
            },
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MeasurementCost":
        cost = cls(notes=list(payload.get("notes", [])))
        for layer, row in (payload.get("by_layer") or {}).items():
            cost.add(
                layer,
                usd=float(row.get("usd", 0.0)),
                calls=int(row.get("calls", 0)),
                seconds=float(row.get("seconds", 0.0)),
            )
        return cost


TERMINOLOGY_NOTE: dict[str, Any] = {
    "titre": "Stabilité task-side ≠ fiabilité agent-side",
    "corps": (
        "Le score de cette carte porte sur la <b>tâche</b>, pas sur l'agent. Il mesure si "
        "l'item de benchmark mesure encore, à la date indiquée, ce qu'il mesurait à sa "
        "publication. Il ne faut pas le confondre avec la <i>reliability</i> agent-side "
        "de HAL / Rabanser et al. (ICML 2026), qui mesure la variance du résultat d'un "
        "même agent entre plusieurs exécutions de la même tâche. Les deux dimensions sont "
        "orthogonales et se composent : un agent parfaitement reproductible sur une tâche "
        "périmée produit un chiffre parfaitement reproductible et parfaitement faux."
    ),
    "lignes": [
        ("Objet mesuré", "l'agent", "la tâche (l'item de benchmark)"),
        ("Ce qui varie", "l'exécution (décodage, harnais)", "le monde (le web vivant)"),
        ("Protocole", "k exécutions de la même tâche", "1 mesure datée, répétée dans le temps"),
        ("Échelle de temps", "minutes à heures", "mois à années"),
        ("Symptôme", "variance du score entre exécutions",
         "le score reste stable et ne veut plus rien dire"),
        ("Remède", "répéter, publier un intervalle", "re-dater, réparer ou retirer la tâche"),
    ],
}


@dataclass(slots=True)
class HealthCard:
    """Bulletin de santé complet d'un benchmark à une date donnée."""

    benchmark: str
    generated_at: _dt.date
    corpus_path: str | None
    corpus_digest: str | None
    n_tasks: int
    layers: list[str]
    channels: list[str]
    tool_version: str
    model: StabilityModel
    assessments: list[StabilityAssessment]
    cost: MeasurementCost = field(default_factory=MeasurementCost)
    prior_description: dict[str, Any] = field(default_factory=dict)
    limits: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Configuration effective des détecteurs (profil de canal L2, backend L3). Deux
    #: mesures qui ne partagent pas leur backend L3 ne sont pas comparables ; `CardDiff`
    #: doit pouvoir le dire au lieu de laisser attribuer un changement d'outil à une
    #: décadence du web.
    protocol: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return aggregate_scores(self.assessments, model=self.model)

    def to_dict(self, *, max_tasks_detailed: int = 0) -> dict[str, Any]:
        """Sérialisation canonique.

        ``max_tasks_detailed=0`` sérialise toutes les tâches : la carte est la source du
        différentiel, et un diff sur un échantillon ne veut rien dire.
        """
        rows = self.assessments if not max_tasks_detailed else most_degraded(
            self.assessments, limit=max_tasks_detailed
        )
        return {
            "schema": SCHEMA_VERSION,
            "meta": {
                "benchmark": self.benchmark,
                "generated_at": self.generated_at.isoformat(),
                "tool_version": self.tool_version,
                "corpus": self.corpus_path,
                "corpus_sha256": self.corpus_digest,
                "n_tasks": self.n_tasks,
                "layers": list(self.layers),
                "channels": list(self.channels),
                "protocol": dict(self.protocol),
                "ground_truth_prior": self.prior_description,
            },
            "scoring_model": self.model.provenance(),
            "summary": self.summary(),
            "cost": self.cost.to_dict(self.n_tasks),
            "by_category": by_category(self.assessments),
            "by_site": by_site(self.assessments),
            # Les tâches les plus dégradées portent leurs constats complets (preuve
            # citable) ; la liste exhaustive est compacte, sans quoi le même constat L2 de
            # site serait recopié pour chacune de ses 45 tâches.
            "most_degraded": [
                a.to_dict(include_drivers=True) for a in most_degraded(self.assessments, limit=40)
            ],
            "tasks": [a.to_dict(include_drivers=False) for a in rows],
            "terminology": TERMINOLOGY_NOTE,
            "limits": list(self.limits),
            "notes": list(self.notes),
            "extra": dict(self.extra),
        }

    def write_json(self, path: str | Path, **kwargs: Any) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(**kwargs), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        return target


def sha256_of(path: str | Path, *, limit: int = 64) -> str | None:
    """Empreinte du corpus : deux mesures ne sont comparables que sur le même corpus."""
    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None
    return digest[:limit]


def build_card(
    health: BenchmarkHealth,
    *,
    model: StabilityModel = DEFAULT_MODEL,
    prior: PractitionerPrior | None = None,
    assessments: Sequence[StabilityAssessment] | None = None,
    today: _dt.date | None = None,
    layers: Sequence[str] = ("L1",),
    cost: MeasurementCost | None = None,
    limits: Sequence[str] = (),
    notes: Sequence[str] = (),
    protocol: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> HealthCard:
    """Construit la carte de santé depuis un bulletin déjà calculé.

    ``layers`` est la liste des couches *effectivement* exécutées : une carte sans L2 ne
    dit rien de l'accessibilité des sites, et le rapport doit l'afficher plutôt que de
    laisser croire à une mesure complète. ``assessments`` évite de recalculer les scores
    quand l'appelant les a déjà.
    """
    from .scoring import score_health  # import local : évite un cycle à la lecture

    day = today or health.generated_at
    index = prior or PractitionerPrior.empty()
    rows = list(assessments) if assessments is not None else score_health(
        health, model=model, prior=index, today=day
    )
    return HealthCard(
        benchmark=health.benchmark,
        generated_at=day,
        corpus_path=health.source,
        corpus_digest=sha256_of(health.source) if health.source else None,
        n_tasks=len(rows),
        layers=list(layers),
        channels=[c.value for c in health.channels],
        tool_version=health.tool_version,
        model=model,
        assessments=rows,
        cost=cost or MeasurementCost(),
        prior_description=index.describe(),
        limits=list(limits) or list(default_limits(layers, health)),
        notes=list(notes) + list(health.notes),
        protocol=dict(protocol or {}),
        extra=dict(extra or {}),
    )


def default_limits(layers: Sequence[str], health: BenchmarkHealth) -> list[str]:
    """Limites déduites de ce qui a été exécuté, et de ce qui ne l'a pas été.

    Une carte L1 seule ne dit rien de la dérive de contenu (rappel mesuré à 0 % sur cette
    catégorie) : sans ces lignes, un lecteur interpréterait un score élevé comme une
    bonne santé.
    """
    out: list[str] = []
    upper = {l.upper() for l in layers}
    if "L2" not in upper:
        out.append(
            "Couche L2 non exécutée : aucune URL n'a été sondée. La dérive de contenu "
            "(T2) et le refus d'accès (T3) ne sont donc vus que par leurs indices "
            "textuels — le rappel de la couche statique sur la dérive de contenu est "
            "mesuré à 0 %. Un score élevé signifie « rien de visible dans l'énoncé », "
            "pas « tâche en bonne santé »."
        )
    if "L3" not in upper:
        out.append(
            "Couche L3 non exécutée : l'ambiguïté (T5) et la solvabilité ne sont pas "
            "évaluées. Ces défauts n'empêchent pas la tâche de s'exécuter, ils rendent "
            "son verdict arbitraire — ils sont invisibles pour les couches L1 et L2."
        )
    if any(c is Channel.HTTP_DATACENTER for c in health.channels):
        out.append(
            "Les sondes réseau sont parties d'une IP de datacenter. Sur les trois sites "
            "bloqués que nous avons pu recouper avec un navigateur, deux répondaient "
            "normalement à celui-ci : les constats d'accès refusé sont donc pondérés par "
            "κ = 0,40 et ne doivent pas être lus comme des tâches mortes."
        )
    out.append(
        "Les sondes ne portent que sur l'URL de départ de chaque tâche — WebVoyager n'en "
        "fournit pas d'autre. Rien n'est dit de l'état du site après navigation : les "
        "taux publiés bornent la décadence par le bas."
    )
    out.append(
        "Le score est ordinal avant d'être cardinal : les confiances des détecteurs ne "
        "sont pas calibrées. Comparer deux tâches est légitime, lire un score comme une "
        "probabilité ne l'est pas."
    )
    return out


def _templates_dir(explicit: str | Path | None = None) -> Path | None:
    """Résout le répertoire des gabarits (cf. docstring du module)."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("BDOCTOR_TEMPLATES")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve().parent
    candidates.append(here.parent / "templates")
    candidates.append(here / "templates")
    for candidate in candidates:
        if (candidate / "health_card.html").exists():
            return candidate
    return None


#: Coquille minimale utilisée si ``templates/`` est introuvable (installation sans données
#: de paquet). Volontairement sobre : le rapport reste lisible et complet, il est
#: seulement moins soigné, et le pied de page le signale.
_FALLBACK_SHELL = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{title}}</title><style>{{css}}</style></head><body><main>
<header class="card-head"><h1>{{benchmark}}</h1><p class="subtitle">{{subtitle}}</p>
<dl class="provenance">{{provenance}}</dl></header>
{{sections}}
<aside class="terminology">{{terminology}}</aside>
<section><h2>Limites de cette mesure</h2><ul class="limits">{{limits}}</ul></section>
<footer>{{footer}}</footer></main></body></html>"""

_FALLBACK_CSS = (
    "body{font-family:system-ui,sans-serif;max-width:64rem;margin:2rem auto;padding:0 1rem;"
    "line-height:1.5}table{border-collapse:collapse;width:100%;font-size:.9rem}"
    "th,td{border:1px solid #ccc;padding:.35rem .6rem;text-align:left}"
    "h2{font-size:1rem;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid #ccc}"
    ".num{text-align:right;font-variant-numeric:tabular-nums}"
)


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _pct(x: float, digits: int = 1) -> str:
    return f"{100 * x:.{digits}f} %"


def _grade_badge(grade: str) -> str:
    return f'<span class="badge g-{_esc(grade)}">{_esc(grade)}</span>'


def _table(headers: Sequence[tuple[str, bool]], rows: Sequence[Sequence[str]]) -> str:
    """Tableau HTML. ``headers`` = (libellé, aligné à droite)."""
    head = "".join(
        f'<th class="{"num" if right else ""}">{_esc(label)}</th>' for label, right in headers
    )
    body = []
    for row in rows:
        cells = "".join(row)
        body.append(f"<tr>{cells}</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _kpi(value: str, label: str, sub: str = "") -> str:
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return f'<div class="kpi"><div class="value">{value}</div><div class="label">{_esc(label)}</div>{sub_html}</div>'


def _grade_bar(grades: Mapping[str, int], total: int, *, compact: bool = False) -> str:
    """Barre empilée des notes. ``compact`` produit la variante fine, pour les tableaux."""
    if not total:
        return ""
    parts = []
    for letter in ("A", "B", "C", "D"):
        n = grades.get(letter, 0)
        if not n:
            continue
        width = 100 * n / total
        label = "" if compact else (f"{letter} {n}" if width > 6 else "")
        parts.append(f'<span class="g-{letter}" style="width:{width:.3f}%">{label}</span>')
    cls = "grade-bar compact" if compact else "grade-bar"
    title = " ".join(f"{g} {grades.get(g, 0)}" for g in ("A", "B", "C", "D"))
    return f'<div class="{cls}" title="{_esc(title)}">' + "".join(parts) + "</div>"


def _terminology_html() -> str:
    rows = "".join(
        f"<tr><td>{_esc(a)}</td><td>{_esc(b)}</td><td>{_esc(c)}</td></tr>"
        for a, b, c in TERMINOLOGY_NOTE["lignes"]
    )
    return (
        f'<h2>{_esc(TERMINOLOGY_NOTE["titre"])}</h2>'
        f'<p>{TERMINOLOGY_NOTE["corps"]}</p>'
        '<div class="table-wrap"><table><thead><tr><th></th>'
        "<th>Fiabilité agent-side (HAL, Rabanser)</th>"
        "<th>Validité task-side (cette carte)</th></tr></thead><tbody>"
        f"{rows}</tbody></table></div>"
    )


def _provenance_html(pairs: Sequence[tuple[str, str]]) -> str:
    return "".join(
        f"    <dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>\n" for k, v in pairs if v not in (None, "")
    )


def _section(title: str, body: str, note: str = "") -> str:
    note_html = f'<p class="note">{note}</p>' if note else ""
    return f"<section><h2>{_esc(title)}</h2>{body}{note_html}</section>"


def render_html(
    card: HealthCard,
    *,
    template_dir: str | Path | None = None,
    max_degraded: int = 30,
) -> str:
    """Rend la carte de santé en une page HTML autonome (CSS inlinée, aucun script)."""
    summary = card.summary()

    kpis = "".join([
        _kpi(f'{summary["mean_stability"]:.3f}', "stabilité moyenne",
             f'médiane {summary["median_stability"]:.3f}'),
        _kpi(f'{summary["rate_below_A"] * 100:.1f} %', "tâches sous la note A",
             f'{summary["n_below_A"]} / {card.n_tasks}'),
        _kpi(str(summary["n_D"]), "tâches en note D",
             "à ne pas publier sans revue"),
        _kpi(f'{card.cost.total_usd:.4f} $', "coût de la mesure",
             f'{card.cost.total_calls} appels · {card.cost.total_seconds:.0f} s'),
    ])
    sections = [
        _section(
            "Vue d'ensemble",
            f'<div class="kpi-row">{kpis}</div>'
            + '<div style="margin-top:1rem">'
            + _grade_bar(summary["grades"], card.n_tasks)
            + '<div class="legend">'
            + "".join(
                f'<span><b>{g}</b> S ≥ {GRADE_THRESHOLDS[g]:.2f} — '
                f'{summary["grades"][g]} tâches ({_pct(summary["grade_rates"][g])})</span>'
                for g in ("A", "B", "C", "D")
            )
            + "</div></div>",
            "Le score global est la moyenne des scores de tâches, jamais leur produit : un "
            "benchmark n'est pas cassé parce qu'une tâche l'est, il est dégradé en "
            "proportion. La moyenne masque la queue de distribution, d'où la barre de notes.",
        )
    ]

    cats = by_category(card.assessments)
    cat_rows = []
    max_n = max((row["n_tasks"] for row in cats.values()), default=0) or 1
    for value, row in cats.items():
        if not row["n_tasks"]:
            continue
        category = Category(value)
        width = 100 * row["n_tasks"] / max_n
        origins = row["origins"]
        cat_rows.append([
            f'<td class="id">{_esc(category.code)}</td>',
            f"<td>{_esc(_CATEGORY_LABELS.get(category, category.slug))}</td>",
            f'<td class="num">{row["n_tasks"]}</td>',
            f'<td class="num">{_pct(row["rate"])}</td>',
            f'<td class="num">{row["mean_risk"]:.3f}</td>',
            f'<td><span class="bar-track"><span class="bar" style="width:{width:.2f}%"></span></span></td>',
            f'<td class="why">détecteurs {origins["detector"]} · praticiens '
            f'{origins["prior"]} · les deux {origins["detector+prior"]}</td>',
        ])
    sections.append(
        _section(
            "Répartition par catégorie de la taxonomie",
            _table(
                [("Code", False), ("Mode de décadence", False), ("Tâches", True),
                 ("Part", True), ("Risque moyen", True), ("", False), ("Origine du constat", False)],
                cat_rows,
            ),
            "Une tâche peut relever de plusieurs catégories : la somme des effectifs dépasse "
            "le nombre de tâches. La colonne « origine » distingue ce que les détecteurs ont "
            "vu de ce que les praticiens avaient déjà signalé — c'est la mesure de ce que "
            "l'outil apporte au-delà de la vérité terrain.",
        )
    )

    site_rows = []
    for site, row in by_site(card.assessments).items():
        bar = _grade_bar(row["grades"], row["n"], compact=True)
        site_rows.append([
            f"<td>{_esc(site)}</td>",
            f'<td class="num">{row["n"]}</td>',
            f'<td class="num">{row["mean_stability"]:.3f}</td>',
            f'<td class="num">{row["min_stability"]:.3f}</td>',
            f'<td class="num">{row["n_below_A"]} ({_pct(row["rate_below_A"], 0)})</td>',
            f'<td style="min-width:9rem">{bar}</td>',
            f'<td class="why">{_esc(row["dominant_category"] or "—")}</td>',
        ])
    sections.append(
        _section(
            "Par site",
            _table(
                [("Site", False), ("n", True), ("Stabilité ⌀", True), ("min", True),
                 ("Sous A", True), ("Notes", False), ("Catégorie dominante", False)],
                site_rows,
            ),
            "Trié par stabilité croissante. Un site entier en bas de tableau signale un "
            "sous-ensemble à retirer plutôt que des tâches à réparer une à une.",
        )
    )

    worst_rows = []
    for a in most_degraded(card.assessments, limit=max_degraded):
        stale = ' <span class="badge neutral">à re-mesurer</span>' if a.stale else ""
        worst_rows.append([
            f'<td class="id">{_esc(a.task_id)}</td>',
            f"<td>{_grade_badge(a.grade)}</td>",
            f'<td class="num">{a.score:.3f}</td>',
            f'<td class="num">{a.score_detector:.3f}</td>',
            f'<td class="id">{_esc(a.headline_category)}</td>',
            f'<td class="why">{_esc(a.headline_explanation)}{stale}</td>',
        ])
    sections.append(
        _section(
            f"Les {len(worst_rows)} tâches les plus dégradées",
            _table(
                [("Tâche", False), ("Note", False), ("Score", True),
                 ("Score détecteurs seuls", True), ("Cat.", False), ("Ce qui porte le risque", False)],
                worst_rows,
            ),
            "« Score détecteurs seuls » exclut l'a priori des praticiens : c'est le chiffre "
            "que l'outil produirait sur un benchmark sans vérité terrain, donc le seul "
            "transposable. L'écart entre les deux colonnes mesure ce que l'outil doit encore "
            "à des annotateurs humains.",
        )
    )

    provenance = card.model.provenance()
    model_rows = [
        ["<td>κ (crédibilité du canal)</td>",
         f'<td class="num">{provenance["channel_credibility"].get("http_datacenter", 1.0):.2f}</td>',
         f'<td class="why">{_esc(provenance["channel_credibility_source"])}</td>'],
        ["<td>λ (décadence d'une observation)</td>",
         f'<td class="num">{provenance["world_decay_per_month"]:.4f}/mois</td>',
         f'<td class="why">{_esc(provenance["world_decay_source"])}</td>'],
        ["<td>λ (constats d'accès)</td>",
         f'<td class="num">{provenance["access_decay_per_month"]:.4f}/mois</td>',
         f'<td class="why">{_esc(provenance["access_decay_source"])}</td>'],
        ["<td>Poids des praticiens</td>",
         f'<td class="num">suppr. {provenance["prior_weights"]["remove"]:.2f} · '
         f'réécr. {provenance["prior_weights"]["modify"]:.2f}</td>',
         f'<td class="why">{_esc(provenance["prior_weights_source"])}</td>'],
        ["<td>Seuils de note</td>",
         f'<td class="num">{" · ".join(f"{g}≥{v:.2f}" for g, v in GRADE_THRESHOLDS.items() if g != "D")}</td>',
         f'<td class="why">{_esc(provenance["grade_thresholds_source"])}</td>'],
        ["<td>Agrégation</td>",
         f'<td class="num">{_esc(provenance["aggregation"])}</td>',
         '<td class="why">OU bruité entre catégories (modes de défaillance indépendants), '
         'maximum à l\'intérieur d\'une catégorie (pas de double comptage d\'une même preuve)</td>'],
    ]
    sections.append(
        _section(
            "Paramètres du score et leur provenance",
            "<p>S(τ,t) = ∏<sub>g∈T1..T8</sub> (1 − ρ<sub>g</sub>) &nbsp;·&nbsp; "
            "ρ<sub>g</sub> = max( max<sub>f∈g</sub> w(σ<sub>f</sub>)·c<sub>f</sub>·κ(γ<sub>f</sub>)"
            "·φ(t−t<sub>f</sub>) , π<sub>g</sub> )</p>"
            + _table([("Paramètre", False), ("Valeur", True), ("Provenance", False)], model_rows),
            "Aucune de ces valeurs n'est un réglage : chacune est recalculable par une "
            "fonction du module <code>scoring</code> à partir des mesures citées.",
        )
    )

    cost_rows = []
    for layer, row in card.cost.to_dict(card.n_tasks)["by_layer"].items():
        cost_rows.append([
            f"<td>{_esc(layer)}</td>",
            f'<td class="num">{row["usd"]:.5f} $</td>',
            f'<td class="num">{row["calls"]}</td>',
            f'<td class="num">{row["seconds"]:.1f} s</td>',
        ])
    if cost_rows:
        sections.append(
            _section(
                "Coût de la mesure",
                _table([("Couche", False), ("Coût", True), ("Appels", True), ("Temps", True)], cost_rows)
                + f'<p class="note">Total {card.cost.total_usd:.5f} $ pour {card.n_tasks} '
                  f"tâches, soit {card.cost.per_task(card.n_tasks):.2e} $ par tâche. "
                  + " ".join(_esc(x) for x in card.cost.notes)
                  + "</p>",
            )
        )

    prior_desc = card.prior_description or {}
    provenance_pairs = [
        ("Date de la mesure", card.generated_at.isoformat()),
        ("Corpus", card.corpus_path or "—"),
        ("Empreinte SHA-256", card.corpus_digest or "—"),
        ("Tâches", str(card.n_tasks)),
        ("Couches exécutées", ", ".join(card.layers) or "—"),
        ("Canaux d'accès", ", ".join(card.channels) or "—"),
        ("A priori praticiens",
         f'{prior_desc.get("n_flagged_by_at_least_one", 0)} tâches signalées par ≥1 '
         f'annotateur sur {prior_desc.get("n_tasks", 0)}' if prior_desc.get("n_tasks")
         else "aucun (score détecteurs seuls)"),
        ("Outil", f"benchmark-doctor {card.tool_version}"),
    ]

    dirpath = _templates_dir(template_dir)
    if dirpath:
        shell = (dirpath / "health_card.html").read_text(encoding="utf-8")
        css_path = dirpath / "health_card.css"
        css = css_path.read_text(encoding="utf-8") if css_path.exists() else _FALLBACK_CSS
        footer_extra = ""
    else:
        shell, css = _FALLBACK_SHELL, _FALLBACK_CSS
        footer_extra = " Gabarit embarqué (répertoire <code>templates/</code> introuvable)."

    footer = (
        f"Généré par benchmark-doctor {_esc(card.tool_version)} le "
        f"{_esc(card.generated_at.isoformat())}. Page autonome : aucune ressource externe, "
        "aucun script. Le score mesure la validité <b>task-side</b> de chaque tâche, pas la "
        "performance d'un agent." + footer_extra
    )
    limits_html = "".join(f"    <li>{_esc(x)}</li>\n" for x in card.limits)

    out = shell
    for marker, value in [
        ("{{title}}", f"Carte de santé — {card.benchmark} — {card.generated_at.isoformat()}"),
        ("{{css}}", css),
        ("{{benchmark}}", _esc(f"Carte de santé — {card.benchmark}")),
        ("{{subtitle}}", _esc(
            f"{card.n_tasks} tâches · mesure du {card.generated_at.isoformat()} · "
            f"couches {'+'.join(card.layers)} · stabilité moyenne {summary['mean_stability']:.3f}"
        )),
        ("{{provenance}}", _provenance_html(provenance_pairs)),
        ("{{sections}}", "\n".join(sections)),
        ("{{terminology}}", _terminology_html()),
        ("{{limits}}", limits_html),
        ("{{footer}}", footer),
    ]:
        out = out.replace(marker, value)
    return out


_CATEGORY_LABELS: dict[Category, str] = {
    Category.TEMPORAL: "Dérive temporelle",
    Category.CONTENT_DRIFT: "Dérive de contenu ou d'URL",
    Category.ACCESS_DENIED: "Accès refusé et effets de bord",
    Category.UI_INSTABILITY: "Instabilité d'interface",
    Category.AMBIGUITY: "Ambiguïté de l'énoncé",
    Category.MULTIPLE_SOLUTIONS: "Solutions valides multiples",
    Category.EVAL_BRITTLENESS: "Fragilité de l'évaluation",
    Category.TIMING: "Dépendance de timing",
}


def write_card(
    card: HealthCard,
    *,
    json_path: str | Path | None = None,
    html_path: str | Path | None = None,
    template_dir: str | Path | None = None,
) -> dict[str, str]:
    """Écrit la carte en JSON et/ou en HTML ; renvoie les chemins produits."""
    written: dict[str, str] = {}
    if json_path:
        written["json"] = str(card.write_json(json_path))
    if html_path:
        target = Path(html_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_html(card, template_dir=template_dir), encoding="utf-8")
        written["html"] = str(target)
    return written


@dataclass(slots=True)
class CardDiff:
    """Écart de santé entre deux cartes datées.

    Trois précautions de lecture sont encodées dans l'objet :

    - la comparabilité est vérifiée, pas supposée : empreinte du corpus, couches et
      canaux sont confrontés et tout écart est signalé, faute de quoi comparer une mesure
      L1 à une mesure L1+L2 produirait une fausse dégradation due au seul protocole ;
    - les tâches apparues et disparues sont comptées à part des tâches dégradées, un
      corpus qui rétrécit n'étant pas un corpus qui guérit ;
    - la dégradation se mesure sur le score et non sur la note : une tâche peut perdre
      0,2 point sans changer de lettre, et c'est encore un signal.
    """

    before: dict[str, Any]
    after: dict[str, Any]
    epsilon: float = 0.01

    def comparability(self) -> dict[str, Any]:
        a, b = self.before["meta"], self.after["meta"]
        warnings: list[str] = []
        if a.get("corpus_sha256") != b.get("corpus_sha256"):
            warnings.append(
                "Les deux mesures ne portent pas sur le même fichier de corpus "
                f"({a.get('corpus_sha256')} vs {b.get('corpus_sha256')}) : une partie des "
                "écarts vient du corpus, pas de la santé du benchmark."
            )
        if set(a.get("layers", [])) != set(b.get("layers", [])):
            warnings.append(
                f"Couches différentes ({a.get('layers')} vs {b.get('layers')}) : "
                "l'écart de score est en partie un artefact de protocole."
            )
        if set(a.get("channels", [])) != set(b.get("channels", [])):
            warnings.append(
                f"Canaux d'accès différents ({a.get('channels')} vs {b.get('channels')}) : "
                "nous avons mesuré qu'une même URL change de verdict selon le canal."
            )
        pa, pb = a.get("protocol") or {}, b.get("protocol") or {}
        for key in sorted(set(pa) | set(pb)):
            if pa.get(key) != pb.get(key):
                warnings.append(
                    f"Configuration de détecteur différente ({key} : {pa.get(key)!r} vs "
                    f"{pb.get(key)!r}) : l'écart de score mesure un changement d'outil "
                    "autant qu'un changement du benchmark."
                )
        if self.before.get("scoring_model") != self.after.get("scoring_model"):
            warnings.append(
                "Paramètres du modèle de score différents entre les deux mesures : "
                "les scores ne sont pas comparables tels quels."
            )
        return {
            "comparable": not warnings,
            "warnings": warnings,
            "days_elapsed": self.days_elapsed,
        }

    @property
    def days_elapsed(self) -> int:
        a = _dt.date.fromisoformat(self.before["meta"]["generated_at"])
        b = _dt.date.fromisoformat(self.after["meta"]["generated_at"])
        return (b - a).days

    def _index(self, card: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {row["task_id"]: row for row in card.get("tasks", [])}

    def to_dict(self, *, limit: int = 40) -> dict[str, Any]:
        before, after = self._index(self.before), self._index(self.after)
        common = sorted(set(before) & set(after))
        appeared = sorted(set(after) - set(before))
        disappeared = sorted(set(before) - set(after))

        degraded, improved, unchanged = [], [], 0
        grade_migration: dict[str, int] = {}
        for task_id in common:
            b, a = before[task_id], after[task_id]
            delta = a["stability_score"] - b["stability_score"]
            if b["grade"] != a["grade"]:
                key = f'{b["grade"]}->{a["grade"]}'
                grade_migration[key] = grade_migration.get(key, 0) + 1
            row = {
                "task_id": task_id,
                "site": a.get("site"),
                "score_before": b["stability_score"],
                "score_after": a["stability_score"],
                "delta": round(delta, 4),
                "grade_before": b["grade"],
                "grade_after": a["grade"],
                "top_category_before": b.get("top_category"),
                "top_category_after": a.get("top_category"),
            }
            if delta <= -self.epsilon:
                degraded.append(row)
            elif delta >= self.epsilon:
                improved.append(row)
            else:
                unchanged += 1

        degraded.sort(key=lambda r: r["delta"])
        improved.sort(key=lambda r: -r["delta"])

        sum_before, sum_after = self.before["summary"], self.after["summary"]
        cat_before = self.before.get("by_category", {})
        cat_after = self.after.get("by_category", {})
        category_delta = {}
        for value in set(cat_before) | set(cat_after):
            nb = cat_before.get(value, {}).get("n_tasks", 0)
            na = cat_after.get(value, {}).get("n_tasks", 0)
            if nb or na:
                category_delta[value] = {"before": nb, "after": na, "delta": na - nb}

        site_before = self.before.get("by_site", {})
        site_after = self.after.get("by_site", {})
        site_delta = {}
        for site in set(site_before) | set(site_after):
            sb = site_before.get(site, {}).get("mean_stability")
            sa = site_after.get(site, {}).get("mean_stability")
            if sb is not None and sa is not None:
                site_delta[site] = {
                    "before": sb,
                    "after": sa,
                    "delta": round(sa - sb, 4),
                    "n": site_after.get(site, {}).get("n"),
                }
        site_delta = dict(sorted(site_delta.items(), key=lambda kv: kv[1]["delta"]))

        n_common = len(common) or 1
        elapsed = self.days_elapsed or 1
        return {
            "schema": "bdoctor-health-diff/1",
            "before": {
                "generated_at": self.before["meta"]["generated_at"],
                "benchmark": self.before["meta"]["benchmark"],
                "n_tasks": self.before["meta"]["n_tasks"],
                "layers": self.before["meta"].get("layers"),
                "mean_stability": sum_before["mean_stability"],
            },
            "after": {
                "generated_at": self.after["meta"]["generated_at"],
                "benchmark": self.after["meta"]["benchmark"],
                "n_tasks": self.after["meta"]["n_tasks"],
                "layers": self.after["meta"].get("layers"),
                "mean_stability": sum_after["mean_stability"],
            },
            "comparability": self.comparability(),
            "headline": {
                "days_elapsed": self.days_elapsed,
                "mean_stability_delta": round(
                    sum_after["mean_stability"] - sum_before["mean_stability"], 4
                ),
                "n_degraded": len(degraded),
                "n_improved": len(improved),
                "n_unchanged": unchanged,
                "rate_degraded": round(len(degraded) / n_common, 4),
                "degradation_per_100_tasks_per_month": round(
                    100 * len(degraded) / n_common * 30.44 / elapsed, 3
                ),
                "n_new_D": sum(
                    1 for r in degraded if r["grade_after"] == "D" and r["grade_before"] != "D"
                ),
                "n_left_A": sum(
                    1 for r in degraded if r["grade_before"] == "A" and r["grade_after"] != "A"
                ),
                "n_appeared": len(appeared),
                "n_disappeared": len(disappeared),
            },
            "grade_migration": dict(sorted(grade_migration.items(), key=lambda kv: -kv[1])),
            "grades_before": sum_before["grades"],
            "grades_after": sum_after["grades"],
            "degraded": degraded[:limit],
            "improved": improved[:limit],
            "appeared": appeared[:limit],
            "disappeared": disappeared[:limit],
            "by_category_delta": dict(
                sorted(category_delta.items(), key=lambda kv: -kv[1]["delta"])
            ),
            "by_site_delta": site_delta,
            "cost": {
                "before": self.before.get("cost", {}).get("total_usd", 0.0),
                "after": self.after.get("cost", {}).get("total_usd", 0.0),
            },
            "reading": (
                "Une dégradation ne prouve pas que le site a changé : elle peut venir du "
                "canal, de l'ajout d'une couche ou d'une observation périmée. Le bloc "
                "« comparability » liste ce qui a bougé dans le protocole, à lire avant "
                "d'interpréter le moindre écart."
            ),
        }


def compare_cards(
    before: Mapping[str, Any] | str | Path,
    after: Mapping[str, Any] | str | Path,
    *,
    epsilon: float = 0.01,
) -> CardDiff:
    """Compare deux cartes de santé datées (dictionnaires ou chemins de fichiers JSON).

    ``epsilon`` par défaut (0,01) est le bruit de troncature du format JSON, pas un seuil
    de signification : un écart de 0,05 sur une tâche reste un écart réel.
    """
    a = _load_card_dict(before)
    b = _load_card_dict(after)
    if _dt.date.fromisoformat(a["meta"]["generated_at"]) > _dt.date.fromisoformat(
        b["meta"]["generated_at"]
    ):
        a, b = b, a  # ordre chronologique imposé : un diff à l'envers est illisible
    return CardDiff(before=a, after=b, epsilon=epsilon)


def _load_card_dict(source: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(source, (str, Path)):
        payload = json.loads(Path(source).read_text(encoding="utf-8"))
    else:
        payload = dict(source)
    if "meta" not in payload or "summary" not in payload:
        raise ValueError(
            "ce fichier n'est pas une carte de santé benchmark-doctor "
            "(clés 'meta' et 'summary' attendues)"
        )
    return payload


def render_diff_html(
    diff: CardDiff,
    *,
    template_dir: str | Path | None = None,
    limit: int = 30,
) -> str:
    """Rend le différentiel de santé en une page HTML autonome."""
    data = diff.to_dict(limit=limit)
    head = data["headline"]

    def _delta_cell(value: float, digits: int = 3) -> str:
        cls = "delta-neg" if value < 0 else ("delta-pos" if value > 0 else "delta-nil")
        return f'<td class="num {cls}">{value:+.{digits}f}</td>'

    kpis = "".join([
        _kpi(f'{head["mean_stability_delta"]:+.4f}', "Δ stabilité moyenne",
             f'{data["before"]["mean_stability"]:.3f} → {data["after"]["mean_stability"]:.3f}'),
        _kpi(str(head["n_degraded"]), "tâches dégradées",
             f'{_pct(head["rate_degraded"])} du corpus commun'),
        _kpi(str(head["n_left_A"]), "tâches ayant perdu la note A",
             f'{head["n_new_D"]} nouvelles tâches en D'),
        _kpi(str(head["days_elapsed"]), "jours écoulés",
             f'{head["degradation_per_100_tasks_per_month"]:.2f} dégradations / 100 tâches / mois'),
    ])

    sections = [_section(
        "Vue d'ensemble du différentiel",
        f'<div class="kpi-row">{kpis}</div>',
        "Le taux mensuel est une extrapolation linéaire de l'intervalle observé : il "
        "suppose une décadence uniforme dans le temps, ce que les jalons de WebVoyager "
        "démentent (les patch-sets arrivent par vagues). À lire comme un ordre de grandeur.",
    )]

    warnings = data["comparability"]["warnings"]
    if warnings:
        sections.append(_section(
            "Comparabilité des deux mesures",
            "<ul class='limits'>" + "".join(f"<li>{_esc(w)}</li>" for w in warnings) + "</ul>",
            "Ces écarts de protocole doivent être écartés avant d'attribuer la moindre "
            "dégradation au benchmark lui-même.",
        ))
    else:
        sections.append(_section(
            "Comparabilité des deux mesures",
            "<p>Même corpus (empreinte identique), mêmes couches, mêmes canaux, mêmes "
            "paramètres de score : les écarts ci-dessous sont imputables au benchmark et "
            "au monde, pas au protocole.</p>",
        ))

    if data["grade_migration"]:
        rows = [
            [f'<td class="id">{_esc(k)}</td>', f'<td class="num">{v}</td>']
            for k, v in data["grade_migration"].items()
        ]
        sections.append(_section(
            "Migrations de notes",
            _table([("Transition", False), ("Tâches", True)], rows),
        ))

    if data["degraded"]:
        rows = []
        for r in data["degraded"]:
            rows.append([
                f'<td class="id">{_esc(r["task_id"])}</td>',
                f"<td>{_grade_badge(r['grade_before'])} → {_grade_badge(r['grade_after'])}</td>",
                f'<td class="num">{r["score_before"]:.3f}</td>',
                f'<td class="num">{r["score_after"]:.3f}</td>',
                _delta_cell(r["delta"]),
                f'<td class="id">{_esc(r["top_category_after"] or "—")}</td>',
            ])
        sections.append(_section(
            f"Tâches dégradées ({head['n_degraded']}, les {len(rows)} pires affichées)",
            _table([("Tâche", False), ("Note", False), ("Avant", True), ("Après", True),
                    ("Δ", True), ("Cat.", False)], rows),
        ))

    if data["improved"]:
        rows = []
        for r in data["improved"]:
            rows.append([
                f'<td class="id">{_esc(r["task_id"])}</td>',
                f"<td>{_grade_badge(r['grade_before'])} → {_grade_badge(r['grade_after'])}</td>",
                f'<td class="num">{r["score_before"]:.3f}</td>',
                f'<td class="num">{r["score_after"]:.3f}</td>',
                _delta_cell(r["delta"]),
            ])
        sections.append(_section(
            f"Tâches améliorées ({head['n_improved']})",
            _table([("Tâche", False), ("Note", False), ("Avant", True), ("Après", True),
                    ("Δ", True)], rows),
            "Une tâche « améliorée » a le plus souvent été réparée par un patch, ou bien "
            "une observation réseau défavorable a été contredite par une nouvelle mesure. "
            "Le second cas est un signal sur le canal, pas sur la tâche.",
        ))

    site_rows = []
    for site, row in data["by_site_delta"].items():
        site_rows.append([
            f"<td>{_esc(site)}</td>",
            f'<td class="num">{row["n"]}</td>',
            f'<td class="num">{row["before"]:.3f}</td>',
            f'<td class="num">{row["after"]:.3f}</td>',
            _delta_cell(row["delta"]),
        ])
    if site_rows:
        sections.append(_section(
            "Dérive par site",
            _table([("Site", False), ("n", True), ("Avant", True), ("Après", True), ("Δ", True)],
                   site_rows),
        ))

    cat_rows = []
    for value, row in data["by_category_delta"].items():
        category = Category(value)
        cat_rows.append([
            f'<td class="id">{_esc(category.code)}</td>',
            f"<td>{_esc(_CATEGORY_LABELS.get(category, category.slug))}</td>",
            f'<td class="num">{row["before"]}</td>',
            f'<td class="num">{row["after"]}</td>',
            _delta_cell(row["delta"], 0),
        ])
    if cat_rows:
        sections.append(_section(
            "Dérive par catégorie de la taxonomie",
            _table([("Code", False), ("Mode de décadence", False), ("Avant", True),
                    ("Après", True), ("Δ", True)], cat_rows),
        ))

    provenance_pairs = [
        ("Mesure initiale", f'{data["before"]["generated_at"]} · '
                            f'{data["before"]["n_tasks"]} tâches · '
                            f'couches {"+".join(data["before"].get("layers") or [])}'),
        ("Mesure finale", f'{data["after"]["generated_at"]} · '
                          f'{data["after"]["n_tasks"]} tâches · '
                          f'couches {"+".join(data["after"].get("layers") or [])}'),
        ("Intervalle", f'{head["days_elapsed"]} jours'),
        ("Tâches apparues / disparues", f'{head["n_appeared"]} / {head["n_disappeared"]}'),
        ("Coût cumulé", f'{data["cost"]["before"]:.5f} $ + {data["cost"]["after"]:.5f} $'),
    ]

    dirpath = _templates_dir(template_dir)
    if dirpath:
        shell = (dirpath / "health_card.html").read_text(encoding="utf-8")
        css_path = dirpath / "health_card.css"
        css = css_path.read_text(encoding="utf-8") if css_path.exists() else _FALLBACK_CSS
    else:
        shell, css = _FALLBACK_SHELL, _FALLBACK_CSS

    limits_html = "".join(
        f"    <li>{_esc(x)}</li>\n"
        for x in [
            data["reading"],
            "Une tâche inchangée n'est pas une tâche vérifiée : elle est inchangée pour "
            "les détecteurs exécutés, qui ne voient pas tout (rappel nul de la couche "
            "statique sur la dérive de contenu).",
            "L'extrapolation mensuelle suppose une décadence uniforme ; les jalons réels "
            "montrent des vagues, pas un flux régulier.",
        ]
    )
    out = shell
    for marker, value in [
        ("{{title}}", f'Différentiel de santé — {data["after"]["benchmark"]} — '
                      f'{data["before"]["generated_at"]} → {data["after"]["generated_at"]}'),
        ("{{css}}", css),
        ("{{benchmark}}", _esc(f'Différentiel de santé — {data["after"]["benchmark"]}')),
        ("{{subtitle}}", _esc(
            f'{data["before"]["generated_at"]} → {data["after"]["generated_at"]} '
            f'({head["days_elapsed"]} jours) · {head["n_degraded"]} tâches dégradées, '
            f'{head["n_improved"]} améliorées'
        )),
        ("{{provenance}}", _provenance_html(provenance_pairs)),
        ("{{sections}}", "\n".join(sections)),
        ("{{terminology}}", _terminology_html()),
        ("{{limits}}", limits_html),
        ("{{footer}}", "Différentiel produit par benchmark-doctor — c'est cette vue, et "
                       "non la carte isolée, qui distingue une surveillance continue d'un "
                       "audit ponctuel."),
    ]:
        out = out.replace(marker, value)
    return out


def write_diff(
    diff: CardDiff,
    *,
    json_path: str | Path | None = None,
    html_path: str | Path | None = None,
    template_dir: str | Path | None = None,
    limit: int = 40,
) -> dict[str, str]:
    """Écrit le différentiel en JSON et/ou en HTML ; renvoie les chemins produits."""
    written: dict[str, str] = {}
    if json_path:
        target = Path(json_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(diff.to_dict(limit=limit), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        written["json"] = str(target)
    if html_path:
        target = Path(html_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            render_diff_html(diff, template_dir=template_dir, limit=limit), encoding="utf-8"
        )
        written["html"] = str(target)
    return written
