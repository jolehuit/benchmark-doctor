#!/usr/bin/env python3
"""Collecte d'une cellule navigateur de la matrice — Chrome réel piloté par agent-browser.

    python experiments/collecte_navigateur.py --cellule browser_residential --passe 1 \\
        --sortie runs/matrice/browser_residential_p1.json \\
        --har runs/har --captures runs/captures

Ce que le script capture, et pourquoi trois fois plutôt qu'une
--------------------------------------------------------------

Une observation de navigateur n'est pas un objet unique. Le script conserve donc :

1. **le corps réseau du document** (`network request <id>` → ``responseBody``) — le seul
   terme directement comparable au canal HTTP, puisque c'est le même octet-flux ;
2. **le DOM rendu** (`get html body`) — ce que voit un agent web après exécution du
   JavaScript, donc après résolution éventuelle d'un défi anti-bot ;
3. **le HAR et une capture d'écran** — la preuve qu'un tiers peut rouvrir. C'est ce qui
   distingue cette campagne des quatre observations saisies à la main qu'elle remplace :
   une signature sans pièce jointe n'est pas vérifiable.

Le mode `--headed` n'est pas cosmétique. En mode sans affichage, Chrome annonce
``HeadlessChrome/148.0.0.0`` dans son User-Agent : mesurer ainsi, c'est se signaler comme
robot au moment même où l'on mesure la façon dont les sites traitent les robots, et
attribuer au moteur de rendu un effet qui vient de l'aveu. En mode avec fenêtre, l'agent
présente l'User-Agent authentique du navigateur — ni masqué, ni maquillé.

Discipline d'accès : une seule navigation de document par site et par passe, sessions
indépendantes et refermées, aucun clic, aucune saisie, aucune navigation interne. Le
confinement de domaines (`--confinement`) est disponible mais désactivé par défaut : il
fausse la mesure sur les sites dont le rendu dépend de ressources tierces (voir la classe
`Cli`). La contrainte tient donc au script, pas à un drapeau.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matrice_lib as lib

#: Délai laissé au navigateur après le chargement, avant lecture du DOM. Un défi
#: Cloudflare ou AWS WAF se résout en quelques secondes ; lire le DOM trop tôt le
#: capturerait dans son état d'interstitiel et attribuerait au moteur de rendu un échec
#: qui n'est qu'un défaut de patience.
ATTENTE_RESOLUTION_MS = 6_000

#: `robots.txt` d'arxiv.org déclare `Crawl-delay: 15` pour `User-agent: *`. Les autres
#: cibles n'en déclarent aucun pour `*` ; la campagne applique 2 s partout ailleurs.
DELAIS_PAR_HOTE = {"arxiv.org": 15.0}

TIMEOUT_COMMANDE_S = 120


class Cli:
    """Enveloppe du CLI : une session isolée par site, toujours refermée.

    Le confinement par `--allowed-domains` est optionnel, et ce n'est pas un relâchement
    de discipline : mesuré le 16/08, il **fabrique des refus**. `dictionary.cambridge.org`
    confiné à son seul hôte rend un DOM vide, que le classifieur prend pour un
    interstitiel ; le même site sans confinement rend 221 ko et son vrai titre. La page
    dépend de ressources tierces (bandeau de consentement, AMP) pour afficher son contenu,
    et les bloquer revient à mesurer le confinement plutôt que le site.

    La campagne conserve donc les deux mesures : sans confinement pour le verdict — un
    canal « navigateur » doit rendre ce qu'un navigateur rend — et avec confinement comme
    analyse de sensibilité. La contrainte d'accès, elle, ne repose pas sur ce drapeau mais
    sur le script : une seule navigation par site, aucun clic, aucune saisie, aucune
    navigation interne, sessions isolées et refermées.
    """

    def __init__(self, session: str, domaines: str | None, headed: bool = True) -> None:
        self.session = session
        self.domaines = domaines
        self.headed = headed

    def __call__(self, *args: str, json_sortie: bool = False) -> Any:
        commande = ["agent-browser", "--session", self.session]
        if self.headed:
            commande.append("--headed")
        if self.domaines:
            commande += ["--allowed-domains", self.domaines]
        if json_sortie:
            commande.append("--json")
        commande += [a for a in args]
        try:
            resultat = subprocess.run(
                commande, capture_output=True, text=True, timeout=TIMEOUT_COMMANDE_S
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"timeout CLI ({TIMEOUT_COMMANDE_S}s)"} if json_sortie else ""
        if not json_sortie:
            return resultat.stdout
        try:
            return json.loads(resultat.stdout)
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": (resultat.stderr or resultat.stdout or "sortie illisible")[:300],
            }

    def fermer(self) -> None:
        subprocess.run(
            ["agent-browser", "--session", self.session, "close"],
            capture_output=True, text=True, timeout=60,
        )


def _erreur_reseau(message: str) -> bool:
    """Distingue une panne de transport d'un refus applicatif.

    Un 403, un 402 ou un interstitiel sont des **données** : les réessayer reviendrait à
    insister jusqu'à obtenir la réponse qui arrange. Une socket coupée est du bruit, et
    mérite une seconde tentative — une seule.
    """
    bruit = (
        "err_connection", "err_timed_out", "err_name_not_resolved", "err_network",
        "err_socket", "err_address", "err_empty_response", "timeout", "net::err",
    )
    bas = (message or "").lower()
    return any(m in bas for m in bruit)


def _document_principal(documents: list[dict], url_finale: str) -> dict | None:
    """Choisit la requête de document qui est celle de la page, pas d'une iframe.

    Une page moderne charge plusieurs documents : bandeau de consentement, iframe de
    mesure publicitaire, ancre reCAPTCHA. Ils portent tous ``resourceType: Document``.
    Prendre le dernier, comme le faisait la première version de ce script, revient à
    publier le statut et les en-têtes d'un tiers en les attribuant au site. Vérifié sur
    les HAR de la passe 1 : le « document » retenu pour Booking depuis le centre de
    données était ``ep2.adtrafficquality.google/sodar/...``, et pour ESPN en résidentiel
    une ancre reCAPTCHA. Le statut 200 publié appartenait à ces tiers.

    La règle retenue, par ordre de préférence : l'URL exacte de la page finale, puis le
    dernier document du même hôte que la page finale, puis le premier document de la
    session, qui est la navigation initiale.
    """
    if not documents:
        return None
    from urllib.parse import urlsplit

    exact = [e for e in documents if e.get("url") == url_finale]
    if exact:
        return exact[-1]
    hote = urlsplit(url_finale).netloc.lower()
    meme_hote = [e for e in documents if urlsplit(str(e.get("url", ""))).netloc.lower() == hote]
    if meme_hote:
        return meme_hote[-1]
    return documents[0]


def sonder(
    cible: dict,
    cellule: str,
    passe: int,
    rep_har: Path,
    rep_cap: Path,
    confinement: bool = False,
) -> dict:
    """Sonde une URL et renvoie l'observation sérialisée (verdict DOM en tête)."""
    url, site, hote = cible["url"], cible["site"], cible["hote"]
    cle = site.lower().replace(" ", "_")
    suffixe = "_confine" if confinement else ""
    session = f"mat_{cellule}_{cle}_p{passe}{suffixe}"
    chemin_har = rep_har / f"{cellule}_{cle}_p{passe}{suffixe}.har"
    chemin_cap = rep_cap / f"{cellule}_{cle}_p{passe}{suffixe}.png"

    cli = Cli(session, hote if confinement else None)
    debut = time.monotonic()
    erreur: str | None = None
    try:
        cli("network", "har", "start", "--content", "text")
        ouverture = cli("open", url, json_sortie=True)
        if not ouverture.get("success"):
            message = str(ouverture.get("error") or "")
            if _erreur_reseau(message):
                time.sleep(3)
                ouverture = cli("open", url, json_sortie=True)
            if not ouverture.get("success"):
                erreur = message[:300]

        cli("wait", str(ATTENTE_RESOLUTION_MS))

        url_finale = (cli("get", "url", json_sortie=True).get("data") or {}).get("url")
        titre = (cli("get", "title", json_sortie=True).get("data") or {}).get("title")
        dom = (cli("get", "html", "body", json_sortie=True).get("data") or {}).get("html") or ""
        # Un DOM vide n'est presque jamais une observation : c'est une lecture ratée. Le
        # laisser passer produirait un faux verdict, et le pire de tous — le classifieur
        # voit un corps 2xx minuscule sans titre et conclut à l'interstitiel, c'est-à-dire
        # qu'il impute au site un défaut de la mesure. Une seconde lecture, puis l'aveu.
        if not dom.strip():
            time.sleep(3)
            dom = (cli("get", "html", "body", json_sortie=True).get("data") or {}).get("html") or ""
            if not dom.strip():
                erreur = (erreur or "") + " | DOM vide apres deux lectures : capture invalide"
        ua = (cli("eval", "navigator.userAgent", json_sortie=True).get("data") or {}).get("result")

        requetes = cli("network", "requests", "--type", "document", json_sortie=True)
        entrees = (requetes.get("data") or {}).get("requests") or []
        documents = [e for e in entrees if e.get("resourceType") == "Document"]
        principal = _document_principal(documents, url_finale or url)
        redirections = [
            int(e["status"]) for e in documents[:-1]
            if isinstance(e.get("status"), int) and 300 <= e["status"] < 400
        ]

        corps_reseau, taille_reseau = "", 0
        if principal and principal.get("requestId"):
            detail = cli("network", "request", str(principal["requestId"]), json_sortie=True)
            corps_reseau = (detail.get("data") or {}).get("responseBody") or ""
            taille_reseau = len(corps_reseau.encode("utf-8"))

        cli("screenshot", "--full", str(chemin_cap))
        cli("network", "har", "stop", str(chemin_har))
    finally:
        cli.fermer()

    # Repli sur le HAR quand le protocole de débogage n'a pas rendu le corps.
    origine_corps = "cdp"
    if not corps_reseau.strip():
        corps_reseau, taille_reseau = lib.corps_document_depuis_har(chemin_har, url_finale)
        origine_corps = "har" if corps_reseau.strip() else "indisponible"

    capture = lib.compresser_capture(chemin_cap)
    elagage = lib.elaguer_har(chemin_har) if chemin_har.exists() else {"elague": False}

    ecoule = (time.monotonic() - debut) * 1000.0
    # La version du navigateur est lue sur le navigateur lui-même, jamais écrite en dur :
    # les deux machines de la campagne n'installent pas forcément la même, et un nom de
    # canal qui ment sur son moteur rend la comparaison invérifiable.
    version = "inconnue"
    if ua:
        trouve = re.search(r"Chrome/([\d.]+)", str(ua))
        if trouve:
            version = trouve.group(1)

    obs_dom, obs_reseau = lib.observation_navigateur(
        url=url,
        cellule=cellule,
        channel_name=f"{cellule}:agent-browser-0.34.0/chrome-{version}",
        status=(principal or {}).get("status"),
        final_url=url_finale or (principal or {}).get("url"),
        headers=(principal or {}).get("responseHeaders") or {},
        corps_reseau=corps_reseau,
        taille_reseau=taille_reseau,
        dom=dom,
        redirect_chain=redirections,
        elapsed_ms=ecoule,
        error=erreur,
    )
    # Un corps absent ne se classe pas. Le classifieur, lui, classerait volontiers :
    # il verrait un 2xx de zéro octet et conclurait au `soft_404`, imputant au site une
    # page morte qui n'est qu'une lecture manquée.
    verdict_reseau = lib.classify(obs_reseau) if origine_corps != "indisponible" else None
    charge = lib.serialiser(
        obs_dom,
        cellule=cellule,
        passe=passe,
        extras={
            "site": site,
            "hote": hote,
            "titre": titre,
            "user_agent": ua,
            "mode": "headed",
            "confinement_domaines": confinement,
            "attente_resolution_ms": ATTENTE_RESOLUTION_MS,
            "har": f"har/{chemin_har.name}" if chemin_har.exists() else None,
            "har_elagage": elagage,
            "screenshot": f"captures/{capture.name}" if capture and capture.exists() else None,
            # Le second verdict, sur le corps que le serveur a réellement envoyé.
            "signature_corps_reseau": verdict_reseau.signature.value if verdict_reseau else None,
            "vendor_corps_reseau": verdict_reseau.vendor.value if verdict_reseau else None,
            "origine_corps_reseau": origine_corps,
            "defi_dans_corps_reseau_integral": lib.marqueur_defi_integral(corps_reseau),
            "taille_corps_reseau": taille_reseau,
            "extrait_corps_reseau": obs_reseau.excerpt[:1200],
            **lib.diagnostic_dom(dom, titre),
        },
    )
    return charge


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument(
        "--cellule", choices=["browser_residential", "browser_datacenter"], required=True
    )
    parseur.add_argument("--passe", type=int, required=True)
    parseur.add_argument("--sortie", type=Path, required=True)
    parseur.add_argument("--har", type=Path, required=True)
    parseur.add_argument("--captures", type=Path, required=True)
    parseur.add_argument(
        "--cibles",
        type=Path,
        default=None,
        help="jeu de cibles ; par défaut les 15 URL de la campagne. Sert au banc local.",
    )
    parseur.add_argument(
        "--confinement",
        action="store_true",
        help=(
            "confiner le navigateur à l'hôte cible via --allowed-domains. Hors mesure de "
            "sensibilité, laisser désactivé : le confinement bloque les ressources tierces "
            "dont certains sites ont besoin pour rendre leur contenu, et fabrique alors de "
            "faux refus."
        ),
    )
    parseur.add_argument(
        "--sites",
        nargs="*",
        default=None,
        help=(
            "ne sonder que ces sites, et fusionner dans le fichier de sortie existant. "
            "Sert à reprendre une observation dont la capture a échoué, sans re-solliciter "
            "les quatorze sites dont la mesure est valide."
        ),
    )
    args = parseur.parse_args()

    args.har.mkdir(parents=True, exist_ok=True)
    args.captures.mkdir(parents=True, exist_ok=True)

    liste = lib.cibles(args.cibles)
    if args.sites:
        demandes = {s.lower() for s in args.sites}
        liste = [c for c in liste if c["site"].lower() in demandes]
        if not liste:
            print(f"aucun site ne correspond à {args.sites}", flush=True)
            return 1
    observations: list[dict] = []
    dernier: dict[str, float] = {}

    print(f"[{args.cellule}] passe {args.passe} — {len(liste)} URL, Chrome avec fenêtre", flush=True)
    for i, cible in enumerate(liste, 1):
        hote = cible["hote"]
        delai = DELAIS_PAR_HOTE.get(hote, lib.MIN_INTERVAL_S)
        precedent = dernier.get(hote)
        if precedent is not None:
            attente = delai - (time.monotonic() - precedent)
            if attente > 0:
                time.sleep(attente)
        charge = sonder(
            cible, args.cellule, args.passe, args.har, args.captures, args.confinement
        )
        dernier[hote] = time.monotonic()
        observations.append(charge)
        meta = charge["meta"]
        print(
            f"  {i:2}/{len(liste)} {cible['site']:22} {str(charge['status']):>5} "
            f"dom={meta['signature']:20} reseau={meta['signature_corps_reseau']:20} "
            f"{charge['body_size']:>8} o",
            flush=True,
        )

    subprocess.run(["agent-browser", "close", "--all"], capture_output=True, timeout=60)

    contenu = lib.entete(
        cellule=args.cellule,
        collector=(
            "agent-browser 0.34.0 pilotant Google Chrome for Testing 148.0.7778.167 "
            "(mode avec fenêtre, User-Agent par défaut du navigateur, aucun mode furtif, "
            "aucune rotation d'identité)"
        ),
        method=(
            "une navigation de document par URL, session Chrome neuve et refermée pour "
            f"chaque site ; {ATTENTE_RESOLUTION_MS} ms d'attente après chargement pour "
            "laisser un défi JavaScript se résoudre ; statut et en-têtes pris sur la "
            "dernière requête de type Document (`network requests --type document`), "
            "corps réseau pris sur `network request <id>` (responseBody), DOM rendu pris "
            "sur `get html body` ; HAR et capture plein écran conservés pour chaque "
            "observation ; classification par benchmark_doctor.detectors.l2_liveness."
            "classify — le même code que les autres cellules."
        ),
        limits=[
            "Deux corps coexistent et reçoivent deux verdicts. `meta.signature` classe le "
            "DOM rendu, c'est-à-dire ce que verrait un agent ; "
            "`meta.signature_corps_reseau` classe le corps envoyé par le serveur, seul "
            "terme comparable au canal HTTP. Les confondre reviendrait à comparer un "
            "navigateur à un client HTTP sur deux objets différents.",
            "`body_size` de l'observation principale est la taille du DOM rendu en "
            "UTF-8, pas celle de la réponse HTTP : un DOM est toujours plus gros qu'un "
            "corps servi, et le seuil d'interstitiel du classifieur (15 000 octets) est "
            "donc moins souvent franchi par le bas. La taille réseau est conservée "
            "séparément dans `meta.taille_corps_reseau`.",
            "Le délai d'attente après chargement est fixé à "
            f"{ATTENTE_RESOLUTION_MS} ms pour toutes les cibles. Un défi plus lent que "
            "cela serait capturé dans son état d'interstitiel et compté comme un refus.",
            "Une seule navigation par site et par passe : aucun vote, aucune moyenne. "
            "Les sous-ressources chargées automatiquement par la page ne sont pas des "
            "requêtes de la campagne — elles sont visibles dans le HAR.",
        ],
        extras={"passe": args.passe, "n_observations": len(observations)},
    )
    if args.sites and args.sortie.exists():
        # Reprise partielle : on remplace les observations re-sondées et on garde les
        # autres telles quelles, en conservant l'en-tête d'origine — l'heure de collecte
        # des observations non reprises ne doit pas être réécrite.
        ancien = json.loads(args.sortie.read_text(encoding="utf-8"))
        reprises = {o["url"] for o in observations}
        fusion = [o for o in ancien.get("observations", []) if o["url"] not in reprises]
        fusion += observations
        ordre = {c["url"]: i for i, c in enumerate(lib.cibles())}
        fusion.sort(key=lambda o: ordre.get(o["url"], 999))
        ancien["observations"] = fusion
        ancien.setdefault("reprises", []).append(
            {
                "collected_at": contenu["collected_at"],
                "sites": [c["site"] for c in liste],
                "motif": "capture invalide lors du passage initial (DOM vide)",
            }
        )
        ancien["n_observations"] = len(fusion)
        contenu = ancien
    else:
        contenu["observations"] = observations

    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    args.sortie.write_text(
        json.dumps(contenu, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"→ {args.sortie} ({len(observations)} observations)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
