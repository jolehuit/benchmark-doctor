# Measurement methodology

Reference measurement: WebVoyager, 643 tasks, 2026-08-15. Every figure below is dated, carries the
channel it was observed through, and is checked against the artifact that holds it by
`experiments/verifier_chiffres.py`.

## 1. What is measured

A benchmark task is a triple *(statement, start URL, expected outcome)* evaluated against the live
web, valid at time *t* if an agent solving it correctly at *t* would be scored correct and an agent
failing it would be scored incorrect. Decay is the loss of that property over time, the task text
unchanged; it is distinct from a construction flaw, from saturation, a property of the agent
population, and from agent-side reliability, the variance of an agent across runs. The measurable
proxy is a stability score in [0, 1] with an A to D grade, computed from findings, at an explicit
date, through an explicit channel. The scale is ordinal: reading a score as a probability of failure
claims more than the measurement supports.

The closest neighbouring work audits once rather than continuously: Emergence WebVoyager
(arXiv:2603.29020), a manual audit that prevents further decay by instantiating dates at run time;
ABA (arXiv:2605.26079), a generic audit of task validity with no liveness probing and no notion of
an access channel; BenchJack (arXiv:2605.12673), which audits scoring harnesses for exploitability;
Terminal-Bench 2.1, build-time quality control by the maintainers of a sandboxed benchmark. The
thirteen benchmarks surveyed are in `docs/panel_treize_benchmarks.md`.

## 2. Corpus and reference date

| | |
|---|---|
| Corpus | `MinorJerry/WebVoyager` @ `091544539eba485dbd74ef3742011ddeede37336` (2024-03-02) |
| File | `data/WebVoyager_data.jsonl`, saved as `data/raw/webvoyager_original.jsonl` |
| SHA-256 | `69b19fd86c23f1a500244a3724e039aa7ca6a1223d03e11eb10e308d4f11c488` |
| Tasks, sites | 643, 15 |
| Reference date | 2026-08-15, frozen (`REFERENCE_DATE` in `run_all.py`, `TODAY` in `analysis_longitudinal.py`) |

**The corpus is pinned, never `main`**: every card records `meta.corpus_sha256` and `bdoctor diff`
refuses to declare two cards comparable when the digests differ, so an upstream edit cannot be
counted as decay. The reference date is frozen rather than read from the clock, so published figures
do not drift between runs; `--today` moves it.

## 3. The access channel, and why every verdict carries it

On 2026-08-15 at 23:10 UTC, `https://www.allrecipes.com/` returned 402 Payment Required from a
datacenter IP and 200 OK from a cloud browser 47 seconds later. The status of a benchmark task is a
property of the pair *(task, access channel)*, and four consequences are wired into the code.

a. `Finding.channel` is always present. It defaults to `static`, which is itself the claim that no
request was made and is the right value for the whole L1 layer; a detector that opens a connection
or queries a model sets the channel it used, among `http_datacenter`, `http_residential`,
`browser_local`, `browser_cloud` and `llm`. Leaving the default on a network finding would make it
irreproducible and grant it the full credibility given to static observations.

b. Channel-imputable responses are eliminated before anything is imputed to the site, the L2
classifier evaluating the `CHANNEL_BLOCKED` signature first (`Observation.looks_proxy_mediated`). In
the reference campaign `github.com` returned 400 with a JSON body naming the measuring machine's
egress proxy, so the response never came from GitHub; without that precedence rule the campaign
would have declared the 41 GitHub tasks dead, 6.4 % of the corpus.

c. Network findings are discounted by a channel credibility factor κ, worth 0.40 for
`http_datacenter` and `http_residential` and 1.00 for `static`, `browser_local`, `browser_cloud` and
`llm`. It is derived in `runs/l2_probe_20260815.json`: of the blocked URLs for which a browser
channel was also available, 2 of 3 answered normally to the browser and 1 block was confirmed. With
a denominator of 3 it is a working constant rather than an estimate, it applies only to T3 findings
from a network channel, and `bdoctor score-model` reports how much the aggregates move when it is
varied. The crossed campaign of 2026-08-16 read 0.50 against the datacenter browser, an interval
overlapping 0.40, which is kept (`experiments/RAPPORT_CANAUX.md`).

