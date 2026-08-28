"""L1 — dérive temporelle (T1) et non-reproductibilité temporelle (T7).

Principe discriminant : une date passée n'invalide qu'une tâche TRANSACTIONNELLE. On ne
prend pas un vol parti il y a deux ans, mais « combien d'articles ArXiv annoncés en
octobre 2023 mentionnent SimCSE ? » reste parfaitement exécutable en 2026. Distinguer ces
deux régimes fait passer la précision du détecteur de 66 % à 83 % contre la ground truth
Magnitude (cf. `bdoctor l1-eval`).

Trois familles de signaux sont émises :

- ``past_date_*``     : date absolue révolue à la date d'analyse → T1, sévérité fonction
  de l'intention (transactionnelle / archivistique / indéterminée) ;
- ``yearless_date*``  : jour + mois sans millésime (« from Dec 25th to Dec 26th »). La tâche
  s'auto-réactualise à chaque exécution, donc l'attendu de référence ne vaut plus rien ;
- ``relative_date``   : « latest », « today », « current ». La tâche reste exécutable
  indéfiniment mais sa réponse de référence est périmée par construction : c'est de la
  fragilité d'évaluation → T7, pas T1. Cette distinction évite de gonfler artificiellement
  le taux de decay (96 tâches concernées).

Toutes les observations portent le canal ``Channel.STATIC`` : aucune requête réseau n'est
faite ici, donc aucune conclusion sur l'accessibilité réelle du site ne peut en sortir.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from enum import Enum

from ..models import Category, Channel, Finding, Severity, Task

__all__ = [
    "DateMention",
    "TemporalIntent",
    "detect_temporal_decay",
    "extract_date_mentions",
    "classify_temporal_intent",
    "TRANSACTIONAL_SITES",
    "ARCHIVAL_SITES",
]

DETECTOR_NAME = "l1_temporal"

_MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_MONTH_RE = "(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_ORD = r"(?:st|nd|rd|th)?"
# Bornes d'année : WebVoyager date de 2024 ; au-delà de 2035 il s'agit presque toujours
# d'un nombre qui ressemble à une année (référence produit, quantité) et non d'une date.
_YEAR_RE = r"(?:19|20)\d{2}"

#: Motifs ordonnés du plus spécifique au plus général. Un empan déjà consommé par un
#: motif plus spécifique n'est pas réanalysé : « March 20, 2024 » ne doit pas produire
#: en plus une mention d'année nue « 2024 ».
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("iso", re.compile(rf"\b({_YEAR_RE})-(\d{{1,2}})-(\d{{1,2}})\b")),
    ("numeric", re.compile(rf"\b(\d{{1,2}})[/.](\d{{1,2}})[/.]({_YEAR_RE})\b")),
    ("month_day_year", re.compile(
        rf"\b({_MONTH_RE})\s+(\d{{1,2}}){_ORD}(?:\s*[-–]\s*\d{{1,2}}{_ORD})?,?\s+({_YEAR_RE})\b",
        re.I)),
    ("day_month_year", re.compile(
        rf"\b(\d{{1,2}}){_ORD}\s+(?:of\s+)?({_MONTH_RE}),?\s+({_YEAR_RE})\b", re.I)),
    ("month_year", re.compile(rf"\b({_MONTH_RE})\s+({_YEAR_RE})\b", re.I)),
    ("season", re.compile(rf"\b({_YEAR_RE})[-/](\d{{2}})\b")),
    ("month_day", re.compile(rf"\b({_MONTH_RE})\s+(\d{{1,2}}){_ORD}\b", re.I)),
    ("day_month", re.compile(rf"\b(\d{{1,2}}){_ORD}\s+(?:of\s+)?({_MONTH_RE})\b", re.I)),
    ("year", re.compile(rf"\b({_YEAR_RE})\b")),
]


@dataclass(frozen=True, slots=True)
class DateMention:
    """Une date repérée dans l'énoncé d'une tâche.

    ``kind`` vaut ``full`` (jour+mois+année), ``month_year``, ``year``, ``season``
    (« 2023-24 ») ou ``month_day`` (jour et mois sans millésime — le cas piégeux).
    """

    text: str
    kind: str
    year: int | None
    month: int | None
    day: int | None
    start: int
    end: int

    def is_past(self, today: _dt.date) -> bool:
        """Vrai si la date est certainement révolue à ``today``.

        Une mention sans millésime (``month_day``) est indécidable, donc jamais révolue.
        """
        if self.kind == "month_day" or self.year is None:
            return False
        if self.kind == "year":
            return self.year < today.year
        if self.kind == "season":
            # « 2023-24 season » : révolue dès que l'année de fin est passée.
            return (self.year + 1) < today.year
        if self.kind == "month_year" or self.month is None:
            return (self.year, self.month or 12) < (today.year, today.month)
        try:
            return _dt.date(self.year, self.month, self.day or 1) < today
        except ValueError:  # date invalide écrite dans l'énoncé (p. ex. 29 février)
            return (self.year, self.month) < (today.year, today.month)

    def is_future(self, today: _dt.date) -> bool:
        """Vrai si la date est encore à venir (utile pour annoncer une péremption)."""
        if self.kind == "month_day" or self.year is None:
            return False
        if self.kind == "year":
            return self.year > today.year
        if self.kind == "season":
            return self.year > today.year
        if self.kind == "month_year" or self.month is None:
            return (self.year, self.month or 1) > (today.year, today.month)
        try:
            return _dt.date(self.year, self.month, self.day or 28) > today
        except ValueError:
            return (self.year, self.month) > (today.year, today.month)

    def as_date(self) -> _dt.date | None:
        if self.year is None or self.month is None or self.day is None:
            return None
        try:
            return _dt.date(self.year, self.month, self.day)
        except ValueError:
            return None


def _month_number(token: str) -> int | None:
    return _MONTHS.get(token.strip(". ").lower())


def extract_date_mentions(text: str) -> list[DateMention]:
    """Extrait toutes les dates d'un énoncé, sans double comptage des empans.

    Écrit à la main plutôt qu'avec ``dateparser`` : les énoncés de benchmark contiennent
    des faux positifs qu'une bibliothèque généraliste résout de façon opaque
    (« 2 adults », « 4.5 stars », « 16-inch »).
    """
    mentions: list[DateMention] = []
    taken: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < e and s < end for s, e in taken)

    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            if overlaps(m.start(), m.end()):
                continue
            year = month = day = None
            mention_kind = "full"
            if kind == "iso":
                year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif kind == "numeric":
                a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
                # Ordre jour/mois ambigu (20/12 vs 12/20) : on tranche quand c'est possible,
                # sinon on retient la convention américaine du corpus d'origine.
                if a > 12:
                    day, month = a, b
                elif b > 12:
                    month, day = a, b
                else:
                    month, day = a, b
            elif kind == "month_day_year":
                month, day, year = _month_number(m.group(1)), int(m.group(2)), int(m.group(3))
            elif kind == "day_month_year":
                day, month, year = int(m.group(1)), _month_number(m.group(2)), int(m.group(3))
            elif kind == "month_year":
                month, year = _month_number(m.group(1)), int(m.group(2))
                mention_kind = "month_year"
            elif kind == "season":
                year = int(m.group(1))
                mention_kind = "season"
            elif kind == "month_day":
                month, day = _month_number(m.group(1)), int(m.group(2))
                mention_kind = "month_day"
            elif kind == "day_month":
                day, month = int(m.group(1)), _month_number(m.group(2))
                mention_kind = "month_day"
            elif kind == "year":
                year = int(m.group(1))
                mention_kind = "year"
            if mention_kind == "full" and month is None:
                continue
            mentions.append(
                DateMention(
                    text=m.group(0),
                    kind=mention_kind,
                    year=year,
                    month=month,
                    day=day,
                    start=m.start(),
                    end=m.end(),
                )
            )
            taken.append((m.start(), m.end()))

    mentions.sort(key=lambda d: d.start)
    return mentions


#: Formulations qui recalculent la date à chaque exécution. La tâche ne meurt pas ;
#: c'est sa réponse de référence qui devient invérifiable (T7).
RELATIVE_DATE_RE = re.compile(
    r"\b(today|tonight|tomorrow|yesterday|this (?:week|month|year|weekend)|"
    r"next (?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"last (?:week|month|year|night)|past (?:week|month|year|few days|two days)|"
    r"current(?:ly)?|latest|newest|most recent|recently|recent|upcoming|right now|as of now)\b",
    re.I,
)


class TemporalIntent(Enum):
    """Régime temporel d'une tâche datée.

    - ``TRANSACTIONAL`` : la tâche engage une action située dans le futur de la date citée
      (réserver, voler, retirer en magasin). Une date passée la rend inexécutable.
    - ``ARCHIVAL`` : la tâche interroge un fonds documentaire à une date donnée
      (articles publiés en 2023, saison 2023-24). Une date passée est *normale*.
    - ``UNKNOWN`` : ni l'un ni l'autre n'est établi — on reste prudent, sévérité moyenne.
    """

    TRANSACTIONAL = "transactional"
    ARCHIVAL = "archival"
    UNKNOWN = "unknown"


#: Sites dont la raison d'être est une transaction datée dans le futur.
TRANSACTIONAL_SITES = frozenset({"Booking", "Google Flights"})

#: Sites dont la raison d'être est un fonds consultable dans le passé.
ARCHIVAL_SITES = frozenset(
    {"ArXiv", "BBC News", "ESPN", "Cambridge Dictionary", "Wolfram Alpha", "Google Scholar"}
)

#: Marqueurs d'une action transactionnelle datée. Nommés pour pouvoir citer la preuve.
TRANSACTIONAL_MARKERS: dict[str, re.Pattern[str]] = {
    # « book » est un piège : c'est aussi bien le verbe réserver que le nom livre
    # (« a fiction book released in 2024 »). On exige donc un complément réservable,
    # faute de quoi le sous-corpus Amazon bascule à tort en transactionnel.
    "booking": re.compile(
        r"\b(?:book|booking|re-?book|reserve)\s+(?:a|an|the|one|your|my|this|it|me|"
        r"room|rooms|hotel|hotels|flight|flights|table|ticket|tickets)\b"
        r"|\b(?:make a reservation|reservations?|check[-\s]?in|check[-\s]?out date)\b", re.I),
    "stay": re.compile(
        r"\b(\d+[-\s]night|night(?:'s)?\s+stay|stay(?:ing)?\s+(?:from|for|between|starting|on)|"
        r"accommodations?|available for (?:a|the)\b)", re.I),
    "flight": re.compile(
        r"\b(flight|fly(?:ing)?|one[-\s]way|round[-\s]trip|depart(?:s|ing|ure)?|"
        r"leaves? on|leaving on|returns? on|returning on|layover|non[-\s]?stop)\b", re.I),
    "appointment": re.compile(
        r"\b(schedule (?:an?|the)|appointment|in[-\s]store pickup|pick[-\s]?up at|"
        r"rent(?:al)? (?:a|the|car)|delivery (?:on|by))\b", re.I),
    "availability": re.compile(
        r"\b(availabilit(?:y|ies)|vacanc(?:y|ies)|check[-\s]?availability)\b", re.I),
}

#: Marqueurs d'une interrogation archivistique. Une tâche qui les porte reste exécutable
#: malgré une date passée : c'est exactement ce que le détecteur v1 confondait.
ARCHIVAL_MARKERS: dict[str, re.Pattern[str]] = {
    "publication": re.compile(
        r"\b(publish(?:ed)?|announce[ds]?|originally announced|submitt?ed|posted|"
        r"appeared|released)\s+(?:in|on|between|during|before|after)\b", re.I),
    "corpus_query": re.compile(
        r"\b(how many (?:articles|papers|results|entries|submissions)|"
        r"(?:articles?|papers?|preprints?|submissions?)\s+(?:published|announced|submitted|from|in)|"
        r"search (?:for )?(?:articles?|papers?)|journal ref)\b", re.I),
    "season": re.compile(
        r"\b(\d{4}[-/]\d{2,4}\s+season|season of \d{4}|regular season|playoffs?|"
        r"standings|final scores?|box score)\b", re.I),
    "retrospective": re.compile(
        r"\b(who won|winner of|winners of|results? of|history of|archive[sd]?|"
        r"took place|was held|happened in)\b", re.I),
}


@dataclass(frozen=True, slots=True)
class IntentDecision:
    """Résultat de la classification, avec la preuve qui l'a emportée."""

    intent: "TemporalIntent"
    evidence: str
    rule: str


