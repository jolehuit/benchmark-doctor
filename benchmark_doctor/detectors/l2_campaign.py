"""L2 — campagne de mesure multi-canal, et son rapport reproductible.

Ce module orchestre ce que `l2_liveness` et `l2_content` savent faire, et **produit le
chiffre**. Il est séparé des détecteurs pour une raison de méthode : un détecteur doit
rester une fonction pure de (tâche, canal) vers des constats, tandis qu'une campagne est
un protocole daté, avec un échantillon, des témoins et des limites. Confondre les deux,
c'est publier un taux sans son protocole.

Le protocole exécuté le 15/08/2026 comporte quatre phases :

1. **Provenance.** Chaque canal déclare sa configuration (profil d'en-têtes, présence
   d'un proxy d'egress, disponibilité). Sans ce bloc, aucun des chiffres suivants n'est
   réplicable.
2. **Témoins.** Les résolveurs de contenu sont passés sur des identifiants connus pour
   exister et sur des identifiants fabriqués. Un résolveur qui ne les sépare pas est
   écarté de l'analyse plutôt que d'y contribuer silencieusement.
3. **Sites.** Les 15 sites cibles de WebVoyager sont sondés depuis chaque canal
   disponible, et les verdicts sont comparés canal à canal.
4. **Tâches.** Un échantillon stratifié est sondé, en combinant la signature d'accès de
   son URL de départ et l'existence des contenus qu'il cite.

Exécution :

    python -m benchmark_doctor.detectors.l2_campaign \\
        --corpus data/raw/webvoyager_original.jsonl \\
        --out runs/l2_probe_20260815.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import platform
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..channels import BaseChannel, DirectHTTPChannel, PlaywrightChannel, RecordedChannel
from ..models import Channel, Task
from ..parsers.webvoyager import load_webvoyager
from .l2_content import (
    CONTROL_IDENTIFIERS,
    ContentCheck,
    check_identifier,
    check_task,
    coverage,
    extract_identifiers,
)
from .l2_liveness import (
    ChannelComparison,
    LivenessVerdict,
    Signature,
    divergence_rate,
    probe_url,
)

__all__ = ["build_channels", "sample_tasks", "run_campaign", "main"]

#: Les 15 URL de départ du corpus WebVoyager, une par site. Le fait qu'il n'y en ait
#: qu'une par site est en soi un constat sur la conception du benchmark : les 45 tâches
#: Allrecipes partagent un unique point de défaillance d'accès.
TARGET_SITES: dict[str, str] = {
    "Allrecipes": "https://www.allrecipes.com/",
    "Amazon": "https://www.amazon.com/",
    "Apple": "https://www.apple.com/",
    "ArXiv": "https://arxiv.org/",
    "BBC News": "https://www.bbc.com/news/",
    "Booking": "https://www.booking.com/",
    "Cambridge Dictionary": "https://dictionary.cambridge.org/",
    "Coursera": "https://www.coursera.org/",
    "ESPN": "https://www.espn.com/",
    "GitHub": "https://github.com/",
    "Google Flights": "https://www.google.com/travel/flights/",
    "Google Map": "https://www.google.com/maps/",
    "Google Search": "https://www.google.com/",
    "Huggingface": "https://huggingface.co/",
    "Wolfram Alpha": "https://www.wolframalpha.com/",
}


# Canaux


def build_channels(
    *, recorded: str | Path | None = None, min_interval: float = 1.0
) -> list[BaseChannel]:
    """Construit les canaux de la campagne, du moins coûteux au plus coûteux.

    Trois canaux sont montés systématiquement et un quatrième si un enregistrement de
    navigateur cloud est fourni :

    - ``direct_http:browser`` — HTTP avec en-têtes de Chrome ;
    - ``direct_http:minimal`` — HTTP avec un client nu, **ablation du canal** : à IP et à
      instant identiques, la seule présentation du client change-t-elle le verdict ?
    - ``playwright:headless`` — navigateur local, généralement indisponible ici ; il est
      tout de même construit pour que le rapport consigne son indisponibilité au lieu de
      la passer sous silence ;
    - ``browser_cloud:*`` — observations de navigateur cloud rejouées.
    """
    channels: list[BaseChannel] = [
        DirectHTTPChannel(profile="browser", min_interval=min_interval),
        DirectHTTPChannel(profile="minimal", min_interval=min_interval),
        PlaywrightChannel(),
    ]
    if recorded and Path(recorded).exists():
        payload = json.loads(Path(recorded).read_text(encoding="utf-8"))
        channels.append(
            RecordedChannel(
                payload,
                kind=Channel.BROWSER_CLOUD,
                name=payload.get("channel_name", "browser_cloud:recorded"),
                source=str(recorded),
                strict=True,
            )
        )
    return channels


# Échantillon


def sample_tasks(
    tasks: Sequence[Task], *, per_site: int = 3, seed: int = 20260815
) -> list[Task]:
    """Échantillon de tâches : stratifié par site, plus toutes les tâches vérifiables.

    Deux couches, chacune justifiée :

    - **stratification** (``per_site`` tâches par site, tirage reproductible par graine) :
      garantit que l'échantillon ne surreprésente pas les sites accessibles, ce qui
      biaiserait à la baisse le taux de blocage ;
    - **inclusion exhaustive des tâches citant un identifiant résolvable** : elles sont
      rares (5 % du corpus) et ce sont les seules sur lesquelles la vérification de
      contenu produit un résultat ; les tirer au sort reviendrait à jeter le peu de
      signal disponible.
    """
    rng = random.Random(seed)
    by_site: dict[str, list[Task]] = defaultdict(list)
    for task in tasks:
        by_site[task.site or "unknown"].append(task)
    chosen: dict[str, Task] = {}
    for site in sorted(by_site):
        pool = sorted(by_site[site], key=lambda t: t.task_id)
        for task in rng.sample(pool, min(per_site, len(pool))):
            chosen[task.task_id] = task
    for task in tasks:
        if extract_identifiers(task):
            chosen[task.task_id] = task
    return [chosen[k] for k in sorted(chosen)]


# Campagne


def _controls(channel: BaseChannel) -> dict[str, Any]:
    """Passe les témoins et renvoie le bilan de discrimination par résolveur."""
    rows: list[dict[str, Any]] = []
    per_kind: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, "correct": 0, "undecided": 0}
    )
    for identifier, expected in CONTROL_IDENTIFIERS:
        check = check_identifier(identifier, channel)
        correct = check.exists is expected
        stats = per_kind[identifier.kind]
        stats["n"] += 1
        stats["correct"] += int(correct)
        stats["undecided"] += int(check.exists is None)
        rows.append(
            {
                "kind": identifier.kind,
                "value": identifier.value,
                "expected": expected,
                "observed": check.exists,
                "correct": correct,
                "signature": check.signature.value,
                "status": check.status,
                "rationale": check.rationale,
            }
        )
    usable = sorted(k for k, v in per_kind.items() if v["correct"] == v["n"])
    return {
        "rows": rows,
        "by_resolver": {k: dict(v) for k, v in sorted(per_kind.items())},
        "usable_resolvers": usable,
        "n_correct": sum(1 for r in rows if r["correct"]),
        "n_total": len(rows),
        "note": (
            "Seuls les résolveurs qui séparent parfaitement les témoins présents des "
            "témoins fabriqués sont considérés comme exploitables ; les autres "
            "apparaissent dans le rapport mais leurs verdicts ne sont pas agrégés."
        ),
    }


def _probe_sites(
    channels: Sequence[BaseChannel], sites: dict[str, str], *, repeats: int = 1
) -> tuple[dict[str, dict[str, LivenessVerdict]], list[ChannelComparison], dict[str, Any]]:
    """Sonde chaque site depuis chaque canal, ``repeats`` fois, et retient la **signature
    modale**.

    Sonder une seule fois serait une erreur de protocole : les dispositifs anti-bot
    arbitrent au cas par cas, et un site peut répondre `ok` puis `antibot_challenge` à
    une minute d'intervalle sur le même canal. Publier un tirage unique reviendrait à
    présenter un aléa comme un état. Le rapport retient donc la signature majoritaire et
    conserve **tous** les tirages, plus un taux d'instabilité par canal — qui est
    lui-même un résultat sur la reproductibilité de ce type de mesure.

    Les canaux rejoués ne sont sondés qu'une fois : répéter un enregistrement donnerait
    une stabilité de 100 % par construction et ne mesurerait rien.
    """
    n = max(1, repeats)
    per_site: dict[str, dict[str, LivenessVerdict]] = {}
    draws: dict[str, dict[str, list[LivenessVerdict]]] = {}
    for site, url in sites.items():
        per_channel_draws: dict[str, list[LivenessVerdict]] = {}
        for channel in channels:
            if not channel.available():
                continue
            if isinstance(channel, RecordedChannel) and url not in channel.urls:
                continue  # le canal rejoué n'a pas cette URL : ne rien inventer
            times = 1 if isinstance(channel, RecordedChannel) else n
            per_channel_draws[channel.name] = [probe_url(url, channel) for _ in range(times)]
        draws[site] = per_channel_draws
        per_site[site] = {
            name: _modal_verdict(vs) for name, vs in per_channel_draws.items() if vs
        }
    comparisons = [
        ChannelComparison(url=sites[site], verdicts=verdicts)
        for site, verdicts in per_site.items()
    ]
    return per_site, comparisons, _stability(draws, repeats=n)


def _modal_verdict(verdicts: Sequence[LivenessVerdict]) -> LivenessVerdict:
    """Verdict dont la signature est la plus fréquente ; à égalité, le premier tirage."""
    counts = Counter(v.signature for v in verdicts)
    best = max(counts.items(), key=lambda kv: (kv[1], -list(counts).index(kv[0])))[0]
    return next(v for v in verdicts if v.signature is best)


def _stability(
    draws: dict[str, dict[str, list[LivenessVerdict]]], *, repeats: int
) -> dict[str, Any]:
    """Taux d'instabilité de la signature, par canal réseau."""
    by_channel: dict[str, dict[str, Any]] = {}
    for site, per_channel in draws.items():
        for name, verdicts in per_channel.items():
            if len(verdicts) < 2:
                continue
            entry = by_channel.setdefault(name, {"n_sites": 0, "unstable_sites": {}})
            entry["n_sites"] += 1
            sigs = [v.signature.value for v in verdicts]
            if len(set(sigs)) > 1:
                entry["unstable_sites"][site] = sigs
    for entry in by_channel.values():
        n = entry["n_sites"]
        entry["n_unstable"] = len(entry["unstable_sites"])
        entry["instability_rate"] = round(entry["n_unstable"] / n, 4) if n else 0.0
    return {
        "repeats": repeats,
        "measured": repeats >= 2 and bool(by_channel),
        "by_channel": by_channel,
        "all_draws": {
            site: {name: [v.signature.value for v in vs] for name, vs in per_channel.items()}
            for site, per_channel in draws.items()
        },
    }


