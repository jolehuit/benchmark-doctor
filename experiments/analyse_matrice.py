#!/usr/bin/env python3
"""Analyse de la matrice des canaux : accords, facteurs isolés, κ, répétabilité.

    python experiments/analyse_matrice.py --runs runs/matrice --sortie runs/matrice/analyse.json

Deux grandeurs portent la lettre κ dans cette campagne, et les confondre serait une faute
----------------------------------------------------------------------------------------

- **κ de Cohen** mesure l'*accord* entre deux canaux qui jugent les mêmes sites, corrigé
  du hasard. Il répond à « ces deux canaux disent-ils la même chose ? » et vaut 1 quand
  ils sont d'accord partout, 0 quand leur accord n'excède pas le hasard. Il est
  **symétrique** : aucun des deux canaux n'y est la référence.

- **κ de crédibilité** est le paramètre du score publié par le mémoire. Il ne mesure pas
  un accord mais une *probabilité* : sachant que le canal HTTP depuis un centre de
  données annonce un refus, quelle chance ce refus a-t-il d'être réel ? Le mémoire
  l'estime par la règle de succession de Laplace, (k+1)/(n+2), sur n = 3 URL bloquées
  disposant d'une contrepartie navigateur, dont k = 1 blocage confirmé — d'où 0,40. Il est
  **asymétrique** : le canal HTTP y est l'accusé, l'autre canal le juge.

Le script calcule les deux, séparément et sous ces deux noms.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matrice_lib as lib

#: Signatures qui ne disent rien du site : la réponse vient du canal, ou rien n'est venu.
#: Les compter comme des refus imputerait au site un défaut de l'infrastructure — c'est
#: précisément l'erreur que la couche L2 du paquet a été écrite pour empêcher.
NON_IMPUTABLES = {"channel_blocked", "unreachable"}

ORDRE_CELLULES = ["http_datacenter", "http_residential", "browser_residential", "browser_datacenter"]


def accessible(signature: str) -> bool | None:
    """Binaire accessible / refusé. ``None`` quand le verdict n'est pas imputable au site."""
    if signature in NON_IMPUTABLES:
        return None
    return signature == "ok"


# Chargement


def charger(rep: Path) -> dict[tuple[str, int], dict[str, dict]]:
    """(cellule, passe) → {site: observation}."""
    table: dict[tuple[str, int], dict[str, dict]] = {}
    for chemin in sorted(rep.glob("*.json")):
        if chemin.name in ("analyse.json",) or "_confine" in chemin.name:
            continue
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
        if "observations" not in contenu:
            continue
        cellule = contenu.get("channel")
        passe = int(contenu.get("passe") or 1)
        table.setdefault((cellule, passe), {})
        for observation in contenu["observations"]:
            site = observation.get("meta", {}).get("site") or observation["url"]
            table[(cellule, passe)][site] = observation
    return table


def signature(observation: dict) -> str:
    return observation.get("meta", {}).get("signature", "?")


# κ de Cohen


def kappa_cohen(paires: list[tuple[bool, bool]]) -> dict[str, Any]:
    """κ de Cohen sur un binaire, avec les effectifs de la table 2×2.

    Le cas dégénéré compte : quand les deux canaux disent « accessible » partout, l'accord
    observé vaut 1 et l'accord attendu aussi, si bien que κ vaut 0/0. Renvoyer 0 laisserait
    croire à un désaccord total, renvoyer 1 à une concordance démontrée ; les deux
    mentiraient. Le script renvoie ``None`` et le dit.
    """
    n = len(paires)
    if n == 0:
        return {"kappa": None, "n": 0, "motif": "aucune paire comparable"}
    a = sum(1 for x, y in paires if x and y)          # accessible / accessible
    b = sum(1 for x, y in paires if x and not y)      # accessible / refusé
    c = sum(1 for x, y in paires if not x and y)      # refusé / accessible
    d = sum(1 for x, y in paires if not x and not y)  # refusé / refusé
    po = (a + d) / n
    pe = ((a + b) * (a + c) + (c + d) * (b + d)) / (n * n)
    table = {"acc_acc": a, "acc_ref": b, "ref_acc": c, "ref_ref": d}
    if abs(1 - pe) < 1e-12:
        return {
            "kappa": None,
            "n": n,
            "accord_observe": round(po, 4),
            "table": table,
            "motif": (
                "κ indéfini : les deux canaux rendent le même verdict sur la totalité des "
                "sites comparables, donc l'accord attendu par hasard vaut déjà 1. "
                "L'accord est parfait, mais κ ne peut pas le mesurer."
            ),
        }
    return {
        "kappa": round((po - pe) / (1 - pe), 4),
        "n": n,
        "accord_observe": round(po, 4),
        "accord_attendu": round(pe, 4),
        "table": table,
        "desaccords": b + c,
    }


