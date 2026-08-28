#!/usr/bin/env python3
"""Banc d'essai local de la chaîne de collecte — aucun site tiers n'est touché.

Une campagne qui découvre ses bogues de plomberie sur les sites réels dépense le seul
capital qu'elle ne peut pas reconstituer : la patience des serveurs qu'elle sonde, et
l'IP personnelle d'où elle sort. Ce banc rejoue donc localement les cinq réponses qui
comptent — page normale, pay-per-crawl Cloudflare, interstitiel AWS WAF, refus 403,
coquille vide — et vérifie que la chaîne complète (récupération → `Observation` →
`classify`) leur donne la signature attendue, sur le canal HTTP **et** sur le canal
navigateur.

Il vérifie aussi le cas qui distingue les deux canaux, et qu'un client HTTP ne peut pas
voir : un interstitiel qui, une fois le JavaScript exécuté, se remplace par la vraie page.
Le corps réseau dit « challenge », le DOM rendu dit « page » — les deux verdicts sont
justes, et c'est tout l'objet de la campagne.

    python experiments/fixtures_matrice.py            # HTTP seul
    python experiments/fixtures_matrice.py --navigateur   # + agent-browser
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matrice_lib as lib

# Les réponses rejouées

_PAGE_NORMALE = (
    "<!doctype html><html><head><title>Recettes et cuisine</title></head><body>"
    "<h1>La ressource de recettes de reference</h1>"
    + "<p>Contenu editorial reel, repete pour depasser le seuil d'interstitiel.</p>" * 400
    + "</body></html>"
)

_PAYWALL_CF = (
    "<!doctype html><html><head><title></title></head><body>"
    "<p>If you are a reader experiencing an access issue, please contact "
    "<a href=\"mailto:support@people.inc\">support@people.inc</a>. Pay-per-crawl: "
    "this site charges for automated access.</p></body></html>"
)

_CHALLENGE_WAF = (
    "<!doctype html><html><head><title></title></head><body>"
    "<div id=\"challenge-container\">Checking your browser before accessing the site. "
    "Please enable JavaScript and cookies to continue.</div>"
    "<script>window.awsWafCookieDomainList = [];</script></body></html>"
)

_INTERSTITIEL_PUIS_PAGE = (
    "<!doctype html><html><head><title></title></head><body>"
    "<div id=\"challenge-container\">Checking your browser before accessing the site. "
    "Please enable JavaScript and cookies to continue.</div>"
    "<script>window.awsWafCookieDomainList = [];"
    "document.addEventListener('DOMContentLoaded', function () {"
    "  document.title = 'Reservations et sejours';"
    "  document.body.innerHTML = '<h1>Trouvez votre sejour</h1>' + "
    "    '<p>Contenu reel servi apres resolution du defi.</p>'.repeat(400);"
    "});</script></body></html>"
)

_COQUILLE = "<!doctype html><html><head><title>x</title></head><body></body></html>"

#: chemin → (statut, en-têtes supplémentaires, corps, signature attendue sur le corps réseau)
CAS: dict[str, tuple[int, dict[str, str], str, str]] = {
    "/normale": (200, {"server": "nginx"}, _PAGE_NORMALE, "ok"),
    "/paywall": (
        402,
        {"server": "cloudflare", "cf-ray": "a2bc07f19d9cf27e-IAD",
         "set-cookie": "__cf_bm=test; HttpOnly; Secure"},
        _PAYWALL_CF,
        "paywall_402",
    ),
    "/challenge": (
        202,
        {"server": "CloudFront", "x-amzn-waf-action": "challenge"},
        _CHALLENGE_WAF,
        "antibot_challenge",
    ),
    "/refus": (403, {"server": "nginx"}, "<html><body>Forbidden</body></html>", "forbidden_403"),
    "/coquille": (200, {"server": "nginx"}, _COQUILLE, "soft_404"),
    "/resolu": (
        202,
        {"server": "CloudFront", "x-amzn-waf-action": "challenge"},
        _INTERSTITIEL_PUIS_PAGE,
        "antibot_challenge",
    ),
}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        chemin = self.path.split("?")[0]
        if chemin not in CAS:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        statut, entetes, corps, _ = CAS[chemin]
        charge = corps.encode("utf-8")
        self.send_response(statut)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(charge)))
        for cle, valeur in entetes.items():
            self.send_header(cle, valeur)
        self.end_headers()
        self.wfile.write(charge)

    def log_message(self, *args) -> None:  # silence
        pass


def _serveur() -> tuple[ThreadingHTTPServer, int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


# Vérifications


def _verifier_http(port: int) -> list[str]:
    echecs: list[str] = []
    canal = lib.canal_http("http_residential")
    canal.min_interval = 0.0
    for chemin, (_, _, _, attendu) in CAS.items():
        observation = canal.fetch(f"http://127.0.0.1:{port}{chemin}")
        charge = lib.serialiser(observation, cellule="http_residential", passe=0)
        obtenu = charge["meta"]["signature"]
        etat = "ok " if obtenu == attendu else "ECHEC"
        print(f"  [{etat}] http {chemin:12} attendu={attendu:20} obtenu={obtenu}")
        if obtenu != attendu:
            echecs.append(f"http {chemin}: attendu {attendu}, obtenu {obtenu}")
    return echecs


def _ab(session: str, *args: str, confiner: bool = False) -> subprocess.CompletedProcess:
    """Appelle le CLI. `--allowed-domains` attend un hôte **sans port** : passer
    ``127.0.0.1:8765`` fait rejeter la navigation, ce que le banc a vérifié."""
    commande = ["agent-browser", "--session", session]
    if confiner:
        commande += ["--allowed-domains", "127.0.0.1"]
    commande += list(args)
    return subprocess.run(commande, capture_output=True, text=True, timeout=120)


def _verifier_navigateur(port: int) -> list[str]:
    """Vérifie la chaîne navigateur, y compris la divergence corps réseau / DOM rendu."""
    echecs: list[str] = []
    session = f"fixtures_{int(time.time())}"
    try:
        for chemin, (_, _, _, attendu_reseau) in CAS.items():
            url = f"http://127.0.0.1:{port}{chemin}"
            _ab(session, "network", "har", "start", "--content", "text", port=port)
            ouverture = _ab(session, "open", "--json", url, port=port)
            if ouverture.returncode != 0:
                echecs.append(f"navigateur {chemin}: open a echoue — {ouverture.stderr[:200]}")
                continue
            requetes = _ab(session, "network", "requests", "--json", "--type", "document")
            dom = _ab(session, "get", "html", "body").stdout
            _ab(session, "network", "har", "stop", "/dev/null")

            try:
                liste = json.loads(requetes.stdout)
            except json.JSONDecodeError:
                echecs.append(f"navigateur {chemin}: sortie network requests illisible")
                continue
            entrees = liste if isinstance(liste, list) else liste.get("requests", [])
            doc = next((e for e in reversed(entrees) if url in str(e.get("url", ""))), None)
            if doc is None:
                echecs.append(f"navigateur {chemin}: aucune requete document trouvee")
                continue

            detail = _ab(session, "network", "request", str(doc.get("id") or doc.get("requestId")))
            corps_reseau = detail.stdout

            obs_dom, obs_reseau = lib.observation_navigateur(
                url=url,
                cellule="browser_residential",
                channel_name="browser_residential:fixtures",
                status=doc.get("status"),
                final_url=doc.get("url"),
                headers=doc.get("responseHeaders") or doc.get("headers") or {},
                corps_reseau=corps_reseau,
                taille_reseau=len(corps_reseau.encode("utf-8")),
                dom=dom,
            )
            sig_dom = lib.classify(obs_dom).signature.value
            sig_reseau = lib.classify(obs_reseau).signature.value
            print(
                f"  [    ] navigateur {chemin:12} statut={doc.get('status')} "
                f"dom={sig_dom:20} reseau={sig_reseau}"
            )
            if chemin == "/resolu" and sig_dom == sig_reseau:
                echecs.append(
                    "/resolu : le DOM rendu et le corps reseau donnent le meme verdict "
                    f"({sig_dom}) — le banc ne distingue plus les deux corps"
                )
    finally:
        _ab(session, "close")
    return echecs


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--navigateur", action="store_true")
    args = parseur.parse_args()

    httpd, port = _serveur()
    print(f"banc local sur 127.0.0.1:{port}")
    try:
        echecs = _verifier_http(port)
        if args.navigateur:
            echecs += _verifier_navigateur(port)
    finally:
        httpd.shutdown()

    if echecs:
        print("\nECHECS :")
        for e in echecs:
            print(f"  - {e}")
        return 1
    print("\nchaine validee")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
