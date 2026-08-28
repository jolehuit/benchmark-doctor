"""L2 — existence des contenus cités par les tâches (T2, dérive de contenu).

La dérive de contenu pèse environ un quart des patches de la ground truth
(« GitHub Pro does not exist anymore », « This phone is no longer sold ») et la couche
statique n'en attrape rien : au seuil HIGH, L1 seul recense **0 des 21 tâches étiquetées
T2**. La raison est structurelle, aucune analyse de l'énoncé ne peut savoir si un modèle
Hugging Face a été dépublié. Il faut le demander au site.

Le principe retenu : **ne mécaniser que ce qui est vérifiable sans ambiguïté**. Une tâche
qui dit « trouve un modèle populaire de traduction » ne cite aucun objet dont l'existence
soit décidable ; une tâche qui dit « ouvre ``argilla/notux-chat-ui`` » en cite un, et une
API publique répond par oui ou par non. Le module extrait donc des **identifiants
résolvables** et interroge la source d'autorité correspondante :

===================  ==========================================================
Résolveur            Source d'autorité
===================  ==========================================================
``arxiv_id``         ``https://arxiv.org/abs/<id>``
``arxiv_category``   ``https://arxiv.org/list/<cat>/recent``
``huggingface_repo`` ``https://huggingface.co/api/{models,datasets,spaces}/<id>``
``huggingface_name`` ``https://huggingface.co/api/models?search=<nom>``
``github_repo``      ``https://api.github.com/repos/<owner>/<repo>``
``cambridge_word``   ``https://dictionary.cambridge.org/dictionary/english/<mot>``
===================  ==========================================================

Trois précautions qui font la différence entre une mesure et une illusion de mesure :

1. **La couverture est faible et doit être publiée comme telle.** Sur les 643 tâches de
   WebVoyager, très peu citent un identifiant brut ; l'essentiel des énoncés ArXiv,
   GitHub et Hugging Face décrit une *recherche* (« le dépôt le plus étoilé »), pas un
   objet. Le rappel de ce détecteur est donc plafonné par le corpus, pas par le code.
2. **Un identifiant non résolu n'est pas un identifiant absent.** Quand le canal renvoie
   un blocage (proxy d'egress, 403, challenge), ``exists`` vaut ``None`` et aucun constat
   de decay n'est émis. C'est la même règle qu'en `l2_liveness` : ne jamais imputer au
   site ce qui vient du canal.
3. **Les résolveurs sont testables à vide.** `CONTROL_IDENTIFIERS` fournit des
   identifiants connus pour exister et d'autres fabriqués pour ne pas exister : un
   résolveur qui répond « existe » aux deux ne mesure rien, et la campagne le montre.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import quote, unquote

from ..channels import BaseChannel, Observation
from ..models import Category, Channel, Finding, Severity, Task
from .l2_liveness import Signature, classify

__all__ = [
    "Identifier",
    "ContentCheck",
    "extract_identifiers",
    "check_identifier",
    "check_task",
    "detect_content_existence",
    "RESOLVERS",
    "CONTROL_IDENTIFIERS",
]

DETECTOR_NAME = "l2_content"

# Extraction des identifiants

#: Identifiant arXiv moderne (``2401.13919``), avec version facultative.
_ARXIV_ID = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b")

#: Catégorie arXiv (``cs.CL``, ``astro-ph.GA``) ou archive sans sous-classe (``quant-ph``).
_ARXIV_CATEGORY = re.compile(
    r"\b((?:cs|math|astro-ph|cond-mat|gr-qc|hep-ex|hep-lat|hep-ph|hep-th|math-ph|"
    r"nlin|nucl-ex|nucl-th|physics|quant-ph|stat|eess|econ|q-bio|q-fin)"
    r"(?:\.[A-Za-z]{2,3})?)\b"
)

#: Chemin ``propriétaire/nom`` d'un dépôt GitHub ou Hugging Face.
_SLUG = re.compile(r"\b([A-Za-z0-9][\w.\-]{1,38})/([A-Za-z0-9][\w.\-]{1,60})\b")

#: Mots outils et noms de langues : un énoncé de dictionnaire dit « traduis le mot X
#: *into* French », et une extraction naïve prend « into » pour l'entrée à vérifier.
#: Les exclure fait passer la précision d'extraction de 23/25 à 23/23 sur le corpus.
_WORD_STOPWORDS = frozenset(
    {
        "from", "into", "in", "on", "to", "for", "with", "the", "this", "that", "its",
        "english", "french", "chinese", "spanish", "german", "italian", "japanese",
        "korean", "russian", "portuguese", "arabic", "dutch", "polish", "turkish",
        "british", "american", "uk", "us", "word", "words", "term", "entry", "meaning",
        "definition", "pronunciation", "example", "sentence", "translation",
    }
)

#: Faux positifs classiques du motif ``a/b`` dans une phrase anglaise.
_SLUG_STOPWORDS = frozenset(
    {
        "and", "or", "and/or", "n", "a", "the", "his", "her", "km", "mi", "kg", "lb",
        "am", "pm", "yes", "no", "in", "out", "on", "off", "http", "https", "www",
        "24", "7", "24/7", "input", "output", "read", "write", "male", "female",
    }
)

#: Le mot recherché dans une tâche de dictionnaire, cité entre guillemets ou introduit
#: par « the word ». La double capture couvre les deux tournures du corpus.
_QUOTED_WORD = re.compile(
    r"(?:word|term|entry)\s+['\"“]([A-Za-z][A-Za-z\-']{2,30})['\"”.]"
    r"|['\"“]([A-Za-z][A-Za-z\-']{2,30})['\"”.]?\s*(?:on|in)\s+the\s+Cambridge"
    r"|(?:word|term)\s+([A-Za-z][A-Za-z\-']{2,30})\b"
)

#: Identifiants de licence SPDX : ils ont exactement la forme d'un nom de modèle
#: (``cc-by-sa-4.0``, ``apache-2.0``) et les énoncés Hugging Face en citent souvent.
#: Les extraire produirait des vérifications d'existence sur des objets qui ne sont pas
#: des modèles — un faux positif garanti.
_LICENSE_LIKE = re.compile(
    r"^(?:cc[\-0]|apache[\-\s]?2|mit|bsd|gpl|lgpl|agpl|afl|artistic|bigscience|"
    r"creativeml|openrail|llama\d?|gemma|wtfpl|unlicense|osl|epl|mpl|isc|zlib)",
    re.I,
)

#: Nom de modèle Hugging Face cité sans propriétaire (``all-MiniLM-L6-v2``, ``bert-base``).
#: Exige un tiret et un chiffre ou un mot technique, pour éviter d'attraper de la prose.
_HF_BARE_NAME = re.compile(
    r"\b((?:[A-Za-z]+[\-_])+(?:[A-Za-z]*\d[\w.\-]*|base|large|small|uncased|cased)"
    r"[\w.\-]*)\b"
)


@dataclass(frozen=True, slots=True)
class Identifier:
    """Un objet nommé dans une tâche, dont l'existence est décidable par une API.

    Args:
        kind: nom du résolveur compétent (clé de `RESOLVERS`).
        value: l'identifiant normalisé, tel qu'il sera envoyé à l'API.
        evidence: l'extrait de l'énoncé d'où il vient — sans quoi le constat n'est pas
            auditable et l'on ne peut pas juger d'une extraction abusive.
    """

    kind: str
    value: str
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "value": self.value, "evidence": self.evidence}


def _excerpt(text: str, start: int, end: int, width: int = 40) -> str:
    lo, hi = max(0, start - width), min(len(text), end + width)
    return f"{'…' if lo else ''}{text[lo:hi].strip()}{'…' if hi < len(text) else ''}"


def extract_identifiers(task: Task) -> list[Identifier]:
    """Extrait les identifiants vérifiables d'une tâche.

    L'extraction est **conditionnée au site** de la tâche : le motif ``a/b`` ne devient un
    dépôt que dans une tâche GitHub ou Hugging Face, et un mot entre guillemets ne devient
    une entrée de dictionnaire que dans une tâche Cambridge. Sans ce conditionnement, le
    détecteur produirait surtout du bruit — et un détecteur bruyant sur une catégorie où
    le statique fait déjà 0 % de rappel ne serait pas un progrès.
    """
    site = (task.site or "").lower()
    q = task.question
    out: list[Identifier] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: str, evidence: str) -> None:
        key = (kind, value.lower())
        if key not in seen:
            seen.add(key)
            out.append(Identifier(kind=kind, value=value, evidence=evidence))

    if "arxiv" in site:
        for m in _ARXIV_ID.finditer(q):
            add("arxiv_id", m.group(1), _excerpt(q, m.start(), m.end()))
        for m in _ARXIV_CATEGORY.finditer(q):
            # Une archive sans sous-classe n'est un identifiant que si elle est écrite
            # sous sa forme technique ; « physics » en toutes lettres ne l'est pas.
            value = m.group(1)
            if "." in value or "-" in value:
                add("arxiv_category", value, _excerpt(q, m.start(), m.end()))

    if "huggingface" in site or "hugging face" in site:
        for m in _SLUG.finditer(q):
            owner, name = m.group(1), m.group(2)
            if owner.lower() in _SLUG_STOPWORDS or name.lower() in _SLUG_STOPWORDS:
                continue
            add("huggingface_repo", f"{owner}/{name}", _excerpt(q, m.start(), m.end()))
        for m in _HF_BARE_NAME.finditer(q):
            name = m.group(1)
            if "/" in name or name.lower() in _SLUG_STOPWORDS or len(name) < 6:
                continue
            if _LICENSE_LIKE.match(name):
                continue
            if any(name in i.value for i in out):
                continue
            add("huggingface_name", name, _excerpt(q, m.start(), m.end()))

    if "github" in site:
        for m in _SLUG.finditer(q):
            owner, name = m.group(1), m.group(2)
            if owner.lower() in _SLUG_STOPWORDS or name.lower() in _SLUG_STOPWORDS:
                continue
            add("github_repo", f"{owner}/{name}", _excerpt(q, m.start(), m.end()))

    if "cambridge" in site or "dictionary" in site:
        for m in _QUOTED_WORD.finditer(q):
            word = next((g for g in m.groups() if g), None)
            if not word:
                continue
            word = word.strip(".'\" ")
            if word.lower() in _WORD_STOPWORDS or word.lower() in _SLUG_STOPWORDS:
                continue
            add("cambridge_word", word, _excerpt(q, m.start(), m.end()))

    return out


# Résolveurs


@dataclass(frozen=True, slots=True)
class ContentCheck:
    """Résultat de la vérification d'un identifiant.

    Args:
        exists: ``True`` (présent), ``False`` (absent, constat de decay), ``None``
            (indécidable depuis ce canal — le cas le plus important à ne pas confondre
            avec ``False``).
        signature: signature d'accès de la réponse (réutilise le classifieur L2), qui
            explique *pourquoi* le résultat est indécidable le cas échéant.
    """

    task_id: str | None
    identifier: Identifier
    url: str
    exists: bool | None
    signature: Signature
    status: int | None
    channel: Channel
    channel_name: str
    evidence: str
    rationale: str
    observed_at: _dt.datetime
    title: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def decided(self) -> bool:
        return self.exists is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "identifier": self.identifier.to_dict(),
            "url": self.url,
            "exists": self.exists,
            "signature": self.signature.value,
            "status": self.status,
            "channel": self.channel.value,
            "channel_name": self.channel_name,
            "evidence": self.evidence[:300],
            "rationale": self.rationale,
            "title": self.title,
            "observed_at": self.observed_at.isoformat(),
            "extra": dict(self.extra),
        }


#: URL d'interrogation par type d'identifiant. Une fonction plutôt qu'un gabarit : les
#: identifiants doivent être encodés, et Hugging Face distingue modèles, jeux de données
#: et espaces sur des chemins différents.
def _arxiv_id_url(value: str) -> str:
    return f"https://arxiv.org/abs/{quote(value)}"


def _arxiv_category_url(value: str) -> str:
    return f"https://arxiv.org/list/{quote(value)}/recent"


def _hf_repo_urls(value: str) -> list[str]:
    v = quote(value, safe="/")
    return [
        f"https://huggingface.co/api/models/{v}",
        f"https://huggingface.co/api/datasets/{v}",
        f"https://huggingface.co/api/spaces/{v}",
    ]


def _hf_search_url(value: str) -> str:
    return f"https://huggingface.co/api/models?search={quote(value)}&limit=1"


def _github_repo_url(value: str) -> str:
    return f"https://api.github.com/repos/{quote(value, safe='/')}"


def _cambridge_url(value: str) -> str:
    return f"https://dictionary.cambridge.org/dictionary/english/{quote(value.lower())}"


#: Titre HTML, pour citer ce que le site a répondu plutôt que de le résumer.
_TITLE = re.compile(r"<title[^>]*>(.{0,200}?)</title>", re.I | re.S)

#: Identifiant renvoyé par une API JSON, lisible même sur un extrait tronqué.
_JSON_ID = re.compile(r'"(?:id|modelId|full_name)"\s*:\s*"([^"]{1,120})"')

#: Terme de recherche d'une URL d'API, pour vérifier que le résultat le contient bien.
_SEARCH_PARAM = re.compile(r"[?&]search=([^&]+)")


def _search_term(url: str) -> str | None:
    m = _SEARCH_PARAM.search(url)
    return unquote(m.group(1)) if m else None


def _interpret_html(obs: Observation, sig: Signature) -> tuple[bool | None, str, str | None]:
    """Interprète une réponse HTML : existe / n'existe pas / indécidable."""
    title_match = _TITLE.search(obs.excerpt or "")
    title = " ".join(title_match.group(1).split()) if title_match else None
    if sig is Signature.DEAD_404:
        return False, f"le site répond {obs.status} : la ressource n'existe pas", title
    if sig is Signature.SOFT_404:
        return False, "réponse 200 annonçant une page introuvable (soft-404)", title
    if sig is Signature.REDIRECT_HOME:
        # Le site a renvoyé 200, mais sur une page plus haute que celle demandée : c'est
        # sa façon de dire « inconnu ». Cas mesuré sur Cambridge Dictionary.
        return (
            False,
            f"URL absorbée par {obs.final_path} : le contenu demandé n'existe pas",
            title,
        )
    if sig is Signature.OK:
        return True, f"le site répond {obs.status} avec une page de contenu", title
    return None, f"indécidable depuis ce canal (signature : {sig.value})", title


