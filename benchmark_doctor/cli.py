"""Interface en ligne de commande de benchmark-doctor (`bdoctor`).

Quatre commandes, dans l'ordre où l'on s'en sert :

- ``bdoctor scan CORPUS`` : bulletin de santé statique d'un corpus (JSON + résumé) ;
- ``bdoctor l1-eval CORPUS --patches P.json`` : précision/rappel de la couche L1 contre
  un patch-set servant de ground truth, avec l'ablation des variantes de détecteurs ;
- ``bdoctor audit CORPUS --layers l1,l2,l3 --channel direct --out rapport.html`` :
  la campagne complète, qui produit la carte de santé ;
- ``bdoctor diff AVANT.json APRÈS.json`` : le différentiel entre deux mesures datées.

Les couches L2 et L3 sont importées paresseusement pour que la couche statique reste
exécutable sans réseau, sans clé d'API et sans dépendance optionnelle. Une couche
demandée mais indisponible est signalée dans le rapport au lieu d'interrompre la
campagne : « L2 non exécutée » est une information, un `ImportError` n'en est pas une.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from . import __version__, run_l1
from .models import BenchmarkHealth, Channel, Severity, Task, TaskVerdict
from .parsers.webvoyager import load_webvoyager


_TEMPORAL_HARD_PREFIXES = ("past_date_", "yearless_date_")


def _v1_naive(verdict: TaskVerdict) -> bool:
    """Détecteur v1 « naïf » du 15/08/2026 : toute date passée ou sans millésime, quelle
    que soit l'intention, plus tout motif d'effet de bord, quelle que soit sa force."""
    for f in verdict.findings:
        if f.detector == "l1_temporal" and f.signal and f.signal.startswith(_TEMPORAL_HARD_PREFIXES):
            return True
        if f.detector == "l1_sideeffect":
            return True
    return False


def _v2_contextual(verdict: TaskVerdict) -> bool:
    """Détecteur v2 « contextuel » : seuls les constats de sévérité HIGH comptent, ce qui
    revient à ne retenir que les dates passées sur tâche transactionnelle et les effets de
    bord réellement bloquants."""
    return verdict.is_flagged(Severity.HIGH)


def _v2_plus_reference(verdict: TaskVerdict) -> bool:
    """v2 augmenté du proxy statique de dérive de contenu (références nommées)."""
    return _v2_contextual(verdict) or any(f.detector == "l1_reference" for f in verdict.findings)


def _v2_plus_reference_strict(verdict: TaskVerdict) -> bool:
    """v2 augmenté du proxy resserré (produits versionnés, paliers, rubriques nommées),
    sans le motif générique « chaîne entre guillemets »."""
    return _v2_contextual(verdict) or any(
        f.detector == "l1_reference" and f.signal != "named_content" for f in verdict.findings
    )


def _v2_plus_medium(verdict: TaskVerdict) -> bool:
    """Seuil abaissé à MEDIUM sur l'ensemble des détecteurs L1."""
    return verdict.is_flagged(Severity.MEDIUM)


ABLATIONS: dict[str, tuple[str, Callable[[TaskVerdict], bool]]] = {
    "v1_naive": ("v1 naïf (date passée OU effet de bord, sans contexte)", _v1_naive),
    "v2_contextual": ("v2 contextuel (transactionnel/archivistique + effets bloquants)", _v2_contextual),
    "v2_reference": ("v2 + proxy références nommées (toutes)", _v2_plus_reference),
    "v2_reference_strict": ("v2 + proxy références resserré (hors chaînes citées)", _v2_plus_reference_strict),
    "v2_medium": ("seuil MEDIUM sur tous les détecteurs L1", _v2_plus_medium),
}


# Les bornes de mots ne sont pas cosmétiques : sans elles, « ambiguous what 'updates'
# means » est classé « temporel » parce que « up-DATE-s » contient « date ». Le script
# exploratoire du 15/08 avait ce défaut ; la ventilation des motifs de patch s'en trouve
# légèrement modifiée (cf. rapport).
_REASON_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("temporal", re.compile(
        r"\bdates?\b|\b20[12]\d\b|\boutdated\b|\bout of date\b|\bcurrent(?:ly)?\b|\bsuperseded\b|"
        r"\bno longer (?:current|the latest)\b|\bexpired?\b|\bseasons?\b|"
        r"\balready (?:released|happened)\b|\bin the past\b", re.I)),
    ("content_drift", re.compile(
        r"no longer exist|no longer (?:sold|available|listed|seems)|removed|discontinued|"
        r"does not exist|\bdne\b|unavailable|not available|gone|deleted|defunct|"
        r"there (?:is|are) no\b|doesn'?t exist", re.I)),
    ("impossible", re.compile(
        r"impossible|cannot|can'?t|no (?:reasonable )?way|requires? (?:login|account|sign)|"
        r"login|payment|purchase|checkout", re.I)),
    ("ambiguity", re.compile(r"ambiguous|unclear|vague|subjective|ill[- ]defined|what '", re.I)),
]


def classify_patch_reason(reason: str) -> str:
    """Classe une raison de patch en catégorie approximative.

    Heuristique par mots-clés, à annoncer comme telle : les raisons libres de Magnitude
    mélangent souvent deux motifs (« phone no longer sold, and the 15 Pro can't be
    compared »). Elle sert à ventiler le rappel, pas à produire un chiffre publiable seul.
    """
    for label, pattern in _REASON_RULES:
        if pattern.search(reason or ""):
            return label
    return "other"


