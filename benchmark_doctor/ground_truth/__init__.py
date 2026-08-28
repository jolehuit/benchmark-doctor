"""Vérité terrain multi-annotateurs de WebVoyager : ingestion, réconciliation, désaccord.

WebVoyager n'a pas de mainteneur depuis mars 2024, mais huit acteurs ont publié, à des
dates différentes, leur propre version corrigée du corpus. Ce sous-paquet les ramène à un
format commun — un verdict daté par tâche et par source — puis mesure ce sur quoi ils ne
s'accordent pas.

Chaîne de traitement :

1. `fetch_sources` — récupère les patch-sets manquants aux révisions épinglées ;
2. `loaders`       — un chargeur par source, identifiants normalisés ;
3. `reconcile`     — fusion vers `data/ground_truth.json` ;
4. `stats`         — effectifs, matrice de désaccord, kappas, prévalence par catégorie ;
5. `taxonomy`      — les 8 catégories et la relecture manuelle des 121 raisons Magnitude.

En ligne de commande :

    python3 -m benchmark_doctor.ground_truth.fetch_sources
    python3 -m benchmark_doctor.ground_truth.reconcile
    python3 -m benchmark_doctor.ground_truth.stats --embed
"""

from __future__ import annotations

__all__ = ["loaders", "reconcile", "sources", "stats", "taxonomy"]