# κ de crédibilité (Laplace)


def kappa_credibilite(
    accuse: dict[str, dict], juge: dict[str, dict]
) -> dict[str, Any]:
    """Réestime le paramètre du score : un refus annoncé par `accuse` est-il réel ?

    Reproduit la règle du mémoire — (k+1)/(n+2) — mais sur les sites réellement mesurés
    par les deux canaux, au lieu de trois.
    """
    bloques, confirmes, detail = [], [], []
    for site, obs_a in accuse.items():
        obs_j = juge.get(site)
        if obs_j is None:
            continue
        sig_a, sig_j = signature(obs_a), signature(obs_j)
        acc_a, acc_j = accessible(sig_a), accessible(sig_j)
        if acc_a is None or acc_j is None or acc_a is not False:
            continue  # on ne juge que les refus imputables, jugés par un canal imputable
        bloques.append(site)
        confirme = acc_j is False
        if confirme:
            confirmes.append(site)
        detail.append(
            {
                "site": site,
                "signature_accuse": sig_a,
                "signature_juge": sig_j,
                "blocage_confirme": confirme,
            }
        )
    n, k = len(bloques), len(confirmes)
    return {
        "n_refus_annonces": n,
        "k_refus_confirmes": k,
        "kappa_laplace": round((k + 1) / (n + 2), 4) if n or k else None,
        "proportion_brute": round(k / n, 4) if n else None,
        "ic95_proportion": intervalle_jeffreys(k, n) if n else None,
        "detail": detail,
    }


def permutation_kappa(paires: list[tuple[bool, bool]], tirages: int = 20_000) -> float | None:
    """p bilatéral d'un test de permutation sur κ de Cohen.

    Nécessaire parce que κ n'est pas lisible seul quand les marges sont déséquilibrées.
    Avec onze à quatorze verdicts `ok` sur quinze, un κ négatif ne signale pas un désaccord
    systématique : il signale que la prévalence écrase le terme d'accord attendu. Le test
    remélange les verdicts d'un canal et compte combien de fois le hasard fait au moins
    aussi bien que la valeur observée.

    La graine est fixée : un p qui change d'une exécution à l'autre n'est pas un résultat.
    """
    import random

    n = len(paires)
    if n < 2:
        return None
    reference = kappa_cohen(paires).get("kappa")
    if reference is None:
        return None
    gauche = [x for x, _ in paires]
    droite = [y for _, y in paires]
    alea = random.Random(20260816)
    au_moins_aussi_extreme = 0
    for _ in range(tirages):
        melange = droite[:]
        alea.shuffle(melange)
        valeur = kappa_cohen(list(zip(gauche, melange))).get("kappa")
        if valeur is not None and abs(valeur) >= abs(reference) - 1e-12:
            au_moins_aussi_extreme += 1
    return round(au_moins_aussi_extreme / tirages, 4)


def _betainc(a: float, b: float, x: float) -> float:
    """Fonction bêta incomplète régularisée I_x(a, b), par fraction continue.

    Écrite à la main plutôt qu'importée : la campagne doit pouvoir être rejouée sans
    installer une pile scientifique, et l'intégration naïve échoue ici. Avec a = 0,5 la
    densité Beta diverge en 0, et une somme de rectangles y perd deux décimales, ce qui
    déplace la borne basse de l'intervalle au point de la rendre trompeuse.

    Méthode de Lentz pour la fraction continue, telle qu'on la trouve dans les recettes
    numériques classiques.
    """
    from math import exp, lgamma

    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    facteur = exp(
        lgamma(a + b) - lgamma(a) - lgamma(b) + a * __import__("math").log(x)
        + b * __import__("math").log(1 - x)
    )
    if x < (a + 1) / (a + b + 2):
        return facteur * _betacf(a, b, x) / a
    return 1 - facteur * _betacf(b, a, 1 - x) / b