def load_ground_truth(path: str | Path) -> dict[str, dict[str, Any]]:
    """Charge un patch-set servant de ground truth.

    Trois formats, ceux des patch-sets publics réels :

    - dictionnaire Magnitude ``{task_id: {reason, prev, new?}}``, où l'absence de clé
      ``new`` signale une suppression et sa présence une réécriture d'énoncé ;
    - liste d'identifiants (``WebVoyagerImpossibleTasks.json`` de browser-use) ;
    - JSONL de tâches exclues (snapshots Skyvern), dont seuls les identifiants comptent.
    """
    text = Path(path).read_text(encoding="utf-8")
    if str(path).endswith(".jsonl"):
        ids = [json.loads(line)["id"] for line in text.splitlines() if line.strip()]
        return {str(i): {"reason": "", "action": "delete", "category": "unlabelled"} for i in ids}
    payload = json.loads(text)
    if isinstance(payload, list):  # certains patch-sets ne publient qu'une liste d'IDs
        return {
            str(task_id): {"reason": "", "action": "delete", "category": "unlabelled"}
            for task_id in payload
        }
    out: dict[str, dict[str, Any]] = {}
    for task_id, entry in payload.items():
        if isinstance(entry, str):
            entry = {"reason": entry}
        out[str(task_id)] = {
            "reason": entry.get("reason", ""),
            "action": "edit" if "new" in entry else "delete",
            "prev": entry.get("prev"),
            "new": entry.get("new"),
            "category": classify_patch_reason(entry.get("reason", "")),
        }
    return out


def _parse_date(value: str | None) -> _dt.date | None:
    return _dt.date.fromisoformat(value) if value else None


def _fmt_pct(x: float) -> str:
    return f"{100 * x:5.1f} %"


def cmd_scan(args: argparse.Namespace) -> int:
    """Produit le bulletin de santé L1 d'un corpus."""
    today = _parse_date(args.today) or _dt.date.today()
    tasks = load_webvoyager(args.corpus, benchmark=args.benchmark)
    health = run_l1(tasks, today=today, benchmark=args.benchmark, source=str(args.corpus))
    threshold = Severity(args.threshold)
    predicate = ABLATIONS[args.policy][1] if args.policy else None
    policy_label = ABLATIONS[args.policy][0] if args.policy else None

    summary = health.summary(threshold, predicate, policy_label)
    print(f"benchmark-doctor {__version__} — couche L1 (statique, canal=static)")
    print(f"corpus      : {args.corpus}")
    print(f"date        : {today.isoformat()}   politique : {summary['flag_policy']}")
    print(f"tâches      : {summary['n_tasks']}")
    print(f"signalées   : {summary['n_flagged']}  ({_fmt_pct(summary['flag_rate'])})")
    print(f"stabilité ⌀ : {summary['mean_stability']}   notes : {summary['grades']}")

    print("\nPrévalence par catégorie de la taxonomie (tâches concernées) :")
    for cat, n in health.category_prevalence().items():
        if n:
            print(f"  {cat:<22} {n:4d}  ({_fmt_pct(n / max(1, health.n_tasks))})")

    print("\nSous-motifs déclenchés :")
    for signal, n in health.signal_counts().items():
        print(f"  {signal:<32} {n:4d}")

    print("\nPar site (trié par taux de flag dur) :")
    for site, row in health.by_site(threshold, predicate).items():
        print(f"  {site:<22} {row['flagged']:3d}/{row['n']:3d}  {_fmt_pct(row['flag_rate'])}"
              f"   stabilité ⌀ {row['mean_stability']}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(health.to_dict(threshold, predicate, policy_label), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"\nRapport JSON écrit dans {args.json}")
    return 0


def _prf(flagged: set[str], truth: set[str]) -> tuple[float, float, float]:
    tp = len(flagged & truth)
    precision = tp / len(flagged) if flagged else 0.0
    recall = tp / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def cmd_l1_eval(args: argparse.Namespace) -> int:
    """Évalue la couche L1 contre un patch-set servant de ground truth."""
    today = _parse_date(args.today) or _dt.date.today()
    tasks = load_webvoyager(args.corpus, benchmark=args.benchmark)
    health = run_l1(tasks, today=today, benchmark=args.benchmark, source=str(args.corpus))
    truth_entries = load_ground_truth(args.patches)
    corpus_ids = {v.task.task_id for v in health.verdicts}
    truth = set(truth_entries) & corpus_ids

    print(f"benchmark-doctor {__version__} — évaluation de la couche L1")
    print(f"corpus        : {args.corpus}  ({len(corpus_ids)} tâches)")
    print(f"ground truth  : {args.patches}  ({len(truth)} tâches patchées, "
          f"{len(truth_entries) - len(truth)} hors corpus)")
    print(f"date d'analyse: {today.isoformat()}")

    by_category: dict[str, set[str]] = defaultdict(set)
    for task_id in truth:
        by_category[truth_entries[task_id]["category"]].add(task_id)
    by_action: dict[str, set[str]] = defaultdict(set)
    for task_id in truth:
        by_action[truth_entries[task_id]["action"]].add(task_id)

    print("\nComposition de la ground truth :")
    for label, ids in sorted(by_category.items(), key=lambda kv: -len(kv[1])):
        print(f"  {label:<16} {len(ids):4d}")
    for label, ids in sorted(by_action.items()):
        print(f"  action={label:<9} {len(ids):4d}")

    print("\nAblation des politiques de décision :")
    header = f"  {'variante':<22} {'flags':>6} {'P':>7} {'R':>7} {'F1':>7} {'hors GT':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    results: dict[str, dict[str, Any]] = {}
    flags_by_variant: dict[str, set[str]] = {}
    for key, (label, predicate) in ABLATIONS.items():
        flagged = {v.task.task_id for v in health.verdicts if predicate(v)}
        flags_by_variant[key] = flagged
        p, r, f1 = _prf(flagged, truth)
        outside = sorted(flagged - set(truth_entries))
        results[key] = {
            "label": label,
            "n_flags": len(flagged),
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "n_outside_ground_truth": len(outside),
            "outside_ground_truth": outside,
            "recall_by_category": {},
        }
        for cat, ids in by_category.items():
            results[key]["recall_by_category"][cat] = round(len(ids & flagged) / len(ids), 4)
        print(f"  {key:<22} {len(flagged):6d} {_fmt_pct(p)} {_fmt_pct(r)} {_fmt_pct(f1)} {len(outside):8d}")
    for key, (label, _) in ABLATIONS.items():
        print(f"    {key:<22} = {label}")
    print("  « hors GT » = tâches signalées absentes du patch-set : decay accumulé depuis le")
    print("  gel de la ground truth (06/07/2025) ou faux positif — à trancher à la main.")

    print("\nRappel par catégorie de la ground truth :")
    cats = sorted(by_category, key=lambda c: -len(by_category[c]))
    print(f"  {'variante':<22}" + "".join(f"{c[:12]:>14}" for c in cats))
    for key in ABLATIONS:
        row = results[key]["recall_by_category"]
        print(f"  {key:<22}" + "".join(f"{100 * row[c]:13.0f}%" for c in cats))

    # Ces patch-sets tiers sont partiels (browser-use ne publie que ses tâches
    # « impossibles », Skyvern ses tâches périmées) : seul le rappel y est interprétable.
    cross: dict[str, dict[str, Any]] = {}
    if args.cross:
        print("\nRappel contre des patch-sets indépendants (précision non interprétable :")
        print("ces patch-sets sont partiels, une tâche absente n'est pas une tâche saine) :")
        print(f"  {'patch-set':<34} {'n':>5} " + "".join(f"{k[:13]:>15}" for k in ABLATIONS))
        for extra in args.cross:
            extra_truth = set(load_ground_truth(extra)) & corpus_ids
            row = {
                key: round(len(extra_truth & flags_by_variant[key]) / len(extra_truth), 4)
                for key in ABLATIONS
            }
            cross[str(extra)] = {"size": len(extra_truth), "recall": row}
            name = Path(extra).name
            print(f"  {name:<34} {len(extra_truth):5d} "
                  + "".join(f"{100 * row[k]:14.0f}%" for k in ABLATIONS))

    # Signalées aujourd'hui mais absentes du patch-set : decay accumulé depuis le gel de
    # la ground truth, ou faux positifs. Borne basse, à échantillonner à la main.
    hard = flags_by_variant["v2_contextual"]
    new_flags = sorted(hard - set(truth_entries))
    print(f"\nSignalées par v2 et absentes du patch-set : {len(new_flags)}")
    for task_id in new_flags[: args.show]:
        verdict = next(v for v in health.verdicts if v.task.task_id == task_id)
        signals = sorted({f.signal for f in verdict.findings if f.severity >= Severity.HIGH})
        print(f"  {task_id:<22} {','.join(s for s in signals if s)}")
    if len(new_flags) > args.show:
        print(f"  … ({len(new_flags) - args.show} de plus)")

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "tool_version": __version__,
                    "reference_date": today.isoformat(),
                    "corpus": str(args.corpus),
                    "corpus_size": len(corpus_ids),
                    "ground_truth": str(args.patches),
                    "ground_truth_size": len(truth),
                    "ground_truth_by_category": {k: sorted(v) for k, v in by_category.items()},
                    "ablations": results,
                    "cross_validation": cross,
                    "new_flags_vs_ground_truth": new_flags,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"\nRésultats JSON écrits dans {args.json}")
    return 0


