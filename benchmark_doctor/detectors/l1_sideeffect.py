"""L1 — effets de bord et accès restreint (T3).

Une tâche de benchmark web qui demande de se connecter, d'acheter, de réserver
effectivement ou d'écrire à quelqu'un pose un problème structurel : soit l'agent
d'évaluation n'a pas les moyens de l'exécuter (pas de compte, pas de moyen de paiement),
soit il ne *doit* pas l'exécuter (effet irréversible sur un site tiers réel). Dans les
deux cas la tâche n'est pas évaluable de bout en bout, et la ground truth le confirme :
Magnitude supprime « Cannot schedule actual, in-store pickup » (Apple--9), browser-use
maintient un fichier ``WebVoyagerImpossibleTasks.json`` de 55 identifiants.

Ce que le détecteur corrige par rapport à la version naïve du 15/08, mesuré sur les
643 tâches :

- **le verbe doit avoir son complément.** ``\\b(book|reserve|reservation)\\b`` touche
  13 tâches dont 9 patchées (précision 69 %) : il attrape « a fiction **book** », « a
  travel guide **book** », « online **booking** » ; en exigeant un complément réservable
  (``book a room``, ``reserve the table``) on tombe à 7 tâches dont 7 patchées ;
- **les verbes à particule ne sont pas des verbes de commerce.** ``check out`` sur ESPN
  signifie « consulte » (« Check out LeBron James' stats ») : le motif brut produisait
  5 faux positifs à lui seul, contre zéro pour ``checkout`` agglutiné ;
- **la négation compte.** « finish the quiz **without login** » ne demande pas de compte ;
  un motif nié ne déclenche rien.

Les motifs restants sont gradués : ``HIGH`` quand l'action est bloquante (identifiants,
paiement, écriture sur un site tiers, impression), ``MEDIUM`` quand elle est seulement
suspecte (message sortant, inscription à un flux). Le seuil de flag dur ne retient que
les premiers, ce qui laisse les seconds visibles dans le rapport sans polluer le taux
annoncé.
"""

from __future__ import annotations

import datetime as _dt
import re

from ..models import Category, Channel, Finding, Severity, Task

__all__ = ["detect_side_effects", "SIDE_EFFECT_PATTERNS", "BLOCKING_SIGNALS"]

DETECTOR_NAME = "l1_sideeffect"

#: Motifs d'effet de bord, avec sévérité et confiance. L'ordre n'a pas d'importance :
#: tous les motifs déclenchés sont émis, un rapport doit montrer tout ce qu'il a vu.
SIDE_EFFECT_PATTERNS: dict[str, tuple[re.Pattern[str], Severity, float, str]] = {
    # -- engageants : nécessitent un compte, un paiement ou modifient un état distant ----
    "auth_required": (
        re.compile(
            r"\b(log ?in|log ?into|sign ?in|sign ?up|signing in|create an? (?:new )?account|"
            r"register (?:for|an|a)|my account|your account|account settings|"
            r"enter your (?:email|password|credentials))\b",
            re.I,
        ),
        Severity.HIGH,
        0.85,
        "exige des identifiants que le harnais d'évaluation n'a pas",
    ),
    # Attention au « check out » phrastique : sur ESPN, « Check out LeBron James' stats »
    # veut dire « consulte », pas « passe à la caisse ». Seule la forme agglutinée ou
    # explicitement commerciale est retenue.
    "purchase_commit": (
        re.compile(
            r"\b(add (?:it )?to (?:the |your |my )?(?:cart|bag|basket)|\bcheckout\b|"
            r"proceed to check ?out|complete the check ?out|"
            r"place (?:an? )?order|buy (?:it )?now|complete the (?:purchase|payment)|"
            r"proceed to payment|enter (?:your )?(?:payment|card|credit card))\b",
            re.I,
        ),
        Severity.HIGH,
        0.85,
        "achat effectif : irréversible et impossible sans moyen de paiement",
    ),
    "state_mutation": (
        re.compile(
            r"\b(star the (?:repo|repository)|fork the (?:repo|repository)|"
            r"open an? (?:issue|pull request)|leave a (?:review|comment|rating)|"
            r"post a (?:comment|review|message)|upload (?:a|the|your)|"
            r"delete (?:the|your)|save (?:it )?to (?:your|my) (?:list|wishlist|library)|"
            r"add (?:it )?to (?:your|my) (?:wishlist|watchlist|favou?rites|library))\b",
            re.I,
        ),
        Severity.HIGH,
        0.75,
        "écriture sur un site tiers réel : effet de bord irréversible",
    ),
    "booking_commit": (
        re.compile(
            r"\b(?:book|re-?book|reserve)\s+(?:a|an|the|one|your|my|this|it|me|"
            r"room|rooms|hotel|hotels|flight|flights|table|ticket|tickets)\b"
            r"|\b(?:make a reservation|complete the booking|confirm the (?:booking|reservation))\b",
            re.I,
        ),
        Severity.HIGH,
        0.70,
        (
            "réservation effective : impossible sans compte ni paiement — la ground truth "
            "supprime ces tâches (« Cannot actually reserve a hotel »)"
        ),
    ),
    "local_action": (
        re.compile(r"\bprint (?:the|this|it|out)\b|\bsave (?:the|this) (?:page|map) as\b", re.I),
        Severity.HIGH,
        0.70,
        "action hors navigateur (impression, export local) : hors de portée d'un agent web",
    ),
    # -- intermédiaires : bloquants seulement si l'énoncé exige l'aboutissement ----------
    "contact_flow": (
        re.compile(
            r"\b(send (?:an? )?(?:email|e-mail|message)|contact (?:the |a |an |customer )?"
            r"(?:support|seller|service|us|host)|fill (?:in|out) the (?:contact )?form|"
            r"submit the form)\b",
            re.I,
        ),
        Severity.MEDIUM,
        0.60,
        "envoi de message sortant : effet de bord sur un tiers réel",
    ),
    "subscription": (
        re.compile(
            r"\b(subscribe(?: to)?|newsletter|sign up for (?:the |a )?(?:newsletter|alerts?|updates?))\b",
            re.I,
        ),
        Severity.MEDIUM,
        0.55,
        "inscription à un flux : nécessite une adresse réelle",
    ),
}