d. Liveness is classified into signatures rather than a boolean, since `status == 200` is not
aliveness: `booking.com` returned 202 with `x-amzn-waf-action: challenge`. The signatures are `OK`,
`DEAD_404`, `PAYWALL_402`, `FORBIDDEN_403`, `ANTIBOT_CHALLENGE`, `CAPTCHA`, `REDIRECT_HOME`,
`SOFT_404`, `SERVER_ERROR`, plus three that describe the measurement instead of the site,
`CHANNEL_BLOCKED`, `UNREACHABLE` and `RATE_LIMITED`, each carrying the channel, the HTTP code, the
body size, the discriminating headers and an excerpt.

An access finding produced from a datacenter IP, which is what CI runners have and what the
reference campaign used, says the benchmark is not measurable from there. Death of the task is a
different claim, and it takes a re-probe through `--channel browser-local` or a recorded browser
observation replayed with `--channel recorded`.

## 4. Layers, detectors and cost

| Layer | Detectors | Observes | Cost (643 tasks) |
|---|---|---|---:|
| L1 static | `l1_temporal`, `l1_sideeffect`, `l1_reference` | the statement only | \$0, 0.1 s, 0 requests |
| L2 probes | `l2_liveness`, `l2_content` | the start URL | \$0, 45 HTTP requests |
| L3 LLM | `l3_ambiguity`, `l3_solvability` | the statement, judged | \$0.26298, 1 286 calls |

The campaign made 1 331 outbound calls in all, 45 L2 requests and 1 286 L3 calls, for \$0.26298 read
from the provider's `usage.cost` field, \$0.000409 per task. That is the price of a first
measurement; a re-run served by the on-disk cache `runs/l3_cache/` costs nothing, and that cache is
not versioned. L2 issues 45 requests for 643 tasks because WebVoyager gives one start URL per task
over 15 hosts, observations being memoised per host and throttled at one second. **That is also L2's
main weakness**: an access verdict for a host propagates to all of its tasks (Allrecipes 45/45,
Booking 44/44, ESPN 44/44).

The reference protocol is recorded in `meta.protocol` of the card: L2 channel `direct_http:browser`
of kind `http_datacenter`, content checks on, ambiguity backend `llm-judge:gemini-2.5-flash:rubric`
at threshold 0.5, solvability on. The classified excerpt length belongs to that protocol although the
card does not print it. `ChannelHTTP` keeps the first 3 000 characters of the body and the L2
classifier sees no more (`benchmark_doctor/channels.py`); a publisher marker buried past the cut
makes an interstitial pass for a normal page, enough to make two channels looking at the same page
diverge. The campaign of 2026-08-16 keeps 4 000 and checks that none of its own verdicts depends on
the choice. `--l3-backend` also accepts `tfidf` (free, default) and `minilm` (local
sentence-transformers), which run the ambiguity layer with no API key at reduced quality.

The judge is `google/gemini-2.5-flash`, an entry-level commercial model chosen for its cost rather
than its recency and replaceable at the price of a re-validation. It runs at temperature 0 under a
rubric with a decision threshold of 0.5, and the residual verdict flip at that threshold, over five
runs, is 0.7 %. Four things were tried and dropped: max-F1 calibration, which picks the degenerate
"everything is ambiguous" threshold as soon as the scores separate the classes poorly, replaced by
Youden's J; `gemini-2.5-flash-lite`, at AUC 0.551 with a clean rubric; paid embeddings, which do not
beat a free TF-IDF regression; and the first rubric, which quoted five statements of the evaluated
set and, rewritten with fabricated examples, took the judge from F1 0.827 to 0.715 ± 0.006.

