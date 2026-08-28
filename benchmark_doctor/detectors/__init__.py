"""Détecteurs de decay, organisés en trois couches ordonnées par coût.

- ``l1_*`` : analyse statique de l'énoncé, sans réseau, coût nul ;
- ``l2_*`` : sondes web (liveness, anti-bot, existence des contenus) ;
- ``l3_*`` : sondes LLM (ambiguïté, solvabilité, fragilité de l'évaluation).

Ce module n'importe que la couche L1, afin qu'un environnement sans dépendances
réseau (CI minimale, poste hors ligne) puisse exécuter le health-check statique.
Les couches supérieures s'importent explicitement depuis leur module.
"""

from .l1_reference import detect_named_references
from .l1_sideeffect import detect_side_effects
from .l1_temporal import detect_temporal_decay

__all__ = [
    "detect_temporal_decay",
    "detect_side_effects",
    "detect_named_references",
]