#: Sous-motifs considérés comme bloquants (sévérité HIGH) — utile aux tableaux du mémoire.
BLOCKING_SIGNALS = frozenset(
    {name for name, (_, sev, _, _) in SIDE_EFFECT_PATTERNS.items() if sev >= Severity.HIGH}
)


#: Une tâche peut mentionner un effet de bord pour l'**exclure** : « finish the quiz
#: without login », « browse as a guest ». Le motif nié ne doit alors rien déclencher.
_NEGATION_BEFORE = re.compile(r"\b(?:without|no need to|don'?t|do not|never)\s+(?:\w+\s+){0,2}$", re.I)
_NEGATION_AFTER = re.compile(r"^\s*(?:is )?not (?:required|needed)", re.I)


def _is_negated(text: str, start: int, end: int) -> bool:
    """Vrai si le motif détecté est explicitement écarté par l'énoncé."""
    return bool(_NEGATION_BEFORE.search(text[:start]) or _NEGATION_AFTER.match(text[end:]))


def _excerpt(text: str, start: int, end: int, width: int = 40) -> str:
    lo = max(0, start - width)
    hi = min(len(text), end + width)
    return f"{'…' if lo > 0 else ''}{text[lo:hi].strip()}{'…' if hi < len(text) else ''}"


def detect_side_effects(task: Task, *, today: _dt.date | None = None) -> list[Finding]:
    """Détecte les tâches exigeant une authentification ou produisant un effet de bord.

    Args:
        task: la tâche à analyser.
        today: date de l'observation (le détecteur lui-même est atemporel, mais tout
            constat est daté pour rester comparable d'une exécution à l'autre).
    """
    day = today or _dt.date.today()
    q = task.question
    findings: list[Finding] = []

    for signal, (pattern, severity, confidence, rationale) in SIDE_EFFECT_PATTERNS.items():
        m = pattern.search(q)
        if not m or _is_negated(q, m.start(), m.end()):
            continue
        findings.append(
            Finding(
                category=Category.ACCESS_DENIED,
                severity=severity,
                confidence=confidence,
                evidence=_excerpt(q, m.start(), m.end()),
                detector=DETECTOR_NAME,
                channel=Channel.STATIC,
                task_id=task.task_id,
                signal=signal,
                details={"match": m.group(0), "rationale": rationale, "blocking": severity >= Severity.HIGH},
                observed_at=day,
            )
        )
    return findings


detect_side_effects.name = DETECTOR_NAME  # type: ignore[attr-defined]