## 5. From findings to a score

Nothing binary is stored. A `TaskVerdict` keeps its findings, each carrying a severity (how bad it is
if true) and a confidence (how sure the detector is), and whether a task counts as flagged is
computed on demand at an explicit threshold. Several decision policies can therefore be replayed over
one campaign, and any announced decay rate stays inseparable from the rule that produced it.

```
risk(finding)  = severity_weight × confidence × κ(channel, category)
risk(task)     = 1 − Π (1 − risk(finding))          # noisy-OR
stability      = 1 − risk(task)
```

| Constant | Value | Origin |
|---|---|---|
| severity weights | info 0, low 0.25, medium 0.50, high 0.75, critical 1.0 | evenly spaced, no fitting on data |
| grade boundaries | A > 0.75, B > 0.50, C > 0.25, D ≤ 0.25 | one finding of that severity held certain, `1 − w(σ)` |
| prior weights | remove 1.0, modify 0.5 | deletion is unrecoverable, a rewrite is weaker evidence because Magnitude re-dates pre-emptively |
| world decay | λ = 0.0143 / month | Online-Mind2Web replacement log, 52/300 tasks in 13.31 months |
| access decay | 0.0 / month | no measurement exists of weekly anti-bot signature volatility, repeatability was tested over 3 minutes |
| staleness | 30 days | an observation older than this is flagged `stale` in the card |

By default the score folds in a prior drawn from `data/ground_truth.json`, what six annotators did to
each task. It makes the card more useful for a reader choosing tasks to run, and unusable for
validation, since scoring it against the same annotators would measure the tool's ability to copy
what it was given. Validation and CI therefore use `--no-prior`; every card carries both
`stability_score` and `stability_score_detector_only`, and published precision and recall figures are
computed on findings, never on the score.

## 6. Ground truth: seven patch-sets, six annotators, five definitions

Seven teams published a repaired fork of WebVoyager. All revisions are pinned in
`benchmark_doctor/ground_truth/sources.py` and fetched by
`benchmark_doctor/ground_truth/fetch_sources.py`.

| Source | Date | Expresses | In agreement stats |
|---|---|---|---|
| browser-use/eval | 2024-12-15 | 55 tasks listed impossible, 76 statements silently rewritten | yes |
| Skyvern (snapshot 01/2025) | 2025-01-16 | 635 kept, 8 outdated | no, same annotator as 05/2026 |
| Convergence WebVoyager2025Valid | 2025-02-17 | 601 tasks valid until 20 December 2025, the only patch-set with a declared expiry | yes |
| Magnitude `patches.json` | 2025-07-06 | 121 motivated patches, 68 rewrites and 53 deletions | yes |
| Emergence (templates) | 2025-07-21 | 535 templated tasks, dates instantiated at run time | no, re-samples to 35/site |
| Microsoft Fara F595 | 2025-08-31 | 595 tasks kept, no reasons | yes |
| Alumnium | 2026-03-17 | 619 kept, 20 per-site commits whose messages carry the reason | yes |
| Skyvern (snapshot 05/2026) | 2026-05-04 | 635 kept, 8 outdated, commit "refresh dates to 2026/2027" | yes |

Two conventions are frozen because they change the numbers. The date retained is the artifact's
rather than the publication's: Emergence's task file has not moved since 2025-07-21 although the
paper is dated March 2026, and the file date governs the longitudinal study. Skyvern counts as two
dated observations but one annotator, since counting it twice would inflate inter-annotator agreement
with a duplicated voice.

"A defective task" has no unique definition, and publishing one precision-recall pair would silently
choose one. All five are measured side by side: L1's precision moves from 0.986 to 0.164 depending on
which is chosen. Known bias: silence counts as "keep" even when a source never examined a task, so
measured agreement is an upper bound.

