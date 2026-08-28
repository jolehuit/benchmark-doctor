"""Les 8 catégories de decay (C1 du mémoire) et le classement des raisons de Magnitude.

Ce module porte trois choses :

1. **Les définitions** des catégories T1..T8, avec la *règle d'arbitrage* effectivement
   appliquée pour trancher les cas frontaliers — sans elle, la prévalence par catégorie
   n'est pas reproductible.
2. **Le classifieur par mots-clés** (`classify_reason_keywords`), repris à l'identique du
   script exploratoire du 15/08 : il sert de référence basse pour mesurer ce qu'apporte la
   relecture manuelle.
3. **Les étiquettes manuelles** des 121 raisons de Magnitude
   (`magnitude_reason_labels.json`), relues une à une.

Les codes (``"T1_temporal"``…) sont ceux de `benchmark_doctor.models.Category` ; le module
ne l'importe pas pour rester exécutable indépendamment du reste du paquet, mais
`to_models_category` fait le pont quand le paquet est complet.
"""

from __future__ import annotations

import collections
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "CategoryDef",
    "CATEGORIES",
    "ARBITRATION_RULE",
    "classify_reason_keywords",
    "KEYWORD_TO_TAXONOMY",
    "load_manual_labels",
    "prevalence",
    "to_models_category",
]

LABELS_PATH = Path(__file__).with_name("magnitude_reason_labels.json")


@dataclass(frozen=True)
class CategoryDef:
    """Définition d'une catégorie de la taxonomie."""

    code: str
    slug: str
    label: str
    definition: str
    exemple: str


CATEGORIES: tuple[CategoryDef, ...] = (
    CategoryDef(
        "T1", "temporal", "Dérive temporelle",
        "Une date, une saison ou un millésime codé en dur dans l'énoncé appartient désormais au "
        "passé. Sous-type transactionnel (réserver, prendre un vol) : la tâche devient "
        "inexécutable. Sous-type archivistique (consulter un classement 2023) : elle reste "
        "exécutable mais ne mesure plus ce qu'elle prétendait mesurer.",
        "« The booking date '20/12/2023' is explicitly in the past. »",
    ),
    CategoryDef(
        "T2", "content_drift", "Dérive de contenu ou d'URL",
        "L'entité nommée par la tâche — produit, article, page, modèle, rubrique — n'existe "
        "plus, a changé d'adresse, ou n'est plus satisfaite par le catalogue du site.",
        "« GitHub Pro does not exist anymore - only teams »",
    ),
    CategoryDef(
        "T3", "access_denied", "Accès et effets de bord",
        "La tâche suppose une action que l'évaluation ne peut pas produire : authentification, "
        "paiement, réservation réelle, ou franchissement d'une protection anti-robot.",
        "« Cannot actually reserve a hotel »",
    ),
    CategoryDef(
        "T4", "ui_instability", "Instabilité d'environnement ou d'interface",
        "L'entité visée existe toujours mais l'interaction supposée par la tâche — filtre, tri, "
        "contrôle, widget — a disparu ou changé de contrat.",
        "« There's no 'Credit Eligible' filter »",
    ),
    CategoryDef(
        "T5", "ambiguity", "Ambiguïté de la tâche",
        "L'énoncé n'admet pas de réponse déterminée : critère subjectif, référent multiple, "
        "consigne non définie.",
        "« It's very ambiguous what 'updates' means here »",
    ),
    CategoryDef(
        "T6", "multiple_solutions", "Solutions valides multiples",
        "Plusieurs réponses différentes satisfont l'énoncé, sans que la référence n'en retienne "
        "qu'une explicitement.",
        "— (aucune occurrence en catégorie principale chez Magnitude)",
    ),
    CategoryDef(
        "T7", "eval_brittleness", "Fragilité de l'évaluation",
        "La règle de notation ou le juge, et non la tâche, produit un verdict instable.",
        "— (aucune occurrence en catégorie principale chez Magnitude)",
    ),
    CategoryDef(
        "T8", "timing", "Dépendance de timing",
        "La validité dépend d'une fenêtre glissante (« dans les deux derniers jours ») ou d'un "
        "calendrier (saison sportive) : la tâche est vraie par intermittence.",
        "« It is not the NBA season, there is no Bucks game in the last 2 days »",
    ),
)

