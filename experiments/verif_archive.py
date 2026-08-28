#!/usr/bin/env python3
"""Campagne « vérification par archive » : confronter les motifs de disparition
des praticiens aux instantanés de la Wayback Machine.

Le mémoire s'appuie sur une vérité terrain fossile : des correctifs datés, motivés en
clair par des praticiens. Quand Magnitude écrit « GitHub Pro does not exist anymore »,
le dossier le croit sur parole. Ce script cherche, sur un échantillon fermé de douze
cas, à remplacer le témoignage par une observation directe : l'objet visé par la tâche
existait-il autour du gel du benchmark (2024-03-02), et avait-il disparu au plus tard
autour du gel du patch-set Magnitude (2025-07-06) ?

Deux garde-fous structurent le code, parce qu'ils conditionnent la validité du résultat :

1. **Le verdict est dérivé, jamais recopié.** Le plan (`plan_archive.json`) déclare pour
   chaque cas l'URL canonique, les instantanés à citer et les chaînes de caractères qui
   font preuve. Le script refait les requêtes, teste les chaînes dans le HTML brut, en
   déduit un état « objet présent / absent / indéterminé » par instantané, puis applique
   la règle de `verdict()`. Changer un verdict suppose de changer une observation.
2. **L'archive est une infrastructure à but non lucratif.** Toutes les requêtes vers
   web.archive.org passent par `_wayback_get()` : verrou inter-processus, une requête par
   seconde au plus, cache disque, journal exhaustif et plafond dur. Plusieurs agents
   peuvent explorer en parallèle sans jamais dépasser le débit d'un seul.

Sous-commandes :
    cdx <url> [--from AAAA] [--to AAAA]   inventaire des instantanés (API CDX)
    snap <timestamp> <url>                HTML brut d'un instantané (suffixe id_)
    live <url>                            statut du jour sur le web vivant
    budget                                état du plafond de requêtes
    run [--plan F] [--out F]              rejoue la campagne et produit le JSON
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0"

RACINE = Path(__file__).resolve().parent.parent
CACHE = RACINE / "runs" / "archive_cache"
JOURNAL = RACINE / "runs" / "archive_requetes.jsonl"
VERROU = RACINE / "runs" / ".archive_lock"

#: Plafond dur de requêtes réseau vers web.archive.org pour toute la campagne.
#: Le cache ne compte pas : seules les requêtes réellement émises sont décomptées.
BUDGET_MAX = 150

#: Délai minimal entre deux requêtes, en secondes.
DELAI = 1.0

#: Agent honnête : qui, pourquoi, où joindre. Aucune identité maquillée.
UA = (
    "benchmark-doctor/{v} (recherche academique sur la validite temporelle du "
    "benchmark WebVoyager; contact via github.com/jolehuit/memoirem2)"
).format(v=VERSION)

#: Fenêtres temporelles du test. Le corpus est gelé au 2024-03-02, le patch-set
#: Magnitude au 2025-07-06 : l'hypothèse est « présent dans la première, absent dans la
#: seconde ». La fenêtre « après » ne sert qu'à documenter l'état actuel.
GEL_CORPUS = "20240302"
GEL_PATCH = "20250706"
FENETRE_AVANT = ("20230901", "20240630")
FENETRE_PATCH = ("20240701", "20251231")


# réseau


def _horodatage() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _journaliser(entree: dict) -> None:
    entree.setdefault("agent", AGENT)
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entree, ensure_ascii=False) + "\n")


#: Étiquette d'attribution : plusieurs explorateurs partagent le plafond global, chacun
#: doit pouvoir tenir sa propre part sans avoir à deviner ce que les autres consomment.
AGENT = os.environ.get("AGENT_CAS", "-")


def requetes_par_agent() -> dict[str, int]:
    """Répartition des requêtes réseau par étiquette d'agent."""
    parts: dict[str, int] = {}
    if not JOURNAL.exists():
        return parts
    for ligne in JOURNAL.read_text("utf-8").splitlines():
        if not ligne.strip():
            continue
        try:
            e = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if e.get("source") == "reseau" and "web.archive.org" in e.get("url", ""):
            cle = e.get("agent", "-")
            parts[cle] = parts.get(cle, 0) + 1
    return parts


def requetes_emises() -> int:
    """Nombre de requêtes réellement parties vers le réseau (hors cache)."""
    if not JOURNAL.exists():
        return 0
    n = 0
    for ligne in JOURNAL.read_text("utf-8").splitlines():
        if not ligne.strip():
            continue
        try:
            e = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if e.get("source") == "reseau" and "web.archive.org" in e.get("url", ""):
            n += 1
    return n