def _blocking_stats(
    per_site: dict[str, dict[str, LivenessVerdict]], channel_name: str
) -> dict[str, Any]:
    """Taux de blocage d'un canal sur les sites cibles.

    Trois taux distincts, parce que les confondre serait malhonnête :

    - ``site_blocked_rate`` : part des sites que le site lui-même rend inobservables
      (402/403/challenge/CAPTCHA…) ;
    - ``channel_blocked_rate`` : part des sites rendus inobservables par l'infrastructure
      de mesure — un coût de la mesure, pas un decay du benchmark ;
    - ``unobservable_rate`` : la somme des deux, c'est-à-dire ce qu'un praticien subit
      réellement s'il exécute la sonde depuis cette infrastructure.
    """
    verdicts = [v[channel_name] for v in per_site.values() if channel_name in v]
    if not verdicts:
        return {"channel": channel_name, "n_sites": 0}
    site_blocked = [v for v in verdicts if v.is_site_verdict and v.blocks_task]
    channel_blocked = [v for v in verdicts if not v.is_site_verdict]
    ok = [v for v in verdicts if v.signature is Signature.OK]
    n = len(verdicts)
    return {
        "channel": channel_name,
        "n_sites": n,
        "n_ok": len(ok),
        "n_site_blocked": len(site_blocked),
        "n_channel_blocked": len(channel_blocked),
        "site_blocked_rate": round(len(site_blocked) / n, 4),
        "channel_blocked_rate": round(len(channel_blocked) / n, 4),
        "unobservable_rate": round((len(site_blocked) + len(channel_blocked)) / n, 4),
        "signatures": dict(Counter(v.signature.value for v in verdicts).most_common()),
        "vendors": dict(Counter(v.vendor.value for v in verdicts).most_common()),
    }


