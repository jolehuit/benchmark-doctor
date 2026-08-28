"""Style commun des figures du mémoire : sobriété, niveaux de gris, lisibilité à l'impression.

Les figures sont imprimées en noir et blanc sur une page A4 à marges de 2,5 cm, soit 16 cm
de largeur utile. D'où les contraintes du module : aucune teinte porteuse d'information
(l'identité d'une série passe par la valeur, la trame, le style de trait ou une étiquette
directe), une largeur de référence unique pour que les figures s'insèrent à l'échelle 1, si
bien que la taille de police du script est celle qu'on lira sur la page, et une sortie
double PNG 300 ppp / PDF vectoriel, polices incorporées en TrueType pour garder le texte
sélectionnable.

La rampe ``GRAYS`` a été vérifiée avec le validateur de palette ordinale (monotonie de la
clarté, écart ≥ 0,06 entre pas adjacents, contraste du pas le plus clair ≥ 2:1 sur fond
blanc). Elle plafonne à quatre pas : un cinquième ne se distinguerait plus du papier.

La police est Liberation Sans, métriquement compatible avec l'Arial exigé par le vademecum.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

FIGURES_DIR = Path(__file__).resolve().parent
ROOT = FIGURES_DIR.parent
RUNS = ROOT / "runs"
DATA = ROOT / "data"

# Date de mesure gelée : les chiffres du mémoire ne doivent pas bouger d'une relance à
# l'autre. Elle est lue dans les fichiers produits, jamais recalculée ici.
REFERENCE_DATE = "2026-08-15"

#: Rampe à 4 pas, du plus sombre au plus clair. Le pas le plus clair conserve un contraste
#: de 2,11:1 sur fond blanc, ce qui reste visible après photocopie.
GRAYS = ("#1a1a1a", "#4d4d4d", "#808080", "#b0b0b0")
#: Rampe à 3 pas, dérivée de la même échelle.
GRAYS3 = ("#1a1a1a", "#6b6b6b", "#b0b0b0")
#: Rampe à 2 pas.
GRAYS2 = ("#1a1a1a", "#9c9c9c")

INK = "#1a1a1a"          # texte principal et traits porteurs de données
INK_SOFT = "#4d4d4d"     # texte secondaire
INK_MUTED = "#767676"    # annotations
RULE = "#8c8c8c"         # axes
GRID = "#dcdcdc"         # grille, volontairement en retrait
SURFACE = "#ffffff"

#: Encodage secondaire quand deux aplats voisins doivent rester distincts sur une photocopie.
HATCH_LIGHT = "///"
HATCH_CROSS = "xxx"

WIDTH_FULL = 6.3   # 16 cm : largeur utile d'une page A4 à marges de 2,5 cm
WIDTH_HALF = 3.05

BASE_SIZE = 8.5    # contre 11 pt pour le corps du mémoire


def apply_style() -> None:
    """Installe le style commun dans les rcParams de matplotlib."""
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Liberation Sans", "Arial", "Helvetica", "DejaVu Sans"],
            "font.size": BASE_SIZE,
            "axes.titlesize": BASE_SIZE + 1,
            "axes.titleweight": "bold",
            "axes.labelsize": BASE_SIZE,
            "xtick.labelsize": BASE_SIZE - 0.5,
            "ytick.labelsize": BASE_SIZE - 0.5,
            "legend.fontsize": BASE_SIZE - 0.5,
            "figure.titlesize": BASE_SIZE + 1.5,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "text.color": INK,
            "axes.labelcolor": INK,
            "axes.edgecolor": RULE,
            "xtick.color": RULE,
            "ytick.color": RULE,
            "xtick.labelcolor": INK_SOFT,
            "ytick.labelcolor": INK_SOFT,
            "axes.linewidth": 0.6,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "xtick.major.size": 2.5,
            "ytick.major.size": 2.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": False,
            "grid.color": GRID,
            "grid.linewidth": 0.5,
            "grid.linestyle": "-",
            "legend.frameon": False,
            "legend.handlelength": 1.6,
            "legend.handleheight": 0.9,
            "legend.columnspacing": 1.2,
            "legend.labelspacing": 0.4,
            "lines.linewidth": 1.4,
            "lines.markersize": 4.5,
            "hatch.linewidth": 0.55,
            "hatch.color": "#ffffff",
            "patch.linewidth": 0.0,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "figure.dpi": 110,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.02,
        }
    )


NBSP = " "  # espace insécable, exigée en français devant % et :


def fr(value: float, decimals: int = 1) -> str:
    """Formate un nombre à la française : virgule décimale, pas de séparateur de milliers."""
    return f"{value:.{decimals}f}".replace(".", ",")


def pct(value: float, decimals: int = 1) -> str:
    """Formate un pourcentage à la française, espace insécable comprise."""
    return f"{fr(value, decimals)}{NBSP}%"


def usd(value: float) -> str:
    """Formate un montant en dollars, avec assez de décimales pour rester lisible."""
    if value == 0:
        return "0" + NBSP + "$"
    if value < 0.01:
        return fr(value * 100, 2) + NBSP + "¢"
    if value < 1:
        return fr(value, 3) + NBSP + "$"
    return fr(value, 2) + NBSP + "$"


MONTHS_LONG_FR = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril", 5: "mai", 6: "juin",
    7: "juillet", 8: "août", 9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
}


def long_date_fr(iso: str) -> str:
    """« 2026-08-15 » → « 15 août 2026 », pour le corps des légendes."""
    year, month, day = (int(part) for part in iso.split("-"))
    return f"{day} {MONTHS_LONG_FR[month]} {year}"


def count_fr(value: int) -> str:
    """Formate un entier avec l'espace insécable des milliers : 1331 → « 1 331 »."""
    return f"{value:,}".replace(",", NBSP)


def light_axes(ax, *, x_grid: bool = False, y_grid: bool = False) -> None:
    """Grille en retrait, sous les marques, et suppression des cadres inutiles."""
    ax.set_axisbelow(True)
    if x_grid:
        ax.xaxis.grid(True, color=GRID, linewidth=0.5)
    if y_grid:
        ax.yaxis.grid(True, color=GRID, linewidth=0.5)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(fig, stem: str) -> list[Path]:
    """Enregistre une figure en PNG 300 ppp puis en PDF vectoriel, et rend les chemins écrits."""
    written = []
    for ext in ("png", "pdf"):
        path = FIGURES_DIR / f"{stem}.{ext}"
        fig.savefig(path, format=ext)
        written.append(path)
    plt.close(fig)
    return written