def _chemin_cache(url: str) -> Path:
    cle = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return CACHE / f"{cle}.bin"


#: Signatures des defaillances de l'archive elle-meme. Elles se distinguent d'une vraie
#: reponse archivee et ne doivent jamais entrer dans le cache : une page « 504 Gateway
#: Time-out » gelee sur disque ferait echouer silencieusement tout rejeu ulterieur du plan,
#: et une page d'erreur de rejeu serait lue comme un contenu absent.
_DEFAILLANCES = (
    b"This snapshot cannot be displayed due to an internal error",
    b"504 Gateway Time-out",
    b"502 Bad Gateway",
    b"503 Service Temporarily Unavailable",
)


def _est_defaillance_archive(statut: int | None, corps: bytes) -> bool:
    """Distingue une défaillance de l'archive d'une réponse archivée légitime.

    Les signatures sont cherchées dans TOUT le corps : la page d'erreur de rejeu place son
    message après environ 149 ko de licences JavaScript inlinées, si bien qu'un contrôle
    limité aux premiers milliers d'octets ne l'a jamais vue.
    """
    if statut is not None and not (200 <= statut < 400):
        return True
    if not corps:
        return True
    if any(signature in corps for signature in _DEFAILLANCES):
        return True
    return b"<title>Wayback Machine</title>" in corps and b'class="error-text"' in corps


def _wayback_get(url: str, timeout: int = 90, force: bool = False) -> bytes:
    """Requête vers web.archive.org : cache, verrou global, 1 req/s, budget, journal.

    Le verrou est tenu pendant toute la requête. Deux processus qui explorent en
    parallèle sont donc sérialisés : le débit vu par l'archive reste celui d'un seul
    client, quel que soit le nombre d'agents.
    """
    cible = _chemin_cache(url)
    if cible.exists() and not force:
        _journaliser({"t": _horodatage(), "url": url, "source": "cache",
                      "octets": cible.stat().st_size})
        return cible.read_bytes()

    CACHE.mkdir(parents=True, exist_ok=True)
    VERROU.parent.mkdir(parents=True, exist_ok=True)
    with VERROU.open("a+") as verrou:
        fcntl.flock(verrou.fileno(), fcntl.LOCK_EX)
        try:
            # Un autre processus a pu remplir le cache pendant l'attente du verrou.
            if cible.exists() and not force:
                _journaliser({"t": _horodatage(), "url": url, "source": "cache",
                              "octets": cible.stat().st_size})
                return cible.read_bytes()

            emises = requetes_emises()
            if emises >= BUDGET_MAX:
                raise SystemExit(
                    f"BUDGET EPUISE : {emises}/{BUDGET_MAX} requetes deja emises vers "
                    "web.archive.org. Rien n'est envoye. Relever BUDGET_MAX suppose une "
                    "decision explicite."
                )

            verrou.seek(0)
            try:
                dernier = float(verrou.read().strip().split("\n")[-1])
            except (ValueError, IndexError):
                dernier = 0.0
            attente = DELAI - (time.time() - dernier)
            if attente > 0:
                time.sleep(attente)

            debut = time.time()
            requete = urllib.request.Request(url, headers={"User-Agent": UA})
            statut, corps, erreur = None, b"", None
            try:
                with urllib.request.urlopen(requete, timeout=timeout) as reponse:
                    statut = reponse.status
                    corps = reponse.read()
            except urllib.error.HTTPError as exc:
                statut = exc.code
                corps = exc.read()
            except Exception as exc:  # réseau, DNS, timeout
                erreur = f"{type(exc).__name__}: {exc}"

            verrou.seek(0)
            verrou.truncate()
            verrou.write(str(time.time()))
            verrou.flush()

            _journaliser({
                "t": _horodatage(), "url": url, "source": "reseau", "statut": statut,
                "octets": len(corps), "duree_s": round(time.time() - debut, 2),
                "erreur": erreur, "budget_apres": emises + 1,
            })
            if erreur:
                raise RuntimeError(f"{url} : {erreur}")
            if _est_defaillance_archive(statut, corps):
                raise RuntimeError(
                    f"{url} : l'archive a repondu {statut} par une page de defaillance "
                    "(passerelle ou erreur de rejeu). Rien n'est mis en cache : une telle "
                    "reponse gelee ferait echouer tout rejeu ulterieur du plan. Reessayer."
                )
            cible.write_bytes(corps)
            return corps
        finally:
            fcntl.flock(verrou.fileno(), fcntl.LOCK_UN)


