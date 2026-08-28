#!/usr/bin/env python3
"""Télécharge les patch-sets absents de `data/raw/`, aux révisions épinglées par `sources.py`.

Trois des sept patch-sets ne sont pas récupérables par une simple URL « main » :

- **Alumnium** : le fichier `data/WebVoyager_data.jsonl` de la branche par défaut fait
  exactement la même taille que l'original — c'est la copie de base du fork. Le fichier
  patché (619 tâches) n'existe qu'à partir des 20 commits par site de mars 2026.
- **Microsoft Fara** : le fichier utile est `webeval/data/webvoyager/WebVoyager_data_08312025.jsonl`,
  enfoui dans un dépôt volumineux ; le téléchargement direct par le chemin racine échoue.
- **Skyvern 01/2025** : l'instantané ancien n'existe qu'à un commit précis.

Le script n'utilise que des requêtes HTTPS sur des révisions épinglées (pas de `git clone`) :
il est donc rejouable à l'identique et ne dépend pas de l'état futur des dépôts.

Usage :
    python3 -m benchmark_doctor.ground_truth.fetch_sources [--force]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

#: Fichiers dérivés : (nom local, URL épinglée).
DIRECT_FILES: tuple[tuple[str, str], ...] = (
    (
        "browseruse_tasks.jsonl",
        "https://raw.githubusercontent.com/browser-use/eval/"
        "37bfdca3a5ab20775014e8a00ffc0e4d2e000b00/data/WebVoyager_data.jsonl",
    ),
    (
        "skyvern_tasks_20250116.jsonl",
        "https://raw.githubusercontent.com/Skyvern-AI/skyvern/"
        "92c6fddc9b02d2c00f61b074372d80f39fa85220/evaluation/datasets/webvoyager_tasks.jsonl",
    ),
    (
        "skyvern_outdated_20250116.jsonl",
        "https://raw.githubusercontent.com/Skyvern-AI/skyvern/"
        "92c6fddc9b02d2c00f61b074372d80f39fa85220/evaluation/datasets/webvoyager_outdated_tasks.jsonl",
    ),
    (
        "fara_webvoyager_20250831.jsonl",
        "https://raw.githubusercontent.com/microsoft/fara/"
        "ff0dbac1d12005718812afae1a2f53fc8e98f302/webeval/data/webvoyager/WebVoyager_data_08312025.jsonl",
    ),
    (
        "convergence_valid_20251220.csv",
        "https://huggingface.co/datasets/convergence-ai/WebVoyager2025Valid/"
        "resolve/9854e641831b59d5090891830d129f07f54d2219/test.csv",
    ),
    (
        "alumnium_patched.jsonl",
        "https://raw.githubusercontent.com/alumnium-hq/WebVoyager/"
        "e73fddd2a804309486ea3253949edbfb790fa2a4/data/WebVoyager_data.jsonl",
    ),
)

#: Historique Alumnium : un commit par site, dans l'**ordre de filiation git** (topologique),
#: qui n'est pas l'ordre des dates d'auteur — « Remove impossible tasks for Google Search »
#: porte la date du 2026-03-23 mais se situe au milieu de la chaîne. Rejouer les révisions
#: dans l'ordre des dates produirait des différences fantômes et attribuerait la mauvaise
#: raison à des tâches touchées par un autre commit.
#: (sha, date d'auteur, message) — le message porte la raison du verdict, faute de champ dédié.
ALUMNIUM_COMMITS: tuple[tuple[str, str, str], ...] = (
    ("b87f88d30f4649b9c36e762842f24d9cd9ba1aaf", "2026-03-16", "Remove impossible tasks for Allrecipes"),
    ("c4dae8d944451ee076cc5640e4032c48086dcbe1", "2026-03-16", "Remove/update impossible tasks for Amazon"),
    ("ce66d0300b92f6c23fae9b5897ac14d6ee211068", "2026-03-16", "Remove impossible tasks for Apple"),
    ("d76d347cc95da3c2ff3707870b71aadb8356e730", "2026-03-16", "Update impossible tasks for ArXiv"),
    ("eb833a8f458201095622648bddc685fd1e34740e", "2026-03-16", "Remove impossible tasks for BBC News"),
    ("b77b778c71c1831177bce27445a261eb1b5be577", "2026-03-16", "Remove impossible tasks for Booking"),
    ("d7db1c2482a5cb9de3b58b6ee5b19737b9fd985d", "2026-03-16", "Remove impossible tasks for Cambridge Dictionary"),
    ("3229d28ca46a80c24cfa65cb63465116ae8383d8", "2026-03-16", "Remove impossible tasks for Coursera"),
    ("e1b47baa25d8ad14dc1aa5a506b502bbdaf047ab", "2026-03-17", "Remove impossible tasks for Google Flights"),
    ("a6dd339f4d514c28eb42e145e85250f1b5a8e6d2", "2026-03-17", "Remove impossible tasks for Google Map"),
    ("b02ce0e2e42031c8f7ceca369e4e4ae28a893073", "2026-03-23", "Remove impossible tasks for Google Search"),
    ("f7768819babe5dd4c82e4db09a52c495c25b77b3", "2026-03-17", "Remove impossible tasks for Huggingface"),
    ("14fd5b674a0e872f0bc03de1eac87b681571f332", "2026-03-17", "Update dates for Amazon"),
    ("9dcbdd34df1ff27530ab66306c52f8dd2a7a9c13", "2026-03-17", "Update outdated devices for Apple"),
    ("678e576d78db56b27c5484782cb73ce6beef783f", "2026-03-17", "Updates dates for Booking"),
    ("0ef08f7ea1eea636801eef4d1d9586c896db5c4f", "2026-03-17", "Update dates for ESPN"),
    ("442470da0a47dd0f17b8591ed7ce7c0ac6cad5e7", "2026-03-17", "Update dates for Google Flights"),
    ("2b935a32f4816065698671ba7a018dfe2ad80ee1", "2026-03-17", "Update dates for Google Search"),
    ("5d7aa5a3c19431a005e3a57d487c78d7eaf865b7", "2026-03-17", "Update dates for Huggingface"),
    ("e73fddd2a804309486ea3253949edbfb790fa2a4", "2026-03-17", "Update dates for Wolfram Alpha"),
)

ALUMNIUM_BLOB = (
    "https://raw.githubusercontent.com/alumnium-hq/WebVoyager/{sha}/data/WebVoyager_data.jsonl"
)


def _get(url: str, timeout: int = 120) -> bytes:
    """Télécharge une URL, en propageant une erreur lisible."""
    req = urllib.request.Request(url, headers={"User-Agent": "benchmark-doctor/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:  # pragma: no cover - dépend du réseau
        raise RuntimeError(f"HTTP {exc.code} sur {url}") from exc


def _read_jsonl(blob: bytes) -> dict[str, dict]:
    """Indexe un JSONL WebVoyager par identifiant de tâche."""
    out: dict[str, dict] = {}
    for line in blob.decode("utf-8").splitlines():
        line = line.strip()
        if line:
            rec = json.loads(line)
            out[rec["id"]] = rec
    return out


def build_alumnium_history(force: bool = False) -> Path:
    """Reconstitue l'historique tâche par tâche du fork Alumnium.

    Alumnium ne publie pas de fichier de patches : la seule trace du verdict est la
    séquence de commits par site. On rejoue donc les 20 révisions et on date chaque
    suppression / réécriture au commit qui l'a produite.

    Returns:
        Le chemin du fichier `alumnium_history.json` écrit dans `data/raw/`.
    """
    dest = RAW / "alumnium_history.json"
    if dest.exists() and not force:
        print(f"  = {dest.name} (déjà présent)")
        return dest

    print("  → reconstitution de l'historique Alumnium (20 révisions)")
    base = _read_jsonl(_get(ALUMNIUM_BLOB.format(sha="091544539eba485dbd74ef3742011ddeede37336")))
    history: dict[str, dict] = {}
    prev = base
    for sha, date, message in ALUMNIUM_COMMITS:
        cur = _read_jsonl(_get(ALUMNIUM_BLOB.format(sha=sha)))
        for tid in set(prev) - set(cur):
            history[tid] = {"action": "remove", "date": date, "commit": sha, "reason": message}
        for tid, rec in cur.items():
            if tid in prev and prev[tid]["ques"] != rec["ques"]:
                history[tid] = {
                    "action": "modify",
                    "date": date,
                    "commit": sha,
                    "reason": message,
                    "new": rec["ques"],
                }
        prev = cur
    dest.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  + {dest.name} ({len(history)} tâches touchées)")
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="retélécharge même si le fichier existe")
    args = parser.parse_args(argv)

    RAW.mkdir(parents=True, exist_ok=True)
    print(f"Destination : {RAW}")
    for name, url in DIRECT_FILES:
        dest = RAW / name
        if dest.exists() and not args.force:
            print(f"  = {name} (déjà présent)")
            continue
        dest.write_bytes(_get(url))
        print(f"  + {name} ({dest.stat().st_size} octets)")
    build_alumnium_history(force=args.force)
    print("Terminé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