def classify_temporal_intent(task: Task) -> IntentDecision:
    """Classe une tâche datée en transactionnelle / archivistique / indéterminée.

    Ordre de décision, du plus fiable au plus faible :

    1. marqueur lexical explicite dans l'énoncé (un seul des deux camps présent) ;
    2. conflit lexical → le site tranche (Booking et Google Flights sont transactionnels
       par nature, même si l'énoncé contient « released ») ;
    3. aucun marqueur → prior du site ;
    4. sinon indéterminé.
    """
    q = task.question
    site = (task.site or "").strip()

    hits_t = [(name, m.group(0)) for name, pat in TRANSACTIONAL_MARKERS.items()
              if (m := pat.search(q))]
    hits_a = [(name, m.group(0)) for name, pat in ARCHIVAL_MARKERS.items()
              if (m := pat.search(q))]

    if hits_t and not hits_a:
        return IntentDecision(TemporalIntent.TRANSACTIONAL, hits_t[0][1], f"marker:{hits_t[0][0]}")
    if hits_a and not hits_t:
        return IntentDecision(TemporalIntent.ARCHIVAL, hits_a[0][1], f"marker:{hits_a[0][0]}")
    if hits_t and hits_a:
        if site in TRANSACTIONAL_SITES:
            return IntentDecision(
                TemporalIntent.TRANSACTIONAL, hits_t[0][1], f"conflict>site:{site}")
        if site in ARCHIVAL_SITES:
            return IntentDecision(TemporalIntent.ARCHIVAL, hits_a[0][1], f"conflict>site:{site}")
        return IntentDecision(TemporalIntent.TRANSACTIONAL, hits_t[0][1], "conflict>default")
    if site in TRANSACTIONAL_SITES:
        return IntentDecision(TemporalIntent.TRANSACTIONAL, site, f"site:{site}")
    if site in ARCHIVAL_SITES:
        return IntentDecision(TemporalIntent.ARCHIVAL, site, f"site:{site}")
    return IntentDecision(TemporalIntent.UNKNOWN, "", "default")