def _tasks_at_risk(
    tasks: Sequence[Task], per_site: dict[str, dict[str, LivenessVerdict]], channel_name: str
) -> dict[str, Any]:
    """Combien de tâches du corpus deviennent inobservables, par propagation du site.

    WebVoyager n'ayant qu'une URL de départ par site, la signature d'accès d'un site se
    propage mécaniquement à toutes ses tâches. C'est ce qui rend le blocage si coûteux :
    un seul 402 emporte 45 tâches.
    """
    counts = Counter(t.site or "unknown" for t in tasks)
    blocked_site = 0
    blocked_channel = 0
    detail: dict[str, str] = {}
    for site, n in counts.items():
        verdict = per_site.get(site, {}).get(channel_name)
        if verdict is None:
            continue
        detail[site] = verdict.signature.value
        if not verdict.is_site_verdict:
            blocked_channel += n
        elif verdict.blocks_task:
            blocked_site += n
    total = sum(counts.values())
    return {
        "n_tasks": total,
        "n_tasks_site_blocked": blocked_site,
        "n_tasks_channel_blocked": blocked_channel,
        "tasks_site_blocked_rate": round(blocked_site / total, 4) if total else 0.0,
        "tasks_channel_blocked_rate": round(blocked_channel / total, 4) if total else 0.0,
        "tasks_unobservable_rate": round((blocked_site + blocked_channel) / total, 4)
        if total
        else 0.0,
        "site_signature": detail,
    }