def cdx(url: str, depuis: str = "2023", jusqua: str = "2026", limite: int = 400,
        collapse: str = "digest", filtre: str | None = None) -> list[dict]:
    """Inventaire des instantanés d'une URL : horodatage, statut, URL originale.

    C'est la colonne vertébrale de la preuve : elle montre quand la page répondait 200
    et quand elle a commencé à répondre 301 ou 404.
    """
    params = {
        "url": url, "from": depuis, "to": jusqua, "output": "json",
        "fl": "timestamp,statuscode,original,digest,mimetype,length",
        "limit": str(limite),
    }
    if collapse:
        params["collapse"] = collapse
    if filtre:
        params["filter"] = filtre
    adresse = "https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(params)
    brut = _wayback_get(adresse)
    texte = brut.decode("utf-8", "replace").strip()
    if not texte:
        # Un corps vide n'est pas un resultat vide. L'API rend « [] » quand elle n'a rien ;
        # une reponse sans corps est un refus, et la confondre avec « aucun instantane »
        # transformerait un blocage en preuve d'absence.
        raise RuntimeError(
            f"{url} : l'API CDX a repondu un corps vide. Ce n'est pas « aucun instantane », "
            "c'est une reponse inexploitable. Reessayer."
        )
    lignes = json.loads(texte)
    if not lignes:
        return []
    entetes, *reste = lignes
    return [dict(zip(entetes, ligne)) for ligne in reste]


def _decompresser(corps: bytes) -> bytes:
    """Le suffixe `id_` sert le corps *original* tel qu'archivé, encodage compris.

    L'archive rejoue donc un corps gzip ou deflate sans que l'en-tête de la réponse le
    signale toujours : la détection se fait sur les octets de tête, faute de quoi les
    assertions de contenu s'appliqueraient à du binaire et conclueraient « absent » sur
    des pages parfaitement archivées.
    """
    if corps[:2] == b"\x1f\x8b":
        try:
            return zlib.decompress(corps, 16 + zlib.MAX_WBITS)
        except zlib.error:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            return d.decompress(corps)  # flux tronqué : on garde ce qui se lit
    if corps[:1] == b"\x78":
        try:
            return zlib.decompress(corps)
        except zlib.error:
            return corps
    return corps


def instantane(timestamp: str, url: str) -> str:
    """HTML brut d'un instantané : le suffixe `id_` retire la barre de l'archive.

    Les preuves de contenu se lisent dans ce HTML, pas dans un rendu visuel : les pages
    riches en JavaScript s'archivent mal et un rendu incomplet ferait conclure à tort.
    """
    adresse = f"https://web.archive.org/web/{timestamp}id_/{url}"
    return _decompresser(_wayback_get(adresse)).decode("utf-8", "replace")