#: Sévérité et confiance par régime temporel, pour une date absolue révolue.
#: La confiance n'est pas la sévérité : on est très sûr qu'un vol de 2024 ne se réserve
#: plus (0,95) ; on l'est moins de ce qu'implique une année passée sur un site quelconque.
_PAST_POLICY: dict[str, tuple[Severity, float]] = {
    "transactional": (Severity.HIGH, 0.95),
    "unknown": (Severity.MEDIUM, 0.60),
    "archival": (Severity.LOW, 0.50),
}

#: Date sans millésime : la tâche se réactualise toute seule (« from Dec 25th to Dec 26th »
#: désigne le prochain 25 décembre), elle reste donc exécutable — mais sa réponse de
#: référence, elle, a été écrite pour l'hiver 2023-24. C'est de la fragilité d'évaluation
#: (T7), pas de la mort de tâche : la ground truth Magnitude ne patche d'ailleurs aucune
#: des 16 tâches concernées (Booking--0..9, Google Flights--2..9). Les classer en flag dur
#: coûtait 16 faux positifs, soit 9 points de précision.
_YEARLESS_POLICY: dict[str, tuple[Severity, float]] = {
    "transactional": (Severity.MEDIUM, 0.60),
    "unknown": (Severity.LOW, 0.40),
    "archival": (Severity.LOW, 0.35),
}