def _interpret_json(obs: Observation, sig: Signature) -> tuple[bool | None, str, str | None]:
    """Interprète une réponse d'API JSON."""
    if sig is Signature.CHANNEL_BLOCKED:
        return None, "réponse produite par l'infrastructure de mesure, pas par l'API", None
    if obs.status == 404:
        return False, f"l'API répond {obs.status} : identifiant inconnu", None
    if obs.status == 401:
        # Nuance à ne pas écraser : Hugging Face renvoie 401 aussi bien pour un dépôt
        # supprimé que pour un dépôt privé ou restreint, précisément pour ne pas
        # divulguer lesquels existent. Du point de vue de la tâche de benchmark, les
        # trois cas sont équivalents — l'agent anonyme ne peut pas l'ouvrir — mais le
        # constat doit dire lequel des trois n'est pas décidable.
        return (
            False,
            f"l'API répond {obs.status} : ressource non publiquement accessible "
            "(supprimée, privée ou restreinte — l'API publique ne les distingue pas)",
            None,
        )
    if obs.ok:
        body = (obs.excerpt or "").strip()
        if body in ("[]", "[ ]"):
            return False, "recherche API sans résultat", None
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            # L'extrait est tronqué : le JSON n'est pas parsable en entier, mais
            # l'identifiant renvoyé par l'API se lit au début de l'objet. Extraire le
            # nom vaut mieux que perdre la preuve.
            name = _JSON_ID.search(body)
            label = name.group(1) if name else None
            return True, f"l'API répond {obs.status}" + (f" pour {label!r}" if label else ""), label
        if isinstance(payload, list):
            if not payload:
                return False, "recherche API sans résultat", None
            label = payload[0].get("id") or payload[0].get("modelId")
            # Une recherche floue renvoie *toujours* quelque chose : mesuré le 15/08,
            # « cc-by-sa-4.0 » ramène « asddf45334g/cc-by-nc-sa-4.0 », qui n'est pas le
            # même objet. Sans exiger que le résultat contienne réellement le terme
            # cherché, ce résolveur répondrait « existe » à n'importe quoi.
            asked = _search_term(obs.url)
            if asked and label and asked.lower() not in str(label).lower():
                return (
                    None,
                    f"recherche API : le premier résultat {label!r} ne contient pas le "
                    f"terme cherché {asked!r} — correspondance non probante",
                    label,
                )
            return True, f"recherche API : premier résultat {label!r}", label
        label = payload.get("id") or payload.get("full_name") or payload.get("modelId")
        return True, f"l'API répond {obs.status} pour {label!r}", label
    return None, f"indécidable (signature : {sig.value}, statut {obs.status})", None