| Key | Definition | n |
|---|---|---:|
| `flagged≥1` | flagged by ≥1 of the 6 annotators | 169 |
| `majority≥3` | flagged by a majority | 123 |
| `unanimous` | flagged by all 6 | 68 |
| `removed≥1` | *deleted* by ≥1 annotator | 78 |
| `magnitude` | the 121 Magnitude patches alone | 121 |

## 7. Validation protocol

Four decisions, each of which changes the result. Ablation by filtering: the three layers run once
and "L1 alone", "L1+L2", "L1+L2+L3" come from filtering the findings by layer, never from re-running
the campaign, which would introduce a variation of the world where a variation of method is measured.
Validation on findings, never on the published score. Both thresholds, since L3 emits only MEDIUM
findings by construction and evaluating it at HIGH would return zero mechanically. And threshold-free
ranking alongside, since a triage tool is used by sorting.

### Precision, recall and F1 at the MEDIUM threshold

The last column is the AUC of the detector-only ranking against `flagged≥1`, whose prevalence,
169/643 = 0.263, is also the precision of chance against that truth.

| Config | Flags | `flagged≥1` | `majority≥3` | `unanimous` | `removed≥1` | `magnitude` | AUC |
|---|---:|---|---|---|---|---|---:|
| L1 | 134 | 0.754 / 0.598 / 0.667 | 0.634 / 0.691 / 0.661 | 0.478 / 0.941 / 0.634 | 0.202 / 0.346 / 0.255 | 0.634 / 0.703 / 0.667 | 0.818 |
| L2 | 175 | 0.383 / 0.396 / 0.390 | 0.297 / 0.423 / 0.349 | 0.194 / 0.500 / 0.280 | 0.143 / 0.321 / 0.198 | 0.280 / 0.405 / 0.331 | 0.585 |
| L3 | 325 | 0.348 / 0.669 / 0.458 | 0.268 / 0.707 / 0.388 | 0.178 / 0.853 / 0.295 | 0.129 / 0.538 / 0.208 | 0.268 / 0.719 / 0.390 | 0.684 |
| L1+L2 | 265 | 0.487 / 0.763 / 0.595 | 0.393 / 0.846 / 0.536 | 0.253 / 0.985 / 0.402 | 0.177 / 0.603 / 0.274 | 0.381 / 0.835 / 0.523 | 0.831 |
| L1+L3 | 368 | 0.364 / 0.793 / 0.499 | 0.275 / 0.821 / 0.411 | 0.174 / 0.941 / 0.294 | 0.139 / 0.654 / 0.229 | 0.275 / 0.835 / 0.413 | 0.754 |
| L1+L2+L3 | 424 | 0.356 / 0.893 / 0.509 | 0.269 / 0.927 / 0.417 | 0.158 / 0.985 / 0.272 | 0.149 / 0.808 / 0.251 | 0.262 / 0.917 / 0.407 | 0.775 |

At HIGH, in the same artifact `runs/validation_ablation_20260815.json`, L1 flags 73 tasks at
precision 0.986 for recall 0.426 against `flagged≥1`, and the full stack 274 at precision 0.449 for
recall 0.728. L2's rows do not move between thresholds, since it emits only HIGH-severity access
findings; L3 is the mirror image and falls from 325 flags to 139. Adding L3 raises recall and
degrades the ranking, AUC 0.831 for L1+L2 against 0.775 for L1+L2+L3, a defect of the pair
(detector, aggregation).

### Recall by taxonomy category

121 tasks were labelled T1 to T8 by manual reading of the published patch reasons. Format:
*flagged / total (of which by a finding of the right category)*, MEDIUM threshold. A task caught by
a finding of another category counts in the first number and outside the parenthesis.