def _validate_against_patches(
    checks: Sequence[ContentCheck], patches_path: str | Path | None
) -> dict[str, Any]:
    """Confronte les vérifications de contenu décidées à une ground truth de patches.

    La ground truth utilisée est le fichier de patches Magnitude (gelé le 06/07/2025),
    lu directement en JSON pour que cette validation ne dépende d'aucun autre module.

    Une précaution d'interprétation, sans laquelle le tableau serait trompeur : une tâche
    peut être patchée pour une raison **temporelle** alors que le contenu qu'elle cite
    existe toujours. Un « présent » du détecteur face à un patch temporel n'est donc pas
    un faux négatif de la dérive de contenu — c'est une tâche hors du périmètre de ce
    détecteur. Le tableau distingue donc les faux négatifs *toutes raisons* de ceux dont
    la raison annoncée relève effectivement du contenu.
    """
    if not patches_path or not Path(patches_path).exists():
        return {"available": False, "reason": f"ground truth absente : {patches_path}"}
    patches = json.loads(Path(patches_path).read_text(encoding="utf-8"))
    content_words = ("no longer", "does not exist", "doesn't exist", "not exist", "removed",
                     "unavailable", "discontinued", "no NER", "gone", "404")

    decided = [c for c in checks if c.decided]
    rows: list[dict[str, Any]] = []
    tp = fp = fn = tn = 0
    fn_content = 0
    for check in decided:
        patch = patches.get(check.task_id or "")
        reason = (patch or {}).get("reason", "") if isinstance(patch, dict) else ""
        patched = patch is not None
        flagged = check.exists is False
        if flagged and patched:
            tp += 1
        elif flagged and not patched:
            fp += 1
        elif not flagged and patched:
            fn += 1
            if any(w.lower() in reason.lower() for w in content_words):
                fn_content += 1
        else:
            tn += 1
        rows.append(
            {
                "task_id": check.task_id,
                "identifier": check.identifier.value,
                "detector_says_missing": flagged,
                "in_ground_truth": patched,
                "ground_truth_reason": reason,
            }
        )
    precision = tp / (tp + fp) if (tp + fp) else None
    return {
        "available": True,
        "ground_truth": str(patches_path),
        "ground_truth_frozen_at": "2025-07-06",
        "n_decided_checks": len(decided),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative_all_reasons": fn,
        "false_negative_content_reason": fn_content,
        "true_negative": tn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall_on_content_reason": (
            round(tp / (tp + fn_content), 4) if (tp + fn_content) else None
        ),
        "rows": rows,
        "note": (
            "Un faux négatif « toutes raisons » recouvre surtout des patches temporels, "
            "hors périmètre d'un détecteur d'existence de contenu ; seul le rappel sur "
            "les patches dont la raison annoncée relève du contenu est interprétable."
        ),
    }