#: Règle d'arbitrage appliquée aux cas frontaliers, à citer dans le mémoire.
ARBITRATION_RULE = (
    "T2 quand l'ENTITÉ nommée par la tâche a disparu ou changé ; T4 quand l'entité existe "
    "encore mais que l'INTERACTION supposée (filtre, contrôle, widget) n'est plus disponible ; "
    "T8 quand le défaut est intermittent par construction (fenêtre glissante, saison) plutôt "
    "que définitif. Les cas où deux catégories se défendent portent `limite: true` et une "
    "catégorie secondaire."
)

_CODE_TO_DEF = {c.code: c for c in CATEGORIES}


# Référence basse : le classement par mots-clés

_KEYWORD_RULES: tuple[tuple[str, str], ...] = (
    ("temporal", r"date|dates|20[12]\d|outdated|current|superseded|no longer (current|the latest)|expired"),
    ("content_drift", r"no longer exist|removed|discontinued|does not exist|dne|unavailable|not available|gone|deleted|defunct"),
    ("impossible", r"impossible|cannot|can't|requires (login|account|sign)|login|payment|book|purchase"),
    ("ambiguity", r"ambiguous|unclear|vague|multiple|subjective|wtf"),
)

#: Correspondance des classes du classifieur par mots-clés vers la taxonomie.
KEYWORD_TO_TAXONOMY: dict[str, str | None] = {
    "temporal": "T1",
    "content_drift": "T2",
    "impossible": "T3",
    "ambiguity": "T5",
    "other": None,
}


def classify_reason_keywords(reason: str) -> str:
    """Classe une raison libre par mots-clés (référence basse, script du 15/08/2026).

    Les règles sont appliquées dans l'ordre et la première qui accroche l'emporte, ce qui
    explique une partie de ses erreurs : « Cannot actually reserve a hotel » ne contient
    aucune date mais « It is not the NBA season, there is no Bucks game in the last 2 days »
    accroche `current`… et pas toujours au bon endroit.

    Returns:
        ``"temporal"``, ``"content_drift"``, ``"impossible"``, ``"ambiguity"`` ou ``"other"``.
    """
    text = reason.lower()
    for name, pattern in _KEYWORD_RULES:
        if re.search(pattern, text):
            return name
    return "other"


# Étiquettes manuelles


def load_manual_labels(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Charge les étiquettes manuelles des 121 raisons de Magnitude.

    Chaque entrée porte : ``action``, ``raison_publiee``, ``categorie`` (T1..T8),
    ``categorie_secondaire`` (ou ``null``), ``limite`` (booléen : cas frontalier) et
    ``commentaire`` (justification de l'arbitrage).
    """
    return json.loads((path or LABELS_PATH).read_text(encoding="utf-8"))


def prevalence(labels: dict[str, dict[str, Any]], *, secondary: bool = False) -> dict[str, int]:
    """Effectif par catégorie, dans l'ordre T1..T8 (catégories vides comprises).

    Args:
        labels: sortie de `load_manual_labels`.
        secondary: si vrai, compte aussi les catégories secondaires (une tâche peut alors
            être comptée deux fois — utile pour montrer la co-occurrence, pas pour une part).
    """
    counts = collections.Counter()
    for entry in labels.values():
        counts[entry["categorie"]] += 1
        if secondary and entry.get("categorie_secondaire"):
            counts[entry["categorie_secondaire"]] += 1
    return {c.code: counts.get(c.code, 0) for c in CATEGORIES}


def to_models_category(code: str):  # pragma: no cover - dépend du reste du paquet
    """Convertit ``"T1"`` en `benchmark_doctor.models.Category`, si le paquet est complet.

    Returns:
        Le membre d'énumération, ou la chaîne ``"T1_temporal"`` si `models` n'est pas
        importable (le paquet est en cours de construction par ailleurs).
    """
    value = f"{code}_{_CODE_TO_DEF[code].slug}"
    try:
        from benchmark_doctor.models import Category  # import tardif volontaire

        return Category(value)
    except Exception:
        return value
