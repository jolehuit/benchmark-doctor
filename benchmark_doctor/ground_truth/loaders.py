"""Un chargeur par patch-set, ramenant chaque source à un verdict daté par tâche.

Toutes les sources ne disent pas la même chose de la même façon :

============  ==========================================================================
Source        Ce que l'artefact contient
============  ==========================================================================
magnitude     un dictionnaire de patches motivés (raison en clair, `remove` ou `new`)
browseruse    une liste d'identifiants « impossibles » + un fichier de tâches réécrit
skyvern       deux fichiers (tâches retenues / tâches obsolètes), à deux dates
convergence   un CSV de 601 tâches, l'exclusion se lit par différence avec l'original
fara          un JSONL de 595 tâches, idem
alumnium      un JSONL de 619 tâches, l'historique git donne la date et la raison
emergence     535 gabarits sans identifiant WebVoyager : appariement par le texte
============  ==========================================================================

Chaque chargeur renvoie un dictionnaire **complet** : les 643 identifiants d'origine sont
présents, ceux que la source n'a pas touchés reçoivent `action="keep"`. C'est ce qui rend
le nombre d'annotateurs constant par tâche — condition d'application du kappa de Fleiss.

Deux pièges de normalisation sont traités par `normalize_task_id` :

- le séparateur (``Booking--8``, ``Booking-8``, ``Booking_8``, ``Booking 8``) ;
- le nom de site (``GoogleFlights``, ``google flights``, ``Google_Flights``, ``BBCNews``,
  ``Github``, ``HuggingFace``, ``Search Engine``) — ramené aux 15 libellés canoniques.
"""

from __future__ import annotations

import ast
import collections
import csv
import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .sources import ORIGINAL, SOURCES, SourceSpec, source

__all__ = [
    "Verdict",
    "OriginalTask",
    "RAW_DIR",
    "CANONICAL_SITES",
    "normalize_site",
    "normalize_task_id",
    "normalize_question",
    "load_original",
    "load_magnitude",
    "load_browseruse",
    "load_skyvern",
    "load_convergence",
    "load_fara",
    "load_alumnium",
    "load_emergence",
    "load_om2w_journal",
    "LOADERS",
    "load_all",
]

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

KEEP, MODIFY, REMOVE = "keep", "modify", "remove"

#: Les 15 sites du corpus d'origine, orthographe canonique.
CANONICAL_SITES: tuple[str, ...] = (
    "Allrecipes",
    "Amazon",
    "Apple",
    "ArXiv",
    "BBC News",
    "Booking",
    "Cambridge Dictionary",
    "Coursera",
    "ESPN",
    "GitHub",
    "Google Flights",
    "Google Map",
    "Google Search",
    "Huggingface",
    "Wolfram Alpha",
)

#: Clé de comparaison (minuscules, sans séparateur) → libellé canonique.
_SITE_INDEX: dict[str, str] = {re.sub(r"[^a-z0-9]", "", s.lower()): s for s in CANONICAL_SITES}
#: Variantes rencontrées dans les forks et qui ne se réduisent pas par simple normalisation.
_SITE_ALIASES: dict[str, str] = {
    "searchengine": "Google Search",
    "google": "Google Search",
    "googlemaps": "Google Map",
    "bbc": "BBC News",
    "huggingfacehub": "Huggingface",
    "wolfram": "Wolfram Alpha",
    "cambridge": "Cambridge Dictionary",
}


@dataclass(frozen=True)
class Verdict:
    """Verdict d'une source sur une tâche, à une date donnée.

    Args:
        source: clé de la source (`sources.SOURCES`).
        date: date de l'artefact au format ISO.
        action: ``keep``, ``modify`` ou ``remove``.
        reason: raison telle que documentée par la source, ou ``None`` si muette.
        new_question: énoncé réécrit lorsque ``action == "modify"``.
        confidence: ``haute`` ou ``faible`` (cf. `SourceSpec.confidence`).
    """

    source: str
    date: str
    action: str
    reason: str | None = None
    new_question: str | None = None
    confidence: str = "haute"

    def to_dict(self) -> dict[str, Any]:
        """Sérialise avec les noms de champs de la base finale (en français)."""
        out: dict[str, Any] = {
            "source": self.source,
            "date": self.date,
            "action": self.action,
            "raison": self.reason,
            "nouvelle_question": self.new_question,
        }
        if self.confidence != "haute":
            out["confiance"] = self.confidence
        return out


@dataclass(frozen=True)
class OriginalTask:
    """Une tâche du corpus de référence."""

    task_id: str
    site: str
    question: str
    url: str