| Config | T1 | T2 | T3 | T4 | T5 | T8 |
|---|---|---|---|---|---|---|
| L1 | 65/70 (61) | 6/21 (4) | 11/11 (10) | 1/7 (0) | 2/5 (0) | 0/7 (0) |
| L2 | 33/70 (0) | 7/21 (1) | 4/11 (4) | 1/7 (0) | 0/5 (0) | 4/7 (0) |
| L3 | 60/70 (52) | 6/21 (2) | 10/11 (1) | 2/7 (0) | 4/5 (3) | 5/7 (0) |
| L1+L2 | 69/70 (61) | 13/21 (5) | 11/11 (10) | 2/7 (0) | 2/5 (0) | 4/7 (0) |
| L1+L2+L3 | 70/70 (64) | 15/21 (5) | 11/11 (10) | 3/7 (0) | 5/5 (3) | 7/7 (0) |

No labelled task carries T6, and there is no T4, T6 or T8 detector, so the zeros in the parenthesised
column are structural. At HIGH, L1 alone recalls 0/21 on T2, the content-drift blind spot announced
as the justification for building L2; L2 lifts it to 7/21 and L1+L2+L3 to 10/21.

### Marginal contribution of each detector

Truth `flagged≥1`, MEDIUM threshold. Precision and recall are computed on the tasks flagged by that
detector alone; "exclusive" counts tasks no other detector flags.

| Detector | Findings | P | R | F1 | Exclusive (true positives) |
|---|---:|---:|---:|---:|---|
| `l1_temporal` | 260 | 0.900 | 0.479 | 0.625 | 10 (5) |
| `l3_solvability` | 139 | 0.604 | 0.497 | 0.545 | 29 (5) |
| `l2_liveness` | 643 | 0.379 | 0.391 | 0.385 | 55 (16) |
| `l1_reference` | 130 | 0.421 | 0.095 | 0.155 | 22 (8) |
| `l3_ambiguity` | 238 | 0.261 | 0.367 | 0.305 | 108 (11) |
| `l1_sideeffect` | 13 | 0.846 | 0.065 | 0.121 | 2 (1) |
| `l2_content` | 28 | 1.000 | 0.006 | 0.012 | 1 (1) |

Error diagnosis for L1+L2+L3 at HIGH against `flagged≥1`: 151 false positives, by detector
`l2_liveness` anti-bot 70, `l2_liveness` paywall 38, `l3_solvability` 55, `l1_sideeffect` 1, and by
site Allrecipes 38, Amazon 34, ESPN 30, which is where site-level access verdicts propagate; 46 false
negatives, concentrated on Apple 11, BBC News 10 and Huggingface 8, content drift the static layer
cannot see and the probes do not reach, since they only test the start URL.

How much of what the tool flags no annotator ever touched is stored in `decadence_hors_patch_sets` of
`runs/longitudinal_20260815.json`. L1 alone at HIGH flags 73 tasks, of which 2 fall outside the
Magnitude patch-set and 1 outside the union of the six annotators, `GitHub--40`. The full stack at
MEDIUM flags 424, of which 313 fall outside Magnitude and 273 outside that union; those 273 are the
tasks the export leaves undecided.

## 8. Longitudinal protocol

Curve A is mortality as practitioners see it, the cumulative tasks flagged by at least one of the 6
dated annotators, and it has three defects if read as a rate. It is left censored, the first audit
coming 9.5 months after publication and flagging 121 tasks at once with no death date. Observation
effort varies, each point being a different annotator with a different threshold, so a step may be a
wave of decay or a more zealous reader. And a patch records an intent, Magnitude re-dating
pre-emptively and Skyvern refreshing in bulk long before a date is reached.

Curve B is mortality as a constant instrument sees it, the L1 detector replayed month by month on the
frozen corpus. Only the reference date advances, so every task has an exact date of death, known to
the month over 31 grid points, and none of the three defects applies; but it sees one mode of decay,
T1, and nothing that happens on the site. The two curves bound the phenomenon, B being an exact
measure of a subset of causes and A a noisy measure of all causes. Curve B′ applies the same
instrument to the corpus repaired by Magnitude, from the date of repair. Constant-hazard model over
a window Δt in months: λ = −ln(1 − k/n) / Δt, annual rate 1 − e^(−12λ), and a 95 % Wilson interval on
k/n propagated through the same transform.

