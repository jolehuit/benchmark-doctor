#!/usr/bin/env python3
"""Répare les corps réseau manquants d'une collecte navigateur, depuis les HAR conservés.

    python experiments/reparer_corps_reseau.py runs/matrice/browser_residential_p1.json \\
        --har runs/har

Pourquoi une réparation plutôt qu'une nouvelle campagne
------------------------------------------------------

La première passe a enregistré ``taille_corps_reseau = 0`` sur plusieurs sites : le
protocole de débogage de Chrome n'avait plus le corps du document en cache au moment où
il a été réclamé. Le classifieur, à qui l'on présentait alors un 2xx de zéro octet, a
conclu au `soft_404` — il a imputé au site une page morte là où la campagne avait raté sa
lecture.

Le corps n'est pourtant pas perdu : le HAR l'avait capté au vol et il dort dans
``runs/har/``. Le récupérer là plutôt que re-sonder les sites est à la fois plus honnête
et plus économe — re-solliciter quinze serveurs tiers pour retrouver une donnée qu'on
possède déjà serait du gaspillage, et cela remplacerait une observation de la bonne
minute par une observation d'une autre.

Le verdict principal de ces observations, qui porte sur le DOM rendu, n'est pas touché :
seule la mesure secondaire — la signature du corps que le serveur a réellement envoyé —
est recalculée.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matrice_lib as lib


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("fichier", type=Path)
    parseur.add_argument("--har", type=Path, default=Path("runs/har"))
    args = parseur.parse_args()

    contenu = json.loads(args.fichier.read_text(encoding="utf-8"))
    cellule = contenu.get("channel")
    passe = contenu.get("passe", 1)
    repares, echoues = [], []

    controles = []
    for observation in contenu.get("observations", []):
        meta = observation.get("meta", {})
        cle = str(meta.get("site", "")).lower().replace(" ", "_")
        chemin_har = args.har / f"{cellule}_{cle}_p{passe}.har"

        if meta.get("taille_corps_reseau"):
            # Corps déjà en main : rien à réparer, mais le contrôle sur le corps entier
            # reste à faire — c'est lui qui rattrape les interstitiels trop volumineux
            # pour que leur marqueur tienne dans l'extrait classifié.
            corps_entier, _ = lib.corps_document_depuis_har(
                chemin_har, observation.get("final_url")
            )
            source = corps_entier or meta.get("extrait_corps_reseau") or ""
            controle = lib.marqueur_defi_integral(source)
            meta["defi_dans_corps_reseau_integral"] = controle
            if controle["present"] and meta.get("signature_corps_reseau") == "ok":
                controles.append(
                    f"{meta.get('site')} : corps réseau classé `ok` alors qu'il porte "
                    f"{', '.join(controle['marqueurs'])}"
                )
            continue

        corps, taille = lib.corps_document_depuis_har(chemin_har, observation.get("final_url"))
        if not corps.strip():
            meta["signature_corps_reseau"] = None
            meta["vendor_corps_reseau"] = None
            meta["origine_corps_reseau"] = "indisponible"
            echoues.append(meta.get("site"))
            continue

        _, obs_reseau = lib.observation_navigateur(
            url=observation["url"],
            cellule=cellule,
            channel_name=observation["channel_name"],
            status=observation.get("status"),
            final_url=observation.get("final_url"),
            headers=observation.get("headers") or {},
            corps_reseau=corps,
            taille_reseau=taille,
            dom="",
            redirect_chain=observation.get("redirect_chain") or (),
        )
        verdict = lib.classify(obs_reseau)
        avant = meta.get("signature_corps_reseau")
        meta["signature_corps_reseau"] = verdict.signature.value
        meta["vendor_corps_reseau"] = verdict.vendor.value
        meta["taille_corps_reseau"] = taille
        meta["extrait_corps_reseau"] = obs_reseau.excerpt[:1200]
        meta["origine_corps_reseau"] = "har"
        meta["defi_dans_corps_reseau_integral"] = lib.marqueur_defi_integral(corps)
        repares.append(f"{meta.get('site')} : {avant} → {verdict.signature.value}")

    if repares or echoues:
        note = (
            f"Sur {len(repares) + len(echoues)} observations, le corps réseau n'a pas été "
            "rendu par le protocole de débogage lors de la collecte et a été relu dans le "
            f"HAR a posteriori ({len(repares)} récupérés, {len(echoues)} introuvables). Ces "
            "observations portent `meta.origine_corps_reseau` à `har` ou `indisponible`. Le "
            "verdict principal, qui porte sur le DOM rendu, n'est pas concerné."
        )
        limites = contenu.setdefault("limits", [])
        if note not in limites:   # le script est idempotent : on peut le rejouer
            limites.append(note)
    args.fichier.write_text(
        json.dumps(contenu, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    for ligne in repares:
        print(f"  réparé   {ligne}")
    for site in echoues:
        print(f"  introuvable dans le HAR : {site} → signature_corps_reseau = null")
    for ligne in controles:
        print(f"  CONTRADICTION  {ligne}")
    print(f"→ {args.fichier} ({len(repares)} réparés, {len(echoues)} indisponibles)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
