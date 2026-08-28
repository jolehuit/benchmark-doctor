# benchmark-doctor

**Continuous health monitoring for web-live agent benchmarks.**

Web-live agent benchmarks are built on the open web, and the open web moves: hard-coded dates go
past, named products disappear, sites start blocking robots. A benchmark can stay executable while
it stops being valid, because nothing crashes and the numbers simply stop measuring what they used
to. `benchmark-doctor` measures that gap task by task, at an explicit reference date and through an
explicit access channel. Applied to [WebVoyager](https://github.com/MinorJerry/WebVoyager) (643
tasks, upstream frozen since 2024-03-02), it grades 67.3 % of the corpus below A for \$0.00041 per
task, and 100 % of the dated task rewrites a maintainer published in July 2025 had expired again
thirteen months later.

v0.1, research code released with an M2 thesis (Université Paris Cité, 2026), WebVoyager
instrumented end to end and Online-Mind2Web used as a control. Identifiers, CLI flags, this README
and `docs/METHODOLOGY.md` are English; docstrings, CLI output, report field names and the source
records under `docs/` and `exports/` are French, having been written for a French-language thesis.

## What it found

The canonical configuration, and the only one quoted here: WebVoyager, 643 tasks, 15 sites,
reference date 2026-08-15, layers L1+L2+L3 with the solvability pass, L2 over direct HTTP from a
datacenter IP, L3 judged by `google/gemini-2.5-flash` at threshold 0.5, practitioner prior folded
in, grade boundaries 0.75 / 0.50 / 0.25. [`runs/CARTES.md`](runs/CARTES.md) gives the status of the
twelve files of `runs/` that publish a grade distribution.

| Health card | Value |
|---|---|
| Mean task stability | 0.585 (0.612 with detectors only, ignoring the practitioner prior) |
| Median, 10th percentile | 0.569, 0.163 |
| Grades A / B / C / D | 210 (32.7 %) / 138 (21.5 %) / 185 (28.8 %) / 110 (17.1 %) |
| Below grade A | 433 / 643 = 67.3 % |
| Cost | \$0.26298, 1 331 outbound calls (45 HTTP probes, 1 286 LLM), 39.2 s, \$0.000409 per task |

That cost is the price of a first execution, L3 answers being cached on disk. The card replays
offline from the frozen findings journal, through `python3 experiments/carte_canonique.py --check`.
Counting tasks that carry at least one signal of a category: T5 ambiguity 240 (37.3 %), T2 content
drift 187 (29.1 %), T3 access denied 183 (28.5 %), T7 eval brittleness 163 (25.3 %), T1 temporal 124
(19.3 %), T4 UI instability and T8 timing 7 each, T6 multiple solutions none. The T4 and T8 signals
come entirely from human annotators, no detector here emitting those or T6, and the T5 rate is an
upper bound, produced with the first judge rubric, which quoted five statements of the evaluated
set. By site, Booking (0.223 mean stability, 33 of its 44 tasks in D) and Google Flights (0.329) are
at the bottom, both transactional and date-bound, Wolfram Alpha at the top with 0.882; ESPN (0.455)
and Allrecipes (0.471) sit low because they blocked the probes, which is why every finding carries
its channel. Per-site detail and prevalence by detector origin:
[`runs/health_20260815.json`](runs/health_20260815.json).

Magnitude published 121 motivated patches on 2025-07-06, 68 of which rewrite a statement and 65 of
those carry a date. Thirteen months later, 65 of the 65 dated rewrites were past, 60 of them in a
blocking way (a transactional task), and none held a future date.

## Install and use

```bash
git clone https://github.com/jolehuit/benchmark-doctor && cd benchmark-doctor
pip install -e ".[probe,llm]"   # L1, plus requests for the L2 direct channel and httpx for L3
```

Without extras, L1 imports nothing outside the standard library; `browser` adds Playwright for the
optional local-browser channel, `figures` adds matplotlib and numpy for `figures/make_figures.py`,
`stats` adds numpy and scipy for `experiments/validation_hors_echantillon.py`, and `dev` adds
pytest. L3 reads an OpenRouter key from the environment (`OPENROUTER_API_KEY`, or an untracked
`.env`) that L1 and L2 do not need.

`data/` is versioned here: a clone already carries the WebVoyager corpus, the patch-set files under
`data/raw/` and the reconciled `data/ground_truth.json`, so every command below runs on a fresh
clone without downloading anything. The block that follows redoes the recovery from the upstream
sources, for a reader who would rather rebuild those files than trust the copies kept here.

