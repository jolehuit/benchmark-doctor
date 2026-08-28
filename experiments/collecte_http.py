#!/usr/bin/env python3
"""Collecte d'une cellule HTTP de la matrice — sans navigateur.

Sert deux cellules avec le même code, ce qui est le point : à moteur de rendu constant,
la seule chose qui change entre ``http_residential`` et ``http_datacenter`` est l'endroit
d'où sort le paquet IP.

    python experiments/collecte_http.py --cellule http_residential --passe 1 \\
        --sortie runs/matrice/http_residential_p1.json

Politesse : une requête par hôte toutes les 2 secondes, séquentiellement, une seule
requête de document par site et par passe, aucun réessai sur un code HTTP.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matrice_lib as lib


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument(
        "--cellule",
        choices=["http_residential", "http_datacenter"],
        required=True,
        help="cellule mesurée ; détermine le canal déclaré dans les observations",
    )
    parseur.add_argument("--passe", type=int, required=True, help="numéro de passe (1 ou 2)")
    parseur.add_argument("--sortie", type=Path, required=True)
    args = parseur.parse_args()

    canal = lib.canal_http(args.cellule)
    liste = lib.cibles()
    observations: list[dict] = []

    print(f"[{args.cellule}] passe {args.passe} — {len(liste)} URL", flush=True)
    for i, cible in enumerate(liste, 1):
        debut = time.monotonic()
        observation = canal.fetch(cible["url"])
        charge = lib.serialiser(
            observation,
            cellule=args.cellule,
            passe=args.passe,
            extras={"site": cible["site"], "hote": cible["hote"]},
        )
        observations.append(charge)
        print(
            f"  {i:2}/{len(liste)} {cible['site']:22} "
            f"{str(observation.status):>5} {charge['meta']['signature']:20} "
            f"{observation.body_size:>8} o  {time.monotonic() - debut:.1f}s",
            flush=True,
        )

    contenu = lib.entete(
        cellule=args.cellule,
        collector=(
            f"benchmark_doctor.channels.DirectHTTPChannel (profil « browser », "
            f"requests/{__import__('requests').__version__}). "
            "La machine d'exécution n'est pas devinée : elle est décrite par "
            "`environnement.origine_reseau`, relevé au moment de la collecte."
        ),
        method=(
            "requête HTTP GET unique par URL, en-têtes du profil « browser » du paquet "
            "(Chrome 128 de bureau), redirections suivies, corps lu puis décodé "
            "(Accept-Encoding sans Brotli), statut et en-têtes discriminants pris sur la "
            "réponse finale ; classification par benchmark_doctor.detectors.l2_liveness."
            "classify, le même code que la campagne du 15/08."
        ),
        limits=[
            "Une seule requête par URL et par passe : aucune moyenne, aucun vote. Un site "
            "qui alterne ses réponses est vu une fois, pas caractérisé.",
            "Le canal ne rend pas le JavaScript. Un site qui ne sert son contenu qu'après "
            "exécution apparaît vide ou en interstitiel — c'est la définition de la "
            "cellule, pas un défaut de la mesure, mais cela interdit d'en tirer un "
            "verdict sur ce que verrait un agent.",
            "`body_size` est la taille du corps décodé, plafonnée à 500 000 octets par le "
            "canal du paquet ; au-delà, la valeur déclarée par Content-Length est reprise.",
        ],
        extras={"passe": args.passe, "n_observations": len(observations)},
    )
    contenu["observations"] = observations

    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    args.sortie.write_text(
        json.dumps(contenu, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"→ {args.sortie} ({len(observations)} observations)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