| Estimator | k / n | Δt | Annual rate | 95 % CI | Status |
|---|---|---:|---:|---|---|
| A1 raw practitioner cumulative | 169/643 | 26.05 | 13.1 % | [11.4 ; 15.0] | left-censored, overestimates |
| A2 post-first-audit increments | 48/522 | 16.59 | 6.7 % | [5.1 ; 8.8] | recommended headline |
| B constant instrument, frozen corpus | 28/598 | 29.44 | 1.9 % | [1.3 ; 2.8] | strict lower bound (T1 only) |
| B′ constant instrument, repaired corpus | 60/588 | 13.31 | 9.2 % | [7.2 ; 11.7] | |
| C patch rot | 65/65 | 13.31 | 100 % | [92.6 ; 100] | chosen population, not transposable |
| D Online-Mind2Web control | 52/300 | 13.31 | 15.8 % | [12.2 ; 20.1] | maintained benchmark, upper bound of the visible |

**Defensible range, excluding patch rot: 1.9 % to 15.8 % per year.** A2 is the recommended headline
because it drops the left-censored block and measures only increments observed after the first audit.
Online-Mind2Web is actively maintained, so its replacement log measures decay observed under
surveillance, and that it is the highest estimate is the expected direction. Each fork is measured
twice with the same instrument, at its own freeze date and at 2026-08-15. The six estimators, the
curves and the fork-by-fork comparison are in `runs/longitudinal_20260815.json`.

## 9. Artifacts of record and reserves

`python3 experiments/verifier_chiffres.py` re-reads 70 published figures across 12 source files,
offline and at no cost, and returns a non-zero code at the first divergence between a figure and the
artifact that holds it. The figures above name that artifact where they appear; the card itself is
`runs/health_20260815.json`, its sensitivity to κ and to the aggregation rule is in
`runs/carte_canonique_20260815.json`, and the export counts are in
`exports/webvoyager_verified_v0.1.stats.json`.

Four reserves go with them. **Multiplicity**: the ablation artifact holds 6 configurations at 2
thresholds crossed with 5 truth definitions, so 60 one-sided binomial tests, for which Bonferroni at
5 % gives 8.3·10⁻⁴; recomputed from the artifact, the smallest p-value against `removed≥1` is
1.4·10⁻³, reached by L1+L3 at HIGH, so no configuration beats chance on that truth. The T5 signal
rate of 37.33 % comes from the campaign of 15/08, run with the rubric that quoted five statements of
the evaluated set, and was not recomputed with the clean rubric, so it is an upper bound; the clean
value of 0.715 ± 0.006 is in `runs/ablation_l3_clean_20260816.json` and in `figures/legendes.md`. The
0.986 precision of L1 is in-sample, 71 of its 72 true positives being Magnitude tasks, and its
out-of-sample reference figure is the MEDIUM row of `runs/validation_hors_echantillon_20260816.json`,
P 0.327 against 0.092 by chance and lift 3.55. And the L3 figures are not
reproducible offline, `runs/l3_cache/` not being versioned and a fresh clone re-calling the API for 2
to 4 % of differing findings. Three of the measurements quoted above are established in
`experiments/CONTRE_VERIFICATION.md`, which prevails over this page where the two differ: the F1 of
the ambiguity judge, the filiation of the annotators behind the κ band, and the out-of-sample grid.

Two conventions stay open. `access_decay_per_month = 0` is a declared absence of measurement rather
than a measured zero. And the canonical patch in the export is chosen by recency rather than by vote,
since the 87 tasks with divergent patches receive textually different rewrites and no voting rule
reconciles different dates; that choice is defensible and arbitrary, and 20 of the 116 retained
patches are themselves expired at the measurement date.