@dataclass(frozen=True, slots=True)
class _Resolver:
    """Un résolveur : des URL à essayer et une façon de lire la réponse."""

    urls: Callable[[str], list[str]]
    interpret: Callable[[Observation, Signature], tuple[bool | None, str, str | None]]
    authority: str


RESOLVERS: dict[str, _Resolver] = {
    "arxiv_id": _Resolver(lambda v: [_arxiv_id_url(v)], _interpret_html, "arxiv.org/abs"),
    "arxiv_category": _Resolver(
        lambda v: [_arxiv_category_url(v)], _interpret_html, "arxiv.org/list"
    ),
    "huggingface_repo": _Resolver(_hf_repo_urls, _interpret_json, "huggingface.co/api"),
    "huggingface_name": _Resolver(
        lambda v: [_hf_search_url(v)], _interpret_json, "huggingface.co/api/models?search"
    ),
    "github_repo": _Resolver(
        lambda v: [_github_repo_url(v)], _interpret_json, "api.github.com/repos"
    ),
    "cambridge_word": _Resolver(
        lambda v: [_cambridge_url(v)], _interpret_html, "dictionary.cambridge.org"
    ),
}


#: Témoins de validation des résolveurs : moitié d'objets réels, moitié fabriqués.
#: Un résolveur qui ne les sépare pas ne mesure rien ; la campagne exécute ce jeu avant
#: d'interpréter le moindre chiffre sur le corpus.
CONTROL_IDENTIFIERS: tuple[tuple[Identifier, bool], ...] = (
    (Identifier("arxiv_id", "2401.13919", "témoin : article WebVoyager"), True),
    (Identifier("arxiv_id", "9999.99999", "témoin : identifiant impossible"), False),
    (Identifier("arxiv_category", "cs.CL", "témoin : catégorie réelle"), True),
    (Identifier("huggingface_repo", "bert-base-uncased", "témoin : modèle réel"), True),
    (
        Identifier("huggingface_repo", "nonexistent-org/model-qui-nexiste-pas-42", "témoin"),
        False,
    ),
    (Identifier("huggingface_name", "all-MiniLM-L6-v2", "témoin : nom de modèle réel"), True),
    (
        Identifier(
            "huggingface_name", "modele-qui-nexiste-pas-xyz-42", "témoin : nom fabriqué"
        ),
        False,
    ),
    (Identifier("cambridge_word", "serendipity", "témoin : mot réel"), True),
    (Identifier("cambridge_word", "zzzqqxwv", "témoin : mot fabriqué"), False),
    (Identifier("github_repo", "pytorch/pytorch", "témoin : dépôt réel"), True),
    (Identifier("github_repo", "nonexistent-org-42/nope", "témoin : dépôt fabriqué"), False),
)


