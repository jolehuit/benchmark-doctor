"""Manifeste des sources de vérité terrain (« patch-sets ») utilisées pour WebVoyager.

Chaque entrée décrit **une observation datée** du corpus WebVoyager par un acteur tiers :
qui a regardé le benchmark, quand, à quel commit, et ce que son artefact exprime
(exclusion d'une tâche, réécriture, conservation).

Deux points méthodologiques y sont figés, parce qu'ils conditionnent toute la suite :

1. **La date est celle de l'artefact, pas celle du papier.** Pour Emergence, le fichier de
   tâches n'a pas bougé depuis le 2025-07-21 alors que la publication est datée de mars 2026 ;
   c'est la date du fichier qui fait foi dans l'étude longitudinale.
2. **Skyvern compte pour deux sources datées** (2025-01-16 et 2026-05-04) mais pour **un seul
   annotateur**. Les statistiques d'accord inter-annotateurs n'en retiennent qu'une (la plus
   récente), sans quoi l'accord serait artificiellement gonflé par un annotateur dupliqué.

Tous les identifiants de commit sont épinglés : `fetch_sources.py` télécharge exactement ces
révisions, ce qui rend la base reconstructible à l'identique.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["SourceSpec", "SOURCES", "ANNOTATORS", "source", "annotator_sources"]


@dataclass(frozen=True)
class SourceSpec:
    """Description d'un patch-set.

    Args:
        key: identifiant court utilisé partout dans la base (`verdicts[].source`).
        label: nom lisible, utilisé dans les tableaux produits par `stats`.
        annotator: équipe qui a produit le verdict. Deux sources peuvent partager un
            annotateur (les deux instantanés Skyvern) : c'est cette clé qui sert à ne
            compter qu'une fois un même annotateur dans les calculs d'accord.
        date: date de l'artefact (ISO), telle que datée par le dépôt d'origine.
        repo: dépôt ou dataset d'origine.
        commit: révision épinglée.
        expresses: ce que l'artefact dit réellement, formulé sans interprétation.
        confidence: `haute` si les verdicts sont explicites et attribuables au decay ;
            `faible` si l'exclusion d'une tâche peut avoir une autre cause (rééchantillonnage).
        counted_in_agreement: faux pour les sources exclues du calcul d'accord principal.
        note: réserve méthodologique éventuelle.
    """

    key: str
    label: str
    annotator: str
    date: str
    repo: str
    commit: str
    expresses: str
    confidence: str = "haute"
    counted_in_agreement: bool = True
    note: str = ""
    files: tuple[str, ...] = field(default_factory=tuple)


#: Le corpus de référence : 643 tâches, gelé depuis le 2024-03-02.
ORIGINAL = SourceSpec(
    key="original",
    label="WebVoyager (original)",
    annotator="webvoyager",
    date="2024-03-02",
    repo="MinorJerry/WebVoyager",
    commit="091544539eba485dbd74ef3742011ddeede37336",
    expresses="corpus de référence, 643 tâches",
    files=("webvoyager_original.jsonl",),
)


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        key="browseruse",
        label="browser-use/eval",
        annotator="browser-use",
        date="2024-12-15",
        repo="browser-use/eval",
        commit="37bfdca3a5ab20775014e8a00ffc0e4d2e000b00",
        expresses=(
            "liste explicite de 55 tâches jugées impossibles + réécriture silencieuse "
            "de 76 énoncés dans le fichier de tâches (aucune raison documentée)"
        ),
        files=("browseruse_tasks.jsonl", "browseruse_impossible.json"),
    ),
    SourceSpec(
        key="skyvern_2025",
        label="Skyvern (instantané 01/2025)",
        annotator="skyvern",
        date="2025-01-16",
        repo="Skyvern-AI/skyvern",
        commit="92c6fddc9b02d2c00f61b074372d80f39fa85220",
        expresses="635 tâches conservées + 8 listées dans webvoyager_outdated_tasks.jsonl",
        counted_in_agreement=False,
        note="Même annotateur que skyvern_2026 : conservé pour le longitudinal, exclu de l'accord.",
        files=("skyvern_tasks_20250116.jsonl", "skyvern_outdated_20250116.jsonl"),
    ),
    SourceSpec(
        key="convergence",
        label="Convergence WebVoyager2025Valid",
        annotator="convergence",
        date="2025-02-17",
        repo="hf:convergence-ai/WebVoyager2025Valid",
        commit="9854e641831b59d5090891830d129f07f54d2219",
        expresses=(
            "601 tâches déclarées « valid until 20th December 2025 » — seul patch-set "
            "assorti d'une date de péremption explicite"
        ),
        files=("convergence_valid_20251220.csv",),
    ),
    SourceSpec(
        key="magnitude",
        label="Magnitude patches.json",
        annotator="magnitude",
        date="2025-07-06",
        repo="magnitudedev/webvoyager",
        commit="87009319e1a971e170a05d26ebffcba01a2fbcd2",
        expresses="121 patches motivés tâche par tâche : 68 réécritures + 53 suppressions",
        files=("magnitude_patches.json", "magnitude_patched.jsonl"),
    ),
    SourceSpec(
        key="emergence",
        label="Emergence WebVoyager (templates)",
        annotator="emergence",
        date="2025-07-21",
        repo="EmergenceAI/EmergenceWebVoyager",
        commit="e988bb135551a10bab2d33d969f2fb0f5c569fe7",
        expresses=(
            "535 tâches templatées (35 par site) avec instanciation des dates à l'exécution ; "
            "aucun identifiant WebVoyager conservé"
        ),
        confidence="faible",
        counted_in_agreement=False,
        note=(
            "L'exclusion d'une tâche n'est pas attribuable au decay : Emergence rééchantillonne "
            "à 35 tâches par site (les sites en comptaient 41 à 46). Le rattachement aux "
            "identifiants d'origine est fait par appariement de texte, donc approximatif."
        ),
        files=("emergence_template.json",),
    ),
    SourceSpec(
        key="fara",
        label="Microsoft Fara F595",
        annotator="microsoft-fara",
        date="2025-08-31",
        repo="microsoft/fara",
        commit="ff0dbac1d12005718812afae1a2f53fc8e98f302",
        expresses="595 tâches retenues (WebVoyager_data_08312025.jsonl), aucune raison documentée",
        note="Fichier daté du 2025-08-31 dans son nom, publié au commit initial du 2025-11-24.",
        files=("fara_webvoyager_20250831.jsonl",),
    ),
    SourceSpec(
        key="alumnium",
        label="Alumnium WebVoyager",
        annotator="alumnium",
        date="2026-03-17",
        repo="alumnium-hq/WebVoyager",
        commit="e73fddd2a804309486ea3253949edbfb790fa2a4",
        expresses=(
            "619 tâches conservées ; 20 commits par site (2026-03-16 → 2026-03-23) dont le "
            "message donne la raison : « Remove impossible tasks for X » / « Update dates for X »"
        ),
        note=(
            "Fork du dépôt ORIGINAL (base = commit MinorJerry 2024-03-02), pas du fork Magnitude : "
            "l'audit est indépendant, pas un « re-audit » de Magnitude."
        ),
        files=("alumnium_patched.jsonl", "alumnium_history.json"),
    ),
    SourceSpec(
        key="skyvern_2026",
        label="Skyvern (instantané 05/2026)",
        annotator="skyvern",
        date="2026-05-04",
        repo="Skyvern-AI/skyvern",
        commit="b9649d27344550ff2542c890f986d30e321e7ed6",
        expresses=(
            "635 tâches conservées + 8 obsolètes ; commit « refresh webvoyager_tasks.jsonl "
            "dates to 2026/2027 »"
        ),
        files=("skyvern_tasks.jsonl", "skyvern_outdated.jsonl"),
    ),
)

#: Sources retenues pour l'accord inter-annotateurs (une par annotateur).
ANNOTATORS: tuple[str, ...] = tuple(s.key for s in SOURCES if s.counted_in_agreement)


def source(key: str) -> SourceSpec:
    """Retrouve une source par sa clé.

    Raises:
        KeyError: si la clé est inconnue.
    """
    for spec in (*SOURCES, ORIGINAL):
        if spec.key == key:
            return spec
    raise KeyError(f"source inconnue : {key!r}")


def annotator_sources() -> tuple[SourceSpec, ...]:
    """Les sources comptées dans l'accord inter-annotateurs, dans l'ordre chronologique."""
    return tuple(s for s in SOURCES if s.counted_in_agreement)
