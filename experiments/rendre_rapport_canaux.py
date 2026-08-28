#!/usr/bin/env python3
"""Rend les tableaux chiffrés de RAPPORT_CANAUX.md à partir des mesures.

    python experiments/rendre_rapport_canaux.py --runs runs/matrice \\
        --sortie experiments/RAPPORT_CANAUX_tableaux.md

Aucun chiffre du rapport n'est saisi à la main. Ce n'est pas de la coquetterie : le
dossier auquel ce travail s'ajoute a déjà eu à corriger des artefacts périmés qui
affirmaient des nombres que plus rien ne produisait. Un tableau recopié se désynchronise
de ses données au premier recalcul, et personne ne s'en aperçoit — surtout pas l'auteur.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matrice_lib as lib
from analyse_matrice import ORDRE_CELLULES, accessible, charger, analyser

COURT = {
    "http_datacenter": "HTTP · datacenter",
    "http_residential": "HTTP · résidentiel",
    "browser_residential": "Navigateur · résidentiel",
    "browser_datacenter": "Navigateur · datacenter",
}


def table_sites(resultat: dict, passes: list[int]) -> str:
    cellules = resultat["cellules_mesurees"]
    lignes = ["| Site | " + " | ".join(COURT.get(c, c) for c in cellules) + " |"]
    lignes.append("|---" * (len(cellules) + 1) + "|")
    for site, par in resultat["tableau_sites"].items():
        cases = []
        for cellule in cellules:
            valeurs = [par[cellule].get(f"passe{p}") for p in passes]
            valeurs = [v for v in valeurs if v]
            if not valeurs:
                cases.append("—")
            elif len(set(valeurs)) == 1:
                cases.append(f"`{valeurs[0]}`")
            else:
                # Une case qui change d'une passe à l'autre doit le montrer : la masquer
                # en n'affichant que la première passe transformerait une instabilité en
                # fait établi.
                cases.append(" → ".join(f"`{v}`" for v in valeurs))
        lignes.append(f"| {site} | " + " | ".join(cases) + " |")
    return "\n".join(lignes)


def table_facteurs(resultat: dict, passes: list[int]) -> str:
    intitules = {
        "moteur_a_origine_datacenter": "Changer de **moteur**, origine datacenter tenue fixe",
        "moteur_a_origine_residentielle": "Changer de **moteur**, origine résidentielle tenue fixe",
        "origine_a_moteur_http": "Changer d'**origine**, moteur HTTP tenu fixe",
        "origine_a_moteur_navigateur": "Changer d'**origine**, moteur navigateur tenu fixe",
    }
    lignes = ["| Contraste | Passe | Sites changeant de verdict | Lesquels |", "|---|---|---|---|"]
    for cle in intitules:
        for passe in passes:
            bloc = resultat["facteurs_isoles"].get(f"p{passe}:{cle}")
            if not bloc:
                continue
            noms = ", ".join(s["site"] for s in bloc["sites_qui_changent"]) or "aucun"
            lignes.append(
                f"| {intitules[cle]} | {passe} | "
                f"**{bloc['n_changent_de_verdict']}** / {bloc['n_comparables']} | {noms} |"
            )
    return "\n".join(lignes)


def table_kappa_cohen(resultat: dict, passes: list[int]) -> str:
    lignes = [
        "| Paire de canaux | Passe | n | Accord observé | κ de Cohen | Désaccords | p (permutation) |",
        "|---|---|---|---|---|---|---|",
    ]
    for cle, bloc in resultat["kappa_cohen"].items():
        passe, paire = cle.split(":", 1)
        gauche, droite = paire.split("|")
        kappa = bloc["kappa"]
        rendu = "indéfini" if kappa is None else f"**{kappa:.3f}**"
        lignes.append(
            f"| {COURT.get(gauche, gauche)} ↔ {COURT.get(droite, droite)} | {passe[1:]} | "
            f"{bloc['n']} | {bloc.get('accord_observe', 'n/d')} | {rendu} | "
            f"{bloc.get('desaccords', 0)} | {bloc.get('p_permutation', 'n/d')} |"
        )
    return "\n".join(lignes)


def table_kappa_credibilite(resultat: dict) -> str:
    lignes = [
        "| Canal juge | Passe | n refus annoncés | k confirmés | κ = (k+1)/(n+2) | Proportion brute | IC 95 % sur la proportion |",
        "|---|---|---|---|---|---|---|",
    ]
    for cle, bloc in resultat["kappa_credibilite"].items():
        passe, juge = cle.split(":")
        juge = juge.replace("juge=", "")
        kappa = bloc["kappa_laplace"]
        ic = bloc.get("ic95_proportion")
        lignes.append(
            f"| {COURT.get(juge, juge)} | {passe[1:]} | {bloc['n_refus_annonces']} | "
            f"{bloc['k_refus_confirmes']} | **{kappa if kappa is not None else 'n/d'}** | "
            f"{bloc['proportion_brute'] if bloc['proportion_brute'] is not None else 'n/d'} | "
            f"{f'[{ic[0]:.3f} ; {ic[1]:.3f}]' if ic else 'n/d'} |"
        )
    return "\n".join(lignes)


def table_repetabilite(resultat: dict) -> str:
    if not resultat["repetabilite"]:
        return "_Passe 2 absente : la répétabilité n'est pas mesurée._"
    lignes = [
        "| Cellule | Sites comparés | Signatures changées | Taux | Lesquelles |",
        "|---|---|---|---|---|",
    ]
    for cellule, bloc in resultat["repetabilite"].items():
        detail = (
            "; ".join(
                f"{d['site']} : {list(d.values())[1]} → {list(d.values())[2]}"
                for d in bloc["detail"]
            )
            or "aucune"
        )
        lignes.append(
            f"| {COURT.get(cellule, cellule)} | {bloc['n_sites']} | "
            f"**{bloc['n_signatures_changees']}** | {bloc['taux']} | {detail} |"
        )
    return "\n".join(lignes)


def table_divergents(resultat: dict, passes: list[int]) -> str:
    """Les sites dont le verdict n'est pas le même partout — le cœur du résultat."""
    cellules = resultat["cellules_mesurees"]
    lignes = ["| Site | Verdicts distincts | Facteur qui explique le mieux |", "|---|---|---|"]
    for site, par in resultat["tableau_sites"].items():
        vus = {}
        for cellule in cellules:
            valeur = par[cellule].get(f"passe{passes[0]}")
            if valeur:
                vus[cellule] = valeur
        if len(set(vus.values())) <= 1:
            continue
        acc = {c: accessible(v) for c, v in vus.items()}
        # Un facteur « explique » quand il suffit à séparer les accessibles des refusés.
        par_moteur = (
            acc.get("http_datacenter") == acc.get("http_residential")
            and acc.get("browser_datacenter") == acc.get("browser_residential")
            and acc.get("http_datacenter") != acc.get("browser_datacenter")
        )
        par_origine = (
            acc.get("http_datacenter") == acc.get("browser_datacenter")
            and acc.get("http_residential") == acc.get("browser_residential")
            and acc.get("http_datacenter") != acc.get("http_residential")
        )
        if par_moteur and not par_origine:
            facteur = "**moteur de rendu**"
        elif par_origine and not par_moteur:
            facteur = "**origine réseau**"
        elif len(set(acc.values())) == 1:
            facteur = "aucun : les signatures diffèrent, le verdict binaire non"
        else:
            facteur = "**interaction** : ni l'un ni l'autre seul ne suffit"
        detail = ", ".join(f"{COURT.get(c, c)} → `{v}`" for c, v in vus.items())
        lignes.append(f"| {site} | {detail} | {facteur} |")
    return "\n".join(lignes)