def run_campaign(
    corpus: str | Path,
    *,
    channels: Sequence[BaseChannel] | None = None,
    per_site: int = 3,
    today: _dt.date | None = None,
    ground_truth: str | Path | None = None,
    repeats: int = 1,
) -> dict[str, Any]:
    """Exécute la campagne complète et renvoie le rapport, prêt à sérialiser."""
    day = today or _dt.date.today()
    tasks = load_webvoyager(corpus)
    chans = list(channels) if channels is not None else build_channels()
    live = [c for c in chans if c.available()]
    primary = next(
        (c for c in live if c.name == "direct_http:browser"), live[0] if live else None
    )
    if primary is None:
        raise RuntimeError("aucun canal disponible : la campagne ne peut pas être exécutée")

    # -- phase 2 : témoins ------------------------------------------------------------
    controls = _controls(primary)

    # -- phase 3 : sites --------------------------------------------------------------
    site_verdicts, comparisons, repeatability = _probe_sites(
        live, TARGET_SITES, repeats=repeats
    )

    # -- phase 4 : tâches -------------------------------------------------------------
    sample = sample_tasks(tasks, per_site=per_site)
    task_rows: list[dict[str, Any]] = []
    content_checks: list[ContentCheck] = []
    for task in sample:
        site_verdict = site_verdicts.get(task.site or "", {}).get(primary.name)
        checks = check_task(task, primary) if extract_identifiers(task) else []
        content_checks.extend(checks)
        task_rows.append(
            {
                "task_id": task.task_id,
                "site": task.site,
                "start_url": task.start_url,
                "question": task.question[:220],
                "liveness": site_verdict.to_dict() if site_verdict else None,
                "content_checks": [c.to_dict() for c in checks],
                "verdict_note": (
                    "signature d'accès héritée du site : WebVoyager ne fournit qu'une URL "
                    "de départ par site"
                ),
            }
        )

    decided = [c for c in content_checks if c.decided]
    missing = [c for c in decided if c.exists is False]

    report: dict[str, Any] = {
        "campaign": {
            "name": "l2_probe",
            "benchmark": "webvoyager",
            "corpus": str(corpus),
            "generated_at": day.isoformat(),
            "started_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "n_tasks_corpus": len(tasks),
            "n_sites": len(TARGET_SITES),
            "n_tasks_sampled": len(sample),
            "python": platform.python_version(),
            "protocol": [
                "1. provenance des canaux",
                "2. témoins de résolveurs (identifiants réels vs fabriqués)",
                "3. sondage des 15 sites depuis chaque canal disponible",
                "4. sondage d'un échantillon stratifié de tâches (accès + contenus cités)",
            ],
        },
        "channels": [c.describe() for c in chans],
        "controls": controls,
        "sites": {
            site: {
                "url": TARGET_SITES[site],
                "by_channel": {name: v.to_dict() for name, v in verdicts.items()},
                "draws": repeatability["all_draws"].get(site, {}),
            }
            for site, verdicts in site_verdicts.items()
        },
        "blocking": {
            c.name: _blocking_stats(site_verdicts, c.name)
            for c in live
            if c.name != "playwright:headless"
        },
        "tasks_at_risk": {
            c.name: _tasks_at_risk(tasks, site_verdicts, c.name)
            for c in live
            if c.name != "playwright:headless"
        },
        # `all_draws` est déjà publié site par site : on ne le duplique pas ici.
        "repeatability": {k: v for k, v in repeatability.items() if k != "all_draws"},
        "channel_dependence": {
            "per_url": [c.to_dict() for c in comparisons],
            "summary": divergence_rate(comparisons),
        },
        "content": {
            "coverage": coverage(tasks),
            "coverage_sample": coverage(sample),
            "n_checks": len(content_checks),
            "n_decided": len(decided),
            "n_missing": len(missing),
            "missing": [c.to_dict() for c in missing],
            "by_kind": dict(
                Counter(c.identifier.kind for c in content_checks).most_common()
            ),
            "decided_by_kind": dict(
                Counter(c.identifier.kind for c in decided).most_common()
            ),
            "validation_vs_ground_truth": _validate_against_patches(
                content_checks, ground_truth
            ),
        },
        "tasks": task_rows,
    }
    report["limits"] = _limits(report)
    return report