# Normalisation des identifiants


def normalize_site(name: str) -> str:
    """Ramène un nom de site à son orthographe canonique.

    ``"GoogleFlights"``, ``"google flights"`` et ``"Google_Flights"`` donnent tous
    ``"Google Flights"``. Un nom inconnu est renvoyé tel quel, après compactage des
    espaces : mieux vaut un site non reconnu qu'un site mal rattaché.
    """
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return _SITE_INDEX.get(key) or _SITE_ALIASES.get(key) or re.sub(r"\s+", " ", name).strip()


def normalize_task_id(raw_id: str) -> str:
    """Normalise un identifiant de tâche vers la forme canonique ``Site--N``.

    Gère les variantes de séparateur (``--``, ``-``, ``_``, espace, ``:``) et les
    orthographes de site rencontrées dans les forks.

    Examples:
        >>> normalize_task_id("GoogleFlights-12")
        'Google Flights--12'
        >>> normalize_task_id("bbcnews__3")
        'BBC News--3'
    """
    text = str(raw_id).strip()
    match = re.match(r"^(?P<site>.*?)[\s\-_:]*(?P<num>\d+)$", text)
    if not match:
        return text
    site = normalize_site(match.group("site"))
    return f"{site}--{int(match.group('num'))}"


def normalize_question(text: str) -> str:
    """Forme comparable d'un énoncé : minuscules, sans URL ni ponctuation.

    Sert à décider si deux sources proposent « le même » énoncé : les patch-sets ajoutent
    ou retirent l'URL de départ et la ponctuation finale sans que cela constitue une
    réécriture de la tâche.
    """
    text = re.sub(r"https?://\S+", " ", text.lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


#: Alias interne historique.
_norm_text = normalize_question


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# Corpus de référence


def load_original(raw_dir: Path | None = None) -> dict[str, OriginalTask]:
    """Charge les 643 tâches du corpus WebVoyager d'origine."""
    path = (raw_dir or RAW_DIR) / "webvoyager_original.jsonl"
    tasks: dict[str, OriginalTask] = {}
    for rec in _read_jsonl(path):
        tid = normalize_task_id(rec["id"])
        tasks[tid] = OriginalTask(
            task_id=tid,
            site=normalize_site(rec["web_name"]),
            question=rec["ques"],
            url=rec.get("web", ""),
        )
    return tasks


def _blank(spec: SourceSpec, tasks: Iterable[str]) -> dict[str, Verdict]:
    """Initialise un verdict `keep` pour toutes les tâches d'une source."""
    return {
        tid: Verdict(spec.key, spec.date, KEEP, confidence=spec.confidence) for tid in tasks
    }


def _diff_verdicts(
    spec: SourceSpec,
    original: dict[str, OriginalTask],
    kept: dict[str, str],
    *,
    reason_remove: str,
    reason_modify: str,
) -> dict[str, Verdict]:
    """Déduit les verdicts d'un patch-set qui ne publie qu'un fichier de tâches.

    Args:
        kept: identifiant normalisé → énoncé retenu par la source.
        reason_remove: raison à consigner pour les tâches absentes du fichier.
        reason_modify: raison à consigner pour les énoncés réécrits.
    """
    verdicts = _blank(spec, original)
    for tid, task in original.items():
        if tid not in kept:
            verdicts[tid] = Verdict(spec.key, spec.date, REMOVE, reason_remove, None, spec.confidence)
        elif _norm_text(kept[tid]) != _norm_text(task.question):
            verdicts[tid] = Verdict(
                spec.key, spec.date, MODIFY, reason_modify, kept[tid], spec.confidence
            )
    return verdicts


# Chargeurs par source


def load_magnitude(
    original: dict[str, OriginalTask], raw_dir: Path | None = None
) -> dict[str, Verdict]:
    """Magnitude : le seul patch-set avec une raison rédigée pour chaque tâche.

    Format : ``{task_id: {reason, prev, new}}`` pour une réécriture,
    ``{task_id: {reason, remove: true}}`` pour une suppression.
    """
    spec = source("magnitude")
    patches = json.loads(((raw_dir or RAW_DIR) / "magnitude_patches.json").read_text("utf-8"))
    verdicts = _blank(spec, original)
    for raw_id, patch in patches.items():
        tid = normalize_task_id(raw_id)
        if patch.get("remove"):
            verdicts[tid] = Verdict(spec.key, spec.date, REMOVE, patch.get("reason"))
        else:
            verdicts[tid] = Verdict(spec.key, spec.date, MODIFY, patch.get("reason"), patch.get("new"))
    return verdicts


def load_browseruse(
    original: dict[str, OriginalTask], raw_dir: Path | None = None
) -> dict[str, Verdict]:
    """browser-use : liste d'« impossible tasks » + réécritures silencieuses du fichier.

    Les 55 identifiants restent physiquement présents dans leur fichier de tâches ; c'est
    la liste séparée qui les exclut de la notation. Une tâche à la fois réécrite et
    déclarée impossible est comptée comme supprimée (l'exclusion prime).
    """
    spec = source("browseruse")
    root = raw_dir or RAW_DIR
    impossible = {
        normalize_task_id(x) for x in json.loads((root / "browseruse_impossible.json").read_text("utf-8"))
    }
    edited = {normalize_task_id(r["id"]): r["ques"] for r in _read_jsonl(root / "browseruse_tasks.jsonl")}
    verdicts = _blank(spec, original)
    for tid, task in original.items():
        if tid in impossible:
            verdicts[tid] = Verdict(
                spec.key, spec.date, REMOVE, "listée dans WebVoyagerImpossibleTasks.json"
            )
        elif tid in edited and _norm_text(edited[tid]) != _norm_text(task.question):
            verdicts[tid] = Verdict(
                spec.key, spec.date, MODIFY, "énoncé réécrit sans justification publiée", edited[tid]
            )
    return verdicts


def load_skyvern(
    original: dict[str, OriginalTask], snapshot: str = "2026", raw_dir: Path | None = None
) -> dict[str, Verdict]:
    """Skyvern : deux instantanés datés du même dépôt.

    Args:
        snapshot: ``"2025"`` (2025-01-16) ou ``"2026"`` (2026-05-04, commit
            « refresh webvoyager_tasks.jsonl dates to 2026/2027 »).
    """
    spec = source("skyvern_2025" if snapshot == "2025" else "skyvern_2026")
    root = raw_dir or RAW_DIR
    tasks_file, outdated_file = (
        ("skyvern_tasks_20250116.jsonl", "skyvern_outdated_20250116.jsonl")
        if snapshot == "2025"
        else ("skyvern_tasks.jsonl", "skyvern_outdated.jsonl")
    )
    kept = {normalize_task_id(r["id"]): r["ques"] for r in _read_jsonl(root / tasks_file)}
    outdated = {normalize_task_id(r["id"]) for r in _read_jsonl(root / outdated_file)}
    verdicts = _diff_verdicts(
        spec,
        original,
        kept,
        reason_remove="absente du fichier de tâches",
        reason_modify="énoncé rafraîchi (commit de mise à jour des dates)",
    )
    for tid in outdated:
        verdicts[tid] = Verdict(
            spec.key, spec.date, REMOVE, "listée dans webvoyager_outdated_tasks.jsonl"
        )
    return verdicts


def load_convergence(
    original: dict[str, OriginalTask], raw_dir: Path | None = None
) -> dict[str, Verdict]:
    """Convergence : 601 tâches déclarées valides jusqu'au 20/12/2025.

    Le CSV porte l'identifiant dans une colonne `metadata` sérialisée en littéral Python
    (guillemets simples) — d'où `ast.literal_eval` plutôt que `json.loads`. L'énoncé se
    voit ajouter un suffixe « Use <url>. » systématique, retiré avant comparaison.
    """
    spec = source("convergence")
    path = (raw_dir or RAW_DIR) / "convergence_valid_20251220.csv"
    kept: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            meta = ast.literal_eval(row["metadata"])
            question = re.sub(r"\s*Use https?://\S+\s*$", "", row["task"]).strip()
            kept[normalize_task_id(meta["id"])] = question
    return _diff_verdicts(
        spec,
        original,
        kept,
        reason_remove="absente du sous-ensemble « valid until 20th December 2025 »",
        reason_modify="énoncé réécrit pour rester valide jusqu'au 20/12/2025",
    )


def load_fara(original: dict[str, OriginalTask], raw_dir: Path | None = None) -> dict[str, Verdict]:
    """Microsoft Fara : le sous-ensemble F595, instantané daté du 31/08/2025."""
    spec = source("fara")
    path = (raw_dir or RAW_DIR) / "fara_webvoyager_20250831.jsonl"
    kept = {normalize_task_id(r["id"]): r["ques"] for r in _read_jsonl(path)}
    return _diff_verdicts(
        spec,
        original,
        kept,
        reason_remove="absente de WebVoyager_data_08312025.jsonl",
        reason_modify="énoncé réécrit dans WebVoyager_data_08312025.jsonl",
    )


def load_alumnium(
    original: dict[str, OriginalTask], raw_dir: Path | None = None
) -> dict[str, Verdict]:
    """Alumnium : 619 tâches, verdicts datés par l'historique git site par site.

    Alumnium ne publie pas de fichier de patches ; la raison de chaque verdict est le
    message du commit qui l'a produit (« Remove impossible tasks for Booking »…), et sa
    date celle de ce commit — d'où des verdicts échelonnés du 16 au 23 mars 2026.
    """
    spec = source("alumnium")
    root = raw_dir or RAW_DIR
    kept = {normalize_task_id(r["id"]): r["ques"] for r in _read_jsonl(root / "alumnium_patched.jsonl")}
    history_path = root / "alumnium_history.json"
    history = (
        {normalize_task_id(k): v for k, v in json.loads(history_path.read_text("utf-8")).items()}
        if history_path.exists()
        else {}
    )
    verdicts = _diff_verdicts(
        spec,
        original,
        kept,
        reason_remove="absente du fichier de tâches Alumnium",
        reason_modify="énoncé réécrit par Alumnium",
    )
    # L'historique git affine date et raison, sans changer l'action déduite du fichier.
    for tid, entry in history.items():
        if tid not in verdicts:
            continue
        current = verdicts[tid]
        if current.action == KEEP:
            continue
        verdicts[tid] = Verdict(
            spec.key,
            entry.get("date", spec.date),
            current.action,
            entry.get("reason"),
            current.new_question,
        )
    return verdicts


def load_emergence(
    original: dict[str, OriginalTask],
    raw_dir: Path | None = None,
    threshold: float = 0.55,
) -> tuple[dict[str, Verdict], dict[str, Any]]:
    """Emergence : 535 gabarits, rattachés aux identifiants d'origine par le texte.

    Emergence a retemplaté le benchmark sans conserver les identifiants WebVoyager. Le
    rattachement se fait donc par appariement d'énoncés, site par site, en affectation
    gloutonne sur la similarité décroissante (`difflib`), ce qui interdit qu'un même
    original soit revendiqué par deux gabarits.

    Réserve : l'absence d'une tâche chez Emergence n'est pas un verdict de suppression
    pour cause de decay, Emergence rééchantillonnant à 35 tâches par site alors que les
    sites d'origine en comptent 41 à 46. Ces verdicts sont donc marqués
    `confiance="faible"` et exclus de l'accord inter-annotateurs.

    Returns:
        Le dictionnaire de verdicts, et un rapport d'appariement (taux, similarité
        médiane, gabarits sans correspondance).
    """
    spec = source("emergence")
    templates = json.loads(((raw_dir or RAW_DIR) / "emergence_template.json").read_text("utf-8"))

    def instantiate(tpl: dict[str, Any]) -> str:
        text = tpl["intent_template"]
        for key, value in tpl.get("instantiation_dict", {}).items():
            text = text.replace("{{" + key + "}}", str(value))
        return re.sub(r"^Using the website\s*,?\s*", "", text).strip()

    by_site: dict[str, list[OriginalTask]] = collections.defaultdict(list)
    for task in original.values():
        by_site[task.site].append(task)

    templates_by_site: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for tpl in templates:
        templates_by_site[normalize_site(tpl.get("domain", ""))].append(tpl)

    matched: dict[str, tuple[dict[str, Any], float]] = {}
    unmatched_templates: list[dict[str, Any]] = []
    for site, tpls in templates_by_site.items():
        candidates = by_site.get(site, [])
        pairs: list[tuple[float, int, str]] = []
        texts = {tpl["id"]: _norm_text(instantiate(tpl)) for tpl in tpls}
        for tpl in tpls:
            for cand in candidates:
                ratio = difflib.SequenceMatcher(None, texts[tpl["id"]], _norm_text(cand.question)).ratio()
                pairs.append((ratio, tpl["id"], cand.task_id))
        pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
        used_tpl: set[int] = set()
        used_task: set[str] = set()
        index = {tpl["id"]: tpl for tpl in tpls}
        for ratio, tpl_id, task_id in pairs:
            if ratio < threshold:
                break
            if tpl_id in used_tpl or task_id in used_task:
                continue
            used_tpl.add(tpl_id)
            used_task.add(task_id)
            matched[task_id] = (index[tpl_id], ratio)
        unmatched_templates.extend(tpl for tpl in tpls if tpl["id"] not in used_tpl)

    verdicts = _blank(spec, original)
    for tid in original:
        if tid not in matched:
            verdicts[tid] = Verdict(
                spec.key,
                spec.date,
                REMOVE,
                "absente du sous-ensemble Emergence (rééchantillonnage à 35 tâches/site)",
                None,
                "faible",
            )
            continue
        tpl, ratio = matched[tid]
        question = instantiate(tpl)
        if ratio < 0.95 or "@eval:" in question:
            verdicts[tid] = Verdict(
                spec.key,
                spec.date,
                MODIFY,
                "réécrite en gabarit instancié à l'exécution",
                question,
                "faible",
            )
    report = {
        "seuil_similarite": threshold,
        "gabarits": len(templates),
        "apparies": len(matched),
        "gabarits_sans_correspondance": len(unmatched_templates),
        "originaux_sans_correspondance": len(original) - len(matched),
        "similarite_mediane": (
            round(sorted(r for _, r in matched.values())[len(matched) // 2], 3) if matched else None
        ),
    }
    return verdicts, report


def load_om2w_journal(raw_dir: Path | None = None) -> dict[str, Any]:
    """Extrait le journal daté de remplacement de tâches d'Online-Mind2Web.

    Contre-exemple du benchmark **maintenu** : là où WebVoyager est gelé depuis mars 2024,
    Online-Mind2Web publie dans son README les vagues de remplacement, datées, avec la
    liste des identifiants concernés.

    Returns:
        ``{"vagues": [{date, n_taches, task_ids, resume}], "taches_distinctes": n, ...}``
    """
    path = (raw_dir or RAW_DIR) / "om2w_readme.md"
    text = path.read_text(encoding="utf-8")
    waves: list[dict[str, Any]] = []
    for match in re.finditer(r"^####\s*(\d{4})/(\d{2})/(\d{2})\s*$(.*?)(?=^####|\Z)", text, re.M | re.S):
        year, month, day, body = match.groups()
        ids: list[str] = []
        for block in re.findall(r"\[(.*?)\]", body, re.S):
            ids.extend(re.findall(r"['\"]([0-9a-f]{16,}(?:_\d+)?)['\"]", block))
        summary = re.search(r"\*\*Update summary:\*\*\s*(.+?)\n\n", body, re.S)
        waves.append(
            {
                "date": f"{year}-{month}-{day}",
                "n_taches": len(ids),
                "task_ids": ids,
                "resume": " ".join(summary.group(1).split()) if summary else None,
            }
        )
    waves.sort(key=lambda w: w["date"])
    distinct = {tid.split("_")[0] for wave in waves for tid in wave["task_ids"]}
    return {
        "benchmark": "Online-Mind2Web",
        "taille_corpus": 300,
        "vagues": waves,
        "n_vagues": len(waves),
        "remplacements_cumules": sum(w["n_taches"] for w in waves),
        "taches_distinctes_remplacees": len(distinct),
        "premiere_vague": waves[0]["date"] if waves else None,
        "derniere_vague": waves[-1]["date"] if waves else None,
    }


#: Table des chargeurs, indexée par clé de source.
LOADERS: dict[str, Callable[..., Any]] = {
    "browseruse": load_browseruse,
    "skyvern_2025": lambda original, raw_dir=None: load_skyvern(original, "2025", raw_dir),
    "convergence": load_convergence,
    "magnitude": load_magnitude,
    "emergence": load_emergence,
    "fara": load_fara,
    "alumnium": load_alumnium,
    "skyvern_2026": lambda original, raw_dir=None: load_skyvern(original, "2026", raw_dir),
}


def load_all(raw_dir: Path | None = None) -> tuple[
    dict[str, OriginalTask], dict[str, dict[str, Verdict]], dict[str, Any]
]:
    """Charge le corpus et les huit jeux de verdicts, dans l'ordre chronologique.

    Returns:
        ``(taches_originales, {cle_source: {task_id: Verdict}}, rapports)`` où `rapports`
        contient les diagnostics d'appariement (Emergence) et les effectifs par source.
    """
    original = load_original(raw_dir)
    verdicts: dict[str, dict[str, Verdict]] = {}
    reports: dict[str, Any] = {}
    for spec in SOURCES:
        loader = LOADERS[spec.key]
        result = loader(original, raw_dir)
        if isinstance(result, tuple):
            result, report = result
            reports[spec.key] = report
        verdicts[spec.key] = result
    reports["effectifs"] = {
        key: dict(collections.Counter(v.action for v in per_task.values()))
        for key, per_task in verdicts.items()
    }
    return original, verdicts, reports