# Vérification


def check_identifier(
    identifier: Identifier,
    channel: BaseChannel,
    *,
    task_id: str | None = None,
    timeout: float | None = None,
) -> ContentCheck:
    """Vérifie l'existence d'un identifiant auprès de sa source d'autorité.

    Les résolveurs à plusieurs URL (Hugging Face : modèle, puis jeu de données, puis
    espace) s'arrêtent à la première réponse positive ; si toutes répondent « inconnu »,
    l'identifiant est déclaré absent ; si l'une est indécidable, le verdict global l'est
    aussi — le doute ne se résout jamais en accusation.
    """
    resolver = RESOLVERS.get(identifier.kind)
    if resolver is None:
        raise KeyError(f"aucun résolveur pour {identifier.kind!r}")

    last: ContentCheck | None = None
    undecided: ContentCheck | None = None
    for url in resolver.urls(identifier.value):
        obs = channel.fetch(url, timeout=timeout)
        sig = classify(obs).signature
        exists, rationale, title = resolver.interpret(obs, sig)
        check = ContentCheck(
            task_id=task_id,
            identifier=identifier,
            url=url,
            exists=exists,
            signature=sig,
            status=obs.status,
            channel=obs.channel,
            channel_name=obs.channel_name,
            evidence=obs.excerpt[:300],
            rationale=f"{rationale} [autorité : {resolver.authority}]",
            observed_at=obs.observed_at,
            title=title,
            extra={"body_size": obs.body_size, "vendor_headers": dict(obs.headers)},
        )
        if exists is True:
            return check
        if exists is None and undecided is None:
            undecided = check
        last = check
    return undecided or last  # type: ignore[return-value]