```bash
curl -sSL -o data/raw/webvoyager_original.jsonl \
  https://raw.githubusercontent.com/MinorJerry/WebVoyager/091544539eba485dbd74ef3742011ddeede37336/data/WebVoyager_data.jsonl
# expected sha256: 69b19fd86c23f1a500244a3724e039aa7ca6a1223d03e11eb10e308d4f11c488
python3 -m benchmark_doctor.ground_truth.fetch_sources --force   # pinned revisions
python3 -m benchmark_doctor.ground_truth.reconcile               # rebuilds data/ground_truth.json
```

`fetch_sources` retrieves seven files and skips any that is already there unless `--force` is
passed. It covers four of the eight dated patch-sets end to end (Skyvern 01/2025, Convergence, Fara,
Alumnium, whose history it replays commit by commit) plus one of the two browser-use files; the
Magnitude, Emergence and Skyvern 05/2026 files and browser-use's list of impossible tasks are not
scripted, and `benchmark_doctor/ground_truth/sources.py` pins the revision of each. Those eight
snapshots come from seven teams, Skyvern having published twice, and six of them are counted in the
inter-annotator agreement.

```bash
# Static health bulletin: L1 only, free, offline, at an explicit reference date
bdoctor scan data/raw/webvoyager_original.jsonl --today 2026-08-15 --json runs/health.json

# Full campaign and health card, JSON and standalone HTML
bdoctor audit data/raw/webvoyager_original.jsonl \
    --layers l1,l2,l3 --channel direct --l3-backend llm --l3-solvability \
    --today 2026-08-15 --out runs/health.html

# Differential between two dated cards, the continuous-monitoring primitive
bdoctor diff runs/health_2026-08-15.json runs/health_2026-08-22.json --json runs/diff.json
```

`--no-prior` scores on the detectors alone, which is what CI and every validation figure use.
`--channel` picks the L2 access channel: `direct` (HTTP with browser headers), `direct-minimal`
(bare client), `browser-local` (Playwright, if installed), `recorded` (replay a saved observation
file, so the numbers stay recomputable offline), `none`. Two cards are comparable only when produced
in the same configuration. `bdoctor --help` has the rest, and `benchmark_doctor` imports as a
library.

## Three layers ordered by cost

| Layer | What it inspects | Detectors | Cost on 643 tasks | Pays in |
|---|---|---|---:|---|
| L1 static | the task statement alone | `l1_temporal`, `l1_sideeffect`, `l1_reference` | \$0, 0.1 s, 0 requests | nothing |
| L2 web probes | the start URL: liveness, anti-bot, paywall, soft-404 | `l2_liveness`, `l2_content` | \$0, 45 requests, 38.5 s | requests and latency |
| L3 LLM probes | ambiguity and solvability of the statement | `l3_ambiguity`, `l3_solvability` | \$0.263, 1 286 calls, 0.5 s | money |

Each layer pays a different currency and has to earn its place before the next one is switched on.
L2 makes 45 requests for 643 tasks because the corpus shares 15 start URLs and observations are
memoised per host. L3 carries all the money, split almost evenly between ambiguity (\$0.13177) and
solvability (\$0.13121).

## Two rules that shape the design

Every finding carries its access channel. On 2026-08-15 at 23:10 UTC, `https://www.allrecipes.com/`
returned 402 Payment Required (Cloudflare pay-per-crawl) from a datacenter IP and 200 OK from a
cloud browser forty-seven seconds later, so the status of a task is a property of the pair (task,
access channel). `Finding.channel` is always present: it defaults to `static`, which is itself the
claim that no request was made, and a detector that opens a connection or calls a model records the
channel it used. Network findings are discounted by a credibility factor (κ = 0.40 for datacenter
HTTP), and a `CHANNEL_BLOCKED` signature is evaluated before anything is imputed to the site;
without it, this campaign would have declared the 41 GitHub tasks dead because of an egress proxy.

No binary verdict is ever stored. A `TaskVerdict` keeps its findings, each with a severity (how bad
it is if true) and a confidence (how sure the detector is), and whether a task counts as flagged is
computed on demand at an explicit threshold, so several decision policies can be replayed over one
campaign and any announced decay rate stays inseparable from the rule that produced it. Risks
aggregate as a noisy-OR, `risk = severity_weight × confidence`, and the boundaries 0.75 / 0.50 /
0.25 are each one finding of that severity held certain. The scale is ordinal: a stability of 0.30
does not announce a 30 % chance of failure.

## Validation, export, monitoring

The ground truth is six published repairs of WebVoyager read as annotations, and since a defective
task has no unique definition, five are measured side by side, from flagged by at least one
annotator (169 tasks) to flagged by all six (68). L1 alone reaches precision 0.986 at recall 0.426
against the first, but that figure is in-sample, 71 of its 72 true positives belonging to the
patch-set the detectors were tuned on; out of sample, on the 522 tasks Magnitude never touched, it
holds at precision 0.327 against 0.092 by chance, lift 3.55, p = 3.6·10⁻³ after site stratification.
Complete grids, per-category recall, per-detector contribution, decay rates and the Online-Mind2Web
control: [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md); disjoint-split validation:
[`experiments/CONTRE_VERIFICATION.md`](experiments/CONTRE_VERIFICATION.md).

