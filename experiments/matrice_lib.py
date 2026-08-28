"""Socle commun de la campagne « matrice des canaux ».

Pourquoi ce module existe plutôt qu'un script autonome
------------------------------------------------------

La campagne doit produire des verdicts *comparables* à ceux déjà publiés dans
``runs/l2_probe_20260815.json``. Réimplémenter les règles de classification aurait suffi
à ruiner la comparaison : deux implémentations d'un même arbre de décision divergent au
premier cas limite, et l'écart mesuré entre canaux serait alors indiscernable d'un écart
entre classifieurs.

Ce module n'implémente donc **aucune règle**. Il importe ``benchmark_doctor`` et appelle
`l2_liveness.classify` — le même code, sur les quatre cellules. Tout ce qu'il ajoute est
de la plomberie : nommage des cellules, sérialisation au schéma des runs existants, et
conversion d'une capture de navigateur en `Observation`.

Nommage des cellules
--------------------

Le plan d'expérience croise deux facteurs — moteur de rendu et origine réseau — et donne
quatre cellules. L'énumération ``Channel`` du paquet, écrite avant ce plan, ne les nomme
pas ainsi : elle connaît ``browser_local`` et ``browser_cloud``, qui décrivent *où tourne
le navigateur* et non *d'où sort le paquet IP*. Les deux vocabulaires se recouvrent sans
se confondre.

Plutôt que de modifier l'énumération du paquet — ce qui toucherait au code sur lequel les
chiffres publiés reposent — la correspondance est explicite ici, et chaque observation
sérialisée porte les deux noms : ``channel`` (le nom de cellule du plan) et
``meta.channel_enum`` (le nom du paquet). Aucune information n'est perdue, aucun chiffre
existant n'est touché.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

_RACINE = Path(__file__).resolve().parent.parent
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from benchmark_doctor.channels import (  # noqa: E402
    BROWSER_HEADERS,
    DISCRIMINATING_HEADERS,
    DirectHTTPChannel,
    Observation,
    _clean_excerpt,
)
from benchmark_doctor.detectors.l2_liveness import classify  # noqa: E402
from benchmark_doctor.models import Channel  # noqa: E402

# Les quatre cellules du plan

#: Nom de cellule → canal générique du paquet. La cellule est le vocabulaire du plan
#: d'expérience (moteur × origine) ; le canal est le vocabulaire du paquet.
CELLULES: dict[str, Channel] = {
    "http_datacenter": Channel.HTTP_DATACENTER,
    "http_residential": Channel.HTTP_RESIDENTIAL,
    "browser_residential": Channel.BROWSER_LOCAL,
    "browser_datacenter": Channel.BROWSER_CLOUD,
}

#: Les deux facteurs croisés, pour l'analyse.
FACTEURS: dict[str, dict[str, str]] = {
    "http_datacenter": {"moteur": "aucun", "origine": "datacenter"},
    "http_residential": {"moteur": "aucun", "origine": "residentielle"},
    "browser_residential": {"moteur": "navigateur", "origine": "residentielle"},
    "browser_datacenter": {"moteur": "navigateur", "origine": "datacenter"},
}

#: Longueur de l'extrait conservé **et classifié**. Le canal de référence du 15/08 en
#: retenait 3 000 ; la campagne en retient 4 000 et vérifie séparément (cf.
#: `analyse_matrice.py`) qu'aucun verdict ne dépend de ce choix. La longueur d'extrait
#: est un paramètre de mesure : un marqueur d'éditeur enfoui au-delà de la coupure fait
#: passer un interstitiel pour une page normale.
EXCERPT_CHARS = 4_000

#: Délai minimal entre deux requêtes vers le même hôte. Deux fois la valeur du canal de
#: référence : la campagne sort par l'IP personnelle d'une machine résidentielle, dont un
#: bannissement serait définitif et hors du périmètre du mémoire.
MIN_INTERVAL_S = 2.0

TIMEOUT_S = 25.0
RETRIES_RESEAU = 1


def cibles(chemin: Path | None = None) -> list[dict[str, str]]:
    """Charge les 15 URL de la campagne."""
    chemin = chemin or Path(__file__).resolve().parent / "cibles_matrice.json"
    return json.loads(chemin.read_text(encoding="utf-8"))["cibles"]


# Sérialisation


def serialiser(
    observation: Observation,
    *,
    cellule: str,
    passe: int,
    extras: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Sérialise une observation au schéma des runs existants, verdict inclus.

    Le verdict n'est pas recalculé ailleurs : il est produit ici, par le classifieur du
    paquet, et déposé dans ``meta.signature``. C'est la garantie que les quatre cellules
    ont été jugées par le même code.
    """
    verdict = classify(observation)
    charge = observation.to_dict()
    charge["channel"] = cellule
    charge["meta"] = {
        **dict(observation.meta),
        **dict(extras or {}),
        "signature": verdict.signature.value,
        "vendor": verdict.vendor.value,
        "confidence": verdict.confidence,
        "rationale": verdict.rationale,
        "channel_enum": observation.channel.value,
        "moteur": FACTEURS[cellule]["moteur"],
        "origine": FACTEURS[cellule]["origine"],
        "passe": passe,
    }
    return charge