def check_task(
    task: Task, channel: BaseChannel, *, timeout: float | None = None
) -> list[ContentCheck]:
    """Vérifie tous les identifiants extraits d'une tâche."""
    return [
        check_identifier(i, channel, task_id=task.task_id, timeout=timeout)
        for i in extract_identifiers(task)
    ]


def finding_from_check(check: ContentCheck) -> Finding | None:
    """Convertit une vérification en constat, ou ``None`` si elle n'apprend rien.

    Un identifiant absent est un constat de dérive de contenu à forte sévérité — c'est
    exactement ce que le statique ne sait pas voir. Un identifiant présent produit un
    constat ``INFO`` : consigner ce qui va bien a une valeur propre dans un rapport de
    santé, cela distingue « vérifié vivant » de « non vérifié ». Un identifiant
    indécidable ne produit rien : le silence est le seul verdict honnête.
    """
    if check.exists is None:
        return None
    absent = check.exists is False
    return Finding(
        category=Category.CONTENT_DRIFT,
        severity=Severity.CRITICAL if absent else Severity.INFO,
        confidence=0.90 if absent else 0.85,
        evidence=f"{check.identifier.evidence} → {check.rationale}",
        detector=DETECTOR_NAME,
        channel=check.channel,
        task_id=check.task_id,
        signal=f"{check.identifier.kind}_{'missing' if absent else 'present'}",
        details={
            "identifier": check.identifier.value,
            "kind": check.identifier.kind,
            "url": check.url,
            "status": check.status,
            "signature": check.signature.value,
            "title": check.title,
            "channel_name": check.channel_name,
            "rationale": check.rationale,
        },
        observed_at=check.observed_at.date(),
    )