`exports/webvoyager_verified_v0.1.jsonl` holds 643 lines, one per task, reconciling those six audits
with measured stability metadata: `noyau` (core, never flagged by anyone) 474, `surveiller` 26,
`corriger` 63, `retirer` 9, `conteste` 71. Verified refers to the reconciliation of verdicts and the
dating of measurements, never to a task being runnable, since 84 of the 563 consensual tasks carry a
date already past ([`exports/README.md`](exports/README.md) has the fields and the caveats).
[`.github/workflows/weekly.yml`](.github/workflows/weekly.yml) then runs L1 and L2 every Monday
without an API key, diffs the card against the previous week and opens an issue when mean stability
drops too far, refusing to alert when the two cards are not comparable, a different corpus digest,
different layers or a different L2 channel profile, because a movement caused by a protocol change
is decay only in appearance. Its runners have datacenter IPs, so every access finding it records
carries κ = 0.40, and it scores with `--no-prior`.

## Limits

1. Half the taxonomy is uninstrumented: no T4 (UI instability), T6 (multiple valid solutions) or T8
   (timing) detector at all, and T7 covered only by relative-date phrasing. Of the eight categories
   described, five have an emitter and four are recalled with the right category on labelled data.
2. Precision of the full stack is 0.449 at HIGH against `flagged≥1` and cannot be rescued at this
   scale. No number it produces settles the deletion of a task without a human opening the site.
3. Adding a layer can degrade the ranking. L1+L2 ranks better (AUC 0.831) than L1+L2+L3 (0.775):
   more coverage is not monotonically better under noisy-OR aggregation.
4. L2 findings are site-granular. One start URL per task, so an access verdict for a host propagates
   to all its tasks (Allrecipes 45/45, Booking 44/44, ESPN 44/44) and false positives cluster there.
5. The six patch-sets have different goals and thresholds, and silence counts as "keep" even when a
   source never examined the task, so the measured agreement is an upper bound.
6. 273 tasks that no annotator ever flagged score below A, 29 of them D. Whether those are false
   positives or defects nobody looked at is undecided here, and settling it means opening the sites.
7. The longitudinal instrument measures textual expiry, not execution failure: no agent was run. A
   past date is provably invalid on a transactional site, elsewhere only a loss of relevance.
8. Everything is frozen to 2026-08-15 (`REFERENCE_DATE` in `run_all.py`, `TODAY` in
   `analysis_longitudinal.py`). Changing that date changes every figure above.

## Reproduce

```bash
python3 run_all.py --phase audit      # L1+L2+L3 over 643 tasks at the frozen reference date
python3 run_all.py --phase validate   # P/R/F1, 5 ground truths, 2 thresholds, layer ablation
python3 run_all.py --phase export     # WebVoyager-Verified v0.1 and its README
python3 analysis_longitudinal.py      # mortality curves, decay rates, fork health, controls
python3 -m pytest -q
```

`--phase validate` replays `runs/health_20260815_findings.json` and needs neither network nor API
key. `--phase audit` re-runs the campaign against the live web, and what it measures today will
differ from the figures published here, taken on 2026-08-15. The pipeline tests lock those figures:
change a detector and they fail, which is the signal that everything above has to be recomputed.
Protocol: [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md). Contributing:
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Cite

```bibtex
@software{penso2026benchmarkdoctor,
  author = {Penso, Max}, year = {2026}, version = {0.1.0}, license = {MIT},
  title = {benchmark-doctor: continuous health monitoring for web-live agent benchmarks}
}

@mastersthesis{penso2026decay,
  author = {Penso, Max}, year = {2026}, type = {M\'emoire de Master 2 MIAGE},
  school = {Universit\'e Paris Cit\'e, UFR de Math\'ematiques et Informatique},
  title = {Le decay des benchmarks d'agents web : taxonomie, d\'etection automatis\'ee
           et \'etude longitudinale de WebVoyager}
}
```

If you use the reconciled verdict base or WebVoyager-Verified v0.1, please also cite the six
patch-set authors it reconciles, who did the looking; their pinned revisions are listed in
`benchmark_doctor/ground_truth/sources.py`.

## Licence

MIT for the code and for the fields this project adds. The third-party corpora and patch-sets kept
under `data/raw/`, at the revisions pinned in `benchmark_doctor/ground_truth/sources.py`, remain
under their own licences. See [`LICENSE`](LICENSE).