def _betacf(a: float, b: float, x: float, iterations: int = 300) -> float:
    """Fraction continue de la bêta incomplète (algorithme de Lentz modifié)."""
    minuscule = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < minuscule:
        d = minuscule
    d = 1.0 / d
    resultat = d
    for m in range(1, iterations + 1):
        m2 = 2 * m
        num = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + num * d
        if abs(d) < minuscule:
            d = minuscule
        c = 1.0 + num / c
        if abs(c) < minuscule:
            c = minuscule
        d = 1.0 / d
        resultat *= d * c
        num = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + num * d
        if abs(d) < minuscule:
            d = minuscule
        c = 1.0 + num / c
        if abs(c) < minuscule:
            c = minuscule
        d = 1.0 / d
        delta = d * c
        resultat *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return resultat


def intervalle_jeffreys(k: int, n: int) -> tuple[float, float] | None:
    """Intervalle de crédibilité à 95 % sur une proportion, loi Beta(k+0.5, n-k+0.5).

    Publier κ = 0,17 contre κ = 0,50 sans intervalle laisse croire que les deux valeurs
    sont distinguables. Sur quatre observations, elles ne le sont pas. L'intervalle rend
    visible ce que l'effectif autorise à dire.
    """
    if n <= 0:
        return None
    a, b = k + 0.5, n - k + 0.5

    def quantile(cible: float) -> float:
        bas, haut = 0.0, 1.0
        for _ in range(80):
            milieu = (bas + haut) / 2
            if _betainc(a, b, milieu) < cible:
                bas = milieu
            else:
                haut = milieu
        return (bas + haut) / 2

    return round(quantile(0.025), 4), round(quantile(0.975), 4)


def fisher_exact_unilateral(a: int, b: int, c: int, d: int) -> float:
    """p bilatéral du test exact de Fisher sur une table 2×2, sans dépendance externe.

    Sert à une seule question, mais elle est centrale : l'écart entre le nombre de sites
    que fait basculer le moteur et le nombre que fait basculer l'origine est-il autre
    chose que du bruit ?
    """
    from math import comb

    n = a + b + c + d
    lignes, colonnes = (a + b, c + d), (a + c, b + d)

    def proba(x: int) -> float:
        return (
            comb(lignes[0], x)
            * comb(lignes[1], colonnes[0] - x)
            / comb(n, colonnes[0])
        )

    observe = proba(a)
    total = 0.0
    bas = max(0, colonnes[0] - lignes[1])
    haut = min(lignes[0], colonnes[0])
    for x in range(bas, haut + 1):
        p = proba(x)
        if p <= observe * (1 + 1e-9):
            total += p
    return round(min(1.0, total), 4)


# Rapport