def _limits(report: dict[str, Any]) -> list[str]:
    """Limites de la campagne, calculées depuis ses propres chiffres.

    Écrites par le code plutôt qu'à la main : une limite recopiée d'une exécution
    précédente est une limite fausse dès la deuxième exécution.
    """
    blocking = report["blocking"].get("direct_http:browser", {})
    dep = report["channel_dependence"]["summary"]
    cov = report["content"]["coverage"]
    out = [
        f"Canal principal : HTTP direct depuis une IP de datacenter, derrière un proxy "
        f"d'egress interceptant. {blocking.get('n_channel_blocked', 0)} des "
        f"{blocking.get('n_sites', 0)} sites sont inobservables à cause de ce proxy et non "
        f"du site : ces cas sont classés `channel_blocked` et exclus de tout taux de decay.",
        f"Taux de blocage imputable aux sites : "
        f"{blocking.get('site_blocked_rate', 0) * 100:.1f} % des sites cibles depuis ce "
        f"canal. Ce n'est pas un taux de tâches mortes — c'est un taux d'inobservabilité, "
        f"qui dépend du canal et doit être republié à chaque changement d'infrastructure.",
        f"Couverture de la vérification de contenu : "
        f"{cov['n_tasks_with_identifier']}/{cov['n_tasks']} tâches "
        f"({cov['coverage_rate'] * 100:.1f} %) citent un identifiant résolvable. Le rappel "
        f"de ce détecteur est donc plafonné par le corpus : la majorité des énoncés "
        f"WebVoyager décrivent une recherche, pas un objet nommé.",
        "Les sondes portent sur l'URL de départ des tâches, pas sur l'état interne du site "
        "après navigation : une tâche peut être inexécutable alors que sa page d'accueil "
        "répond 200. La couche L2 borne donc par le bas le taux réel de decay.",
    ]
    rep = report.get("repeatability", {})
    if rep.get("measured"):
        for name, stats in rep["by_channel"].items():
            if stats["n_unstable"]:
                out.append(
                    f"Stabilité de la mesure sur {rep['repeats']} sondages successifs "
                    f"({name}) : {stats['n_unstable']}/{stats['n_sites']} sites changent "
                    f"de signature d'un sondage à l'autre "
                    f"({stats['instability_rate'] * 100:.1f} %) — "
                    f"{', '.join(sorted(stats['unstable_sites']))}. Pour ces sites, un "
                    f"verdict publié sans nombre de répétitions n'est pas reproductible."
                )
            else:
                out.append(
                    f"Stabilité de la mesure sur {rep['repeats']} sondages successifs "
                    f"({name}) : aucune des {stats['n_sites']} signatures ne change. "
                    f"Trois tirages en quelques minutes ne disent toutefois rien de la "
                    f"stabilité à l'échelle de la journée ou de la semaine, ni depuis une "
                    f"autre IP."
                )
    if dep.get("n_comparable"):
        out.append(
            f"Dépendance au canal mesurée sur {dep['n_comparable']} URL comparables "
            f"(deux canaux imputables au site ou plus) : {dep['n_disagree']} divergent. "
            f"L'échantillon comparable est petit — la mesure établit l'existence du "
            f"phénomène et son ordre de grandeur, pas sa fréquence sur le web en général."
        )
    else:
        out.append(
            "Aucune URL n'a pu être comparée sur deux canaux imputables au site : la "
            "dépendance au canal n'est pas quantifiée dans cette exécution."
        )
    return out