def _sortie_git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=10, cwd=_RACINE
        ).stdout.strip() or None
    except Exception:
        return None


def ip_publique(timeout: float = 15.0) -> dict[str, Any]:
    """Relève l'ASN et le pays de l'IP de sortie — la variable indépendante du plan.

    L'IP elle-même n'est **pas** enregistrée : c'est une donnée personnelle, et l'ASN
    suffit à qualifier l'origine (FAI grand public contre hébergeur). Une campagne dont
    le facteur principal est l'origine réseau doit néanmoins prouver cette origine,
    sinon le facteur n'est pas documenté.
    """
    import urllib.request

    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=timeout) as rep:
            data = json.loads(rep.read().decode("utf-8"))
        brute = data.get("ip", "")
        return {
            "asn_org": data.get("org"),
            "pays": data.get("country"),
            "region": data.get("region"),
            "ip_prefixe": ".".join(brute.split(".")[:2]) + ".x.x" if "." in brute else None,
            "hebergeur_declare": bool(data.get("hosting")),
        }
    except Exception as exc:
        return {"erreur": f"{type(exc).__name__}: {exc}"[:200]}


def entete(
    *,
    cellule: str,
    collector: str,
    method: str,
    limits: Iterable[str],
    extras: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """En-tête d'un fichier de run : provenance complète et limites déclarées."""
    return {
        "collected_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "channel": cellule,
        "collector": collector,
        "method": method,
        "environnement": {
            "systeme": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "python": platform.python_version(),
            "origine_reseau": ip_publique(),
            "proxy_egress": bool(
                os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
            ),
            "commit": _sortie_git("rev-parse", "--short", "HEAD"),
        },
        "parametres": {
            "excerpt_chars": EXCERPT_CHARS,
            "min_interval_s": MIN_INTERVAL_S,
            "timeout_s": TIMEOUT_S,
            "retries_reseau": RETRIES_RESEAU,
            "retries_sur_code_http": 0,
        },
        "limits": list(limits),
        **dict(extras or {}),
    }


# Canal HTTP


def canal_http(cellule: str) -> DirectHTTPChannel:
    """Le canal HTTP de la campagne, réglé à l'identique du canal de référence.

    Seuls deux paramètres diffèrent de la campagne du 15/08 : l'origine réseau — c'est
    le facteur étudié — et le délai entre requêtes, porté de 1 s à 2 s. Le profil
    d'en-têtes, le délai d'attente, la politique de réessai et le traitement de
    l'encodage sont ceux du paquet, importés et non recopiés.
    """
    return DirectHTTPChannel(
        profile="browser",
        kind=CELLULES[cellule],
        timeout=TIMEOUT_S,
        excerpt_chars=EXCERPT_CHARS,
        min_interval=MIN_INTERVAL_S,
        retries=RETRIES_RESEAU,
        allow_redirects=True,
    )


# Canal navigateur


#: Corps de document conservé dans un HAR élagué, en caractères.
HAR_CORPS_DOCUMENT_MAX = 200_000

#: Bornes de la capture d'écran conservée.
CAPTURE_LARGEUR_MAX = 1_280
CAPTURE_HAUTEUR_MAX = 5_000
CAPTURE_QUALITE = 80


def corps_document_depuis_har(chemin: Path, url_finale: str | None) -> tuple[str, int]:
    """Récupère le corps du document principal dans le HAR.

    `network request <id>` ne rend pas toujours le corps : le protocole de débogage de
    Chrome libère les corps de réponse de son cache selon sa propre logique, et une page
    lourde ou redirigée revient parfois vide. Enregistrer un corps vide comme s'il venait
    du serveur serait une faute de mesure grave — le classifieur y lit un 2xx sans contenu
    et conclut à un `soft_404`, c'est-à-dire qu'il impute au site une page morte là où la
    campagne a simplement raté sa lecture. Le HAR, lui, a capté le corps au vol.

    Returns:
        (corps, taille en octets). ``("", 0)`` si le HAR ne le porte pas non plus.
    """
    if not chemin.exists():
        return "", 0
    try:
        har = json.loads(chemin.read_text(encoding="utf-8"))
    except Exception:
        return "", 0
    documents = [
        e
        for e in har.get("log", {}).get("entries", [])
        if str(e.get("_resourceType", "")).lower() == "document"
        and (e.get("response", {}).get("content", {}) or {}).get("text")
    ]
    if not documents:
        return "", 0
    # Même règle que `_document_principal` du collecteur : l'URL exacte, sinon le même
    # hôte, sinon la navigation initiale. Prendre le dernier document attraperait une
    # iframe tierce (consentement, mesure publicitaire, ancre reCAPTCHA) et attribuerait
    # son corps au site.
    from urllib.parse import urlsplit

    choisi = None
    if url_finale:
        for entree in reversed(documents):
            if entree.get("request", {}).get("url") == url_finale:
                choisi = entree
                break
        if choisi is None:
            hote = urlsplit(url_finale).netloc.lower()
            memes = [
                e
                for e in documents
                if urlsplit(str(e.get("request", {}).get("url", ""))).netloc.lower() == hote
            ]
            if memes:
                choisi = memes[-1]
    choisi = choisi or documents[0]
    contenu = choisi.get("response", {}).get("content", {})
    texte = contenu.get("text") or ""
    taille = contenu.get("size")
    if not isinstance(taille, int) or taille <= 0:
        taille = len(texte.encode("utf-8"))
    return texte, taille


def elaguer_har(chemin: Path) -> dict[str, Any]:
    """Élague un HAR pour qu'il tienne dans un dépôt, sans perdre ce qui prouve.

    Un HAR complet d'une page d'accueil moderne pèse plusieurs dizaines de mégaoctets,
    presque entièrement en images, polices et bundles JavaScript. Les verser dans un
    dépôt Git rendrait la preuve intransportable, donc inconsultable, donc inutile.

    Ce qui est conservé : **toutes** les requêtes, avec leur URL, leur méthode, leur
    statut, leurs en-têtes et leurs temps — c'est-à-dire tout ce sur quoi un tiers peut
    contredire la classification. Ce qui est vidé : le contenu des réponses autres que le
    document principal. Chaque entrée vidée porte la mention ``_content_elague`` avec la
    taille d'origine, pour qu'aucun lecteur ne prenne un corps absent pour un corps vide.
    """
    try:
        har = json.loads(chemin.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"elague": False, "erreur": f"{type(exc).__name__}: {exc}"[:200]}

    avant = chemin.stat().st_size
    entrees = har.get("log", {}).get("entries", [])
    videes = 0
    for entree in entrees:
        contenu = entree.get("response", {}).get("content", {})
        texte = contenu.get("text")
        if not texte:
            continue
        type_ressource = str(entree.get("_resourceType", "")).lower()
        if type_ressource == "document":
            if len(texte) > HAR_CORPS_DOCUMENT_MAX:
                contenu["text"] = texte[:HAR_CORPS_DOCUMENT_MAX]
                contenu["_content_tronque"] = {"taille_origine": len(texte)}
            continue
        contenu["text"] = ""
        contenu["_content_elague"] = {"taille_origine": len(texte)}
        videes += 1

    har.setdefault("log", {}).setdefault("_comment", "")
    har["log"]["_elagage"] = {
        "regle": (
            "corps conservés pour les entrées _resourceType=document (tronqués à "
            f"{HAR_CORPS_DOCUMENT_MAX} caractères) ; corps des sous-ressources vidés, "
            "en-têtes, statuts, URL et temps intégralement conservés"
        ),
        "entrees_totales": len(entrees),
        "entrees_corps_vide": videes,
        "octets_avant": avant,
    }
    chemin.write_text(json.dumps(har, ensure_ascii=False), encoding="utf-8")
    apres = chemin.stat().st_size
    return {
        "elague": True,
        "entrees": len(entrees),
        "octets_avant": avant,
        "octets_apres": apres,
    }


def compresser_capture(chemin_png: Path) -> Path | None:
    """Convertit une capture pleine page en JPEG borné, et retire le PNG.

    Une capture pleine page d'un site marchand dépasse dix mégaoctets. Ce que la capture
    doit prouver — « cette page était un interstitiel de vérification, pas le site » — se
    lit dans les premiers milliers de pixels et survit largement à une recompression.
    """
    try:
        from PIL import Image
    except ImportError:
        return chemin_png  # Pillow absent : on garde le PNG plutôt que rien
    if not chemin_png.exists():
        return None
    # Une capture pleine page d'un site marchand dépasse les 89 millions de pixels au-delà
    # desquels Pillow soupçonne une « decompression bomb » et refuse d'ouvrir le fichier.
    # Ici l'image vient de notre propre navigateur : le garde-fou n'a rien à protéger, et
    # le laisser actif ferait échouer la compression des seules pages assez longues pour
    # en avoir besoin.
    Image.MAX_IMAGE_PIXELS = None
    try:
        with Image.open(chemin_png) as image:
            image = image.convert("RGB")
            if image.height > CAPTURE_HAUTEUR_MAX:
                image = image.crop((0, 0, image.width, CAPTURE_HAUTEUR_MAX))
            if image.width > CAPTURE_LARGEUR_MAX:
                ratio = CAPTURE_LARGEUR_MAX / image.width
                image = image.resize(
                    (CAPTURE_LARGEUR_MAX, max(1, int(image.height * ratio))),
                    Image.LANCZOS,
                )
            chemin_jpg = chemin_png.with_suffix(".jpg")
            image.save(chemin_jpg, "JPEG", quality=CAPTURE_QUALITE, optimize=True)
        chemin_png.unlink()
        return chemin_jpg
    except Exception:
        return chemin_png


def marqueur_defi_integral(texte: str) -> dict[str, Any]:
    """Cherche un marqueur d'interstitiel dans le corps **entier**, pas dans l'extrait.

    Le classifieur du paquet ne lit que ``excerpt``, borné à quelques milliers de
    caractères. Ce choix était sûr en 2026 sur les interstitiels alors observés, qui
    pesaient de 600 à 4 000 octets. Il ne l'est plus : mesuré le 16/08, le défi Cloudflare
    Turnstile servi à ``allrecipes.com`` depuis un centre de données pèse **330 ko**, son
    titre est « Just a moment... » et son marqueur ``cf-turnstile`` tombe bien au-delà de
    la coupure. Le classifieur voit alors un corps 2xx volumineux sans marqueur et conclut
    `ok` : il déclare accessible une page qui n'est qu'une salle d'attente.

    Ce contrôle ne remplace pas le verdict — modifier le classifieur en cours de campagne
    rendrait les cellules incomparables. Il le contredit quand il a tort, et la
    contradiction est enregistrée.
    """
    from benchmark_doctor.detectors.l2_liveness import _CAPTCHA_TEXT, _CHALLENGE_TEXT

    aplati = " ".join((texte or "").split())
    marqueurs = []
    if _CHALLENGE_TEXT.search(aplati):
        marqueurs.append("challenge")
    if _CAPTCHA_TEXT.search(aplati):
        marqueurs.append("captcha")
    for jeton in ("cf-turnstile", "cf-chl-", "awswafcookiedomainlist", "__cf_chl", "px-captcha"):
        if jeton in aplati.lower():
            marqueurs.append(jeton)
    return {"marqueurs": sorted(set(marqueurs)), "present": bool(marqueurs)}


def diagnostic_dom(dom: str, titre: str | None) -> dict[str, Any]:
    """Constate factuellement ce que le navigateur affiche, sans passer par `classify`.

    Ce diagnostic existe à cause d'une limite réelle du classifieur, mise au jour par le
    banc local : la règle du code 202 (« un site ne sert pas son accueil en 202 ») est
    évaluée **avant** le corps et sans appel possible. Elle est juste pour un client HTTP,
    à qui le WAF sert effectivement un interstitiel. Elle devient fausse pour un
    navigateur qui a résolu le défi par calcul et affiche la vraie page sans nouvelle
    navigation : le code de la réponse initiale reste 202, et le verdict reste
    « refusé » alors que l'agent voit le site.

    Modifier le classifieur pour corriger cela reviendrait à changer les règles au milieu
    de la comparaison, et donc à rendre les quatre cellules incomparables. Le parti pris
    est l'inverse : le classifieur publié tranche, et ce diagnostic enregistre à côté ce
    que le navigateur affichait vraiment. Les désaccords entre les deux sont un résultat
    de la campagne, pas un défaut à masquer.
    """
    from benchmark_doctor.detectors.l2_liveness import (  # import local : symboles privés
        _CAPTCHA_TEXT,
        _CHALLENGE_TEXT,
    )

    aplati = " ".join((dom or "").split())
    taille = len((dom or "").encode("utf-8"))
    marqueur_defi = bool(_CHALLENGE_TEXT.search(aplati)) or bool(_CAPTCHA_TEXT.search(aplati))
    titre_utile = bool((titre or "").strip())
    return {
        # Un DOM vide est une lecture ratée, pas un site vide. Le signaler explicitement
        # évite qu'une analyse aval compte comme « refus » ce qui n'est qu'une panne de
        # capture — c'est exactement le genre de faux positif que la couche L2 du paquet
        # a été écrite pour empêcher, appliqué ici à notre propre outillage.
        "dom_valide": bool(aplati),
        "dom_taille": taille,
        "dom_titre_present": titre_utile,
        "dom_marqueur_defi": marqueur_defi,
        # Seuil repris de ANTIBOT_BODY_MAX (15 000 o) : au-delà, un corps 2xx est
        # considéré comme une vraie page par le paquet lui-même.
        "page_reelle_affichee": taille > 15_000 and titre_utile and not marqueur_defi,
    }


def observation_navigateur(
    *,
    url: str,
    cellule: str,
    channel_name: str,
    status: int | None,
    final_url: str | None,
    headers: Mapping[str, str],
    corps_reseau: str,
    taille_reseau: int,
    dom: str,
    redirect_chain: Iterable[int] = (),
    elapsed_ms: float | None = None,
    error: str | None = None,
    meta: Mapping[str, Any] | None = None,
) -> tuple[Observation, Observation]:
    """Construit les deux observations d'une capture de navigateur.

    Un navigateur produit **deux** corps là où un client HTTP n'en produit qu'un, et les
    confondre est l'erreur qui guette toute comparaison de canaux :

    - le *corps réseau* est ce que le serveur a envoyé pour le document principal. C'est
      le seul terme comparable au canal HTTP direct, puisque c'est le même objet ;
    - le *DOM rendu* est ce que le navigateur affiche après exécution du JavaScript.
      C'est ce que voit un agent web — et c'est là qu'un challenge résolu par calcul
      cesse d'être un interstitiel pour devenir la vraie page.

    Les deux sont donc classifiés séparément. Leur divergence n'est pas un défaut de
    mesure : c'est précisément l'effet que la campagne cherche à quantifier.

    Returns:
        (observation sur le DOM rendu, observation sur le corps réseau).
    """
    entetes = {
        k.lower(): v for k, v in dict(headers).items() if k.lower() in DISCRIMINATING_HEADERS
    }
    commun = dict(
        url=url,
        channel=CELLULES[cellule],
        channel_name=channel_name,
        status=status,
        final_url=final_url,
        headers=entetes,
        redirect_chain=tuple(redirect_chain),
        elapsed_ms=elapsed_ms,
        error=error,
    )
    obs_dom = Observation(
        **commun,
        body_size=len(dom.encode("utf-8")),
        excerpt=_clean_excerpt(dom, EXCERPT_CHARS),
        meta={**dict(meta or {}), "rendered": True, "corps": "dom_rendu"},
    )
    obs_reseau = Observation(
        **commun,
        body_size=taille_reseau,
        excerpt=_clean_excerpt(corps_reseau, EXCERPT_CHARS),
        meta={**dict(meta or {}), "rendered": False, "corps": "reseau_document"},
    )
    return obs_dom, obs_reseau


__all__ = [
    "CELLULES",
    "FACTEURS",
    "EXCERPT_CHARS",
    "MIN_INTERVAL_S",
    "cibles",
    "serialiser",
    "entete",
    "canal_http",
    "observation_navigateur",
    "classify",
    "Observation",
    "Channel",
    "BROWSER_HEADERS",
]
