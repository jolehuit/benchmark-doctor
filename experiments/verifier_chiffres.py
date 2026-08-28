#!/usr/bin/env python3
"""Vérifie que chaque chiffre publié est celui de son artefact source.

Un chiffre recopié à la main dans un rapport devient, à la première correction oubliée, un
jeu de chiffres de plus. Ce script relit les fichiers de `runs/`, `exports/` et `data/` et
compare chaque valeur publiée à celle qu'ils portent. Il ne recalcule rien, à l'exception
des lifts et des p-valeurs contre `supprimee_1`, que la grille de validation ne stocke pas.

Exécution : hors ligne, déterministe, 0,00 $, moins d'une seconde.

    python3 experiments/verifier_chiffres.py

Sortie : une ligne par chiffre, et un code de retour non nul au premier écart.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent


def load(rel: str) -> Any:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def jsonl(rel: str) -> list[dict[str, Any]]:
    return [json.loads(l) for l in (ROOT / rel).read_text(encoding="utf-8").splitlines() if l.strip()]


#: (repère, libellé, valeur publiée, fichier qui en fait foi, accesseur)
CHECKS: list[tuple[str, str, Any, str, Callable[[Any], Any]]] = [
    # -- 1. Carte de santé canonique -----------------------------------------------------
    ("1.1", "corpus : nombre de tâches", 643, "runs/health_20260815.json",
     lambda d: d["meta"]["n_tasks"]),
    ("1.1", "corpus : empreinte sha256 (12 premiers)", "69b19fd86c23", "runs/health_20260815.json",
     lambda d: d["meta"]["corpus_sha256"][:12]),
    ("1.2", "stabilité moyenne", 0.5851, "runs/health_20260815.json",
     lambda d: d["summary"]["mean_stability"]),
    ("1.2", "stabilité moyenne, détecteurs seuls", 0.6123, "runs/health_20260815.json",
     lambda d: d["summary"]["mean_stability_detector_only"]),
    ("1.3", "notes A/B/C/D", {"A": 210, "B": 138, "C": 185, "D": 110},
     "runs/health_20260815.json", lambda d: d["summary"]["grades"]),
    ("1.4", "part du corpus sous la note A", 0.6734, "runs/health_20260815.json",
     lambda d: d["summary"]["rate_below_A"]),
    ("1.5", "coût de la campagne (USD)", 0.262982, "runs/health_20260815.json",
     lambda d: d["cost"]["total_usd"]),
    ("1.5", "coût par tâche (USD)", 0.00040899, "runs/health_20260815.json",
     lambda d: d["cost"]["usd_per_task"]),
    ("1.6", "κ retenu (crédibilité HTTP datacenter)", 0.4, "runs/health_20260815.json",
     lambda d: d["scoring_model"]["channel_credibility"]["http_datacenter"]),
    ("1.7", "échelle de notes", {"A": 0.75, "B": 0.5, "C": 0.25, "D": 0.0},
     "runs/health_20260815.json", lambda d: d["scoring_model"]["grade_thresholds"]),
    ("1.8", "Booking : tâches sous A", 44, "runs/health_20260815.json",
     lambda d: d["by_site"]["Booking"]["n_below_A"]),
    ("1.8", "Booking : note D", 33, "runs/health_20260815.json",
     lambda d: d["by_site"]["Booking"]["grades"]["D"]),
    ("1.8", "Google Flights : tâches sous A", 42, "runs/health_20260815.json",
     lambda d: d["by_site"]["Google Flights"]["n_below_A"]),

    # -- 2. Sensibilité, dans la configuration canonique ----------------------------------
    ("2.1", "rejeu hors ligne identique à la carte publiée", True,
     "runs/carte_canonique_20260815.json", lambda d: d["controle_de_rejeu"]["identique"]),
    ("2.2", "κ = 0,0 → tâches en D", 83, "runs/carte_canonique_20260815.json",
     lambda d: [r for r in d["sensibilite_kappa"] if r["kappa"] == 0.0][0]["note_D"]),
    ("2.2", "κ = 0,2 → tâches en D", 100, "runs/carte_canonique_20260815.json",
     lambda d: [r for r in d["sensibilite_kappa"] if r["kappa"] == 0.2][0]["note_D"]),
    ("2.2", "κ = 0,4 (retenu) → tâches en D", 110, "runs/carte_canonique_20260815.json",
     lambda d: [r for r in d["sensibilite_kappa"] if r["kappa"] == 0.4][0]["note_D"]),
    ("2.2", "κ = 1,0 → tâches en D", 177, "runs/carte_canonique_20260815.json",
     lambda d: [r for r in d["sensibilite_kappa"] if r["kappa"] == 1.0][0]["note_D"]),
    ("2.3", "tâches multi-catégories", 510, "runs/carte_canonique_20260815.json",
     lambda d: d["sensibilite_agregation"]["n_taches_multi_categories"]),
    ("2.3", "changements de note OU bruité → maximum", 122,
     "runs/carte_canonique_20260815.json",
     lambda d: d["sensibilite_agregation"]["n_changements_de_note"]),
    ("2.4", "échelle héritée sur la carte canonique", {"A": 193, "B": 124, "C": 146, "D": 180},
     "runs/carte_canonique_20260815.json",
     lambda d: d["sensibilite_echelle_de_notes"]["distribution_heritee"]),

    # -- 3. Couche L1 --------------------------------------------------------------------
    ("3.1", "L1 seuil HIGH : tâches signalées", 73, "runs/health_webvoyager_20260815.json",
     lambda d: d["summary"]["n_flagged"]),
    ("3.1", "L1 seuil HIGH : taux de signalement", 0.1135,
     "runs/health_webvoyager_20260815.json", lambda d: d["summary"]["flag_rate"]),
    ("3.2", "L1 seul : notes après unification de l'échelle",
     {"A": 509, "B": 61, "C": 73, "D": 0}, "runs/health_webvoyager_20260815.json",
     lambda d: d["summary"]["grades"]),
    ("3.3", "L1/HIGH contre signalee_1 : précision", 0.9863,
     "runs/validation_ablation_20260815.json",
     lambda d: d["ablation"]["L1"]["seuils"]["high"]["contre"]["signalee_1"]["precision"]),
    ("3.3", "L1/HIGH contre signalee_1 : rappel", 0.426,
     "runs/validation_ablation_20260815.json",
     lambda d: d["ablation"]["L1"]["seuils"]["high"]["contre"]["signalee_1"]["recall"]),
    ("3.4", "L1/HIGH contre supprimee_1 : précision", 0.1644,
     "runs/validation_ablation_20260815.json",
     lambda d: d["ablation"]["L1"]["seuils"]["high"]["contre"]["supprimee_1"]["precision"]),
    ("3.5", "L1+L2+L3/MEDIUM : tâches signalées", 424,
     "runs/validation_ablation_20260815.json",
     lambda d: d["ablation"]["L1+L2+L3"]["seuils"]["medium"]["n_flagged"]),
    ("3.5", "L1+L2+L3/MEDIUM contre signalee_1 : rappel", 0.8935,
     "runs/validation_ablation_20260815.json",
     lambda d: d["ablation"]["L1+L2+L3"]["seuils"]["medium"]["contre"]["signalee_1"]["recall"]),

    # -- 4. Validation hors échantillon ---------------------------------------------------
    ("4.1", "hors échantillon : verdict L1/HIGH", "non validable hors échantillon",
     "runs/validation_hors_echantillon_20260816.json",
     lambda d: d["conclusions"]["L1_high"]["verdict"]),
    ("4.2", "hors échantillon : verdict L1/MEDIUM",
     "tient hors échantillon, y compris après correction du groupement par site",
     "runs/validation_hors_echantillon_20260816.json",
     lambda d: d["conclusions"]["L1_medium"]["verdict"]),

    # -- 5. Accord inter-annotateurs -----------------------------------------------------
    ("5.1", "tâches signalées par au moins 1 annotateur", 169, "data/ground_truth.json",
     lambda d: d["statistiques"]["couverture"]["signalee_par_au_moins_1"]),
    ("5.1", "tâches signalées par les 6", 68, "data/ground_truth.json",
     lambda d: d["statistiques"]["couverture"]["signalee_par_tous"]),
    ("5.1", "tâches jamais signalées", 474, "data/ground_truth.json",
     lambda d: d["statistiques"]["couverture"]["jamais_signalee"]),
    ("5.2", "Fleiss κ, 3 catégories, 6 annotateurs", 0.7371, "data/ground_truth.json",
     lambda d: d["statistiques"]["accord"]["fleiss_3categories"]["kappa"]),
    ("5.2", "Fleiss κ, exclusion seule", 0.5136, "data/ground_truth.json",
     lambda d: d["statistiques"]["accord"]["fleiss_exclusion"]["kappa"]),
    ("5.3", "tâches réécrites par ≥ 2 annotateurs", 87, "data/ground_truth.json",
     lambda d: d["statistiques"]["reparations"]["taches_reecrites_par_2_annotateurs_ou_plus"]),
    ("5.3", "dont millésimes divergents (mesure exigeante)", 76, "data/ground_truth.json",
     lambda d: d["statistiques"]["reparations"]["dont_millesimes_divergents"]),
    ("5.3", "variantes distinctes en moyenne", 4.0, "data/ground_truth.json",
     lambda d: d["statistiques"]["reparations"]["variantes_moyennes"]),

    # -- 6. Longitudinal -----------------------------------------------------------------
    ("6.1", "correctifs Magnitude datés déjà périmés", 65, "runs/longitudinal_20260815.json",
     lambda d: d["rouille_des_correctifs"]["resultats"]["reecritures_deja_perimees_texte"]),
    ("6.1", "correctifs conservant une date future", 0, "runs/longitudinal_20260815.json",
     lambda d: d["rouille_des_correctifs"]["resultats"]["encore_une_date_future"]),
    ("6.2", "taux annuel de décadence retenu (A2)", 0.0674, "runs/longitudinal_20260815.json",
     lambda d: d["taux_de_decadence"]["recommandation_pour_le_memoire"]["valeur"]),
    ("6.3", "browser-use : corpus réel après exclusions", 588,
     "runs/longitudinal_20260815.json",
     lambda d: [f for f in d["sante_des_forks"]["forks"] if f["fork"] == "browser-use"][0]["n_taches"]),
    ("6.3", "browser-use : flags à sa naissance (%)", 0.5, "runs/longitudinal_20260815.json",
     lambda d: [f for f in d["sante_des_forks"]["forks"] if f["fork"] == "browser-use"][0]["signalees_a_sa_naissance_high_pct"]),
    ("6.4", "Online-Mind2Web : tâches distinctes remplacées", 52,
     "runs/longitudinal_20260815.json",
     lambda d: d["controle_online_mind2web"]["taches_distinctes_remplacees"]),
    ("6.5", "Alumnium 03/2026 : corpus réel", 619, "runs/longitudinal_20260815.json",
     lambda d: [f for f in d["sante_des_forks"]["forks"] if f["fork"].startswith("Alumnium")][0]["n_taches"]),
    ("6.5", "Alumnium 03/2026 : flags au 15/08 (%)", 8.9, "runs/longitudinal_20260815.json",
     lambda d: [f for f in d["sante_des_forks"]["forks"] if f["fork"].startswith("Alumnium")][0]["signalees_au_15_08_2026_high_pct"]),

    # -- 8. Taux de signalement par catégorie (ce ne sont PAS des prévalences) -------------
    ("8.1", "T5 ambiguïté : taux de signalement", 0.3733, "runs/health_20260815.json",
     lambda d: d["by_category"]["T5_ambiguity"]["rate"]),
    ("8.1", "T2 dérive de contenu : taux de signalement", 0.2908, "runs/health_20260815.json",
     lambda d: d["by_category"]["T2_content_drift"]["rate"]),
    ("8.1", "T7 fragilité d'évaluation : taux de signalement", 0.2535,
     "runs/health_20260815.json", lambda d: d["by_category"]["T7_eval_brittleness"]["rate"]),
    ("8.2", "tâches du noyau notées sous A (indécidées)", 273,
     "exports/webvoyager_verified_v0.1.stats.json",
     lambda d: d["desaccord_outil_praticiens"]["noyau_sous_A"]),
    ("8.2", "tâches portant un patch publié", 116,
     "exports/webvoyager_verified_v0.1.stats.json",
     lambda d: d["patches"]["n_taches_avec_patch_publie"]),

    # -- 7. Export WebVoyager-Verified ---------------------------------------------------
    ("7.1", "lignes de l'export", 643, "exports/webvoyager_verified_v0.1.stats.json",
     lambda d: d["n_taches"]),
    ("7.2", "sous-ensemble consensuel", 563, "exports/webvoyager_verified_v0.1.stats.json",
     lambda d: d["n_sous_ensemble_executable"]),
    ("7.3", "dont énoncés déjà périmés", 84, "exports/webvoyager_verified_v0.1.stats.json",
     lambda d: d["enonces_perimes"]["n_enonces_perimes"]),
    ("7.3", "taux d'énoncés périmés", 0.1492, "exports/webvoyager_verified_v0.1.stats.json",
     lambda d: d["enonces_perimes"]["taux_enonces_perimes"]),
    ("7.4", "énoncés d'origine encore sains (chiffre de référence)", 479,
     "exports/webvoyager_verified_v0.1.stats.json",
     lambda d: d["enonces_perimes"]["n_enonce_original_sain"]),
    ("7.5", "lançables après patch canonique valide", 536,
     "exports/webvoyager_verified_v0.1.stats.json",
     lambda d: d["enonces_perimes"]["n_lancable_apres_patch_valide"]),
    ("7.6", "patches canoniques déjà périmés (corpus entier)", 20,
     "exports/webvoyager_verified_v0.1.stats.json",
     lambda d: d["patches"]["n_patches_deja_perimes"]),
    ("7.6", "patches périmés dans le sous-ensemble consensuel", 14,
     "exports/webvoyager_verified_v0.1.stats.json",
     lambda d: d["enonces_perimes"]["n_patches_perimes_dans_le_sous_ensemble"]),
    ("7.7", "chaque ligne porte le champ `enonce_perime`", 643,
     "exports/webvoyager_verified_v0.1.jsonl",
     lambda rows: sum(1 for r in rows if "enonce_perime" in r)),

    # -- 0. Statut éditorial des cartes (la configuration canonique elle-même) ------------
    ("0.1", "carte canonique estampillée", "canonique", "runs/health_20260815.json",
     lambda d: d["statut_editorial"]["statut"]),
    ("0.2", "carte tfidf marquée exploratoire", "configuration exploratoire, non citée",
     "runs/health_card_webvoyager_20260816.json",
     lambda d: d["statut_editorial"]["mention"]),
    ("0.2", "carte sans solvabilité marquée exploratoire",
     "configuration exploratoire, non citée",
     "runs/health_card_webvoyager_llm_20260816.json",
     lambda d: d["statut_editorial"]["mention"]),
    ("0.3", "tables de sensibilité non canoniques marquées exploratoires",
     "configuration exploratoire, non citée", "runs/scoring_model_20260816.json",
     lambda d: d["statut_editorial"]["mention"]),
]


def _p_binomiale(k: int, n: int, p0: float) -> float:
    """P(X ≥ k) sous Binomiale(n, p0) — test unilatéral, sans dépendance externe."""
    import math

    return sum(math.comb(n, i) * p0**i * (1 - p0) ** (n - i) for i in range(k, n + 1))


def _supprimee_1(cfg: str, seuil: str, quoi: str) -> Callable[[Any], Any]:
    """Lift ou p-valeur d'une configuration contre la vérité `supprimee_1`.

    Ces deux quantités ne sont stockées nulle part : la grille de validation publie P, R et
    F1 mais jamais la précision attendue au hasard, sans laquelle une précision affichée ne
    dit ni bien ni mal. C'est l'absence relevée par `experiments/CONTRE_VERIFICATION.md`, et
    la seule façon de garantir qu'elle ne se reproduise pas est de la recalculer ici à chaque
    contrôle.
    """

    def acces(d: Any) -> float:
        bloc = d["ablation"][cfg]["seuils"][seuil]
        prevalence = d["ground_truths"]["supprimee_1"]["n"] / d["meta"]["n_tasks"]
        contre = bloc["contre"]["supprimee_1"]
        if quoi == "lift":
            return round(contre["precision"] / prevalence, 2)
        return round(_p_binomiale(contre["tp"], bloc["n_flagged"], prevalence), 3)

    return acces


CHECKS += [
    ("3.6", "supprimee_1 · L1/high : lift", 1.36, "runs/validation_ablation_20260815.json",
     _supprimee_1("L1", "high", "lift")),
    ("3.6", "supprimee_1 · L1/high : p unilatérale", 0.17,
     "runs/validation_ablation_20260815.json", _supprimee_1("L1", "high", "p")),
    ("3.6", "supprimee_1 · L1+L2+L3/high : lift", 1.35,
     "runs/validation_ablation_20260815.json", _supprimee_1("L1+L2+L3", "high", "lift")),
    ("3.6", "supprimee_1 · L1+L2+L3/high : p unilatérale", 0.022,
     "runs/validation_ablation_20260815.json", _supprimee_1("L1+L2+L3", "high", "p")),
    ("3.6", "supprimee_1 · L1+L2+L3/medium : p unilatérale", 0.053,
     "runs/validation_ablation_20260815.json", _supprimee_1("L1+L2+L3", "medium", "p")),
]


def approx(a: Any, b: Any) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 5e-5
        except (TypeError, ValueError):
            return False
    return a == b


def main() -> int:
    echecs: list[str] = []
    par_section: dict[str, int] = {}
    for section, libelle, attendu, fichier, acces in CHECKS:
        try:
            data = jsonl(fichier) if fichier.endswith(".jsonl") else load(fichier)
            obtenu = acces(data)
        except Exception as exc:  # noqa: BLE001
            echecs.append(f"{section} {libelle} : LECTURE IMPOSSIBLE ({exc})")
            print(f"  ERREUR  {section:<6} {libelle:<52} {fichier}")
            continue
        ok = approx(attendu, obtenu)
        par_section[section] = par_section.get(section, 0) + 1
        if not ok:
            echecs.append(f"{section} {libelle} : publié {attendu!r}, source {obtenu!r} ({fichier})")
        print(f"  {'OK ' if ok else 'ÉCART'}    {section:<6} {libelle:<52} {attendu}")

    print()
    print(f"{len(CHECKS)} chiffres vérifiés sur {len(set(c[3] for c in CHECKS))} fichiers source.")
    if echecs:
        print(f"\n{len(echecs)} ÉCART(S) : un chiffre publié n'est plus celui de son artefact source.")
        for e in echecs:
            print(f"  - {e}")
        return 1
    print("Aucun écart : tous les chiffres du registre sont ceux de leurs fichiers source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
