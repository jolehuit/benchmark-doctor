#!/usr/bin/env python3
"""Consolide les cellules de la campagne en un seul fichier de run.

    python experiments/consolider_matrice.py --runs runs/matrice \\
        --sortie runs/l2_matrice_canaux_20260816.json

Les cellules sont collectées séparément, sur deux machines et à deux moments : c'est la
seule façon de mesurer une origine réseau. Elles n'ont pourtant de sens qu'ensemble, et un
lecteur qui veut contredire le rapport doit pouvoir ouvrir un fichier, pas huit. Ce script
les réunit sans rien recalculer : les verdicts, les extraits et les horodatages sont ceux
qu'a produits la collecte.

Les limites déclarées par chaque cellule sont reprises, préfixées du nom de la cellule.
Aucune n'est résumée ni écartée : une limite qu'on agrège est une limite qu'on perd.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matrice_lib as lib

ORDRE = ["http_datacenter", "http_residential", "browser_residential", "browser_datacenter"]


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--runs", type=Path, default=Path("runs/matrice"))
    parseur.add_argument("--sortie", type=Path, required=True)
    args = parseur.parse_args()

    observations: list[dict] = []
    limites: list[str] = []
    cellules: dict[str, dict] = {}
    collectes: list[str] = []

    fichiers = [
        f
        for f in sorted(args.runs.glob("*.json"))
        if "analyse" not in f.name and "_confine" not in f.name
    ]
    for chemin in fichiers:
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
        if "observations" not in contenu:
            continue
        cellule = contenu.get("channel", "?")
        passe = contenu.get("passe")
        observations.extend(contenu["observations"])
        collectes.append(contenu.get("collected_at", "?"))
        cellules.setdefault(cellule, {})[f"passe{passe}"] = {
            "collected_at": contenu.get("collected_at"),
            "collector": contenu.get("collector"),
            "method": contenu.get("method"),
            "environnement": contenu.get("environnement"),
            "parametres": contenu.get("parametres"),
            "n_observations": len(contenu["observations"]),
            "fichier": f"matrice/{chemin.name}",
        }
        for limite in contenu.get("limits", []):
            marquee = f"[{cellule}, passe {passe}] {limite}"
            if marquee not in limites:
                limites.append(marquee)

    observations.sort(key=lambda o: (o["meta"].get("passe", 0), ORDRE.index(o["channel"]) if o["channel"] in ORDRE else 9, o["url"]))

    contenu = {
        "collected_at": max(collectes) if collectes else None,
        "campagne": "matrice des canaux (moteur de rendu × origine réseau)",
        "collector": (
            "benchmark-doctor / experiments/campagne_matrice.sh — cellules résidentielles "
            "depuis une machine personnelle (macOS, AS12322 Free SAS, France), cellules "
            "datacenter depuis un serveur loué (Ubuntu, AS16276 OVH SAS, France) ; canal "
            "HTTP par benchmark_doctor.channels.DirectHTTPChannel, canal navigateur par "
            "agent-browser 0.34.0 pilotant Google Chrome for Testing 148"
        ),
        "method": (
            "Pour les cellules HTTP : une requête GET par URL, profil d'en-têtes « browser » "
            "du paquet, redirections suivies, statut et en-têtes discriminants pris sur la "
            "réponse finale, corps décodé. Pour les cellules navigateur : une navigation de "
            "document par URL dans une session Chrome neuve et refermée, mode avec fenêtre, "
            "User-Agent par défaut du navigateur, 6 s d'attente après chargement pour "
            "laisser un défi JavaScript se résoudre ; le statut et les en-têtes viennent de "
            "la dernière requête de type Document, le corps réseau de `network request "
            "<id>` ou du HAR, le DOM rendu de `get html body`. Dans les quatre cellules, la "
            "signature est produite par benchmark_doctor.detectors.l2_liveness.classify, "
            "sans modification : c'est ce qui rend les cellules comparables entre elles et "
            "comparables à la campagne du 15/08."
        ),
        "plan": {
            "facteurs": {
                "moteur_de_rendu": ["aucun (client HTTP)", "navigateur réel"],
                "origine_reseau": ["datacenter", "résidentielle"],
            },
            "cellules": lib.FACTEURS,
            "note_nomenclature": (
                "Les noms de cellules sont ceux du plan d'expérience. L'énumération "
                "`benchmark_doctor.models.Channel`, écrite avant ce plan, nomme "
                "`browser_local` et `browser_cloud` ce que le plan appelle "
                "`browser_residential` et `browser_datacenter` : elle décrit où tourne le "
                "navigateur, le plan décrit d'où sort le paquet IP. Chaque observation "
                "porte les deux noms, `channel` et `meta.channel_enum`. L'énumération du "
                "paquet n'a pas été modifiée, pour ne toucher à aucun chiffre publié."
            ),
        },
        "verdicts": {
            "champ_principal": "meta.signature",
            "note": (
                "Pour les cellules navigateur, `meta.signature` classe le DOM rendu, "
                "c'est-à-dire ce que verrait un agent, et `meta.signature_corps_reseau` "
                "classe le corps envoyé par le serveur, seul terme comparable au canal "
                "HTTP. Les deux sont conservés parce qu'ils divergent, et leur divergence "
                "est un résultat de la campagne."
            ),
        },
        "cellules": cellules,
        "n_observations": len(observations),
        "limits": limites,
        "observations": observations,
    }

    args.sortie.write_text(
        json.dumps(contenu, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"→ {args.sortie}")
    print(f"  {len(observations)} observations, {len(cellules)} cellules, {len(limites)} limites")
    for cellule, passes in cellules.items():
        detail = ", ".join(f"{p} : {b['n_observations']}" for p, b in sorted(passes.items()))
        print(f"  {cellule:22} {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