def _excerpt(text: str, start: int, end: int, width: int = 40) -> str:
    """Extrait la preuve avec son contexte immédiat."""
    lo = max(0, start - width)
    hi = min(len(text), end + width)
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(text) else ""
    return f"{prefix}{text[lo:hi].strip()}{suffix}"


def detect_temporal_decay(
    task: Task,
    *,
    today: _dt.date | None = None,
    emit_info: bool = False,
) -> list[Finding]:
    """Détecte la dérive temporelle d'une tâche à la date ``today``.

    Args:
        today: date de référence, à passer explicitement pour tout chiffre publié : le
            résultat de ce détecteur est une fonction du temps.
        emit_info: si vrai, émet aussi les dates futures encore valides (sévérité
            ``INFO``, poids nul) avec leur date de péremption.
    """
    day = today or _dt.date.today()
    q = task.question
    findings: list[Finding] = []

    mentions = extract_date_mentions(q)
    decision = classify_temporal_intent(task)
    intent = decision.intent.value

    past = [m for m in mentions if m.is_past(day)]
    yearless = [m for m in mentions if m.kind == "month_day"]
    future = [m for m in mentions if m.is_future(day)]

    if past:
        severity, confidence = _PAST_POLICY[intent]
        oldest = min(past, key=lambda m: (m.year or 9999, m.month or 1, m.day or 1))
        findings.append(
            Finding(
                category=Category.TEMPORAL,
                severity=severity,
                confidence=confidence,
                evidence=_excerpt(q, oldest.start, oldest.end),
                detector=DETECTOR_NAME,
                channel=Channel.STATIC,
                task_id=task.task_id,
                signal=f"past_date_{intent}",
                details={
                    "dates": [m.text for m in past],
                    "intent": intent,
                    "intent_rule": decision.rule,
                    "intent_evidence": decision.evidence,
                    "reference_date": day.isoformat(),
                    "years": sorted({m.year for m in past if m.year}),
                },
                observed_at=day,
            )
        )

    # La tâche reste exécutable mais interroge une autre période que celle pour laquelle
    # l'attendu a été écrit (WebVoyager : hiver 2023-24), d'où T7 et non T1.
    if yearless and not past:
        severity, confidence = _YEARLESS_POLICY[intent]
        findings.append(
            Finding(
                category=Category.EVAL_BRITTLENESS,
                severity=severity,
                confidence=confidence,
                evidence=_excerpt(q, yearless[0].start, yearless[0].end),
                detector=DETECTOR_NAME,
                channel=Channel.STATIC,
                task_id=task.task_id,
                signal=f"yearless_date_{intent}",
                details={
                    "dates": [m.text for m in yearless],
                    "intent": intent,
                    "intent_rule": decision.rule,
                    "reference_date": day.isoformat(),
                },
                observed_at=day,
            )
        )

    rel = RELATIVE_DATE_RE.search(q)
    if rel:
        findings.append(
            Finding(
                category=Category.EVAL_BRITTLENESS,
                severity=Severity.LOW,
                confidence=0.50,
                evidence=_excerpt(q, rel.start(), rel.end()),
                detector=DETECTOR_NAME,
                channel=Channel.STATIC,
                task_id=task.task_id,
                signal="relative_date",
                details={
                    "expression": rel.group(0).lower(),
                    "note": (
                        "énoncé auto-actualisé : exécutable indéfiniment, "
                        "mais la réponse de référence n'est plus vérifiable"
                    ),
                    "reference_date": day.isoformat(),
                },
                observed_at=day,
            )
        )

    if emit_info and future and not past:
        soonest = min(future, key=lambda m: (m.year or 9999, m.month or 12, m.day or 28))
        findings.append(
            Finding(
                category=Category.TEMPORAL,
                severity=Severity.INFO,
                confidence=0.60,
                evidence=_excerpt(q, soonest.start, soonest.end),
                detector=DETECTOR_NAME,
                channel=Channel.STATIC,
                task_id=task.task_id,
                signal="future_date_valid",
                details={
                    "dates": [m.text for m in future],
                    "intent": intent,
                    "expires_after": (soonest.as_date() or _dt.date(soonest.year or day.year, soonest.month or 12, 28)).isoformat(),
                    "reference_date": day.isoformat(),
                },
                observed_at=day,
            )
        )

    return findings


# Nom exposé pour le protocole `Detector` (les détecteurs sont des fonctions nommées).
detect_temporal_decay.name = DETECTOR_NAME  # type: ignore[attr-defined]
