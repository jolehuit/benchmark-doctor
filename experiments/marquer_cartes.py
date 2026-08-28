#!/usr/bin/env python3
"""Marque le statut éditorial de chaque carte de `runs/`, et écrit l'index `runs/CARTES.md`.

Le dépôt contient dix cartes de santé et deux artefacts de sensibilité, soit douze
configurations du même outil. Une seule sert de référence au mémoire,
`runs/health_20260815.json`, doublée de son rejeu hors ligne ; les dix autres ont une
couche en moins, un backend d'ambiguïté différent ou un canal partiel.

Ce script ne recalcule rien. Il ajoute à chaque JSON un champ ``statut_editorial`` qui dit
si la carte est citable et pourquoi. Il est idempotent.

    python3 experiments/marquer_cartes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"

CANONIQUE = "canonique"
EXPLORATOIRE = "exploratoire"
ENTREE_DIFF = "entree_de_differentiel"

MENTION = {
    CANONIQUE: "carte de référence du mémoire, seule carte citable",
    EXPLORATOIRE: "configuration exploratoire, non citée",
    ENTREE_DIFF: (
        "terme d'un différentiel : sa distribution de notes ne décrit pas un état du "
        "benchmark"
    ),
}

#: Libellé de statut porté par la colonne de l'index.
LIBELLE = {
    CANONIQUE: "canonique",
    EXPLORATOIRE: "exploratoire",
    ENTREE_DIFF: "entrée de différentiel",
}

#: Nom de fichier, associé à son statut et à sa raison. L'ordre suit la lecture.
CARTES: dict[str, tuple[str, str]] = {
    "health_20260815.json": (
        CANONIQUE,
        "Configuration canonique : L1+L2+L3 avec solvabilité, canal direct_http:browser, "
        "contenus vérifiés, juge gemini-2.5-flash au seuil 0,5, a priori des praticiens "
        "inclus, date de référence gelée au 15/08/2026. C'est la carte du README, des "
        "figures et de l'export. Elle se rejoue hors ligne, sans appel réseau, par "
        "`python3 experiments/carte_canonique.py --check`.",
    ),
    "health_card_webvoyager_llm_20260816.json": (
        EXPLORATOIRE,
        "Même juge que la carte canonique, sans la couche de solvabilité et sans "
        "vérification des contenus, au 16/08/2026 : stabilité moyenne 0,638, notes "
        "A 239, B 155, C 180, D 69. Ses chiffres ne se comparent pas à ceux de la carte "
        "canonique, où la solvabilité déplace 41 tâches de A vers des notes inférieures.",
    ),
    "health_card_webvoyager_20260816.json": (
        EXPLORATOIRE,
        "Backend d'ambiguïté `tfidf+logreg` entraîné sur les 139 tâches annotées puis "
        "appliqué aux 643 : 21,6 % du corpus est noté in-sample, précision apparente "
        "0,964 contre 0,654 hors plis. Non citable.",
    ),
    "health_webvoyager_20260815.json": (
        EXPLORATOIRE,
        "Carte L1 seule (`bdoctor scan`), sans modèle de score : le score y vaut "
        "1 − max(risque), sans crédibilité de canal ni décote de fraîcheur. Régénérée le "
        "16/08/2026 avec l'échelle de notes unifiée, ce qui fait passer en C les 65 tâches "
        "que l'échelle héritée classait en D (A 509, B 61, C 73, D 0). Elle donne la "
        "prévalence par catégorie de la couche L1 ; sa distribution de notes ne décrit pas "
        "l'état du benchmark.",
    ),
    "card_direct_20260816.json": (
        ENTREE_DIFF,
        "Terme « après » du différentiel de canal (`diff_channel_artifact`). L1+L2 "
        "uniquement, canal HTTP direct. Elle existe pour être comparée à la carte "
        "navigateur cloud, comparaison que le garde-fou de comparabilité refuse.",
    ),
    "card_browsercloud_20260815.json": (
        ENTREE_DIFF,
        "Terme « avant » du différentiel de canal. 11 des 15 sites n'ont aucune mesure "
        "navigateur et sont notés A par défaut : les 127 « dégradations » du différentiel "
        "mesurent autant la couverture que le canal.",
    ),
    "card_l1_20240302.json": (
        ENTREE_DIFF,
        "Terme « avant » du différentiel temporel : le corpus d'origine évalué à sa date "
        "de publication (02/03/2024), L1 seule.",
    ),
    "card_l1_20260816.json": (
        ENTREE_DIFF,
        "Terme « après » du différentiel temporel, L1 seule au 16/08/2026. Son score "
        "diffère de celui de `health_webvoyager_20260815.json`, qui passe par le modèle "
        "`scoring` avec décote de fraîcheur et a priori des praticiens.",
    ),
    "card_magnitude_20250706.json": (
        ENTREE_DIFF,
        "Terme « avant » du différentiel de pourrissement des correctifs : le corpus "
        "corrigé par Magnitude, évalué à la date de sa publication (06/07/2025).",
    ),
    "card_magnitude_20260816.json": (
        ENTREE_DIFF,
        "Terme « après » du différentiel de pourrissement des correctifs, au 16/08/2026. "
        "L'écart avec `card_magnitude_20250706.json` mesure la dégradation des correctifs "
        "Magnitude depuis leur publication.",
    ),
}

#: Artefacts qui publient des tables de notes sans être des cartes de santé.
AUTRES: dict[str, tuple[str, str]] = {
    "scoring_model_20260816.json": (
        EXPLORATOIRE,
        "Tables de sensibilité (κ, agrégation, échelles) calculées sans la couche de "
        "solvabilité et sans vérification des contenus. La sensibilité à κ y donne "
        "D {53, 62, 69, 74, 144} ; dans la configuration canonique, la même sensibilité "
        "donne D {83, 100, 110, 113, 136, 177}. La table canonique est publiée dans "
        "`runs/carte_canonique_20260815.json`, section `sensibilite_kappa`.",
    ),
    "carte_canonique_20260815.json": (
        CANONIQUE,
        "Rejeu hors ligne de la carte canonique et de ses tables de sensibilité, produites "
        "dans la configuration canonique et dans elle seule, sans appel réseau.",
    ),
}


def stamp(path: Path, statut: str, raison: str) -> bool:
    """Ajoute (ou met à jour) le champ `statut_editorial`. Idempotent."""
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    nouveau = {
        "statut": statut,
        "mention": MENTION[statut],
        "raison": raison,
        "carte_de_reference": "runs/health_20260815.json",
        "index": "runs/CARTES.md",
    }
    if data.get("statut_editorial") == nouveau:
        return False
    # En tête du fichier, pour que le champ apparaisse avant les chiffres.
    data = {"statut_editorial": nouveau, **{k: v for k, v in data.items() if k != "statut_editorial"}}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def resume(path: Path, statut: str) -> str:
    """Une ligne de tableau : statut, configuration et distribution des notes."""
    d = json.loads(path.read_text(encoding="utf-8"))
    # Trois formats coexistent : la carte de `bdoctor audit` (meta/summary), le bulletin
    # L1 de `bdoctor scan` (summary à plat), et le rejeu canonique (resume/configuration).
    cfg = d.get("configuration_canonique") or {}
    s = d.get("summary") or d.get("resume") or {}
    meta = d.get("meta") or {}
    proto = meta.get("protocol") or d.get("protocol") or cfg or {}
    g = s.get("grades") or s.get("notes") or {}
    notes = " / ".join(str(g.get(x, 0)) for x in "ABCD") if g else "-"
    stab = s.get("mean_stability", s.get("stabilite_moyenne", "-"))
    date = (
        meta.get("generated_at")
        or s.get("generated_at")
        or cfg.get("date_de_reference")
        or d.get("reference_date")
        or "-"
    )
    couches = meta.get("layers") or cfg.get("couches") or d.get("layers_executed") or s.get("channels")
    conf = "+".join(couches) if couches else "-"
    if proto.get("l3_solvability") or cfg.get("l3_solvabilite"):
        conf += " +solv"
    backend = proto.get("l3_ambiguity_backend") or cfg.get("l3_ambiguity_backend")
    if backend:
        conf += ", " + backend.replace("llm-judge:", "")
    return f"| `{path.name}` | {LIBELLE[statut]} | {date} | {conf} | {stab} | {notes} |"


def main() -> int:
    modifies: list[str] = []
    lignes_par_statut: dict[str, list[str]] = {CANONIQUE: [], EXPLORATOIRE: [], ENTREE_DIFF: []}
    for nom, (statut, raison) in list(CARTES.items()) + list(AUTRES.items()):
        path = RUNS / nom
        if not path.exists():
            print(f"  ABSENT : {nom}")
            continue
        if stamp(path, statut, raison):
            modifies.append(nom)
        lignes_par_statut[statut].append(resume(path, statut))
        print(f"  {statut:<24} {nom}")

    index = [
        "# Les cartes de `runs/`",
        "",
        "Douze fichiers de `runs/` publient une distribution de notes : dix cartes de santé",
        "et deux artefacts de sensibilité. Une seule est citée dans le mémoire,",
        "`health_20260815.json`. Chaque JSON porte son statut et sa raison en tête de",
        "fichier, dans le champ `statut_editorial`. Cet index est écrit par",
        "`experiments/marquer_cartes.py`.",
        "",
        "| Fichier | Statut | Date | Configuration | Stabilité moyenne | A / B / C / D |",
        "|---|---|---|---|---:|---|",
        *lignes_par_statut[CANONIQUE],
        *lignes_par_statut[EXPLORATOIRE],
        *lignes_par_statut[ENTREE_DIFF],
        "",
        "## Configuration canonique",
        "",
        "Corpus `data/raw/webvoyager_original.jsonl`, 643 tâches, sha256 69b19fd8…c488.",
        "Date de référence gelée au 2026-08-15. Couches L1 + L2 + L3, solvabilité incluse.",
        "Canal L2 `direct_http:browser` (`http_datacenter`, κ = 0,40), contenus vérifiés.",
        "Backend d'ambiguïté `llm-judge:gemini-2.5-flash:rubric`, seuil 0,5. A priori des",
        "praticiens inclus dans le score publié. Échelle de notes A > 0,75, B > 0,50,",
        "C > 0,25, D ≤ 0,25.",
        "",
        "Le rejeu hors ligne de cette carte et de ses tables de sensibilité :",
        "",
        "```",
        "python3 experiments/carte_canonique.py --check",
        "```",
        "",
    ]
    (RUNS / "CARTES.md").write_text("\n".join(index), encoding="utf-8")
    print("\nIndex écrit : runs/CARTES.md")
    print(f"JSON estampillés (modifiés) : {len(modifies)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