#: Parsers de corpus disponibles. WebVoyager est le seul instrumenté à fond ; la clé
#: existe pour que l'ajout d'un second format ne demande pas de toucher à la commande.
PARSERS: dict[str, Callable[..., list[Task]]] = {
    "webvoyager": load_webvoyager,
}


class _MemoChannel:
    """Enveloppe un canal et mémorise ses observations par URL.

    Sans mémoïsation, une campagne L2 sur WebVoyager sonderait 643 fois quinze URL, le
    corpus ne fournissant qu'une URL de départ par site. On tombe à 15 requêtes, ce qui
    change la nature du coût (quelques secondes au lieu de vingt minutes de politesse
    réseau) et évite de déclencher soi-même l'anti-bot que l'on prétend mesurer.

    Conséquence à reporter dans le rapport : le verdict d'accès d'un site est propagé à
    toutes ses tâches. C'est une mesure par site étendue aux tâches, ce qui borne la
    décadence par le bas.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.kind = getattr(inner, "kind", Channel.HTTP_DATACENTER)
        self.name = getattr(inner, "name", "channel")
        self._cache: dict[str, Any] = {}
        self.n_fetches = 0
        self.n_hits = 0
        self.seconds = 0.0

    def fetch(self, url: str, *, timeout: float | None = None) -> Any:
        if url in self._cache:
            self.n_hits += 1
            return self._cache[url]
        start = time.perf_counter()
        obs = self.inner.fetch(url, timeout=timeout)
        self.seconds += time.perf_counter() - start
        self.n_fetches += 1
        self._cache[url] = obs
        return obs

    def fetch_many(self, urls: Iterable[str], *, timeout: float | None = None) -> list[Any]:
        return [self.fetch(u, timeout=timeout) for u in urls]

    def available(self) -> bool:
        return bool(self.inner.available())

    def describe(self) -> dict[str, Any]:
        info = dict(self.inner.describe())
        info["memoised_urls"] = len(self._cache)
        info["n_fetches"] = self.n_fetches
        info["n_cache_hits"] = self.n_hits
        return info


def _ledger_cost(ledger: Any) -> tuple[float, int, str]:
    """Extrait d'un `CostLedger` le coût à publier, le nombre d'appels et une note.

    Le montant retenu est ce qui a été payé plus ce que le cache a évité, et non
    ``cost_usd`` : le coût d'une mesure est celui de sa première exécution, et publier
    celui d'une relecture servie par le cache reviendrait à annoncer qu'un juge LLM est
    gratuit.
    """
    if ledger is None:
        return 0.0, 0, ""
    paid = float(getattr(ledger, "cost_usd", 0.0) or 0.0)
    avoided = float(getattr(ledger, "avoided_cost_usd", 0.0) or 0.0)
    calls = int(getattr(ledger, "calls", 0) or 0)
    cached = int(getattr(ledger, "cached_calls", 0) or 0)
    note = ""
    if cached:
        note = (
            f"{cached} appels servis par le cache (coût évité {avoided:.5f} $) : le coût "
            "publié est celui d'une première exécution, pas d'une relecture."
        )
    return paid + avoided, calls + cached, note


def _make_channel(spec: str, recorded: str | None) -> tuple[Any | None, str]:
    """Instancie le canal demandé ; renvoie (canal, message d'indisponibilité)."""
    from .channels import DirectHTTPChannel, PlaywrightChannel, RecordedChannel

    spec = spec.lower()
    if spec == "none":
        return None, "canal « none » : aucune sonde réseau n'a été exécutée"
    if spec in ("direct", "direct-browser"):
        channel: Any = DirectHTTPChannel(profile="browser")
    elif spec == "direct-minimal":
        channel = DirectHTTPChannel(profile="minimal")
    elif spec in ("browser", "browser-local", "playwright"):
        channel = PlaywrightChannel()
    elif spec == "recorded":
        if not recorded:
            return None, "canal « recorded » demandé sans --recorded : aucune observation à rejouer"
        channel = RecordedChannel(recorded, source=str(recorded))
    else:  # pragma: no cover - argparse borne déjà les valeurs
        return None, f"canal inconnu : {spec}"
    if not channel.available():
        return None, (
            f"canal « {spec} » indisponible dans cet environnement "
            f"({type(channel).__name__}) : la couche L2 est déclarée non exécutée plutôt "
            "que simulée"
        )
    return channel, ""


def _stratified_head(tasks: Sequence[Task], limit: int) -> list[Task]:
    """Sous-échantillon par site, pour les essais rapides (jamais pour un chiffre publié)."""
    if limit <= 0 or limit >= len(tasks):
        return list(tasks)
    buckets: dict[str, list[Task]] = defaultdict(list)
    for task in tasks:
        buckets[task.site or "unknown"].append(task)
    out: list[Task] = []
    index = 0
    while len(out) < limit:
        added = False
        for site in sorted(buckets):
            if index < len(buckets[site]) and len(out) < limit:
                out.append(buckets[site][index])
                added = True
        if not added:
            break
        index += 1
    return out


def _run_layers(
    args: argparse.Namespace, today: _dt.date
) -> tuple[Any, Any, list[str], list[str], dict[str, Any]]:
    """Exécute les couches ; renvoie (bulletin, coût, notes, couches exécutées, protocole).

    Isolé de `cmd_audit` pour que `bdoctor score-model` rejoue exactement la même
    campagne : l'analyse de sensibilité doit porter sur les mêmes constats que le rapport
    publié, sans quoi elle ne prouve rien.
    """
    from .report import MeasurementCost

    layers = [l.strip().upper() for l in args.layers.split(",") if l.strip()]
    unknown = [l for l in layers if l not in ("L1", "L2", "L3")]
    if unknown:
        raise SystemExit(f"couches inconnues : {', '.join(unknown)} (attendu : l1, l2, l3)")

    parser_fn = PARSERS[args.format]
    tasks = parser_fn(args.corpus, benchmark=args.benchmark)
    if args.limit:
        tasks = _stratified_head(tasks, args.limit)

    cost = MeasurementCost()
    notes: list[str] = []
    executed: list[str] = []
    #: Configuration effective des détecteurs. Elle voyage jusqu'au différentiel, qui s'en
    #: sert pour refuser de comparer deux mesures produites par des outils différents.
    protocol: dict[str, Any] = {}

    print(f"benchmark-doctor {__version__} — audit de {args.benchmark}")
    print(f"corpus  : {args.corpus} ({len(tasks)} tâches, format {args.format})")
    print(f"date    : {today.isoformat()}   couches demandées : {','.join(layers)}")

    start = time.perf_counter()
    if "L1" in layers:
        health = run_l1(tasks, today=today, benchmark=args.benchmark, source=str(args.corpus))
        executed.append("L1")
        cost.add("L1", usd=0.0, calls=0, seconds=time.perf_counter() - start)
        print(f"  L1 statique     : {len(health.verdicts)} tâches analysées "
              f"({time.perf_counter() - start:.1f} s, 0,00 $)")
    else:
        health = BenchmarkHealth(
            benchmark=args.benchmark, generated_at=today, source=str(args.corpus),
            tool_version=__version__,
        )
        for task in tasks:
            health.verdicts.append(
                TaskVerdict(task=task, evaluated_at=today, channels=[Channel.STATIC])
            )
        notes.append("Couche L1 non exécutée à la demande de l'appelant.")

    by_id = {v.task.task_id: v for v in health.verdicts}

    if "L2" in layers:
        channel, why = _make_channel(args.channel, args.recorded)
        if channel is None:
            notes.append(f"Couche L2 demandée mais non exécutée — {why}.")
            print(f"  L2 sondes web   : NON EXÉCUTÉE — {why}")
        else:
            from .detectors.l2_content import detect_content_existence
            from .detectors.l2_liveness import detect_liveness

            memo = _MemoChannel(channel)
            start = time.perf_counter()
            n_liveness = n_content = 0
            for verdict in health.verdicts:
                for finding in detect_liveness(verdict.task, channel=memo, today=today):
                    verdict.add(finding)
                    n_liveness += 1
                if args.l2_content:
                    for finding in detect_content_existence(
                        verdict.task, channel=memo, today=today
                    ):
                        verdict.add(finding)
                        n_content += 1
            elapsed = time.perf_counter() - start
            executed.append("L2")
            cost.add("L2", usd=0.0, calls=memo.n_fetches, seconds=elapsed)
            cost.notes.append(
                f"L2 : {memo.n_fetches} requêtes HTTP réelles pour {len(health.verdicts)} "
                f"tâches ({memo.n_hits} réponses mémoïsées) — coût en argent nul, coût en "
                "requêtes borné par le nombre d'URL distinctes du corpus."
            )
            health.notes.append(
                "Canal L2 : " + json.dumps(memo.describe(), ensure_ascii=False)
            )
            protocol["l2_channel"] = memo.name
            protocol["l2_channel_kind"] = memo.kind.value
            protocol["l2_content_checks"] = bool(args.l2_content)
            notes.append(
                "Le verdict d'accès est mesuré par URL de départ puis propagé aux tâches "
                "du site : WebVoyager ne fournit pas d'autre URL. La mesure borne donc la "
                "décadence par le bas et ne dit rien de l'état du site après navigation."
            )
            print(f"  L2 sondes web   : {memo.n_fetches} requêtes ({args.channel}), "
                  f"{n_liveness} constats d'accès, {n_content} constats de contenu "
                  f"({elapsed:.1f} s, 0,00 $)")

    if "L3" in layers:
        try:
            from .detectors.l3_ambiguity import build_scorer, run_ambiguity
        except Exception as exc:  # pragma: no cover - dépend de l'environnement
            notes.append(f"Couche L3 demandée mais non exécutée : {exc}")
            print(f"  L3 sondes LLM   : NON EXÉCUTÉE — {exc}")
        else:
            start = time.perf_counter()
            try:
                scorer = build_scorer(args.l3_backend)
                batches = run_ambiguity(tasks, scorer=scorer, today=today)
            except Exception as exc:
                notes.append(f"Couche L3 (ambiguïté) non exécutée : {exc}")
                print(f"  L3 ambiguïté    : NON EXÉCUTÉE — {exc}")
            else:
                n_amb = 0
                for task, findings in zip(tasks, batches):
                    for finding in findings:
                        by_id[task.task_id].add(finding)
                        n_amb += 1
                elapsed = time.perf_counter() - start
                usd, calls, cache_note = _ledger_cost(getattr(scorer, "ledger", None))
                if cache_note:
                    cost.notes.append("L3 ambiguïté : " + cache_note)
                executed.append("L3")
                protocol["l3_ambiguity_backend"] = getattr(scorer, "name", args.l3_backend)
                protocol["l3_ambiguity_threshold"] = round(float(getattr(scorer, "threshold", 0.5)), 4)
                cost.add("L3", usd=usd, calls=calls, seconds=elapsed)
                if calls > len(tasks):
                    # Le backend distant calibre son seuil en notant les 139 tâches du jeu
                    # annoté avant de traiter le corpus. C'est un coût FIXE, payé une fois
                    # et servi par le cache ensuite ; le confondre avec le coût marginal
                    # par tâche fausserait toute comparaison coût/performance.
                    cost.notes.append(
                        f"L3 : {calls} appels pour {len(tasks)} tâches — l'écart est la "
                        "passe de calibration du seuil sur le jeu annoté (139 énoncés), "
                        "coût fixe payé une seule fois puis servi par le cache."
                    )
                print(f"  L3 ambiguïté    : {n_amb} tâches signalées "
                      f"(backend {getattr(scorer, 'name', args.l3_backend)}, "
                      f"{elapsed:.1f} s, {usd:.5f} $)")
                if getattr(scorer, "calibration_degenerate", False):
                    notes.append(
                        "Le seuil calibré du backend L3 était dégénéré (il signalait plus "
                        "de 90 % du corpus) : il a été ramené à 0,5 par le garde-fou de "
                        "`build_scorer`. Les constats d'ambiguïté sont à lire avec réserve."
                    )

            if args.l3_solvability:
                start = time.perf_counter()
                try:
                    from .detectors.l3_solvability import run_solvability

                    verdicts, batches, ledger = run_solvability(tasks, today=today)
                except Exception as exc:
                    notes.append(f"Couche L3 (solvabilité) non exécutée : {exc}")
                    print(f"  L3 solvabilité  : NON EXÉCUTÉE — {exc}")
                else:
                    n_solv = 0
                    for task, findings in zip(tasks, batches):
                        for finding in findings:
                            by_id[task.task_id].add(finding)
                            n_solv += 1
                    elapsed = time.perf_counter() - start
                    usd, calls, cache_note = _ledger_cost(ledger)
                    protocol["l3_solvability"] = True
                    if cache_note:
                        cost.notes.append("L3 solvabilité : " + cache_note)
                    cost.add("L3", usd=usd, calls=calls, seconds=elapsed)
                    if "L3" not in executed:
                        executed.append("L3")
                    print(f"  L3 solvabilité  : {n_solv} constats ({elapsed:.1f} s, {usd:.5f} $)")
                    notes.append(
                        "Les constats de solvabilité sont produits sans consulter le site "
                        "(canal LLM) : ce sont des a priori datés de la coupure "
                        "d'entraînement du modèle, à confirmer par une sonde L2."
                    )

    return health, cost, notes, executed, protocol


def _load_prior(args: argparse.Namespace, notes: list[str]) -> Any:
    """Charge l'a priori des praticiens, ou un index vide si l'appelant le refuse."""
    from .scoring import PractitionerPrior

    prior = PractitionerPrior.empty() if args.no_prior else PractitionerPrior.load(args.prior)
    if not args.no_prior and len(prior) == 0:
        notes.append(
            "Aucune base de verdicts de praticiens trouvée : le score est celui des "
            "détecteurs seuls."
        )
    return prior


def cmd_audit(args: argparse.Namespace) -> int:
    """Campagne complète : détection multi-couches, score de stabilité, carte de santé."""
    from .report import build_card, write_card
    from .scoring import DEFAULT_MODEL, score_health

    today = _parse_date(args.today) or _dt.date.today()
    health, cost, notes, executed, protocol = _run_layers(args, today)

    prior = _load_prior(args, notes)
    assessments = score_health(health, model=DEFAULT_MODEL, prior=prior, today=today)
    card = build_card(
        health,
        model=DEFAULT_MODEL,
        prior=prior,
        assessments=assessments,
        today=today,
        layers=executed or ["(aucune)"],
        cost=cost,
        notes=notes,
        protocol=protocol,
    )

    summary = card.summary()
    print()
    print(f"stabilité moyenne : {summary['mean_stability']:.3f} "
          f"(détecteurs seuls {summary['mean_stability_detector_only']:.3f})")
    print(f"médiane           : {summary['median_stability']:.3f}   "
          f"décile inférieur : {summary['p10_stability']:.3f}")
    print("notes             : " + "  ".join(
        f"{g} {summary['grades'][g]:4d} ({100 * summary['grade_rates'][g]:4.1f} %)"
        for g in ("A", "B", "C", "D")))
    print(f"sous la note A    : {summary['n_below_A']}/{card.n_tasks} "
          f"({100 * summary['rate_below_A']:.1f} %)")
    print(f"coût de la mesure : {cost.total_usd:.5f} $ "
          f"({cost.total_calls} appels, {cost.total_seconds:.1f} s)")

    print("\nLes 10 tâches les plus dégradées :")
    from .scoring import most_degraded

    for a in most_degraded(assessments, limit=10):
        print(f"  {a.task_id:<22} {a.grade}  S={a.score:.3f}  {a.headline_category:<3} "
              f"{a.headline_explanation[:78]}")

    html_path, json_path = _resolve_outputs(args.out, args.json)
    written = write_card(card, json_path=json_path, html_path=html_path,
                         template_dir=args.templates)
    print()
    for kind, path in written.items():
        print(f"rapport {kind.upper():4s} : {path}")
    if json_path and html_path:
        print("Le JSON est la source du différentiel : conservez-le pour "
              "`bdoctor diff ancien.json nouveau.json`.")
    return 0


def _resolve_outputs(out: str | None, json_out: str | None) -> tuple[str | None, str | None]:
    """Déduit les chemins HTML et JSON des options ``--out`` / ``--json``.

    Un audit écrit toujours son JSON quand un HTML est demandé : le différentiel se
    calcule sur le JSON, et une surveillance qui ne garderait que la page HTML serait
    incapable de se comparer à elle-même la semaine suivante.
    """
    html_path = json_path = None
    if out:
        suffix = Path(out).suffix.lower()
        if suffix in (".html", ".htm"):
            html_path = out
            json_path = json_out or str(Path(out).with_suffix(".json"))
        elif suffix == ".json":
            json_path = out
        else:
            html_path = out + ".html"
            json_path = json_out or out + ".json"
    if json_out:
        json_path = json_out
    if not out and not json_out:
        json_path = None
    return html_path, json_path


def cmd_diff(args: argparse.Namespace) -> int:
    """Différentiel de santé entre deux cartes datées."""
    from .report import compare_cards, write_diff

    diff = compare_cards(args.before, args.after, epsilon=args.epsilon)
    data = diff.to_dict(limit=args.show)
    head = data["headline"]

    print(f"benchmark-doctor {__version__} — différentiel de santé")
    print(f"  {data['before']['generated_at']}  ({data['before']['n_tasks']} tâches, "
          f"couches {'+'.join(data['before'].get('layers') or [])})")
    print(f"→ {data['after']['generated_at']}  ({data['after']['n_tasks']} tâches, "
          f"couches {'+'.join(data['after'].get('layers') or [])})")
    print(f"  intervalle : {head['days_elapsed']} jours")

    if not data["comparability"]["comparable"]:
        print("\nComparabilité limitée, à lire avant toute interprétation :")
        for warning in data["comparability"]["warnings"]:
            print(f"  - {warning}")

    print(f"\nΔ stabilité moyenne : {head['mean_stability_delta']:+.4f} "
          f"({data['before']['mean_stability']:.3f} → {data['after']['mean_stability']:.3f})")
    print(f"dégradées  : {head['n_degraded']:4d}  ({100 * head['rate_degraded']:.1f} % du corpus commun)")
    print(f"améliorées : {head['n_improved']:4d}")
    print(f"inchangées : {head['n_unchanged']:4d}")
    print(f"perdent la note A : {head['n_left_A']}   basculent en D : {head['n_new_D']}")
    print(f"apparues : {head['n_appeared']}   disparues : {head['n_disappeared']}")
    print(f"rythme : {head['degradation_per_100_tasks_per_month']:.2f} dégradations "
          "pour 100 tâches et par mois (extrapolation linéaire)")

    if data["grade_migration"]:
        print("\nMigrations de notes :")
        for transition, n in data["grade_migration"].items():
            print(f"  {transition:<10} {n:4d}")

    if data["degraded"]:
        print(f"\nTâches dégradées (les {min(args.show, len(data['degraded']))} pires) :")
        for row in data["degraded"][: args.show]:
            print(f"  {row['task_id']:<22} {row['grade_before']}→{row['grade_after']}  "
                  f"{row['score_before']:.3f}→{row['score_after']:.3f}  "
                  f"({row['delta']:+.3f})  {row['top_category_after'] or ''}")

    if data["by_site_delta"]:
        print("\nDérive par site (les plus dégradés d'abord) :")
        for site, row in list(data["by_site_delta"].items())[:10]:
            print(f"  {site:<22} {row['before']:.3f} → {row['after']:.3f}  ({row['delta']:+.3f})")

    html_path, json_path = _resolve_outputs(args.out, args.json)
    if html_path or json_path:
        written = write_diff(diff, json_path=json_path, html_path=html_path,
                             template_dir=args.templates, limit=args.show)
        print()
        for kind, path in written.items():
            print(f"différentiel {kind.upper():4s} : {path}")
    return 0


def cmd_score_model(args: argparse.Namespace) -> int:
    """Recalcule les constantes du score et chiffre la sensibilité à chacune.

    κ et λ sont re-dérivés depuis les mesures qui les fondent, puis on montre ce que le
    score devient si on les change. La commande produit aussi l'ablation de l'hypothèse
    d'indépendance entre catégories et la comparaison des deux échelles de notes en
    circulation.
    """
    from .scoring import (
        DEFAULT_MODEL,
        calibrate_channel_credibility,
        calibrate_world_decay,
        compare_aggregations,
        compare_grade_scales,
        score_health,
        sensitivity_channel_credibility,
    )

    today = _parse_date(args.today) or _dt.date.today()
    health, cost, notes, executed, protocol = _run_layers(args, today)
    prior = _load_prior(args, notes)
    assessments = score_health(health, model=DEFAULT_MODEL, prior=prior, today=today)

    report: dict[str, Any] = {
        "tool_version": __version__,
        "reference_date": today.isoformat(),
        "corpus": str(args.corpus),
        "layers_executed": executed,
        "protocol": protocol,
        "model": DEFAULT_MODEL.provenance(),
        "calibration": {},
        "sensitivity": {},
    }

    print("\n" + "=" * 78)
    print("CALIBRATION DES CONSTANTES (re-dérivées depuis les mesures)")
    print("=" * 78)

    if args.probe_report and Path(args.probe_report).exists():
        kappa = calibrate_channel_credibility(args.probe_report)
        report["calibration"]["channel_credibility"] = kappa
        print(f"\nκ — crédibilité d'un constat de blocage (source : {args.probe_report})")
        print(f"  URL bloquées recoupables avec un navigateur : {kappa['n_checkable']}")
        print(f"  blocages confirmés par le navigateur        : {kappa['n_confirmed']}")
        print(f"  estimateur brut  k/n                        : {kappa['kappa_naive']}")
        print(f"  estimateur Laplace (k+1)/(n+2)  → RETENU    : {kappa['kappa_laplace']}")
        for row in kappa["detail"]:
            print(f"    {row['url']:<38} direct={list(row['direct'].values())} "
                  f"navigateur={list(row['browser'].values())}")
    else:
        print("\nκ : rapport de sondes absent (--probe-report), calibration non rejouée.")

    decay = calibrate_world_decay(args.prior)
    report["calibration"]["world_decay"] = decay
    print("\nλ — décadence mensuelle d'une observation de l'état du monde")
    for key in ("online_mind2web", "webvoyager_control"):
        row = decay.get(key)
        if row:
            print(f"  {key:<20} {row['replaced' if 'replaced' in row else 'flagged']}"
                  f"/{row['corpus']} en {row['window_months']} mois "
                  f"→ λ={row['lambda_per_month']}  demi-vie {row['half_life_months']} mois")
    print(f"  retenu : {decay['retained']} ({decay['retained_source']})")

    print("\n" + "=" * 78)
    print("SENSIBILITÉ DU SCORE AUX PARAMÈTRES")
    print("=" * 78)

    agg = compare_aggregations(health, prior=prior, today=today)
    report["sensitivity"]["aggregation"] = agg
    print("\nH3 — indépendance des catégories (OU bruité) vs maximum :")
    print(f"  tâches multi-catégories        : {agg['n_tasks_multi_category']} "
          f"({100 * agg['rate_multi_category']:.1f} %)")
    print(f"  stabilité moyenne OU bruité    : {agg['mean_score_noisy_or']}")
    print(f"  stabilité moyenne maximum      : {agg['mean_score_max']}")
    print(f"  écart absolu moyen             : {agg['mean_abs_delta']}  (max {agg['max_abs_delta']})")
    print(f"  changements de note            : {agg['n_grade_changes']} / {agg['n_tasks']}")

    sens = sensitivity_channel_credibility(health, prior=prior, today=today)
    report["sensitivity"]["channel_credibility"] = sens
    print("\nκ — effet sur la distribution des notes :")
    print(f"  {'κ':>6} {'stabilité ⌀':>13} {'A':>5} {'B':>5} {'C':>5} {'D':>5} {'sous A':>8}")
    for row in sens["rows"]:
        g = row["grades"]
        print(f"  {row['kappa']:>6.3f} {row['mean_stability']:>13.4f} "
              f"{g['A']:>5} {g['B']:>5} {g['C']:>5} {g['D']:>5} "
              f"{100 * row['rate_below_A']:>7.1f} %")

    scales = compare_grade_scales(assessments)
    report["sensitivity"]["grade_scales"] = scales
    print("\nÉchelles de notes en circulation :")
    print(f"  retenue (1 − w(σ))  A≥{scales['thresholds_retained']['A']:.2f} "
          f"B≥{scales['thresholds_retained']['B']:.2f} C≥{scales['thresholds_retained']['C']:.2f}"
          f"  →  {scales['distribution_retained']}")
    print(f"  héritée (models.py) A≥{scales['thresholds_legacy']['A']:.2f} "
          f"B≥{scales['thresholds_legacy']['B']:.2f} C≥{scales['thresholds_legacy']['C']:.2f}"
          f"  →  {scales['distribution_legacy']}")
    print(f"  migrations : {scales['migrations']}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"\nRapport JSON écrit dans {args.json}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bdoctor",
        description="Surveillance de la santé des benchmarks d'agents web (decay).",
    )
    parser.add_argument("--version", action="version", version=f"benchmark-doctor {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="bulletin de santé statique (couche L1) d'un corpus")
    scan.add_argument("corpus", help="fichier JSONL au format WebVoyager")
    scan.add_argument("--benchmark", default="webvoyager", help="nom logique du corpus")
    scan.add_argument("--today", help="date de référence AAAA-MM-JJ (défaut : aujourd'hui)")
    scan.add_argument("--threshold", default="high",
                      choices=[s.value for s in Severity], help="seuil de flag dur")
    scan.add_argument("--policy", choices=list(ABLATIONS),
                      help="politique de décision explicite (remplace le seuil de sévérité)")
    scan.add_argument("--json", help="chemin du rapport JSON à écrire")
    scan.set_defaults(func=cmd_scan)

    ev = sub.add_parser("l1-eval", help="précision/rappel de L1 contre un patch-set")
    ev.add_argument("corpus", help="fichier JSONL au format WebVoyager")
    ev.add_argument("--patches", required=True, help="patch-set JSON (format Magnitude)")
    ev.add_argument("--benchmark", default="webvoyager")
    ev.add_argument("--today", help="date de référence AAAA-MM-JJ")
    ev.add_argument("--cross", nargs="*", default=[],
                    help="patch-sets indépendants (partiels) pour mesurer la généralisation")
    ev.add_argument("--show", type=int, default=15, help="nombre de nouveaux flags à lister")
    ev.add_argument("--json", help="chemin du rapport JSON à écrire")
    ev.set_defaults(func=cmd_l1_eval)

    au = sub.add_parser(
        "audit",
        help="campagne multi-couches + carte de santé (JSON et HTML)",
        description=(
            "Applique les couches demandées, calcule le score de stabilité task-side de "
            "chaque tâche et produit la carte de santé. Exemple : bdoctor audit "
            "data/raw/webvoyager_original.jsonl --format webvoyager --layers l1,l2,l3 "
            "--channel direct --out rapport.html"
        ),
    )
    au.add_argument("corpus", help="fichier de tâches à auditer")
    au.add_argument("--format", default="webvoyager", choices=list(PARSERS),
                    help="format du corpus (défaut : webvoyager)")
    au.add_argument("--layers", default="l1",
                    help="couches à exécuter, séparées par des virgules : l1,l2,l3")
    au.add_argument("--channel", default="direct",
                    choices=["direct", "direct-minimal", "browser-local", "recorded", "none"],
                    help="canal d'accès de la couche L2 (défaut : direct = HTTP, en-têtes "
                         "de navigateur, depuis l'IP courante)")
    au.add_argument("--recorded", help="JSON d'observations à rejouer (canal « recorded »)")
    au.add_argument("--l2-content", action="store_true",
                    help="vérifier aussi l'existence des contenus cités (couverture faible, "
                         "cf. rapport L2)")
    au.add_argument("--l3-backend", default="tfidf",
                    help="backend d'ambiguïté : tfidf (défaut, gratuit) | minilm | "
                         "openrouter | llm")
    au.add_argument("--l3-solvability", action="store_true",
                    help="ajouter le vérificateur de solvabilité (appels LLM facturés)")
    au.add_argument("--benchmark", default="webvoyager", help="nom logique du corpus")
    au.add_argument("--today", help="date de référence AAAA-MM-JJ (défaut : aujourd'hui)")
    au.add_argument("--limit", type=int, default=0,
                    help="n'auditer qu'un sous-échantillon stratifié par site (essais only)")
    au.add_argument("--no-prior", action="store_true",
                    help="ignorer les verdicts de praticiens : score des détecteurs seuls")
    au.add_argument("--prior", help="chemin d'une base de verdicts (défaut : data/ground_truth.json)")
    au.add_argument("--out", help="chemin du rapport HTML (le JSON est écrit à côté)")
    au.add_argument("--json", help="chemin du rapport JSON")
    au.add_argument("--templates", help="répertoire des gabarits HTML")
    au.set_defaults(func=cmd_audit)

    df = sub.add_parser(
        "diff",
        help="différentiel de santé entre deux cartes datées (surveillance continue)",
        description=(
            "Compare deux cartes de santé JSON produites par `bdoctor audit`. C'est cette "
            "vue qui distingue une surveillance continue d'un audit ponctuel."
        ),
    )
    df.add_argument("before", help="carte de santé JSON la plus ancienne")
    df.add_argument("after", help="carte de santé JSON la plus récente")
    df.add_argument("--epsilon", type=float, default=0.01,
                    help="écart de score en deçà duquel une tâche est dite inchangée")
    df.add_argument("--show", type=int, default=25, help="nombre de tâches à lister")
    df.add_argument("--out", help="chemin du différentiel HTML")
    df.add_argument("--json", help="chemin du différentiel JSON")
    df.add_argument("--templates", help="répertoire des gabarits HTML")
    df.set_defaults(func=cmd_diff)

    sm = sub.add_parser(
        "score-model",
        help="re-dérive les constantes du score de stabilité et chiffre leur sensibilité",
        description=(
            "Recalcule κ et λ depuis les mesures qui les fondent, puis montre l'effet de "
            "chaque paramètre sur la distribution des notes. Aucune constante du score "
            "n'est à croire sur parole."
        ),
    )
    sm.add_argument("corpus", help="fichier de tâches")
    sm.add_argument("--format", default="webvoyager", choices=list(PARSERS))
    sm.add_argument("--layers", default="l1,l2",
                    help="couches à exécuter (l2 est nécessaire pour que κ ait un effet)")
    sm.add_argument("--channel", default="direct",
                    choices=["direct", "direct-minimal", "browser-local", "recorded", "none"])
    sm.add_argument("--recorded", help="JSON d'observations à rejouer")
    sm.add_argument("--l2-content", action="store_true")
    sm.add_argument("--l3-backend", default="tfidf")
    sm.add_argument("--l3-solvability", action="store_true")
    sm.add_argument("--benchmark", default="webvoyager")
    sm.add_argument("--today", help="date de référence AAAA-MM-JJ")
    sm.add_argument("--limit", type=int, default=0)
    sm.add_argument("--no-prior", action="store_true")
    sm.add_argument("--prior", help="base de verdicts (défaut : data/ground_truth.json)")
    sm.add_argument("--probe-report", default="runs/l2_probe_20260815.json",
                    help="rapport de sondes L2 d'où re-dériver κ")
    sm.add_argument("--json", help="chemin du rapport JSON à écrire")
    sm.set_defaults(func=cmd_score_model)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
