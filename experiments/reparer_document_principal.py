#!/usr/bin/env python3
"""Recalcule le document principal d'une collecte navigateur, depuis les HAR conservés.

    python experiments/reparer_document_principal.py runs/matrice/browser_residential_p1.json \\
        --har runs/har

Le défaut réparé
----------------

La première version du collecteur retenait la **dernière** requête de type Document comme
document principal de la page. Une page moderne en charge plusieurs : bandeau de
consentement, iframe de mesure publicitaire, ancre reCAPTCHA. Vérifié sur les HAR de la
passe 1, le document ainsi retenu pour Booking depuis le centre de données était
``ep2.adtrafficquality.google/sodar/...``, et pour ESPN en résidentiel une ancre
reCAPTCHA de Google. Le statut, les en-têtes et le corps publiés pour ces observations
appartenaient donc à un tiers, et non au site mesuré.

Le statut entre dans la classification. Une observation dont le statut vient d'une iframe
qui répond 200 peut être classée `ok` alors que le site a répondu 403. Ce script relit
donc le HAR, applique la règle corrigée, et **reclassifie** l'observation avec le statut
et les en-têtes rétablis. Le DOM rendu, lui, n'est pas concerné : il a toujours été celui
de la page principale.

Aucune requête réseau n'est émise : tout est relu dans les preuves déjà conservées.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matrice_lib as lib


def _document_principal(entrees: list[dict], url_finale: str) -> dict | None:
    """Même règle que le collecteur corrigé, appliquée aux entrées d'un HAR."""
    documents = [e for e in entrees if str(e.get("_resourceType", "")).lower() == "document"]
    if not documents:
        return None
    exact = [e for e in documents if e.get("request", {}).get("url") == url_finale]
    if exact:
        return exact[-1]
    hote = urlsplit(url_finale).netloc.lower()
    memes = [
        e
        for e in documents
        if urlsplit(str(e.get("request", {}).get("url", ""))).netloc.lower() == hote
    ]
    if memes:
        return memes[-1]
    return documents[0]


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("fichier", type=Path)
    parseur.add_argument("--har", type=Path, default=Path("runs/har"))
    args = parseur.parse_args()

    contenu = json.loads(args.fichier.read_text(encoding="utf-8"))
    cellule = contenu.get("channel")
    passe = contenu.get("passe", 1)
    corrections: list[str] = []
    intacts = 0

    for observation in contenu.get("observations", []):
        meta = observation.get("meta", {})
        site = meta.get("site", "")
        cle = str(site).lower().replace(" ", "_")
        chemin_har = args.har / f"{cellule}_{cle}_p{passe}.har"
        if not chemin_har.exists():
            continue
        har = json.loads(chemin_har.read_text(encoding="utf-8"))
        entrees = har.get("log", {}).get("entries", [])
        url_finale = observation.get("final_url") or observation["url"]
        principal = _document_principal(entrees, url_finale)
        if principal is None:
            continue

        url_doc = principal.get("request", {}).get("url")
        statut = principal.get("response", {}).get("status")
        entetes = {
            e.get("name", "").lower(): e.get("value", "")
            for e in principal.get("response", {}).get("headers", [])
        }
        corps = (principal.get("response", {}).get("content", {}) or {}).get("text") or ""
        taille = (principal.get("response", {}).get("content", {}) or {}).get("size") or len(
            corps.encode("utf-8")
        )

        ancien_statut = observation.get("status")
        ancienne_signature = meta.get("signature")

        # Le DOM n'a pas bougé : on le rejoue tel qu'il a été enregistré, avec le statut
        # et les en-têtes rétablis. `excerpt` porte déjà le DOM nettoyé et borné.
        obs_dom = lib.Observation(
            url=observation["url"],
            channel=lib.CELLULES[cellule],
            channel_name=observation["channel_name"],
            status=statut,
            final_url=url_finale,
            body_size=observation.get("body_size", 0),
            headers=entetes,
            excerpt=observation.get("excerpt", ""),
            redirect_chain=observation.get("redirect_chain") or (),
            elapsed_ms=observation.get("elapsed_ms"),
            error=observation.get("error"),
        )
        verdict = lib.classify(obs_dom)

        _, obs_reseau = lib.observation_navigateur(
            url=observation["url"],
            cellule=cellule,
            channel_name=observation["channel_name"],
            status=statut,
            final_url=url_finale,
            headers=entetes,
            corps_reseau=corps,
            taille_reseau=taille,
            dom="",
            redirect_chain=observation.get("redirect_chain") or (),
        )
        verdict_reseau = lib.classify(obs_reseau) if corps.strip() else None

        observation["status"] = statut
        observation["headers"] = dict(obs_dom.headers)
        meta["signature"] = verdict.signature.value
        meta["vendor"] = verdict.vendor.value
        meta["confidence"] = verdict.confidence
        meta["rationale"] = verdict.rationale
        meta["document_principal_url"] = url_doc
        meta["signature_corps_reseau"] = (
            verdict_reseau.signature.value if verdict_reseau else None
        )
        meta["vendor_corps_reseau"] = verdict_reseau.vendor.value if verdict_reseau else None
        meta["taille_corps_reseau"] = taille if corps.strip() else 0
        meta["extrait_corps_reseau"] = obs_reseau.excerpt[:1200]
        meta["origine_corps_reseau"] = "har" if corps.strip() else "indisponible"
        meta["defi_dans_corps_reseau_integral"] = lib.marqueur_defi_integral(corps)

        if statut != ancien_statut or verdict.signature.value != ancienne_signature:
            corrections.append(
                f"{site} : statut {ancien_statut} → {statut}, "
                f"signature {ancienne_signature} → {verdict.signature.value} "
                f"(document retenu : {url_doc[:70]})"
            )
        else:
            intacts += 1

    note = (
        "Le document principal a été recalculé a posteriori depuis les HAR : la première "
        "version du collecteur retenait la dernière requête de type Document, ce qui "
        "attrapait parfois une iframe tierce (consentement, mesure publicitaire, ancre "
        "reCAPTCHA) et publiait son statut à la place de celui du site. La règle corrigée "
        "retient l'URL exacte de la page finale, à défaut le dernier document du même "
        "hôte, à défaut la navigation initiale. `meta.document_principal_url` porte le "
        "document retenu pour chaque observation."
    )
    limites = contenu.setdefault("limits", [])
    if note not in limites:
        limites.append(note)

    args.fichier.write_text(
        json.dumps(contenu, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for ligne in corrections:
        print(f"  CORRIGÉ  {ligne}")
    print(f"→ {args.fichier} ({len(corrections)} corrigées, {intacts} inchangées)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
