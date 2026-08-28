"""Lecteur du format WebVoyager (JSON Lines).

Format d'origine (MinorJerry/WebVoyager, `data/WebVoyager_data.jsonl`, gelé le 04/03/2024) :

    {"web_name": "Booking", "id": "Booking--8", "ques": "...", "web": "https://www.booking.com/"}

Les sept patch-sets publics utilisés comme ground truth (Magnitude, Alumnium, Skyvern,
browser-use, Fara, Convergence, Emergence) réutilisent tous ce même schéma, éventuellement
avec des tâches en moins ou des énoncés modifiés : le même parseur les lit donc tous, ce
qui est indispensable pour comparer les forks tâche à tâche.

Le parseur est tolérant sur la forme (lignes vides, BOM, tableau JSON au lieu de JSONL)
et strict sur le fond : une ligne sans identifiant ou sans énoncé est signalée, jamais
silencieusement ignorée.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from ..models import Task

__all__ = [
    "WEBVOYAGER_FIELDS",
    "parse_webvoyager_record",
    "iter_webvoyager",
    "load_webvoyager",
    "load_webvoyager_index",
]

#: Correspondance champ source → champ normalisé.
WEBVOYAGER_FIELDS = {
    "id": "task_id",
    "ques": "question",
    "web_name": "site",
    "web": "start_url",
}


class WebVoyagerParseError(ValueError):
    """Ligne du corpus impossible à normaliser (champ obligatoire manquant)."""


def parse_webvoyager_record(
    record: Mapping[str, Any], *, benchmark: str = "webvoyager"
) -> Task:
    """Normalise un enregistrement WebVoyager en `Task`.

    Accepte aussi les variantes de champs rencontrées dans les forks
    (``task_id``/``question``/``confirmed_task`` chez Online-Mind2Web et Skyvern).
    """
    task_id = record.get("id") or record.get("task_id")
    question = (
        record.get("ques")
        or record.get("question")
        or record.get("confirmed_task")
        or record.get("task")
    )
    if not task_id:
        raise WebVoyagerParseError(f"enregistrement sans identifiant : {record!r}")
    if not question:
        raise WebVoyagerParseError(f"enregistrement {task_id!r} sans énoncé")
    site = record.get("web_name") or record.get("site") or record.get("website")
    start_url = record.get("web") or record.get("start_url") or record.get("url")
    return Task(
        task_id=str(task_id),
        question=str(question).strip(),
        site=str(site) if site else None,
        start_url=str(start_url) if start_url else None,
        benchmark=benchmark,
        raw=dict(record),
    )


def _iter_json_objects(text: str) -> Iterator[Mapping[str, Any]]:
    """Itère sur les objets d'un fichier JSONL — ou d'un tableau JSON, tolérance utile
    parce que certains forks publient leur corpus en `.json` plutôt qu'en `.jsonl`."""
    stripped = text.lstrip("﻿").strip()
    if stripped.startswith("["):
        payload = json.loads(stripped)
        if not isinstance(payload, list):
            raise WebVoyagerParseError("le fichier JSON n'est pas un tableau de tâches")
        for item in payload:
            yield item
        return
    for lineno, line in enumerate(stripped.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - dépend du fichier
            raise WebVoyagerParseError(f"ligne {lineno} illisible : {exc}") from exc


def iter_webvoyager(
    source: str | Path | Iterable[str], *, benchmark: str = "webvoyager"
) -> Iterator[Task]:
    """Itère les tâches d'un corpus WebVoyager.

    Args:
        source: chemin d'un fichier JSONL/JSON, ou itérable de lignes déjà en mémoire.
        benchmark: nom logique du corpus, utile pour distinguer les forks
            (``"webvoyager"``, ``"magnitude"``, ``"skyvern"``…).
    """
    if isinstance(source, (str, Path)):
        text = Path(source).read_text(encoding="utf-8")
    else:
        text = "\n".join(source)
    for record in _iter_json_objects(text):
        yield parse_webvoyager_record(record, benchmark=benchmark)


def load_webvoyager(
    source: str | Path | Iterable[str], *, benchmark: str = "webvoyager"
) -> list[Task]:
    """Charge un corpus WebVoyager complet en mémoire (643 tâches pour l'original)."""
    return list(iter_webvoyager(source, benchmark=benchmark))


def load_webvoyager_index(
    source: str | Path | Iterable[str], *, benchmark: str = "webvoyager"
) -> dict[str, Task]:
    """Charge un corpus indexé par identifiant de tâche.

    Indispensable pour comparer deux forks tâche à tâche (quelles tâches ont disparu,
    lesquelles ont vu leur énoncé réécrit).
    """
    index: dict[str, Task] = {}
    for task in iter_webvoyager(source, benchmark=benchmark):
        if task.task_id in index:
            raise WebVoyagerParseError(f"identifiant dupliqué : {task.task_id}")
        index[task.task_id] = task
    return index
