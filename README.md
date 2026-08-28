# benchmark-doctor

**Continuous health monitoring for web-live agent benchmarks.**

Web-live agent benchmarks are built on the open web, and the open web moves: hard-coded dates
go past, named products disappear, sections get renamed, sites start blocking robots. A
benchmark can therefore stay perfectly *executable* while it quietly stops being *valid* —
nothing crashes, the numbers simply stop measuring what they used to measure. `benchmark-doctor`
measures that gap, task by task, at an explicit reference date and through an explicit access
channel.

Applied to [WebVoyager](https://github.com/MinorJerry/WebVoyager) (643 tasks, upstream frozen
since 2024-03-02), it grades **67.3 % of the corpus below A** for **\$0.00041 per task**, and
finds that **100 % of the dated task rewrites** published by a maintainer in July 2025 had
expired again thirteen months later.

> **Scope and status.** v0.1, research code released with an M2 thesis (Université Paris Cité,
> 2026). One benchmark is instrumented end to end (WebVoyager); one more is used as a control
> (Online-Mind2Web). Identifiers and CLI flags are English; docstrings, CLI output and report
> field names are French, because they were written for a French-language thesis. This README
> and `docs/` are English. See [Limits](#limits) before quoting any number — several of them
> are less flattering than they look.

---

## Table of contents

- [What it found](#what-it-found) · [Install](#install) · [Use](#use)
- [Architecture: three layers ordered by cost](#architecture-three-layers-ordered-by-cost)
- [Two rules that shape the whole design](#two-rules-that-shape-the-whole-design)
- [Validation against seven patch-sets](#validation-against-seven-patch-sets)
- [Longitudinal: does patching help?](#longitudinal-does-patching-help)
- [Continuous monitoring (GitHub Action)](#continuous-monitoring-github-action)
- [Limits](#limits) · [Related work](#related-work) · [Reproduce](#reproduce) · [Cite](#cite)

---

## What it found

WebVoyager, 643 tasks, 15 sites. Reference date **2026-08-15**, layers L1+L2+L3 **with the
solvability pass**, L2 over direct HTTP from a datacenter IP, L3 judged by
`google/gemini-2.5-flash` at threshold 0.5, practitioner prior folded in, grade scale
0.75 / 0.50 / 0.25.

This is the **canonical configuration**, and it is the only one whose numbers appear below.
`runs/` holds nine other cards — different layers, different channel, different L3 backend. They
are not competing states of the benchmark and their figures do not mix with these; each one now
carries a `statut_editorial` field saying so, and `runs/CARTES.md` lists them with the reason.
The card replays offline from the frozen findings journal, at zero cost, via
`python3 experiments/carte_canonique.py --check`.

| Health card | Value |
|---|---|
| Mean task stability | **0.585** (0.612 with detectors only, i.e. ignoring the practitioner prior) |
| Median · 10th percentile | 0.569 · 0.163 |
| Grades A / B / C / D | 210 (32.7 %) / 138 (21.5 %) / 185 (28.8 %) / **110 (17.1 %)** |
| Below grade A | **433 / 643 = 67.3 %** |
| Cost of the measurement | **\$0.26298**, 1 331 outbound calls (45 HTTP probes + 1 286 LLM), 39.2 s → **\$0.000409 / task** |

That cost is the price of a **first** execution. L3 answers are cached on disk, so re-running the
same campaign costs \$0 — which is why any cost figure here is labelled first-run or cache-hit.

Prevalence by taxonomy category — tasks carrying at least one signal of that category, and how
many of those come from a **detector** rather than from the practitioner prior folded into the
card:

| Category | Tasks | Rate | From a detector |
|---|---:|---:|---:|
| T5 ambiguity | 240 | 37.3 % | 238 |
| T2 content drift | 187 | 29.1 % | 174 |
| T3 access denied | 183 | 28.5 % | 183 |
| T7 eval brittleness | 163 | 25.3 % | 163 |
| T1 temporal | 124 | 19.3 % | 120 |
| T4 UI instability | 7 | 1.1 % | **0** |
| T8 timing | 7 | 1.1 % | **0** |
| T6 multiple solutions | 0 | 0 % | **0** |

The three zeros in the last column are the honest headline of this table: the only T4 and T8
signal in the card comes from human annotators, and **no detector in this repository emits T4, T6
or T8 at all**. That is a coverage hole, not a clean bill of health — see [Limits](#limits).

By site, worst first:

| Site | n | Mean stability | Grade D | Dominant category |
|---|---:|---:|---:|---|
| Booking | 44 | **0.223** | **33** | T1 temporal |
| Google Flights | 42 | 0.329 | 7 | T1 temporal |
| ESPN | 44 | 0.455 | 18 | T3 access |
| Allrecipes | 45 | 0.471 | 6 | T3 access |
| Amazon | 41 | 0.474 | 5 | T5 ambiguity |
| BBC News | 42 | 0.502 | 4 | T5 ambiguity |
| Apple | 43 | 0.543 | 7 | T2 content drift |
| Google Map | 41 | 0.627 | 8 | T5 ambiguity |
| Huggingface | 43 | 0.640 | 6 | T5 ambiguity |
| GitHub | 41 | 0.665 | 5 | T2 content drift |
| Coursera | 42 | 0.667 | 3 | T5 ambiguity |
| ArXiv | 43 | 0.726 | 1 | T2 content drift |
| Google Search | 43 | 0.745 | 3 | T7 eval brittleness |
| Cambridge Dictionary | 43 | 0.818 | 3 | T2 content drift |
| Wolfram Alpha | 46 | **0.882** | 1 | T1 temporal |

Booking and Google Flights are transactional and date-bound: you cannot book a flight for a date
that has passed. They are not "hard" — they are dead. ESPN and Allrecipes sit near the bottom for
a *different* reason — they blocked our probes — and that difference is exactly why every finding
has to carry the channel it was observed through.

### The headline result: repairs rot

Magnitude published 121 motivated patches on 2025-07-06, of which 68 rewrite a task statement.
Re-measured on 2026-08-15, thirteen months later:

| | |
|---|---|
| Rewrites carrying a date | 65 / 68 (the other 3 changed a product, not a date) |
| **Dated rewrites now certainly past** | **65 / 65 = 100 %** (95.6 % of all 68 rewrites) |
| Of those, expired in a *blocking* way (transactional task) | 60 / 65 = 92.3 % |
| Rewrites still holding a future date | **0** |

A dated patch has a shelf life of a few months. This is the whole argument for continuous
monitoring, measured rather than asserted.

---

## Install

```bash
git clone <this repository> && cd benchmark-doctor
pip install -e .              # L1 only — zero dependencies, standard library
pip install -e ".[dev]"       # + pytest (89 tests)
pip install requests          # L2 web probes  (see note)
pip install httpx             # L3 LLM probes
```

> **Note.** `pyproject.toml`'s `probe` extra currently lists `httpx` and `playwright`; the
> direct-HTTP channel actually imports `requests`, and `playwright` is only needed for the
> optional local-browser channel. Install `requests` for L2, `httpx` for L3. Both imports are
> lazy: L1 keeps working with neither.

The L1 layer has **no dependencies at all**. That is deliberate: a health check that claims to
cost \$0 should also install without friction.

Data is **not** versioned here (third-party licences). Bootstrap it:

```bash
# the reference corpus, at the pinned upstream revision
mkdir -p data/raw && curl -sSL -o data/raw/webvoyager_original.jsonl \
  https://raw.githubusercontent.com/MinorJerry/WebVoyager/091544539eba485dbd74ef3742011ddeede37336/data/WebVoyager_data.jsonl
# expected sha256: 69b19fd86c23f1a500244a3724e039aa7ca6a1223d03e11eb10e308d4f11c488

# the seven patch-sets used as ground truth, each at a pinned revision
python3 -m benchmark_doctor.ground_truth.fetch_sources
python3 -m benchmark_doctor.ground_truth.reconcile
```

L3 needs an OpenRouter key in the environment (`OPENROUTER_API_KEY`, read from the environment
or from an untracked `.env`). L1 and L2 need no credentials.

---

## Use

```bash
# Static health bulletin (L1 only, free, offline), at an explicit reference date
bdoctor scan data/raw/webvoyager_original.jsonl --today 2026-08-15 --json runs/health.json

# Full multi-layer campaign + health card (JSON and standalone HTML)
bdoctor audit data/raw/webvoyager_original.jsonl \
    --layers l1,l2,l3 --channel direct --l3-backend llm --l3-solvability \
    --today 2026-08-15 --out runs/health.html

# Detector-only scoring: ignore the practitioner prior (this is what CI should use)
bdoctor audit data/raw/webvoyager_original.jsonl --layers l1,l2 --channel direct --no-prior \
    --json runs/health.json

# Precision / recall of L1 against a patch-set, with ablation and cross-validation
bdoctor l1-eval data/raw/webvoyager_original.jsonl \
    --patches data/raw/magnitude_patches.json --today 2026-08-15 \
    --cross data/raw/browseruse_impossible.json data/raw/skyvern_outdated.jsonl

# Health differential between two dated cards — the continuous-monitoring primitive
bdoctor diff runs/health_2026-08-15.json runs/health_2026-08-22.json --json runs/diff.json

# Re-derive the stability-score constants and quantify their sensitivity.
# NOTE: sensitivity tables are only comparable to a health card produced in the SAME
# configuration. The canonical one includes L3 and solvability; a table computed with
# --layers l1,l2 must never be quoted next to the card below. See runs/CARTES.md.
bdoctor score-model data/raw/webvoyager_original.jsonl --layers l1,l2

# Canonical sensitivity tables, replayed offline from the frozen findings journal, $0.00
python3 experiments/carte_canonique.py
```

`--channel` picks the L2 access channel: `direct` (HTTP with browser headers),
`direct-minimal` (bare client — the cheapest ablation of channel dependence), `browser-local`
(Playwright, if installed), `recorded` (replay a saved observation file, so the numbers stay
recomputable offline), `none`.

As a library:

```python
import datetime
from benchmark_doctor import load_webvoyager, run_l1

health = run_l1(load_webvoyager("data/raw/webvoyager_original.jsonl"),
                today=datetime.date(2026, 8, 15))
print(health.summary())    # rates, A/B/C/D grades, prevalence per category
print(health.by_site())    # the dead subsets
```

---

## Architecture: three layers ordered by cost

The ordering is the design: each layer pays a different currency, and each has to earn its place
before the next one is switched on.

| Layer | What it inspects | Detectors | Cost on 643 tasks | Pays in |
|---|---|---|---:|---|
| **L1 static** | the task statement alone | `l1_temporal`, `l1_sideeffect`, `l1_reference` | **\$0**, 0.1 s, 0 requests | nothing |
| **L2 web probes** | the start URL: liveness, anti-bot, paywall, soft-404 | `l2_liveness`, `l2_content` | **\$0**, 45 requests, 38.5 s | requests and latency |
| **L3 LLM probes** | ambiguity and solvability of the statement | `l3_ambiguity`, `l3_solvability` | **\$0.263**, 1 286 calls, 0.5 s | money |

L2 costs \$0 in money and only **45 HTTP requests for 643 tasks**, because WebVoyager tasks
share 15 start URLs and observations are memoised per host. L3 is where all the money goes, split
almost evenly between ambiguity (\$0.132) and solvability (\$0.131). A second run is served
entirely from the on-disk cache and costs \$0.

For comparison, the evaluation runs these benchmarks feed cost \$40 k for 21 730 rollouts (HAL),
up to \$2 829 for a single frontier GAIA run, and 1 000+ human hours for 130 Mind2Web 2 rubrics.
Checking whether the *tasks* are still valid costs four hundredths of a cent each. That asymmetry
is the economic argument for running the check continuously rather than auditing once.

### Taxonomy (T1–T8) and what actually detects it

The last column is the strict test: of the tasks a manual pass labelled with that category, how
many does the full stack flag **with a finding of the right category** (L1+L2+L3, MEDIUM
threshold)? Flagging a broken task for the wrong reason does not count.

| Code | Category | Detected by | Right-category recall |
|---|---|---|---|
| T1 | temporal drift | `l1_temporal` | **64 / 70** |
| T2 | content / URL drift | `l2_content`, `l1_reference` (proxy only) | 5 / 21 |
| T3 | access denied, anti-bot, side effects | `l1_sideeffect`, `l2_liveness` | **10 / 11** |
| T4 | UI / environment instability | — | 0 / 7 |
| T5 | task ambiguity | `l3_ambiguity` | 3 / 5 |
| T6 | multiple valid solutions | — | no labelled task |
| T7 | evaluation brittleness | `l1_temporal` (relative dates only) | no labelled task |
| T8 | timing dependency | — | 0 / 7 |

**Five of eight categories have an emitter** (T1, T2, T3, T5, T7); **T4, T6 and T8 have none**.
And T7 is instrumented only through relative-date phrasing (`latest`, `current`) — a narrow slice
of what "evaluation brittleness" covers. The stack does flag 7/7 of the T8 tasks and 3/7 of the T4
ones, always for another reason: catching a broken task is not detecting the reason it is broken.

---

## Two rules that shape the whole design

**1. Every finding carries its access channel.** On 2026-08-15 at 23:10 UTC,
`https://www.allrecipes.com/` returned **402 Payment Required** (Cloudflare pay-per-crawl) from a
datacenter IP and **200 OK** from a cloud browser *forty-seven seconds later*. Same URL, same
minute, opposite verdicts. The status of a benchmark task is therefore not a property of the
task but of the pair *(task, access channel)*. A tool that publishes "Allrecipes is dead" without
saying where it looked from is counting its own network filtering as benchmark decay. `Finding.channel`
is mandatory, network findings are discounted by a channel credibility factor (κ = 0.40 for
datacenter HTTP), and a `CHANNEL_BLOCKED` signature is evaluated *before* anything is imputed to
the site — without it, this campaign would have declared the 41 GitHub tasks dead because of an
egress proxy.

**2. No binary verdict is ever stored.** A `TaskVerdict` keeps the list of its findings, each with
its own *severity* (how bad it is **if true**) and *confidence* (how sure the detector is). Whether
a task counts as "flagged" is computed on demand, at an explicit threshold. This is what makes it
possible to replay several decision policies over a single measurement campaign — and it makes any
announced decay rate inseparable from the rule that produced it.

Stability score: risks aggregate as a noisy-OR over findings, `risk = severity_weight × confidence`,
grade boundaries at 0.75 / 0.50 / 0.25 (each boundary is "one finding of that severity, held
certain"). The score is **ordinal before it is cardinal**: comparing two tasks is legitimate,
reading a score as a probability is not.

---

## Validation against seven patch-sets

Seven independent teams have published their own repaired fork of WebVoyager. Six of them can be
read as annotations — that is the ground truth here. **There is no single ground truth**: "a
defective task" has no unique definition, so five are measured side by side, and the spread is
itself a result.

| Ground truth | Definition | n |
|---|---|---:|
| `flagged≥1` | flagged by at least 1 of the 6 independent annotators | 169 |
| `majority≥3` | flagged by a majority | 123 |
| `unanimous` | flagged by all 6 | 68 |
| `removed≥1` | *deleted* by at least one annotator | 78 |
| `magnitude` | the 121 Magnitude patches alone | 121 |

**Precision / recall / F1 at the HIGH threshold** ("hard flag"), and AUC of the risk ranking
(threshold-free, detector-only score) against `flagged≥1`:

Chance precision is the prevalence of the truth, 169/643 = **0.263**: that is what a detector
flagging tasks at random would score. No row is publishable without it and without its lift.

| Configuration | Flags | P (`flagged≥1`) | P chance | Lift | R | F1 | F1 (`unanimous`) | AUC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| L1 alone | 73 | **0.986** | 0.263 | 3.75 | 0.426 | 0.595 | 0.894 | 0.818 |
| L2 alone | 175 | 0.383 | 0.263 | 1.46 | 0.396 | 0.390 | 0.280 | 0.585 |
| L3 alone | 139 | 0.604 | 0.263 | 2.30 | 0.497 | 0.545 | 0.512 | 0.684 |
| L1+L2 | 214 | 0.491 | 0.263 | 1.87 | 0.621 | 0.548 | 0.468 | **0.831** |
| L1+L3 | 153 | 0.640 | 0.263 | 2.44 | 0.580 | **0.609** | 0.570 | 0.754 |
| L1+L2+L3 | 274 | 0.449 | 0.263 | 1.71 | **0.728** | 0.555 | 0.386 | 0.775 |

At the MEDIUM threshold ("wide flag"), L1+L2+L3 reaches **recall 0.893** at precision 0.356 —
lift 1.35, while flagging 424 of 643 tasks (66 %).

> **This whole table is in-sample and must never be quoted on its own.** The L1 detectors were
> tuned on the Magnitude patch-set, and 71 of L1's 72 true positives here *are* Magnitude tasks.
> The out-of-sample grid — a disjoint split, chance precision, lift, a binomial test and a
> site-clustered correction on every row — lives in
> [`experiments/VALIDATION.md`](experiments/VALIDATION.md) and is the reference result.
> Headline: on the 522 tasks Magnitude never touched, L1/HIGH flags **2** tasks (1 correct,
> p = 0.17); L1/MEDIUM holds at precision **0.327** against 0.092 by chance, lift 3.55,
> p = 3.6·10⁻³ after site stratification.

Three things to read off this table, none of them flattering:

- **L1 alone is nearly exact and half-blind — on the corpus it was tuned on.** Precision 0.986
  (72 of 73 flags are real), recall 0.426, but 71 of those 72 true positives are Magnitude
  patches. Against the unanimous ground truth it reaches F1 0.894 — the tasks everyone agrees are
  broken are, overwhelmingly, the temporally dead ones. Out of sample the HIGH threshold is not
  measurable and MEDIUM is the defensible operating point.
- **The full stack is a triage tool, not a verdict tool.** Recall 0.728 at HIGH, 0.893 at MEDIUM,
  but precision below 0.45. 151 false positives, of which 108 carry an `l2_liveness` finding
  (site-level blocks propagated to every task of that host: 70 anti-bot, 38 paywall) and 55 an
  `l3_solvability` finding — a task can carry several. By site: Allrecipes 38, Amazon 34, ESPN 30.
- **Adding L3 improves recall and *degrades ranking*.** Best AUC is L1+L2 (0.831); adding L3 drops
  it to 0.775, because a low-precision detector combined with noisy-OR aggregation raises
  everybody's risk. That is a defect of the (detector, aggregation) pair, and it is published
  rather than hidden.

**What each detector actually adds** (truth `flagged≥1`, MEDIUM threshold; "exclusive" = tasks
only this detector flags):

| Detector | Findings | P | R | F1 | Exclusive (true positives) |
|---|---:|---:|---:|---:|---|
| `l1_temporal` | 260 | 0.900 | 0.479 | 0.625 | 10 (5) |
| `l3_solvability` | 139 | 0.604 | 0.497 | 0.545 | 29 (5) |
| `l2_liveness` | 643 | 0.379 | 0.391 | 0.385 | 55 (16) |
| `l1_reference` | 130 | 0.421 | 0.095 | 0.155 | 22 (8) |
| `l3_ambiguity` | 238 | 0.261 | 0.367 | 0.305 | 108 (11) |
| `l1_sideeffect` | 13 | 0.846 | 0.065 | 0.121 | 2 (1) |
| `l2_content` | 28 | **1.000** | 0.006 | 0.012 | 1 (1) |

`l2_content` is perfect and useless: one decided check out of 28 catches a real defect
(`Huggingface--10`). That is a property of the corpus, not a bug, and it will not improve.

The **content-drift blind spot** of static analysis, announced as the justification for L2, is
confirmed: at the HIGH threshold, L1 alone recalls **0/21** T2 tasks; L2 lifts it to 7/21 and
L1+L2+L3 to 10/21.

---

## Longitudinal: does patching help?

Two mortality curves are published, and neither is dropped in favour of the other.

**Curve A — mortality as practitioners see it.** Cumulative tasks flagged by ≥1 of the 6 dated
annotators: 121 (2024-12, browser-use) → 126 (2025-02) → 133 (2025-07, Magnitude) → 153 (2025-08,
Fara) → 157 (2026-03) → **169 (2026-05, 26.3 %)**. Real observation — someone actually opened the
site — but heavily **left-censored**: 121 tasks were already flagged at the first audit, 9.5 months
after publication, and nobody knows when they died.

**Curve B — mortality as a constant instrument sees it.** The L1 detector replayed month by month
over the *frozen* corpus, so every task has a computable date of death. Result: 45 flagged at
2024-03-01, 73 at 2024-04-01, then **flat until 2026-08-15**. All 28 deaths fall in H1 2024. The
explanation is measurable: the original corpus contained only **31 dates still in the future** at
publication (median horizon 8 days) against 57 already past and 529 tasks with no date at all.
WebVoyager's temporal decay was essentially already spent on day one.

**Curve B′ — same instrument, on the corpus *repaired* by Magnitude.** From 2/590 on the day of
repair to **62/590 (10.5 %) by April 2026**: 60 new deaths, all in H1 2026, 61 time bombs planted
at repair time with a median horizon of 237 days. Concentrated on Google Flights (31/39) and
Booking (29/40). Repairing a web-live benchmark with hard-coded dates does not remove the decay;
it reschedules it.

**Annual decay rate** — constant-hazard model λ = −ln(1−k/n)/Δt, annual rate = 1−e^(−12λ), Wilson
95 % intervals:

| Estimator | Annual rate | 95 % CI | Basis | Read as |
|---|---:|---|---|---|
| A1 raw practitioner cumulative | 13.1 % | [11.4 ; 15.0] | 169/643, 26.05 mo | left-censored → overestimates |
| **A2 post-first-audit increments** | **6.7 %** | **[5.1 ; 8.8]** | 48/522, 16.59 mo | **the defensible headline** |
| B constant instrument, frozen corpus | 1.9 % | [1.3 ; 2.8] | 28/598, 29.44 mo | strict lower bound, T1 only |
| B′ constant instrument, repaired corpus | 9.2 % | [7.2 ; 11.7] | 60/588, 13.31 mo | |
| C patch rot | 100 % | [92.6 ; 100] | 65/65, 13.31 mo | chosen population, not transposable |
| D Online-Mind2Web control | 15.8 % | [12.2 ; 20.1] | 52/300, 13.31 mo | a *maintained* benchmark — upper bound of the visible |

Excluding patch rot, the range is **1.9 % – 15.8 % per year**. The control matters: Online-Mind2Web
is actively maintained and replaced 52 of 300 tasks over 7 waves. Its suffixed identifiers reveal
58 replacement events over 55 raw ids over 52 distinct tasks: **5 tasks had to be replaced more
than once** — four twice, one three times. Even active maintenance does not converge.

**Comparative health of the seven forks** (L1, HIGH threshold, at each fork's freeze date → at
2026-08-15):

| Fork | Date | Tasks | At freeze | At 2026-08-15 |
|---|---|---:|---:|---:|
| WebVoyager original | 2024-03-02 | 643 | 47 (7.3 %) | 73 (11.4 %) |
| browser-use | 2024-12-15 | 588 | 3 (0.5 %) | 62 (10.5 %) |
| Skyvern | 2025-01 | 635 | 72 (11.3 %) | 73 (11.5 %) |
| Magnitude | 2025-07 | 590 | 2 (0.3 %) | 62 (10.5 %) |
| Microsoft Fara | 2025-08 | 595 | 11 (1.8 %) | 70 (11.8 %) |
| Alumnium | 2026-03 | 619 | 6 (1.0 %) | 55 (8.9 %) |
| Skyvern (refreshed) | 2026-05 | 635 | 12 (1.9 %) | **20 (3.1 %)** |

Each fork is measured on **its own** corpus, declared exclusions removed. browser-use is 588
tasks, not the 643 lines of `browseruse_tasks.jsonl`: that file still ships the 55 ids of
`WebVoyagerImpossibleTasks.json`. Counting them made 9 of the 12 "at freeze" findings land on
tasks browser-use had already dropped, and inflated its birth rate almost fourfold (1.9 % vs
0.5 %). Its hazard rate moves accordingly, from 5.8 %/yr to 6.2 %/yr.

Every fork converges back to ~11 % within about a year. Only the one refreshed three months before
measurement is healthy. Forking does not cure; it resets a clock.

### WebVoyager-Verified v0.1

`exports/webvoyager_verified_v0.1.jsonl` — 643 lines, one per task, reconciling six independent
audits with measured stability metadata. Statuses (French keys, as in the file): `noyau` (core,
never flagged by anyone) 474 · `surveiller` (watch) 26 · `corriger` (fix) 63 · `retirer` (drop) 9 ·
`conteste` (**contested**) 71.

**Consensus subset = 563 tasks. That is not the number of runnable tasks.** Status comes from the
practitioners' vote, not from the state of the statement: **84 of those 563 (14.9 %) carry a date
that is already in the past** at the measurement date — 63 in `corriger`, 14 in `noyau` (tasks
nobody ever flagged), 7 in `surveiller`. The figure to quote is **479 tasks whose original
statement is still clean**; 536 if you also trust a canonical patch that has not itself expired.
No line is dropped for this: every one of the 643 records carries an `enonce_perime` field with
the offending dates and the evaluation date, so the count recomputes at any later date. *Verified*
in this file's name refers to the reconciliation of verdicts and the dating of measurements —
never to a task being runnable.

The 71 contested tasks are the result, not the residue: they are deleted by at least one
practitioner and kept intact by another. No vote resolves that. Likewise, 20 of the 116 canonical
patches carried over are **already expired** at the measurement date — including the most recent
ones, dated "June 2026" by Skyvern in May 2026. See `exports/README.md` for the full field
reference and caveats.

---

## Continuous monitoring (GitHub Action)

`.github/workflows/weekly.yml` runs **L1 + L2** every Monday (free — no API key needed), publishes
the health card and its HTML report as artifacts, diffs it against the previous week's run, and
opens (or updates) an issue when mean stability drops by more than a configurable number of points.

It deliberately refuses to alert when the two cards are not comparable — different corpus digest,
different layers, different L2 channel profile. An unexplained score movement caused by a protocol
change is not decay, and reporting it as decay is exactly the failure mode this project exists to
name.

Two constraints of that environment are recorded in every run: GitHub-hosted runners have
**datacenter IPs**, so all L2 access findings carry κ = 0.40 and must never be read as "task dead";
and the workflow scores with `--no-prior`, so the number it tracks is what the *detectors* see, not
a replay of a frozen practitioner ground truth.

---

## Limits

Read these before quoting anything above.

1. **Half the taxonomy is uninstrumented.** There is no T4 (UI instability), T6 (multiple valid
   solutions) or T8 (timing) detector at all, and T7 is covered only by relative-date phrasing.
   Eight categories are described; five have an emitter, and only four are recalled with the right
   category on labelled data.

2. **Precision of the full stack is poor and cannot be rescued at this scale.** 0.449 at HIGH
   against `flagged≥1`. It is a triage instrument that ranks and shortlists; it is not an oracle,
   and no number it produces should be used to delete a task without a human opening the site.

3. **Adding a layer can degrade the ranking.** L1+L2 ranks better (AUC 0.831) than L1+L2+L3
   (0.775). More coverage is not monotonically better under noisy-OR aggregation.

4. **L2 findings are site-granular.** WebVoyager gives one start URL per task, so an access verdict
   for a host propagates to all its tasks (Allrecipes 45/45, Booking 44/44, ESPN 44/44). Rates
   bound decay from below; false positives cluster by site.

5. **The ground truth is not truth.** The six patch-sets have different goals and different
   thresholds: Magnitude re-dates pre-emptively, Skyvern refreshes in bulk, browser-use excludes.
   Silence counts as "keep" even when a source never examined the task, so measured agreement is an
   upper bound. The 0.986 precision figure is not "partly" in-sample, it is **entirely** in-sample:
   71 of its 72 true positives are Magnitude tasks, i.e. the very patch-set the L1 rules were tuned
   on; the other five annotators contribute exactly one. See
   [`experiments/VALIDATION.md`](experiments/VALIDATION.md) for the disjoint-split grid that
   replaces it.

6. **273 tasks that nobody ever flagged score below A, 29 of them D.** We cannot say whether those
   are our false positives or defects nobody looked at. Settling it requires opening the sites.

7. **Curve B measures textual expiry, not execution failure**, on a monthly grid. No agent was run.
   A task whose date has passed is provably invalid for a transactional site; elsewhere it merely
   ages.

8. **Everything is frozen to 2026-08-15** (`REFERENCE_DATE` in `run_all.py`,
   `TODAY` in `analysis_longitudinal.py`) so that published figures do not drift between runs. Change
   it and every table above changes — which is the point.

---

## Related work

| Work | What it does | Why it does not cover this |
|---|---|---|
| **Emergence WebVoyager** (Akkil et al., 2026, arXiv:2603.29020, ICLR 2026 AIWILD) | Manual audit of WebVoyager; 535 templated tasks whose dates are instantiated at run time | One-shot human audit plus **prevention by templating**. It repairs a corpus; it does not measure decay over time, and templating cannot be retrofitted onto the existing stock of benchmarks. |
| **ABA** (Wang, Bianchi, …, Zou, 2026, arXiv:2605.26079) | Agentic auditing of benchmark task validity; issues in >25.7 % of tasks; filtering shifts SWE-bench Verified and Terminal-Bench 2 scores by ~10 % | Generic, static, **one-shot**, and with no web-live coverage (verified by reading their code): no liveness probing, no anti-bot classification, no notion of an access channel or of a measurement date. |
| **BenchJack** (Wang, Li, Mang, Cheung, Sen, Song, 2026, arXiv:2605.12673) | Audits 10 benchmarks for **harness exploitability** — eight recurring flaw patterns, 219 distinct flaws; synthesised exploits score near-perfectly without solving a single task | Attacks the *scoring harness*, not the tasks' continued validity. Orthogonal and complementary: a benchmark can be unexploitable and still be dead. |
| **Terminal-Bench 2.1** (2026-05) | Fixed 28 of 89 tasks of TB 2.0; "continuous validation" | **Build-time QA by the maintainers**, on a sandboxed benchmark. It is quality control at construction, not post-release surveillance of a corpus nobody owns. |
| Prevention: Navi-Bench (relative dates), REAL v2 (deterministic replicas), OSWorld 2.0 (versioned mocks), SWE-bench-Live (monthly refresh), Online-Mind2Web (manual community maintenance) | Design tasks that do not decay, or refresh them by hand | All require **rebuilding or owning** the benchmark. None addresses the existing stock of web-live benchmarks that are already published, already cited, and already rotting. |

**The gap this fills**: post-release, web-live, longitudinal, published. And a distinction worth
keeping sharp — HAL/reliability work measures the variance of the **agent** across runs; this
measures the validity of the **task** across time. They compose; they are not the same quantity.

---

## Reproduce

```bash
python3 run_all.py --phase audit      # L1+L2+L3 over 643 tasks at the frozen reference date
python3 run_all.py --phase validate   # P/R/F1, 5 ground truths × 2 thresholds, layer ablation
python3 run_all.py --phase export     # WebVoyager-Verified v0.1 + its README
python3 analysis_longitudinal.py      # mortality curves, decay rates, fork health, controls
python3 -m pytest -q                  # 89 tests
```

`--phase validate` replays `runs/health_20260815_findings.json` and needs neither network nor API
key. The pipeline tests deliberately lock the published figures: change a detector and they fail,
which is the signal that every table in this README has to be recomputed.

Full protocol, channel accounting and the complete 5-ground-truth × 2-threshold grid:
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md). Contributing:
[`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Cite

```bibtex
@software{penso2026benchmarkdoctor,
  author  = {Penso, Max},
  title   = {benchmark-doctor: continuous health monitoring for web-live agent benchmarks},
  year    = {2026},
  version = {0.1.0},
  license = {MIT}
}

@mastersthesis{penso2026decay,
  author  = {Penso, Max},
  title   = {Le decay des benchmarks d'agents web : taxonomie, d\'etection automatis\'ee
             et \'etude longitudinale de WebVoyager},
  school  = {Universit\'e Paris Cit\'e, UFR de Math\'ematiques et Informatique},
  type    = {M\'emoire de Master 2 MIAGE},
  year    = {2026}
}
```

If you use the reconciled verdict base or WebVoyager-Verified v0.1, please also cite the six
patch-set authors it reconciles — they did the looking. Their pinned revisions are listed in
`benchmark_doctor/ground_truth/sources.py`.

## Licence

MIT for the code and for the fields this project adds. The corpora and patch-sets it reads are
**not redistributed** and remain under their own licences. See [`LICENSE`](LICENSE).
