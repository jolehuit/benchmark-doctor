#!/usr/bin/env python3
"""Marque le statut éditorial de chaque carte de `runs/`, et écrit l'index `runs/CARTES.md`.

Le dépôt contient dix cartes de santé. Elles ne se contredisent pas : ce sont dix
configurations du même outil. Le danger n'est pas qu'elles existent, c'est qu'aucune ne
disait laquelle était la référence — si bien que le README publiait une carte pendant que
les tables de sensibilité publiaient une autre (`VERIFICATION.md` §C8).

Ce script ne recalcule rien. Il **estampille** : il ajoute à chaque JSON un champ
``statut_editorial`` disant si la carte est citable, et pourquoi. Il est idempotent.

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
    CANONIQUE: "carte de référence du mémoire — seule carte citable",
    EXPLORATOIRE: "configuration exploratoire, non citée",
    ENTREE_DIFF: (
        "entrée d'un différentiel, pas une carte de santé : ne pas citer ses "
        "distributions de notes comme un état du benchmark"
    ),
}

#: fichier -> (statut, raison). L'ordre est celui de la lecture, pas de l'alphabet.
CARTES: dict[str, tuple[str, str]] = {
    "health_20260815.json": (
        CANONIQUE,
        "Configuration canonique : L1+L2+L3 avec solvabilité, canal direct_http:browser, "
        "contenus vérifiés, juge gemini-2.5-flash seuil 0,5, a priori praticiens inclus, "
        "date de référence gelée au 15/08/2026. C'est la carte du README, des figures et "
        "de l'export. Rejouable hors ligne et à coût nul par "
        "`python3 experiments/carte_canonique.py --check`.",
    ),
    "health_card_webvoyager_llm_20260816.json": (
        EXPLORATOIRE,
        "Même juge que la carte canonique mais SANS la couche de solvabilité et SANS "
        "vérification des contenus, au 16/08. C'est la carte du rapport 5 (stabilité "
        "0,638 · A 239 B 155 C 180 D 69). Ses chiffres ne se mélangent pas à ceux du "
        "README : la solvabilité déplace 41 tâches de A vers des notes inférieures.",
    ),
    "health_card_webvoyager_20260816.json": (
        EXPLORATOIRE,
        "Backend d'ambiguïté `tfidf+logreg`, entraîné sur les 139 tâches annotées puis "
        "appliqué aux 643 : 21,6 % du corpus est noté in-sample, à une précision apparente "
        "de 0,964 contre 0,654 hors plis (`VERIFICATION.md` §C13). Non citable, quel que "
        "soit le chiffre.",
    ),
    "health_webvoyager_20260815.json": (
        EXPLORATOIRE,
        "Carte L1 seule (`bdoctor scan`), sans modèle de score : le score y vaut "
        "1 − max(risque), sans crédibilité de canal ni décote de fraîcheur. Régénérée le "
        "16/08 avec l'échelle de notes unifiée — les 65 tâches que l'échelle héritée "
        "classait en D sont désormais en C (A 509 · B 61 · C 73 · D 0). Utile pour la "
        "prévalence par catégorie de la couche L1, jamais comme état du benchmark.",
    ),
    "card_direct_20260816.json": (
        ENTREE_DIFF,
        "Terme « après » du différentiel de canal (`diff_channel_artifact`). L1+L2 "
        "uniquement, canal HTTP direct. Sa seule fonction est d'être comparée à la carte "
        "navigateur cloud pour montrer que le garde-fou de comparabilité refuse la "
        "comparaison.",
    ),
    "card_browsercloud_20260815.json": (
        ENTREE_DIFF,
        "Terme « avant » du même différentiel. Attention : 11 des 15 sites n'ont AUCUNE "
        "mesure navigateur et sont notés A par défaut (`VERIFICATION.md` §C6). Les 127 "
        "« dégradations » du différentiel mesurent autant la couverture que le canal.",
    ),
    "card_l1_20240302.json": (
        ENTREE_DIFF,
        "Terme « avant » du différentiel temporel : le corpus d'origine évalué à sa date "
        "de publication (02/03/2024), L1 seule.",
    ),
    "card_l1_20260816.json": (
        ENTREE_DIFF,
        "Terme « après » du différentiel temporel, L1 seule au 16/08/2026. Son score "
        "n'est pas celui de `health_webvoyager_20260815.json` : celui-ci passe par le "
        "modèle `scoring` (décote de fraîcheur, a priori), celui-là non.",
    ),
    "card_magnitude_20250706.json": (
        ENTREE_DIFF,
        "Terme « avant » du différentiel de pourrissement des correctifs : le corpus "
        "corrigé par Magnitude, évalué à la date de sa publication.",
    ),
    "card_magnitude_20260816.json": (
        ENTREE_DIFF,
        "Terme « après » du même différentiel. L'écart entre les deux est le résultat "
        "« les correctifs pourrissent », le plus solide du dossier.",
    ),
}

#: Artefacts qui ne sont pas des cartes mais qui publient des tables de notes, et qui ont
#: déjà été confondus avec la carte canonique.
AUTRES: dict[str, tuple[str, str]] = {
    "scoring_model_20260816.json": (
        EXPLORATOIRE,
        "Tables de sensibilité (κ, agrégation, échelles) calculées SANS la couche de "
        "solvabilité et SANS vérification des contenus. C'est la source de la table "
        "κ → D {53, 62, 69, 74, 144} du rapport 5. **Ne jamais coller cette table à côté "
        "de la carte du README** : dans la configuration canonique, la même sensibilité "
        "donne D {83, 100, 110, 113, 136, 177}. La version canonique est dans "
        "`runs/carte_canonique_20260815.json`.",
    ),
    "carte_canonique_20260815.json": (
        CANONIQUE,
        "Rejeu hors ligne de la carte canonique et ses tables de sensibilité, produites "
        "dans la configuration canonique et dans elle seule. 0 appel réseau, 0,00 $.",
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
        "pose_le": "2026-08-16",
    }
    if data.get("statut_editorial") == nouveau:
        return False
    # En tête du fichier : un lecteur qui ouvre le JSON doit le voir avant les chiffres.
    data = {"statut_editorial": nouveau, **{k: v for k, v in data.items() if k != "statut_editorial"}}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def resume(path: Path) -> str:
    """Une ligne de tableau : configuration et distribution des notes."""
    d = json.loads(path.read_text(encoding="utf-8"))
    # Trois formats coexistent : la carte de `bdoctor audit` (meta/summary), le bulletin
    # L1 de `bdoctor scan` (summary à plat), et le rejeu canonique (resume/configuration).
    cfg = d.get("configuration_canonique") or {}
    s = d.get("summary") or d.get("resume") or {}
    meta = d.get("meta") or {}
    proto = meta.get("protocol") or d.get("protocol") or cfg or {}
    g = s.get("grades") or s.get("notes") or {}
    notes = " / ".join(str(g.get(x, 0)) for x in "ABCD") if g else "—"
    stab = s.get("mean_stability", s.get("stabilite_moyenne", "—"))
    date = (
        meta.get("generated_at")
        or s.get("generated_at")
        or cfg.get("date_de_reference")
        or d.get("reference_date")
        or "—"
    )
    couches = meta.get("layers") or cfg.get("couches") or d.get("layers_executed") or s.get("channels")
    conf = "+".join(couches) if couches else "—"
    if proto.get("l3_solvability") or cfg.get("l3_solvabilite"):
        conf += " +solv"
    backend = proto.get("l3_ambiguity_backend") or cfg.get("l3_ambiguity_backend")
    if backend:
        conf += f" · {backend.replace('llm-judge:', '')}"
    return f"| `{path.name}` | {date} | {conf} | {stab} | {notes} |"


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
        lignes_par_statut[statut].append(resume(path))
        print(f"  {statut:<24} {nom}")

    index = [
        "# Les cartes de `runs/` — laquelle citer",
        "",
        "Ce dépôt contient dix cartes de santé et deux artefacts de sensibilité. Elles ne se",
        "contredisent pas : ce sont des **configurations différentes du même outil**. Le",
        "problème corrigé le 16/08/2026 n'était pas un problème de calcul mais de rédaction —",
        "aucune n'était déclarée comme la référence, et le README publiait une carte pendant",
        "que les tables de sensibilité en publiaient une autre (`VERIFICATION.md` §C8).",
        "",
        "**Une seule carte est citable dans le mémoire.** Les autres sont sur le disque parce",
        "qu'elles servent à quelque chose — un différentiel, une ablation — pas parce qu'elles",
        "sont des états concurrents du benchmark.",
        "",
        "Chaque JSON porte désormais son propre verdict dans un champ `statut_editorial` en",
        "tête de fichier. Cet index est écrit par `experiments/marquer_cartes.py`.",
        "",
        "## 1. Carte canonique — la seule citable",
        "",
        "| Fichier | Date | Configuration | Stabilité ⌀ | A / B / C / D |",
        "|---|---|---|---:|---|",
        *lignes_par_statut[CANONIQUE],
        "",
        "Configuration, en toutes lettres : corpus `data/raw/webvoyager_original.jsonl`",
        "(643 tâches, sha256 69b19fd8…c488) · date de référence **gelée au 2026-08-15** ·",
        "couches **L1 + L2 + L3, solvabilité incluse** · canal L2 `direct_http:browser`",
        "(`http_datacenter`, κ = 0,40) · contenus vérifiés · backend d'ambiguïté",
        "**`llm-judge:gemini-2.5-flash:rubric`, seuil 0,5** · a priori des praticiens inclus",
        "dans le score publié · échelle de notes **A > 0,75 · B > 0,50 · C > 0,25 · D ≤ 0,25**.",
        "",
        "Elle se rejoue hors ligne, sans un appel réseau et sans un centime :",
        "",
        "```",
        "python3 experiments/carte_canonique.py --check",
        "```",
        "",
        "## 2. Configurations exploratoires — non citées",
        "",
        "| Fichier | Date | Configuration | Stabilité ⌀ | A / B / C / D |",
        "|---|---|---|---:|---|",
        *lignes_par_statut[EXPLORATOIRE],
        "",
        "## 3. Entrées de différentiels — ce ne sont pas des cartes de santé",
        "",
        "Ces cartes existent pour être **comparées entre elles**. Leur distribution de notes",
        "n'a pas de sens isolément : elle décrit un corpus partiel (L1 seule) ou un canal",
        "partiel (navigateur cloud, 4 sites mesurés sur 15).",
        "",
        "| Fichier | Date | Configuration | Stabilité ⌀ | A / B / C / D |",
        "|---|---|---|---:|---|",
        *lignes_par_statut[ENTREE_DIFF],
        "",
        "## 4. Le piège à éviter, nommément",
        "",
        "Coller dans le même paragraphe « stabilité moyenne 0,585 » (carte canonique) et",
        "« κ = 1 → 144 tâches en note D » (table du rapport 5) est **factuellement faux** :",
        "les deux chiffres viennent de configurations différentes. Dans la configuration",
        "canonique, κ = 1 donne **177** tâches en D. La table canonique est publiée dans",
        "`runs/carte_canonique_20260815.json`, section `sensibilite_kappa`.",
        "",
    ]
    (RUNS / "CARTES.md").write_text("\n".join(index), encoding="utf-8")
    print(f"\nIndex écrit : runs/CARTES.md")
    print(f"JSON estampillés (modifiés) : {len(modifies)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