def web_vivant(url: str, timeout: int = 30) -> dict:
    """Une requête simple vers l'URL canonique actuelle, pour noter son statut du jour.

    Pas de navigation, pas de contournement : un refus (403, 429) est une donnée, pas un
    obstacle à franchir.
    """
    requete = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    ouvreur = urllib.request.build_opener(_SansRedirection)
    resultat = {"url": url, "t": _horodatage()}
    try:
        with ouvreur.open(requete, timeout=timeout) as reponse:
            resultat["statut"] = str(reponse.status)
            resultat["location"] = reponse.headers.get("Location")
    except urllib.error.HTTPError as exc:
        resultat["statut"] = str(exc.code)
        resultat["location"] = exc.headers.get("Location") if exc.headers else None
    except Exception as exc:
        resultat["statut"] = "erreur"
        resultat["erreur"] = f"{type(exc).__name__}: {exc}"
    _journaliser({"t": resultat["t"], "url": url, "source": "web_vivant",
                  "statut": resultat.get("statut")})
    return resultat


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    """Ne suit pas les redirections : un 301 est une observation, pas un détour."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


# lecture du HTML


_BALISES = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_ESPACES = re.compile(r"\s+")


def texte_visible(html: str) -> str:
    """Texte de la page, scripts et styles retirés, espaces normalisés.

    Une chaîne cherchée dans le texte visible ne peut pas être un fragment de code
    JavaScript résiduel : c'est ce qui distingue « le prix est affiché » de « le mot
    apparaît quelque part dans le bundle »."""
    sans = _BALISES.sub(" ", html)
    sans = _TAG.sub(" ", sans)
    sans = (sans.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#x27;", "'")
            .replace("&quot;", '"').replace("&#39;", "'").replace("&gt;", ">")
            .replace("&lt;", "<"))
    return _ESPACES.sub(" ", sans)


def tester(html: str, assertion: dict) -> dict:
    """Évalue une assertion de contenu sur un instantané.

    Types : `contient` / `ne_contient_pas` (texte visible), `contient_html` /
    `ne_contient_pas_html` (HTML brut, pour les attributs et les liens), `regex`.

    La distinction n'est pas cosmétique. Un `ne_contient_pas` porte sur le texte visible,
    d'où les balises ont été retirées : une chaîne qui ne vit que dans un `href` y est
    invisible, et l'assertion est alors satisfaite même sur une page où l'objet est bien
    présent — une assertion qui ne peut pas échouer ne prouve rien. Quand l'objet est un
    lien, un identifiant ou un attribut, l'absence doit être testée sur le HTML brut.
    """
    type_ = assertion["type"]
    chaine = assertion["chaine"]
    portee = html if type_ in {"contient_html", "ne_contient_pas_html"} else texte_visible(html)
    cible = portee if assertion.get("sensible_casse") else portee.lower()
    aiguille = chaine if assertion.get("sensible_casse") else chaine.lower()

    if type_ == "regex":
        trouve = re.search(chaine, portee, re.I) is not None
    else:
        trouve = aiguille in cible

    attendu = type_ not in {"ne_contient_pas", "ne_contient_pas_html"}
    extrait = None
    if trouve and attendu:
        i = cible.find(aiguille) if type_ != "regex" else re.search(chaine, portee, re.I).start()
        extrait = portee[max(0, i - 90): i + len(chaine) + 90].strip()
    return {
        "type": type_, "chaine": chaine, "trouve": trouve,
        "satisfaite": trouve == attendu, "extrait": extrait,
    }


# les verdicts


#: Les assertions qui portent l'absence de l'objet. Les autres servent de témoin : elles
#: attestent que la page est bien archivée, donc qu'une absence n'est pas un trou de capture.
_NEGATIVES = {"ne_contient_pas", "ne_contient_pas_html"}


def etat_instantane(entree: dict) -> str:
    """État de l'objet visé dans un instantané : `present`, `absent`, `indetermine`.

    Un statut 404 ou 410 suffit à conclure à l'absence. Une redirection n'y suffit pas : les
    sites redirigent aussi pour se réorganiser, et c'est la page cible qui tranche, donc une
    assertion de contenu.

    Le cas dissymétrique est celui d'une sonde d'absence qui échoue. Si les témoins passent
    (la page est bien là, bien archivée) mais que les assertions négatives trouvent l'objet,
    alors l'objet est PRÉSENT, et il faut le dire. Rendre `indetermine` dans ce cas rendrait
    le verdict INFIRMEE structurellement inatteignable : le dispositif ne pourrait plus
    contredire le praticien, seulement lui donner raison ou se taire.
    """
    statut = str(entree.get("statut") or "")
    assertions = entree.get("assertions") or []
    if statut in {"404", "410"} and not entree.get("statut_declare_non_confirme"):
        return "absent"
    if not assertions:
        # Sans assertion, rien n'a été lu de la page : le statut seul ne vaut que s'il vient
        # de la CDX. Un statut recopié à la main dans le plan ne doit jamais porter un verdict.
        if entree.get("statut_declare_non_confirme"):
            return "indetermine"
        return "present" if statut.startswith("2") else "indetermine"

    if all(a["satisfaite"] for a in assertions):
        return "present" if entree.get("role_preuve", "presence") == "presence" else "absent"

    if entree.get("role_preuve") == "absence":
        temoins = [a for a in assertions if a["type"] not in _NEGATIVES]
        negatives = [a for a in assertions if a["type"] in _NEGATIVES]
        if temoins and all(a["satisfaite"] for a in temoins) and negatives \
                and not any(a["satisfaite"] for a in negatives):
            return "present"
    return "indetermine"


def verdict(cas: dict) -> tuple[str, str]:
    """Dérive le verdict d'un cas depuis ses instantanés observés.

    CONFIRMEE     présent dans la fenêtre du gel du corpus, absent au plus tard fin 2025.
    INFIRMEE      encore présent, sous sa forme visée, après le gel du patch-set.
    NON_VERIFIABLE  la tâche est une quête : aucune URL stable ne peut porter la réponse.
    INSUFFISANT   URL stable mais couverture d'archive trop lacunaire pour trancher.

    L'absence d'instantané ne prouve jamais l'absence de la page : sans observation de
    présence dans la première fenêtre, le verdict plafonne à INSUFFISANT.
    """
    if cas.get("groupe") == "B":
        return "NON_VERIFIABLE", cas.get("raison_non_verifiable", "quete sans URL stable")

    observes = [i for i in cas.get("instantanes_cites", []) if i.get("etat")]
    presents_avant = [i for i in observes
                      if i["etat"] == "present" and FENETRE_AVANT[0] <= i["timestamp"][:8] <= FENETRE_AVANT[1]]
    presents_apres_patch = [i for i in observes
                            if i["etat"] == "present" and i["timestamp"][:8] > GEL_PATCH]
    absents_fenetre = [i for i in observes
                       if i["etat"] == "absent" and FENETRE_PATCH[0] <= i["timestamp"][:8] <= FENETRE_PATCH[1]]
    absents_tardifs = [i for i in observes
                       if i["etat"] == "absent" and i["timestamp"][:8] > FENETRE_PATCH[1]]

    if not presents_avant:
        return "INSUFFISANT", (
            "aucun instantane n'atteste la presence de l'objet dans la fenetre du gel du "
            "corpus ; l'absence d'instantane ne prouve pas l'absence de la page"
        )
    if presents_apres_patch:
        return "INFIRMEE", (
            f"objet encore present sous sa forme visee au {presents_apres_patch[-1]['timestamp'][:8]}, "
            f"apres le gel du patch-set ({GEL_PATCH})"
        )
    if absents_fenetre:
        # Une absence isolee ne suffit pas : un 404 de maintenance au milieu d'une fenetre de
        # dix-huit mois ne prouve pas une disparition. On exige que plus aucune presence ne
        # soit observee apres la premiere absence retenue.
        premiere_absence = absents_fenetre[0]["timestamp"]
        retours = [i for i in observes if i["etat"] == "present" and i["timestamp"] > premiere_absence]
        if retours:
            return "INSUFFISANT", (
                f"etat non monotone : absent au {premiere_absence[:8]}, mais de nouveau present "
                f"au {retours[-1]['timestamp'][:8]} ; une absence isolee ne prouve pas une disparition"
            )
        return "CONFIRMEE", (
            f"present au {presents_avant[-1]['timestamp'][:8]}, absent au "
            f"{premiere_absence[:8]}, et plus aucune presence observee ensuite"
        )
    if absents_tardifs:
        return "INSUFFISANT", (
            f"disparition observee seulement au {absents_tardifs[0]['timestamp'][:8]}, trop tard "
            f"pour la dater par rapport au gel du patch-set ({GEL_PATCH})"
        )
    return "INSUFFISANT", "aucune observation d'absence dans la fenetre utile"


# campagne


def executer_cas(cas: dict) -> dict:
    """Rejoue un cas : requêtes, assertions, état par instantané, verdict dérivé."""
    resultat = {
        "id": cas["id"],
        "site": cas["id"].split("--")[0],
        "enonce": cas.get("enonce"),
        "motif_praticien": cas["motif_praticien"],
        "groupe": cas.get("groupe", "A"),
        "url_canonique": cas.get("url_canonique"),
        "comment_trouvee": cas.get("comment_trouvee"),
        "instantanes_cites": [],
    }
    for champ in ("observation_remarquable", "notes", "portee_de_la_preuve"):
        if cas.get(champ):
            resultat[champ] = cas[champ]

    if cas.get("groupe") == "B":
        resultat["raison_non_verifiable"] = cas.get("raison_non_verifiable")
        resultat["urls_examinees"] = cas.get("urls_examinees", [])
        # Le verdict NON_VERIFIABLE est une qualification de l'énoncé, pas une mesure : il est
        # posé par le plan. Ce qui peut être rejoué, en revanche, ce sont les observations qui
        # le motivent, et elles le sont ici, faute de quoi la colonne « preuve » du rapport ne
        # serait que de la prose.
        for appui in cas.get("observations_d_appui", []):
            html = instantane(appui["timestamp"], appui["url"])
            resultat.setdefault("observations_d_appui", []).append({
                "question": appui["question"],
                "timestamp": appui["timestamp"],
                "url": appui["url"],
                "caracteres_html": len(html),
                "caracteres_texte_visible": len(texte_visible(html)),
                "assertions": [tester(html, a) for a in appui.get("assertions", [])],
                # Total et distincts : sur une page de collection, ce qui compte n'est pas le
                # nombre d'occurrences d'un lien mais le nombre de recettes réellement listées.
                "comptages": {
                    nom: {"occurrences": len(re.findall(motif, html, re.I)),
                          "distincts": len(set(re.findall(motif, html, re.I)))}
                    for nom, motif in (appui.get("comptages") or {}).items()
                },
            })
        resultat["verdict"], resultat["raison"] = verdict(cas)
        resultat["portee_du_verdict"] = (
            "NON_VERIFIABLE qualifie l'enonce, il n'est pas derive d'une observation : aucune URL "
            "stable ne peut porter la reponse. Les observations d'appui ci-dessus sont rejouees "
            "par le script et etayent cette qualification sans la produire."
        )
        return resultat

    inventaire = cdx(cas["url_canonique"], collapse=cas.get("collapse", "timestamp:6"))
    resultat["inventaire_cdx"] = {
        "echantillonnage": (
            "un instantane par mois (collapse=timestamp:6)"
            if cas.get("collapse", "timestamp:6") == "timestamp:6"
            else f"collapse={cas.get('collapse')}"
        ),
        "nb_instantanes_echantillon": len(inventaire),
        "premier": inventaire[0]["timestamp"] if inventaire else None,
        "dernier": inventaire[-1]["timestamp"] if inventaire else None,
        "statuts": sorted({e.get("statuscode", "?") for e in inventaire}),
        "par_annee": {a: sum(1 for e in inventaire if e["timestamp"][:4] == a)
                      for a in sorted({e["timestamp"][:4] for e in inventaire})},
    }

    for demande in cas.get("instantanes", []):
        entree = {
            "timestamp": demande["timestamp"],
            "role": demande.get("role"),
            "role_preuve": demande.get("role_preuve", "presence"),
        }
        if demande.get("url"):
            entree["url"] = demande["url"]
        depuis_cdx = next((e for e in inventaire if e["timestamp"] == demande["timestamp"]), None)
        # Le statut fait foi depuis la CDX, pas depuis le plan : un statut recopie a la main
        # pourrait porter un verdict a lui seul, sans qu'aucune page ait ete lue.
        statut_cdx = (depuis_cdx or {}).get("statuscode")
        entree["statut"] = statut_cdx or demande.get("statut")
        if statut_cdx and demande.get("statut") and statut_cdx != demande["statut"]:
            entree["divergence_statut"] = {"plan": demande["statut"], "cdx": statut_cdx}
        if not statut_cdx and demande.get("statut"):
            entree["statut_declare_non_confirme"] = True

        assertions = demande.get("assertions", [])
        if assertions:
            html = instantane(demande["timestamp"], demande.get("url") or cas["url_canonique"])
            entree["caracteres_html"] = len(html)
            entree["caracteres_texte_visible"] = len(texte_visible(html))
            entree["page_close"] = html.rstrip().endswith("</html>")
            entree["assertions"] = [tester(html, a) for a in assertions]
        entree["etat"] = etat_instantane(entree)
        entree["preuve"] = demande.get("preuve") or _resumer_preuve(entree)
        resultat["instantanes_cites"].append(entree)

    resultat["instantanes_cites"].sort(key=lambda e: e["timestamp"])

    # Un instantané cité qui ne figure pas dans l'inventaire publié rendrait le rapport
    # incoherent : on lirait une couverture qui s'arrete en 2023 pendant que la preuve
    # cite 2026. Le cas se produit des que la CDX sature son plafond d'entrees.
    # L'inventaire est un echantillon, pas la liste exhaustive : un instantane cite peut ne
    # pas y figurer sans que rien ne cloche. Ce qui clocherait, c'est un inventaire qui ne
    # couvrirait pas la periode d'ou la preuve est tiree - on lirait une couverture arretee
    # en 2023 a cote d'une observation de 2026.
    if inventaire and resultat["instantanes_cites"]:
        bornes = (inventaire[0]["timestamp"][:8], inventaire[-1]["timestamp"][:8])
        hors = [e["timestamp"] for e in resultat["instantanes_cites"]
                if not e.get("url") and not (bornes[0] <= e["timestamp"][:8] <= bornes[1])]
        autres_url = sorted({e["url"] for e in resultat["instantanes_cites"] if e.get("url")})
        if autres_url:
            resultat["inventaire_cdx"]["instantanes_pris_sur_une_autre_url"] = autres_url
        if hors:
            resultat["inventaire_cdx"]["hors_couverture_de_l_inventaire"] = hors
    # Un contrôle complémentaire sert à rendre rejouable une observation qui sort du cadre
    # du test principal. Sans lui, l'affirmation la plus forte du rapport ne serait qu'une
    # note de bas de page ; ici, le script la remesure et l'écrit dans le résultat.
    for controle in cas.get("controles_complementaires", []):
        entrees = cdx(controle["url"], controle.get("from", "2023"), controle.get("to", "2026"),
                      collapse=controle.get("collapse", ""), limite=controle.get("limite", 400))
        distribution: dict[str, int] = {}
        for e in entrees:
            cle = e.get("statuscode") or "-"
            distribution[cle] = distribution.get(cle, 0) + 1
        resultat.setdefault("controles_complementaires", []).append({
            "question": controle["question"],
            "url": controle["url"],
            "fenetre": [controle.get("from", "2023"), controle.get("to", "2026")],
            "nb_instantanes": len(entrees),
            "distribution_des_statuts": distribution,
            "note": (
                "Aucun filtre n'est applique : filtrer sur statuscode ecarte silencieusement les "
                "enregistrements de revisite, dont la colonne vaut « - », et un compteur filtre a "
                "zero ne se distingue pas d'une URL jamais exploree."
            ),
            "premiers": [f"{e['timestamp']} {e.get('statuscode', '-')}" for e in entrees[:5]],
            "derniers": [f"{e['timestamp']} {e.get('statuscode', '-')}" for e in entrees[-3:]],
        })

    if cas.get("url_vivante") or cas.get("url_canonique"):
        vivant = web_vivant(cas.get("url_vivante") or cas["url_canonique"])
        resultat["statut_web_vivant_du_jour"] = vivant.get("statut")
        if vivant.get("location"):
            resultat["redirection_web_vivant"] = vivant["location"]
    resultat["verdict"], resultat["raison"] = verdict(resultat)
    return resultat


def _resumer_preuve(entree: dict) -> str:
    if not entree.get("assertions"):
        return f"statut {entree.get('statut')} au passage du robot"
    morceaux = []
    for a in entree["assertions"]:
        etat = "presente" if a["trouve"] else "absente"
        morceaux.append(f"chaine « {a['chaine']} » {etat}")
    return f"statut {entree.get('statut')} ; " + " ; ".join(morceaux)


def _journal_emis() -> list[dict]:
    """Les requêtes réellement parties sur le réseau, dans l'ordre.

    Le journal complet vit dans `runs/archive_requetes.jsonl`, que le `.gitignore` du dépôt
    exclut. Il est donc recopié ici, dans le fichier de résultats : une campagne dont on ne
    peut pas rejouer le décompte des requêtes n'est pas vérifiable.
    """
    if not JOURNAL.exists():
        return []
    emises = []
    for ligne in JOURNAL.read_text("utf-8").splitlines():
        if not ligne.strip():
            continue
        try:
            e = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if e.get("source") in {"reseau", "web_vivant"}:
            emises.append(e)
    return emises


def run(plan_path: Path, sortie: Path) -> dict:
    plan = json.loads(plan_path.read_text("utf-8"))
    cas_resultats = [executer_cas(c) for c in plan["cas"]]
    comptes: dict[str, int] = {}
    for c in cas_resultats:
        comptes[c["verdict"]] = comptes.get(c["verdict"], 0) + 1

    document = {
        "collected_at": _horodatage(),
        "collector": {
            "outil": "benchmark-doctor / experiments/verif_archive.py",
            "version": VERSION,
            "systeme": f"{platform.system()} {platform.release()} / Python {platform.python_version()}",
            "plan": "experiments/plan_archive.json",
            "user_agent": UA,
        },
        "method": (
            "Pour chaque cas, l'API CDX de la Wayback Machine donne l'inventaire des "
            "instantanés de l'URL canonique entre 2023 et 2026 ; quatre d'entre eux sont "
            "téléchargés en HTML brut (suffixe id_) et testés sur des chaînes de caractères "
            "précises, un cinquième lorsqu'une observation contraire méritait d'être citée, "
            "et deux seulement quand l'inventaire n'en offre pas davantage. "
            "Le verdict n'est pas saisi à la main : il est dérivé de l'état observé par "
            "instantané (présent, absent ou indéterminé) et de sa position par rapport au gel "
            "du corpus (2024-03-02) et à celui du patch-set Magnitude (2025-07-06)."
        ),
        "limits": (
            "La Wayback Machine archive des pages, pas des fonctionnalités : aucune archive ne "
            "permet de rejouer une recherche ni un parcours, donc une tâche formulée comme une "
            "quête reste hors de portée (verdict NON_VERIFIABLE). L'absence d'instantané ne "
            "prouve pas l'absence de la page : la couverture du robot est inégale, d'où "
            "INSUFFISANT plutôt que CONFIRMEE. Une redirection archivée est un signal, pas une "
            "preuve : la page cible est ouverte avant de conclure. Le contenu rendu peut être "
            "incomplet sur les pages riches en JavaScript, donc les preuves portent sur le HTML "
            "archivé et non sur un rendu visuel. Enfin, confirmer qu'un objet a disparu ne dit "
            "rien de l'exécutabilité de la tâche : c'est une condition nécessaire, pas suffisante."
        ),
        "fenetres": {
            "gel_corpus": GEL_CORPUS, "gel_patch": GEL_PATCH,
            "fenetre_avant": FENETRE_AVANT, "fenetre_patch": FENETRE_PATCH,
        },
        "budget_requetes": {"plafond": BUDGET_MAX, "emises_vers_archive": requetes_emises()},
        "resume": comptes,
        "cas": cas_resultats,
        "journal_requetes": _journal_emis(),
    }
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return document


# CLI


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = parseur.add_subparsers(dest="commande", required=True)

    p_cdx = sous.add_parser("cdx", help="inventaire des instantanes d'une URL")
    p_cdx.add_argument("url")
    p_cdx.add_argument("--from", dest="depuis", default="2023")
    p_cdx.add_argument("--to", dest="jusqua", default="2026")
    p_cdx.add_argument("--limit", type=int, default=400)
    p_cdx.add_argument("--collapse", default="digest")
    p_cdx.add_argument("--filter", dest="filtre", default=None,
                       help="filtre CDX, par exemple statuscode:200")

    p_snap = sous.add_parser("snap", help="HTML brut d'un instantane")
    p_snap.add_argument("timestamp")
    p_snap.add_argument("url")
    p_snap.add_argument("--grep", action="append", default=[],
                        help="chaine a chercher dans le texte visible")
    p_snap.add_argument("--out", help="ecrire le HTML brut dans un fichier")
    p_snap.add_argument("--texte", action="store_true", help="afficher le texte visible")
    p_snap.add_argument("--head", type=int, default=3000)

    p_live = sous.add_parser("live", help="statut du jour sur le web vivant")
    p_live.add_argument("url")

    sous.add_parser("budget", help="etat du plafond de requetes")

    p_run = sous.add_parser("run", help="rejoue la campagne depuis le plan")
    p_run.add_argument("--plan", default=str(Path(__file__).parent / "plan_archive.json"))
    p_run.add_argument("--out", default=None)

    args = parseur.parse_args(argv)

    if args.commande == "cdx":
        entrees = cdx(args.url, args.depuis, args.jusqua, args.limit, args.collapse, args.filtre)
        print(f"# {len(entrees)} instantanes pour {args.url}")
        for e in entrees:
            print(f"{e['timestamp']}  {e.get('statuscode','?'):>3}  {e.get('length','?'):>8}  {e['original']}")
        return 0

    if args.commande == "snap":
        html = instantane(args.timestamp, args.url)
        if args.out:
            Path(args.out).write_text(html, "utf-8")
            print(f"# {len(html)} octets -> {args.out}")
        for aiguille in args.grep:
            resultat = tester(html, {"type": "contient", "chaine": aiguille})
            marque = "TROUVE " if resultat["trouve"] else "ABSENT "
            print(f"{marque} « {aiguille} »" + (f" :: …{resultat['extrait']}…" if resultat["extrait"] else ""))
        if args.texte:
            print(texte_visible(html)[: args.head])
        elif not args.grep and not args.out:
            print(html[: args.head])
        return 0

    if args.commande == "live":
        print(json.dumps(web_vivant(args.url), ensure_ascii=False))
        return 0

    if args.commande == "budget":
        emises = requetes_emises()
        print(f"{emises}/{BUDGET_MAX} requetes emises vers web.archive.org "
              f"({BUDGET_MAX - emises} restantes)")
        for cle, n in sorted(requetes_par_agent().items(), key=lambda kv: -kv[1]):
            print(f"  {cle:<20} {n}")
        return 0

    if args.commande == "run":
        plan = Path(args.plan)
        defaut = RACINE / "runs" / f"archive_t2_{datetime.now().strftime('%Y%m%d')}.json"
        sortie = Path(args.out) if args.out else defaut
        document = run(plan, sortie)
        print(json.dumps(document["resume"], ensure_ascii=False))
        print(f"-> {sortie}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