# Ligne de commande


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="l2_campaign",
        description="Campagne de sondes L2 multi-canal sur un corpus de benchmark web-live.",
    )
    parser.add_argument("--corpus", default="data/raw/webvoyager_original.jsonl")
    parser.add_argument("--out", default="runs/l2_probe.json")
    parser.add_argument("--recorded", default="runs/l2_browser_cloud_20260815.json")
    parser.add_argument("--per-site", type=int, default=3)
    parser.add_argument(
        "--ground-truth",
        default="data/raw/magnitude_patches.json",
        help="patches servant de ground truth à la validation du détecteur de contenu",
    )
    parser.add_argument("--min-interval", type=float, default=1.0)
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="nombre de sondages successifs des sites, pour mesurer la stabilité de la mesure",
    )
    parser.add_argument("--today", default=None, help="date de mesure (AAAA-MM-JJ)")
    args = parser.parse_args(argv)

    channels = build_channels(recorded=args.recorded, min_interval=args.min_interval)
    report = run_campaign(
        args.corpus,
        channels=channels,
        per_site=args.per_site,
        today=_dt.date.fromisoformat(args.today) if args.today else None,
        ground_truth=args.ground_truth,
        repeats=args.repeats,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    blocking = report["blocking"].get("direct_http:browser", {})
    print(f"→ {out}")
    print(
        f"  sites : {blocking.get('n_ok')} ok / {blocking.get('n_site_blocked')} bloqués "
        f"par le site / {blocking.get('n_channel_blocked')} bloqués par le canal "
        f"(sur {blocking.get('n_sites')})"
    )
    print(
        f"  tâches sondées : {report['campaign']['n_tasks_sampled']} ; "
        f"contenus vérifiés : {report['content']['n_decided']}/{report['content']['n_checks']} "
        f"décidés, {report['content']['n_missing']} absents"
    )
    print(f"  divergence inter-canaux : {report['channel_dependence']['summary']}")
    validation = report["content"]["validation_vs_ground_truth"]
    if validation.get("available"):
        print(
            f"  vs ground truth Magnitude : VP={validation['true_positive']} "
            f"FP={validation['false_positive']} "
            f"FN(contenu)={validation['false_negative_content_reason']} "
            f"VN={validation['true_negative']}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