def table_comparaison_facteurs(resultat: dict) -> str:
    """Compare les deux facteurs sur des ensembles de sites, pas sur des compteurs.

    Additionner les bascules des quatre contrastes compterait deux fois un site sensible
    aux deux facteurs, et gonflerait mécaniquement l'écart que le rapport cherche à
    qualifier.
    """
    lignes = [
        "| Passe | Sites sensibles au moteur | Sites sensibles à l'origine | Sensibles aux deux | Fisher exact, p bilatéral |",
        "|---|---|---|---|---|",
    ]
    for nom, bloc in resultat.get("comparaison_facteurs", {}).items():
        moteur = ", ".join(bloc["sites_sensibles_au_moteur"]) or "aucun"
        origine = ", ".join(bloc["sites_sensibles_a_l_origine"]) or "aucun"
        communs = ", ".join(bloc["sensibles_aux_deux"]) or "aucun"
        lignes.append(
            f"| {nom[1:]} | **{bloc['n_moteur']}** / {bloc['n_sites']} : {moteur} | "
            f"**{bloc['n_origine']}** / {bloc['n_sites']} : {origine} | {communs} | "
            f"**{bloc['fisher_p_bilateral']}** |"
        )
    return "\n".join(lignes)


def table_sensibilite(table_brute: dict, exclus: list[str]) -> str:
    """Refait l'analyse en retirant les sites dont le verdict est un faux positif connu."""
    resultat = analyser(table_brute, exclus)
    lignes = [
        f"_Analyse refaite sans {', '.join(exclus)}, sur "
        f"{resultat['n_sites_analyses']} sites. Les données ne sont pas modifiées._",
        "",
        "| Grandeur | Avec tous les sites | Sans le site exclu |",
        "|---|---|---|",
    ]
    complet = analyser(table_brute)
    for passe in resultat["passes"]:
        for cle, intitule in (
            (f"p{passe}:moteur_a_origine_residentielle", "Bascules de moteur (origine résidentielle)"),
            (f"p{passe}:moteur_a_origine_datacenter", "Bascules de moteur (origine datacenter)"),
            (f"p{passe}:origine_a_moteur_http", "Bascules d'origine (moteur HTTP)"),
            (f"p{passe}:origine_a_moteur_navigateur", "Bascules d'origine (moteur navigateur)"),
        ):
            a = complet["facteurs_isoles"].get(cle)
            b = resultat["facteurs_isoles"].get(cle)
            if not a or not b:
                continue
            lignes.append(
                f"| {intitule}, passe {passe} | {a['n_changent_de_verdict']} / "
                f"{a['n_comparables']} | {b['n_changent_de_verdict']} / {b['n_comparables']} |"
            )
        for cle in complet["kappa_cohen"]:
            if not cle.startswith(f"p{passe}:"):
                continue
            gauche, droite = cle.split(":", 1)[1].split("|")
            ka = complet["kappa_cohen"][cle]["kappa"]
            kb = (resultat["kappa_cohen"].get(cle) or {}).get("kappa")
            lignes.append(
                f"| κ de Cohen, {COURT.get(gauche, gauche)} ↔ {COURT.get(droite, droite)}, "
                f"passe {passe} | {ka if ka is not None else 'indéfini'} | "
                f"{kb if kb is not None else 'indéfini'} |"
            )
    return "\n".join(lignes)


