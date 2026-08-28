"""Lecteurs de corpus de benchmarks, normalisés vers `benchmark_doctor.models.Task`.

Chaque parseur est responsable d'un format source (WebVoyager et ses forks, plus tard
Online-Mind2Web) et ne fait aucune interprétation : la détection appartient aux
détecteurs, le parseur ne fait que normaliser les champs et signaler les lignes illisibles.
"""

from .webvoyager import (
    iter_webvoyager,
    load_webvoyager,
    parse_webvoyager_record,
)

__all__ = ["iter_webvoyager", "load_webvoyager", "parse_webvoyager_record"]