def detect_content_existence(
    task: Task,
    *,
    channel: BaseChannel,
    today: _dt.date | None = None,
    timeout: float | None = None,
) -> list[Finding]:
    """Détecteur L2 : vérifie l'existence des contenus cités par la tâche."""
    findings: list[Finding] = []
    for check in check_task(task, channel, timeout=timeout):
        finding = finding_from_check(check)
        if finding is None:
            continue
        if today is not None:
            finding = Finding(
                category=finding.category,
                severity=finding.severity,
                confidence=finding.confidence,
                evidence=finding.evidence,
                detector=finding.detector,
                channel=finding.channel,
                task_id=finding.task_id,
                signal=finding.signal,
                details=finding.details,
                observed_at=today,
            )
        findings.append(finding)
    return findings


detect_content_existence.name = DETECTOR_NAME  # type: ignore[attr-defined]


def coverage(tasks: Iterable[Task]) -> dict[str, Any]:
    """Couverture du détecteur sur un corpus : combien de tâches citent un identifiant.

    Ce chiffre est le plafond de rappel du détecteur ; il doit accompagner tout résultat
    publié, faute de quoi un rappel faible serait imputé au code alors qu'il tient au
    corpus.
    """
    tasks = list(tasks)
    per_kind: dict[str, int] = {}
    covered = 0
    for task in tasks:
        ids = extract_identifiers(task)
        if ids:
            covered += 1
        for i in ids:
            per_kind[i.kind] = per_kind.get(i.kind, 0) + 1
    return {
        "n_tasks": len(tasks),
        "n_tasks_with_identifier": covered,
        "coverage_rate": round(covered / len(tasks), 4) if tasks else 0.0,
        "identifiers_by_kind": dict(sorted(per_kind.items(), key=lambda kv: -kv[1])),
    }
