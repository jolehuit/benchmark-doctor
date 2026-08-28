"""L1 — références nommées : proxy statique de la dérive de contenu (T2).

La dérive de contenu représente environ un quart des patches réels de la ground truth
(« GitHub Pro does not exist anymore », « This phone is no longer sold », « No 'New
Releases' section ») et le détecteur naïf du 15/08 en attrapait **0 %** : c'est
précisément ce trou qui justifie la couche L2 (sondes web).

Ce module ne prétend donc pas détecter la dérive de contenu — c'est impossible sans
interroger le site. Il repère les tâches **exposées** à cette dérive : celles qui citent
un objet nommé et versionné dont l'existence n'est pas garantie dans le temps (un modèle
d'iPhone, une puce M3, un palier d'abonnement, un intitulé de section). C'est un *proxy*,
et il faut l'annoncer comme tel : sa confiance est basse par construction, sa sévérité
plafonne à ``MEDIUM``, et il ne franchit jamais le seuil du flag dur.

Son usage prévu n'est pas le verdict mais **l'ordonnancement** : il indique à la couche
L2 quelles tâches méritent une sonde payante en priorité. Mesuré sur WebVoyager, l'ajout
de ce proxy au flag dur fait gagner du rappel et perdre de la précision (cf.
`bdoctor l1-eval`) — l'arbitrage est explicite plutôt que caché dans un seuil.
"""

from __future__ import annotations

import datetime as _dt
import re

from ..models import Category, Channel, Finding, Severity, Task

__all__ = ["detect_named_references", "REFERENCE_PATTERNS"]

DETECTOR_NAME = "l1_reference"

#: Motifs de références nommées, du plus périssable au plus stable.
REFERENCE_PATTERNS: dict[str, tuple[re.Pattern[str], Severity, float, str]] = {
    # Un produit versionné est remplacé par sa génération suivante : la tâche survit
    # syntaxiquement mais interroge un objet retiré du catalogue.
    "versioned_product": (
        re.compile(
            r"\b(iPhone\s?\d{1,2}(?:\s?(?:Pro|Plus|Mini|Max|Pro Max))?|"
            r"iPad(?:\s(?:Pro|Air|Mini))?(?:\s\d{1,2})?|"
            r"MacBook\s?(?:Air|Pro)|iMac|Mac\s?(?:Mini|Studio|Pro)|"
            r"Apple\s?Watch(?:\sSeries\s?\d{1,2}|\sUltra\s?\d?)?|"
            r"AirPods(?:\s(?:Pro|Max))?(?:\s\d)?|Vision\s?Pro|"
            r"M\d(?:\s?(?:Pro|Max|Ultra))?\s?chip|\bM\d\s(?:Pro|Max|Ultra)\b|"
            r"Galaxy\s?[SZ]\d{1,2}|Pixel\s?\d{1,2}|"
            r"RTX\s?\d{3,4}|GTX\s?\d{3,4}|PS[45]|PlayStation\s?\d|Xbox\s?Series\s?[SX]|"
            r"iOS\s?\d{1,2}|macOS\s?(?:\d{1,2}|Sonoma|Ventura|Sequoia|Tahoe)|"
            r"Windows\s?\d{1,2})\b",
            re.I,
        ),
        Severity.MEDIUM,
        0.55,
        "produit versionné : remplacé par sa génération suivante, souvent retiré du catalogue",
    ),
    # Les paliers commerciaux sont renommés ou fusionnés sans préavis — cas d'école de la
    # ground truth : « GitHub Pro does not exist anymore ».
    "plan_or_tier": (
        re.compile(
            r"\b(GitHub\s(?:Pro|Team|Enterprise|Free|Copilot)|Copilot\s(?:Pro|Business)|"
            r"Coursera\s(?:Plus|Plus subscription)|Amazon\sPrime|Prime\s(?:Video|Music)|"
            r"Apple\s(?:One|Care|TV\+|Music|Arcade)|iCloud\+?|"
            r"Booking\.com\sGenius|Genius\slevel|"
            r"(?:free|paid|premium|basic|pro|plus|enterprise)\s(?:tier|plan|subscription))\b",
            re.I,
        ),
        Severity.MEDIUM,
        0.55,
        "palier d'abonnement : renommé, fusionné ou supprimé sans redirection",
    ),
    # Un intitulé de rubrique cité entre guillemets est une dépendance directe à l'UI :
    # « There no longer seems to be an explicit 'World News' section ».
    "named_ui_section": (
        re.compile(
            r"(?:the\s)?['\"“]([A-Z][\w &'\-]{2,30})['\"”]\s(?:section|tab|page|category|filter|menu)"
            r"|\b(?:section|tab|page|category|filter|menu)\s(?:called|named|titled)\s['\"“]?([A-Z][\w &'\-]{2,30})",
            re.I,
        ),
        Severity.MEDIUM,
        0.50,
        "intitulé de rubrique : dépend de la navigation du site, renommée fréquemment",
    ),
    # Contenu nommé (titre d'article, de modèle, de dépôt, de cours). Très fréquent dans
    # WebVoyager (termes de recherche entre guillemets) → confiance délibérément basse.
    "named_content": (
        re.compile(r"['\"“]([A-Za-z][\w\s\-\.:/+]{3,60})['\"”]"),
        Severity.LOW,
        0.30,
        "contenu nommé : peut avoir été renommé, dépublié ou déplacé",
    ),
}


def _excerpt(text: str, start: int, end: int, width: int = 35) -> str:
    lo = max(0, start - width)
    hi = min(len(text), end + width)
    return f"{'…' if lo > 0 else ''}{text[lo:hi].strip()}{'…' if hi < len(text) else ''}"


def detect_named_references(
    task: Task,
    *,
    today: _dt.date | None = None,
    include_named_content: bool = True,
) -> list[Finding]:
    """Repère les références nommées susceptibles d'avoir disparu du site.

    Args:
        task: la tâche à analyser.
        today: date de l'observation.
        include_named_content: inclut le motif générique « chaîne entre guillemets ».
            Il est très bruyant (termes de recherche ArXiv) ; le désactiver donne un
            proxy plus resserré, ce que l'ablation permet de mesurer.

    Returns:
        Des constats T2 de faible confiance, à comprendre comme une file de priorité
        pour la couche L2 et non comme un verdict.
    """
    day = today or _dt.date.today()
    q = task.question
    findings: list[Finding] = []

    for signal, (pattern, severity, confidence, rationale) in REFERENCE_PATTERNS.items():
        if signal == "named_content" and not include_named_content:
            continue
        m = pattern.search(q)
        if not m:
            continue
        matched = next((g for g in m.groups() if g), m.group(0))
        findings.append(
            Finding(
                category=Category.CONTENT_DRIFT,
                severity=severity,
                confidence=confidence,
                evidence=_excerpt(q, m.start(), m.end()),
                detector=DETECTOR_NAME,
                channel=Channel.STATIC,
                task_id=task.task_id,
                signal=signal,
                details={
                    "reference": matched.strip(),
                    "rationale": rationale,
                    "proxy": True,
                    "verify_with": "l2_content",
                },
                observed_at=day,
            )
        )
    return findings


detect_named_references.name = DETECTOR_NAME  # type: ignore[attr-defined]