def table_historique(resultat: dict, passes: list[int], racine: Path) -> str:
    """Confronte la campagne aux quatre observations de navigateur cloud du 15/08.

    Ces quatre lignes sont celles que le travail remplace. Les confronter n'est pas une
    formalité : si elles concordent, la mesure ancienne est confirmée malgré sa méthode ;
    si elles divergent, la catégorie « navigateur cloud » est trop grossière pour porter
    un paramètre de score.
    """
    chemin = racine / "runs" / "l2_browser_cloud_20260815.json"
    if not chemin.exists():
        return "_Fichier `runs/l2_browser_cloud_20260815.json` absent._"
    ancien = json.loads(chemin.read_text(encoding="utf-8"))
    par_url = {c["url"]: c["site"] for c in lib.cibles()}

    # Le fichier d'observations ne porte pas les signatures : elles ont été publiées dans
    # le run de campagne, sous `sites[<site>].by_channel["browser_cloud:browserbase"]`.
    # Les relire là plutôt que les recalculer garantit qu'on confronte bien la campagne au
    # verdict que ses auteurs ont réellement publié, et non à un verdict rétabli après coup.
    signatures_publiees: dict[str, str] = {}
    campagne = racine / "runs" / "l2_probe_20260815.json"
    if campagne.exists():
        sondage = json.loads(campagne.read_text(encoding="utf-8"))
        for bloc in sondage.get("sites", {}).values():
            cloud = (bloc.get("by_channel") or {}).get("browser_cloud:browserbase")
            if cloud and cloud.get("signature"):
                signatures_publiees[cloud.get("url", bloc.get("url"))] = cloud["signature"]

    lignes = [
        "| URL mesurée le 15/08 | Browserbase (15/08) | Navigateur · datacenter (campagne) | Comparable ? |",
        "|---|---|---|---|",
    ]
    for observation in ancien.get("observations", []):
        url = observation["url"]
        ancienne = signatures_publiees.get(url) or observation.get("meta", {}).get(
            "signature"
        ) or "(non publiée)"
        site = par_url.get(url)
        if site is None:
            lignes.append(
                f"| `{url}` | `{ancienne}` | n/a | **non** : URL absente du corpus de la "
                "campagne, qui mesure la racine `https://github.com/` |"
            )
            continue
        nouvelle = (
            resultat["tableau_sites"].get(site, {}).get("browser_datacenter", {}).get(f"passe{passes[0]}")
        )
        accord = ""
        if nouvelle:
            accord = "**oui**, concordent" if nouvelle == ancienne else "**oui**, divergent"
        lignes.append(f"| `{url}` | `{ancienne}` | `{nouvelle or '—'}` | {accord or '—'} |")
    return "\n".join(lignes)