def analyser(
    table: dict[tuple[str, int], dict[str, dict]], exclure: list[str] | None = None
) -> dict[str, Any]:
    cellules = [c for c in ORDRE_CELLULES if any(k[0] == c for k in table)]
    passes = sorted({k[1] for k in table})
    sites = [c["site"] for c in lib.cibles()]
    exclus = {s.lower() for s in (exclure or [])}
    if exclus:
        sites = [s for s in sites if s.lower() not in exclus]

    # -- tableau 15 × cellules, par passe -----------------------------------------------
    tableau: dict[str, dict[str, dict[str, str | None]]] = {}
    for site in sites:
        tableau[site] = {}
        for cellule in cellules:
            tableau[site][cellule] = {
                f"passe{p}": (
                    signature(table[(cellule, p)][site])
                    if (cellule, p) in table and site in table[(cellule, p)]
                    else None
                )
                for p in passes
            }

    # -- κ de Cohen entre chaque paire, passe par passe ---------------------------------
    accords = {}
    for passe in passes:
        for gauche, droite in itertools.combinations(cellules, 2):
            if (gauche, passe) not in table or (droite, passe) not in table:
                continue
            paires, exclus = [], []
            for site in sites:
                og = table[(gauche, passe)].get(site)
                od = table[(droite, passe)].get(site)
                if not og or not od:
                    continue
                ag, ad = accessible(signature(og)), accessible(signature(od))
                if ag is None or ad is None:
                    exclus.append(
                        {"site": site, "gauche": signature(og), "droite": signature(od)}
                    )
                    continue
                paires.append((ag, ad))
            resultat = kappa_cohen(paires)
            resultat["exclus_non_imputables"] = exclus
            resultat["p_permutation"] = permutation_kappa(paires)
            accords[f"p{passe}:{gauche}|{droite}"] = resultat

    # -- les deux facteurs isolés -------------------------------------------------------
    # Le plan croise moteur de rendu (aucun / navigateur) et origine (datacenter /
    # résidentielle). Chaque contraste ne fait varier qu'un facteur, l'autre étant tenu
    # constant : c'est la seule façon d'attribuer un écart à l'un plutôt qu'à l'autre.
    contrastes = {
        "moteur_a_origine_datacenter": ("http_datacenter", "browser_datacenter"),
        "moteur_a_origine_residentielle": ("http_residential", "browser_residential"),
        "origine_a_moteur_http": ("http_datacenter", "http_residential"),
        "origine_a_moteur_navigateur": ("browser_datacenter", "browser_residential"),
    }
    facteurs = {}
    for nom, (gauche, droite) in contrastes.items():
        for passe in passes:
            if (gauche, passe) not in table or (droite, passe) not in table:
                continue
            changent, stables, exclus = [], [], []
            for site in sites:
                og = table[(gauche, passe)].get(site)
                od = table[(droite, passe)].get(site)
                if not og or not od:
                    continue
                ag, ad = accessible(signature(og)), accessible(signature(od))
                if ag is None or ad is None:
                    exclus.append(site)
                    continue
                (changent if ag != ad else stables).append(
                    {"site": site, "de": signature(og), "vers": signature(od)}
                    if ag != ad
                    else site
                )
            facteurs[f"p{passe}:{nom}"] = {
                "gauche": gauche,
                "droite": droite,
                "n_comparables": len(changent) + len(stables),
                "n_changent_de_verdict": len(changent),
                "sites_qui_changent": changent,
                "exclus_non_imputables": exclus,
            }

    # -- les deux facteurs comparés entre eux -------------------------------------------
    # Un site peut être sensible aux deux facteurs (ESPN l'est). Compter les bascules
    # séparément puis les additionner traiterait ce site comme deux observations : la
    # comparaison porte donc sur des ensembles de sites distincts, pas sur des compteurs.
    comparaison = {}
    for passe in passes:
        sensibles_moteur, sensibles_origine = set(), set()
        for cle, bloc in facteurs.items():
            if not cle.startswith(f"p{passe}:"):
                continue
            cible = sensibles_moteur if ":moteur_a_" in cle else sensibles_origine
            cible.update(s["site"] for s in bloc["sites_qui_changent"])
        n_total = len(sites)
        a, b = len(sensibles_moteur), n_total - len(sensibles_moteur)
        c, d = len(sensibles_origine), n_total - len(sensibles_origine)
        comparaison[f"p{passe}"] = {
            "sites_sensibles_au_moteur": sorted(sensibles_moteur),
            "sites_sensibles_a_l_origine": sorted(sensibles_origine),
            "sensibles_aux_deux": sorted(sensibles_moteur & sensibles_origine),
            "n_moteur": a,
            "n_origine": c,
            "n_sites": n_total,
            "fisher_p_bilateral": fisher_exact_unilateral(a, b, c, d),
            "lecture": (
                "p élevé : à cet effectif, l'écart entre les deux facteurs n'est pas "
                "distinguable du hasard. Ce que la campagne établit est que les deux "
                "facteurs existent et portent sur des sites différents, pas leur poids "
                "relatif."
            ),
        }

    # -- κ de crédibilité ---------------------------------------------------------------
    credibilite = {}
    for passe in passes:
        accuse = table.get(("http_datacenter", passe))
        if not accuse:
            continue
        for juge_nom in cellules:
            if juge_nom == "http_datacenter":
                continue
            juge = table.get((juge_nom, passe))
            if not juge:
                continue
            credibilite[f"p{passe}:juge={juge_nom}"] = kappa_credibilite(accuse, juge)

    # -- répétabilité -------------------------------------------------------------------
    repetabilite = {}
    if len(passes) >= 2:
        p1, p2 = passes[0], passes[-1]
        for cellule in cellules:
            if (cellule, p1) not in table or (cellule, p2) not in table:
                continue
            change, total, detail = 0, 0, []
            for site in sites:
                o1 = table[(cellule, p1)].get(site)
                o2 = table[(cellule, p2)].get(site)
                if not o1 or not o2:
                    continue
                total += 1
                s1, s2 = signature(o1), signature(o2)
                if s1 != s2:
                    change += 1
                    detail.append({"site": site, f"passe{p1}": s1, f"passe{p2}": s2})
            repetabilite[cellule] = {
                "n_sites": total,
                "n_signatures_changees": change,
                "taux": round(change / total, 4) if total else None,
                "detail": detail,
            }

    return {
        "cellules_mesurees": cellules,
        "passes": passes,
        "sites_exclus": sorted(exclure or []),
        "n_sites_analyses": len(sites),
        "tableau_sites": tableau,
        "kappa_cohen": accords,
        "facteurs_isoles": facteurs,
        "comparaison_facteurs": comparaison,
        "kappa_credibilite": credibilite,
        "repetabilite": repetabilite,
    }


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--runs", type=Path, default=Path("runs/matrice"))
    parseur.add_argument("--sortie", type=Path, default=Path("runs/matrice/analyse.json"))
    parseur.add_argument(
        "--exclure",
        nargs="*",
        default=None,
        help=(
            "sites retirés de l'analyse. Sert aux analyses de sensibilité : un verdict "
            "dont on a montré qu'il est un faux positif du classifieur ne doit pas être "
            "corrigé en douce dans les données, mais son effet sur les conclusions doit "
            "pouvoir être mesuré."
        ),
    )
    args = parseur.parse_args()

    table = charger(args.runs)
    if not table:
        print(f"aucun run trouvé dans {args.runs}", flush=True)
        return 1
    resultat = analyser(table, args.exclure)
    if args.exclure:
        print(f"sites exclus : {', '.join(args.exclure)}\n")
    args.sortie.write_text(
        json.dumps(resultat, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"cellules : {', '.join(resultat['cellules_mesurees'])}")
    print(f"passes   : {resultat['passes']}\n")
    print("Facteurs isolés (sites changeant de verdict binaire) :")
    for nom, bloc in resultat["facteurs_isoles"].items():
        print(
            f"  {nom:45} {bloc['n_changent_de_verdict']}/{bloc['n_comparables']}"
            + (
                "  → " + ", ".join(s["site"] for s in bloc["sites_qui_changent"])
                if bloc["sites_qui_changent"]
                else ""
            )
        )
    for nom, bloc in resultat.get("comparaison_facteurs", {}).items():
        print(
            f"\n  [{nom}] sensibles au moteur : {bloc['n_moteur']}/{bloc['n_sites']} "
            f"({', '.join(bloc['sites_sensibles_au_moteur']) or 'aucun'})"
            f"\n       sensibles à l'origine : {bloc['n_origine']}/{bloc['n_sites']} "
            f"({', '.join(bloc['sites_sensibles_a_l_origine']) or 'aucun'})"
            f"\n       communs : {', '.join(bloc['sensibles_aux_deux']) or 'aucun'}"
            f"\n       Fisher exact bilatéral : p = {bloc['fisher_p_bilateral']}"
        )
    print("\nκ de Cohen :")
    for nom, bloc in resultat["kappa_cohen"].items():
        print(
            f"  {nom:55} κ={bloc['kappa']} n={bloc['n']} "
            f"p={bloc.get('p_permutation')}"
        )
    print("\nκ de crédibilité (Laplace) :")
    for nom, bloc in resultat["kappa_credibilite"].items():
        print(
            f"  {nom:40} n={bloc['n_refus_annonces']} k={bloc['k_refus_confirmes']} "
            f"κ={bloc['kappa_laplace']}"
        )
    if resultat["repetabilite"]:
        print("\nRépétabilité passe 1 → passe 2 :")
        for cellule, bloc in resultat["repetabilite"].items():
            print(f"  {cellule:25} {bloc['n_signatures_changees']}/{bloc['n_sites']} changent")
    print(f"\n→ {args.sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
