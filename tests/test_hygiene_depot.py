"""Un artefact versionné ne doit pas dépendre de la machine qui l'a produit.

Un chemin absolu de poste de travail dans un fichier suivi par git rend le dépôt
irrejouable ailleurs : le lecteur ne peut ni relancer le script ni relire l'artefact
sans réécrire le chemin à la main. Les sorties de campagne désignent donc toujours
leurs entrées relativement à la racine du dépôt, et ce module vérifie que la règle
tient sur l'ensemble des fichiers texte suivis.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent

#: Formats relus. Les archives réseau (`.har`) en sont exclues à dessein : leur corps est
#: du HTML capturé sur des sites tiers, où une URL enracinée comme `href="/x/y.css"` a la
#: forme d'un chemin absolu sans en être un.
SUFFIXES = {
    ".py", ".md", ".json", ".jsonl", ".yml", ".yaml", ".toml",
    ".cfg", ".ini", ".txt", ".csv", ".sh", ".html", ".css", ".svg",
}

#: Premier segment des arborescences de comptes utilisateurs sur les trois familles de
#: systèmes. Les segments sont assemblés au lieu d'être écrits en toutes lettres, pour que
#: le garde-fou puisse relire son propre code source sans se signaler lui-même.
RACINES_DE_COMPTE = ("home", "Users", "root")

#: Un chemin absolu de poste de travail : arborescence de compte POSIX, ou lettre de
#: lecteur Windows. Le contexte de gauche écarte les URL (`exemple.test/home/x`) et les
#: chemins relatifs, qui ne disent rien de la machine.
MOTIF = re.compile(
    r"(?<![\w.$-])(?:"
    r"/(?:" + "|".join(RACINES_DE_COMPTE) + r")/[\w.-]+"
    r"|[A-Za-z]:[\\/]{1,2}[\w.-]+"
    r")"
)


def _exemple_absolu(racine: str) -> str:
    return f"/{racine}/un_compte/un_projet/runs/sortie.json"


def _exemple_windows(lettre: str) -> str:
    return f"{lettre}:\\un_compte\\un_projet\\runs\\sortie.json"


def _sosies() -> list[str]:
    """Textes qui ont l'allure d'un chemin absolu sans en être un."""
    return [
        "data/raw/webvoyager_original.jsonl",
        "./runs/health_20260815.json",
        "12:30",
    ] + [f"https://exemple.test/{racine}/page.html" for racine in RACINES_DE_COMPTE]


def test_aucun_fichier_versionne_ne_depend_du_poste_qui_l_a_produit():
    # Le motif d'abord : une expression qui a cessé de mordre laisserait le garde-fou au
    # vert sur un dépôt fautif, ce qui est pire que pas de garde-fou du tout.
    for racine in RACINES_DE_COMPTE:
        assert MOTIF.search(_exemple_absolu(racine)), racine
    assert MOTIF.search(_exemple_windows("C"))
    for sosie in _sosies():
        assert not MOTIF.search(sosie), sosie

    # Le dépôt ensuite.
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z"], cwd=RACINE, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git indisponible ou dépôt non initialisé")

    coupables = []
    for nom in listing.split("\0"):
        if not nom:
            continue
        fichier = RACINE / nom
        if fichier.suffix not in SUFFIXES or not fichier.is_file():
            continue
        try:
            texte = fichier.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        coupables += [f"{nom} : {trouve}" for trouve in sorted(set(MOTIF.findall(texte)))]

    assert not coupables, "chemins absolus de poste de travail :\n" + "\n".join(coupables)