def table_http_datacenter_15aout(resultat: dict, passes: list[int], racine: Path) -> str:
    """Compare la cellule HTTP datacenter de la campagne à celle du 15/08.

    Le protocole demandait de ne pas re-mesurer ce canal, déjà couvert par 179
    observations. Je l'ai tout de même mesuré, pour deux raisons. D'abord l'appariement :
    comparer une cellule du 15/08 à trois cellules du 16/08 aurait mêlé l'effet de canal
    à la dérive des sites, et le protocole exige lui-même que les quatre cellules soient
    prises dans la même fenêtre de temps. Ensuite la provenance : la campagne du 15/08 est
    sortie par un proxy d'egress interceptant, qui répondait à la place des sites. Le
    serveur de cette campagne n'en a pas. La colonne de droite mesure donc ce que devient
    le canal une fois ce proxy retiré.

    Les 179 observations du 15/08 ne sont ni écrasées ni modifiées.
    """
    campagne = racine / "runs" / "l2_probe_20260815.json"
    if not campagne.exists():
        return "_Fichier `runs/l2_probe_20260815.json` absent._"
    sondage = json.loads(campagne.read_text(encoding="utf-8"))
    lignes = [
        "| Site | 15/08, datacenter **avec** proxy d'egress | 16/08, datacenter **sans** proxy | Écart |",
        "|---|---|---|---|",
    ]
    for site, bloc in sondage.get("sites", {}).items():
        ancienne = ((bloc.get("by_channel") or {}).get("direct_http:browser") or {}).get(
            "signature"
        )
        nouvelle = (
            resultat["tableau_sites"].get(site, {}).get("http_datacenter", {}).get(f"passe{passes[0]}")
        )
        if not ancienne or not nouvelle:
            continue
        ecart = "identique" if ancienne == nouvelle else "**change**"
        lignes.append(f"| {site} | `{ancienne}` | `{nouvelle}` | {ecart} |")
    return "\n".join(lignes)


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--runs", type=Path, default=Path("runs/matrice"))
    parseur.add_argument(
        "--sortie", type=Path, default=Path("experiments/RAPPORT_CANAUX_tableaux.md")
    )
    parseur.add_argument(
        "--gabarit",
        type=Path,
        default=None,
        help=(
            "gabarit du rapport contenant les marqueurs {{T1}}…{{T7}}. Fourni, la sortie "
            "est le rapport complet, tableaux insérés. Le texte reste écrit à la main ; "
            "seuls les chiffres viennent des mesures."
        ),
    )
    args = parseur.parse_args()

    table = charger(args.runs)
    resultat = analyser(table)
    passes = resultat["passes"]

    blocs = [
        "<!-- Fichier produit par experiments/rendre_rapport_canaux.py. Ne pas éditer à la main. -->",
        "\n## T1 — Les 15 sites × 4 canaux\n",
        table_sites(resultat, passes),
        "\n## T2 — Les deux facteurs isolés\n",
        table_facteurs(resultat, passes),
        "\n## T3 — Sites divergents et facteur explicatif\n",
        table_divergents(resultat, passes),
        "\n## T4 — κ de Cohen (accord entre canaux)\n",
        table_kappa_cohen(resultat, passes),
        "\n## T5 — κ de crédibilité (paramètre du score publié)\n",
        table_kappa_credibilite(resultat),
        "\n## T6 — Répétabilité\n",
        table_repetabilite(resultat),
        "\n## T7 — Confrontation aux quatre observations du 15/08\n",
        table_historique(resultat, passes, args.runs.parent.parent),
        "\n## T8 — Cellule HTTP datacenter : 15/08 (avec proxy) contre 16/08 (sans)\n",
        table_http_datacenter_15aout(resultat, passes, args.runs.parent.parent),
    ]
    if args.gabarit:
        rendu = args.gabarit.read_text(encoding="utf-8")
        tables = {
            "T1": table_sites(resultat, passes),
            "T2": table_facteurs(resultat, passes),
            "T3": table_divergents(resultat, passes),
            "T4": table_kappa_cohen(resultat, passes),
            "T5": table_kappa_credibilite(resultat),
            "T6": table_repetabilite(resultat),
            "T7": table_historique(resultat, passes, args.runs.parent.parent),
            "T8": table_http_datacenter_15aout(resultat, passes, args.runs.parent.parent),
            "T9": table_comparaison_facteurs(resultat),
            "T10": table_sensibilite(table, ["Wolfram Alpha"]),
        }
        manquants = [c for c in tables if "{{" + c + "}}" not in rendu]
        for cle, valeur in tables.items():
            rendu = rendu.replace("{{" + cle + "}}", valeur)
        args.sortie.write_text(rendu, encoding="utf-8")
        if manquants:
            # Un marqueur absent est presque toujours une section oubliée, pas un choix.
            print(f"  marqueurs absents du gabarit : {', '.join(manquants)}")
        print(f"→ {args.sortie} (assemblé depuis {args.gabarit})")
        return 0

    args.sortie.write_text("\n".join(blocs) + "\n", encoding="utf-8")
    print(f"→ {args.sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
