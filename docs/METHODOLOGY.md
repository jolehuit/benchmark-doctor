# Measurement methodology

How every number published by this project is produced, and what each one does and does not
license you to say.

Reference measurement: **WebVoyager, 643 tasks, 2026-08-15**. Everything below is reproducible
with the commands in [§9](#9-reproduction).

---

## 1. What is being measured

A benchmark task is a triple *(statement, start URL, expected outcome)* evaluated against the
live web. Call it **valid at time _t_** if an agent solving it correctly at _t_ would be scored
correct, and an agent failing it would be scored incorrect — i.e. the task still discriminates
what it was built to discriminate.

**Decay** is the loss of that property over time, with the task text unchanged. It is distinct
from three neighbouring notions:

| Not this | Difference |
|---|---|
| Construction flaws (a task that was never valid) | Decay presupposes validity at _t₀_. The two are hard to separate in practice, which is why the longitudinal instrument replays a *constant* detector on a *frozen* corpus. |
| Saturation (agents got good enough) | A property of the agent population, not of the task. |
| Agent-side reliability (variance across runs) | HAL/reliability work measures the **agent**; this measures the **task**. They compose; they are not the same quantity. |

The measurable proxy used throughout is a **task stability score** in [0, 1] with an A–D grade,
computed from findings, at an explicit date, through an explicit channel. It is **ordinal before
it is cardinal**: comparing two tasks or two dates is legitimate; reading a score as a
probability of failure is not.

---

## 2. Corpus and reference date

| | |
|---|---|
| Corpus | `MinorJerry/WebVoyager` @ `091544539eba485dbd74ef3742011ddeede37336` (2024-03-02) |
| File | `data/WebVoyager_data.jsonl` → `data/raw/webvoyager_original.jsonl` |
| SHA-256 | `69b19fd86c23f1a500244a3724e039aa7ca6a1223d03e11eb10e308d4f11c488` |
| Tasks · sites | 643 · 15 |
| Reference date | **2026-08-15**, frozen (`REFERENCE_DATE` in `run_all.py`, `TODAY` in `analysis_longitudinal.py`) |

Two conventions that matter:

- **The corpus is pinned, never `main`.** Every health card records `meta.corpus_sha256`, and
  `bdoctor diff` refuses to declare two cards comparable when the digests differ. Otherwise an
  upstream edit would be silently counted as decay.
- **The reference date is frozen, not `today()`.** Published figures must not drift between runs.
  The consequence is that the cards say `generated_at: 2026-08-15` — that is the **date of
  measurement**, not the date the file was written (2026-08-16 for some artifacts). Pass
  `--today` to move it.

---

## 3. The access channel, and why every verdict carries it

**This is the single most consequential methodological choice in the project.**

On 2026-08-15 at 23:10 UTC, `https://www.allrecipes.com/` returned **402 Payment Required**
(Cloudflare pay-per-crawl, `__cf_bm` cookie) from a datacenter IP, and **200 OK** from a cloud
browser **47 seconds later**. Same URL, same minute, opposite verdicts.

It follows that the status of a benchmark task is not a property of the task, but of the pair
**(task, access channel)**. Four consequences are wired into the code:

**a. `Finding.channel` is mandatory.** Every finding records where it was observed from:
`static` (no request at all — the whole L1 layer), `http_datacenter`, `http_residential`,
`browser_local`, `browser_cloud`, `llm`. A card with no channel is not interpretable.

**b. Channel-imputable responses are eliminated before anything is imputed to the site.** The L2
classifier evaluates the `CHANNEL_BLOCKED` signature *first*. In the reference campaign,
`github.com` returned 400 with a JSON body naming the measuring machine's egress proxy — the
response never came from GitHub. Without that precedence rule the campaign would have declared
the 41 GitHub tasks dead: 6.4 % of the corpus, for a reason having nothing to do with the
benchmark. `Observation.looks_proxy_mediated` implements the detection.

**c. Network findings are discounted by a channel credibility factor κ.**

| Channel | κ |
|---|---:|
| `static` (L1, no request) | 1.00 |
| `http_datacenter`, `http_residential` | **0.40** |
| `browser_local`, `browser_cloud` | 1.00 |
| `llm` | 1.00 |

κ = 0.40 is derived in `runs/l2_probe_20260815.json`: of the blocked URLs for which a browser
channel was also available, 2 of 3 answered normally to the browser, 1 block was confirmed. It
is applied **only to T3 (access denied) findings coming from a network channel** — it is a
statement about the reliability of *that* class of observation, not a global fudge factor. With
so small a denominator it is a working constant, not an estimate; `bdoctor score-model` quantifies
how much the published figures move when it is varied.

**d. Liveness is classified into signatures, never a boolean.** `status == 200` is not aliveness:
`booking.com` returned **202** with `x-amzn-waf-action: challenge`. The signatures are `OK`,
`DEAD_404`, `PAYWALL_402`, `FORBIDDEN_403`, `ANTIBOT_CHALLENGE`, `CAPTCHA`, `REDIRECT_HOME`,
`SOFT_404`, `SERVER_ERROR`, plus three honesty signatures — `CHANNEL_BLOCKED`, `UNREACHABLE`,
`RATE_LIMITED`. Each carries the channel, the HTTP code, the body size, the discriminating
headers and an excerpt, so every L2 verdict is quotable.

**Consequence for readers.** An access finding produced from a datacenter IP — which is what
GitHub-hosted CI runners have, and what the reference campaign used — means *"this benchmark is
not measurable from here"*. It does **not** mean *"this task is dead"*. To claim death, re-probe
through `--channel browser-local` or replay a recorded browser observation with
`--channel recorded`.

**A second channel deserves naming: the measuring infrastructure itself.** The reference campaign
went out through a corporate egress proxy that answers *in place of* the site for some hosts.
That is why the `CHANNEL_BLOCKED` precedence rule exists at all.

---

## 4. Layers, detectors and cost

| Layer | Detectors | Observes | Cost (643 tasks) |
|---|---|---|---:|
| **L1** static | `l1_temporal`, `l1_sideeffect`, `l1_reference` | the statement only | **\$0**, 0.1 s, 0 requests |
| **L2** probes | `l2_liveness`, `l2_content` | the start URL | **\$0**, 45 HTTP requests |
| **L3** LLM | `l3_ambiguity`, `l3_solvability` | the statement, judged | **\$0.26298**, 1 331 calls |

Total **\$0.26298 / 1 331 calls / 39.2 s = \$0.000409 per task**. L3 splits into \$0.13177
(ambiguity) + \$0.13121 (solvability). Costs are read from the provider's `usage.cost` field, not
estimated from token counts. A re-run is served from the on-disk cache (`runs/l3_cache/`) and
costs **\$0** — which is why cost must always be reported with "first measurement" or "cache hit".

L2 issues only 45 requests for 643 tasks because WebVoyager gives one start URL per task and there
are 15 distinct hosts; observations are memoised per host and throttled (1 s minimum interval).
**This is also L2's main weakness**: an access verdict for a host propagates to all of its tasks
(Allrecipes 45/45, Booking 44/44, ESPN 44/44).

Reference protocol recorded in `meta.protocol` of the card:

```
l2_channel               direct_http:browser
l2_channel_kind          http_datacenter
l2_content_checks        true
l3_ambiguity_backend     llm-judge:gemini-2.5-flash:rubric
l3_ambiguity_threshold   0.5
l3_solvability           true
```

`--l3-backend` also accepts `tfidf` (free, default) and `minilm` (local sentence-transformers),
which makes the ambiguity layer runnable with no API key at reduced quality.

---

## 5. From findings to a score

**Nothing binary is ever stored.** A `TaskVerdict` keeps its findings; each carries a *severity*
(how bad it is **if true**) and a *confidence* (how sure the detector is). Whether a task counts
as flagged is computed on demand at an explicit threshold, which is what makes it possible to
replay several decision policies over one measurement campaign — and what makes any announced
decay rate inseparable from the rule that produced it.

```
risk(finding)  = severity_weight × confidence × κ(channel, category)
risk(task)     = 1 − Π (1 − risk(finding))          # noisy-OR
stability      = 1 − risk(task)
```

| Constant | Value | Justification |
|---|---|---|
| severity weights | info 0 · low 0.25 · medium 0.50 · high 0.75 · critical 1.0 | evenly spaced; no fitting on data |
| grade boundaries | A ≥ 0.75 · B ≥ 0.50 · C ≥ 0.25 · D ≥ 0 | each boundary is "one finding of that severity, held certain" — i.e. `1 − w(σ)` |
| prior weights | remove 1.0 · modify 0.5 | deletion is unrecoverable; a rewrite is weaker evidence because Magnitude re-dates pre-emptively |
| world decay | λ = 0.0143 / month | Online-Mind2Web replacement log: 52/300 tasks in 13.35 months (half-life ≈ 48 months) |
| access decay | 0.0 / month | **no measurement exists** of weekly anti-bot signature volatility; repeatability was only tested over 3 minutes. Left at zero and declared, rather than guessed |
| staleness | 30 days | an observation older than this is flagged `stale` in the card |

`bdoctor score-model` re-derives these constants and reports the sensitivity of the published
aggregates to each of them.

### The practitioner prior, and when to switch it off

By default the score folds in a prior drawn from `data/ground_truth.json` (what six independent
annotators did to each task). It makes the card more useful for a reader choosing tasks to run,
and **it makes the card unusable for validation** — scoring it against the same annotators would
measure the tool's ability to copy what it was given.

Therefore:

- **Validation and CI use `--no-prior`** (detector-only score). Every card carries both
  `stability_score` and `stability_score_detector_only`, and both aggregates.
- Published precision/recall figures are computed on **findings**, never on the score.

---

## 6. Ground truth: seven patch-sets, six annotators, five definitions

Seven teams published a repaired fork of WebVoyager. All revisions are pinned in
`benchmark_doctor/ground_truth/sources.py` and downloaded by `fetch_sources.py`.

| Source | Date | Expresses | In agreement stats |
|---|---|---|---|
| browser-use/eval | 2024-12-15 | 55 tasks listed impossible + 76 statements silently rewritten | yes |
| Skyvern (snapshot 01/2025) | 2025-01-16 | 635 kept + 8 outdated | **no** — same annotator as 05/2026 |
| Convergence WebVoyager2025Valid | 2025-02-17 | 601 tasks "valid until 20th December 2025" — the only patch-set with a declared expiry | yes |
| Magnitude `patches.json` | 2025-07-06 | 121 motivated patches: 68 rewrites + 53 deletions | yes |
| Emergence (templates) | 2025-07-21 | 535 templated tasks, dates instantiated at run time | **no** — re-samples to 35/site, exclusions not attributable to decay |
| Microsoft Fara F595 | 2025-08-31 | 595 tasks kept, no reasons | yes |
| Alumnium | 2026-03-17 | 619 kept; 20 per-site commits whose messages carry the reason | yes |
| Skyvern (snapshot 05/2026) | 2026-05-04 | 635 kept + 8 outdated; commit "refresh dates to 2026/2027" | yes |

Two conventions are frozen here because they change the numbers:

1. **The date is the artifact's, not the paper's.** Emergence's task file has not moved since
   2025-07-21 although the publication is dated March 2026; the file date governs the
   longitudinal study.
2. **Skyvern counts as two dated observations but one annotator.** Counting it twice would inflate
   inter-annotator agreement with a duplicated voice.

### There is no single ground truth — there are five

"A defective task" has no unique definition. Publishing one (P, R) pair would silently choose one.
All five are measured side by side; the spread is a result in itself — L1's precision moves from
**0.986 to 0.164** depending on which is chosen.

| Key | Definition | n |
|---|---|---:|
| `flagged≥1` | flagged by ≥1 of the 6 independent annotators | 169 |
| `majority≥3` | flagged by a majority | 123 |
| `unanimous` | flagged by all 6 | 68 |
| `removed≥1` | *deleted* by ≥1 annotator | 78 |
| `magnitude` | the 121 Magnitude patches alone | 121 |

**Known bias**: silence counts as "keep" even when a source never examined a task. Measured
agreement is therefore an **upper bound**.

---

## 7. Validation protocol

Four decisions, each of which changes the result:

**a. One measurement pass; ablation by filtering.** The three layers run once. "L1 alone",
"L1+L2", "L1+L2+L3" are obtained by *filtering the findings by layer*, never by re-running the
campaign. Re-running would introduce a variation of the world where a variation of method is
being measured. This is the operational reason `TaskVerdict` stores no binary verdict.

**b. Validation on findings, never on the published score** (see [§5](#the-practitioner-prior-and-when-to-switch-it-off)).

**c. Both thresholds, always.** L3 emits only MEDIUM findings by construction — an ambiguous task
still executes. Evaluating L3 at HIGH would return zero mechanically.

**d. Threshold-free ranking is reported too** (AUC of the detector-only risk), because a triage
tool is used by sorting, not by thresholding.

### Full grid — precision / recall / F1

**HIGH threshold ("hard flag")**

| Config | Flags | `flagged≥1` | `majority≥3` | `unanimous` | `removed≥1` | `magnitude` |
|---|---:|---|---|---|---|---|
| L1 | 73 | 0.986 / 0.426 / 0.595 | 0.959 / 0.569 / 0.714 | 0.863 / 0.926 / **0.894** | 0.164 / 0.154 / 0.159 | 0.973 / 0.587 / 0.732 |
| L2 | 175 | 0.383 / 0.396 / 0.390 | 0.297 / 0.423 / 0.349 | 0.194 / 0.500 / 0.280 | 0.143 / 0.321 / 0.198 | 0.280 / 0.405 / 0.331 |
| L3 | 139 | 0.604 / 0.497 / 0.545 | 0.511 / 0.577 / 0.542 | 0.381 / 0.779 / 0.512 | 0.209 / 0.372 / 0.267 | 0.518 / 0.595 / 0.554 |
| L1+L2 | 214 | 0.491 / 0.621 / 0.548 | 0.416 / 0.724 / 0.528 | 0.308 / 0.971 / 0.468 | 0.149 / 0.410 / 0.219 | 0.406 / 0.719 / 0.519 |
| L1+L3 | 153 | 0.640 / 0.580 / **0.609** | 0.556 / 0.691 / 0.616 | 0.412 / 0.926 / 0.570 | 0.209 / 0.410 / 0.277 | 0.562 / 0.711 / 0.628 |
| L1+L2+L3 | 274 | 0.449 / 0.728 / 0.555 | 0.361 / 0.805 / 0.499 | 0.241 / 0.971 / 0.386 | 0.164 / 0.577 / 0.256 | 0.354 / 0.802 / 0.491 |

**MEDIUM threshold ("wide flag")**

| Config | Flags | `flagged≥1` | `majority≥3` | `unanimous` | `removed≥1` | `magnitude` |
|---|---:|---|---|---|---|---|
| L1 | 134 | 0.754 / 0.598 / 0.667 | 0.634 / 0.691 / 0.661 | 0.478 / 0.941 / 0.634 | 0.202 / 0.346 / 0.255 | 0.634 / 0.703 / 0.667 |
| L2 | 175 | 0.383 / 0.396 / 0.390 | 0.297 / 0.423 / 0.349 | 0.194 / 0.500 / 0.280 | 0.143 / 0.321 / 0.198 | 0.280 / 0.405 / 0.331 |
| L3 | 325 | 0.348 / 0.669 / 0.458 | 0.268 / 0.707 / 0.388 | 0.178 / 0.853 / 0.295 | 0.129 / 0.538 / 0.208 | 0.268 / 0.719 / 0.390 |
| L1+L2 | 265 | 0.487 / 0.763 / 0.595 | 0.393 / 0.846 / 0.536 | 0.253 / 0.985 / 0.402 | 0.177 / 0.603 / 0.274 | 0.381 / 0.835 / 0.523 |
| L1+L3 | 368 | 0.364 / 0.793 / 0.499 | 0.275 / 0.821 / 0.411 | 0.174 / 0.941 / 0.294 | 0.139 / 0.654 / 0.229 | 0.275 / 0.835 / 0.413 |
| L1+L2+L3 | 424 | 0.356 / **0.893** / 0.509 | 0.269 / 0.927 / 0.417 | 0.158 / 0.985 / 0.272 | 0.149 / 0.808 / 0.251 | 0.262 / 0.917 / 0.407 |

L2's rows are identical at both thresholds: it emits only HIGH-severity access findings, so
lowering the threshold adds nothing. That is the mirror image of L3, which emits only MEDIUM and
whose L3-alone row therefore jumps from 139 to 325 flags.

**AUC of the risk ranking (detector-only score, no threshold)**

| Config | `flagged≥1` | `majority≥3` | `unanimous` | `removed≥1` | `magnitude` |
|---|---:|---:|---:|---:|---:|
| L1 | 0.818 | 0.861 | 0.956 | 0.600 | 0.853 |
| L2 | 0.585 | 0.594 | 0.629 | 0.529 | 0.583 |
| L3 | 0.684 | 0.711 | 0.809 | 0.565 | 0.722 |
| **L1+L2** | **0.831** | **0.879** | **0.975** | **0.627** | **0.869** |
| L1+L3 | 0.754 | 0.785 | 0.883 | 0.588 | 0.789 |
| L1+L2+L3 | 0.775 | 0.807 | 0.905 | 0.613 | 0.809 |

**L1+L2 ranks best in all five columns; adding L3 degrades the ranking.** Recall at threshold
improves, ordering worsens: a low-precision detector under noisy-OR aggregation raises everyone's
risk. This is a property of the (detector, aggregation) pair and is published, not hidden.

### Recall by taxonomy category

121 tasks were labelled T1–T8 by manual reading of the published patch reasons. Format:
*flagged / total (of which by a finding of the **right** category)*, MEDIUM threshold. Flagging a
broken task for the wrong reason is not detection.

| Config | T1 | T2 | T3 | T4 | T5 | T8 |
|---|---|---|---|---|---|---|
| L1 | 65/70 (61) | 6/21 (4) | 11/11 (10) | 1/7 (0) | 2/5 (0) | 0/7 (0) |
| L2 | 33/70 (0) | 7/21 (1) | 4/11 (4) | 1/7 (0) | 0/5 (0) | 4/7 (0) |
| L3 | 60/70 (52) | 6/21 (2) | 10/11 (1) | 2/7 (0) | 4/5 (3) | 5/7 (0) |
| L1+L2 | 69/70 (61) | 13/21 (5) | 11/11 (10) | 2/7 (0) | 2/5 (0) | 4/7 (0) |
| L1+L2+L3 | 70/70 (64) | 15/21 (5) | 11/11 (10) | 3/7 (0) | 5/5 (3) | 7/7 (0) |

No labelled task carries T6. **There is no T4, T6 or T8 detector**: the zeros in the parenthesised
column are structural, not tuning failures.

At the HIGH threshold, L1 alone recalls **0/21** on T2 — the content-drift blind spot announced as
the justification for building L2. L2 lifts it to 7/21, L1+L2+L3 to 10/21.

### Marginal contribution of each detector

Truth `flagged≥1`, MEDIUM threshold. "Findings" counts emitted findings; P/R are computed on
*tasks flagged by that detector alone*. "Exclusive" = tasks no other detector flags.

| Detector | Findings | P | R | F1 | Exclusive (true positives) |
|---|---:|---:|---:|---:|---|
| `l1_temporal` | 260 | 0.900 | 0.479 | 0.625 | 10 (5) |
| `l3_solvability` | 139 | 0.604 | 0.497 | 0.545 | 29 (5) |
| `l2_liveness` | 643 | 0.379 | 0.391 | 0.385 | 55 (16) |
| `l1_reference` | 130 | 0.421 | 0.095 | 0.155 | 22 (8) |
| `l3_ambiguity` | 238 | 0.261 | 0.367 | 0.305 | 108 (11) |
| `l1_sideeffect` | 13 | 0.846 | 0.065 | 0.121 | 2 (1) |
| `l2_content` | 28 | **1.000** | 0.006 | 0.012 | 1 (1) |

### Error diagnosis (L1+L2+L3, HIGH, vs `flagged≥1`)

- **151 false positives.** By detector (a task may carry several): `l2_liveness` anti-bot 70,
  `l2_liveness` paywall 38, `l3_solvability` 55, `l1_sideeffect` 1, `l1_temporal` **0**. By site:
  Allrecipes 38, Amazon 34, ESPN 30 — i.e. concentrated exactly where site-level access verdicts
  propagate.
- **46 false negatives**, concentrated on Apple 11, BBC News 10, Huggingface 8 — content drift the
  static layer cannot see and the probes do not reach (they only test the start URL).

### Decay accumulated outside the patch-sets

How many tasks does the tool flag today that no annotator ever touched?

| Configuration | Flagged | Outside Magnitude | Outside the union of all 6 |
|---|---:|---:|---:|
| L1 / naive v1 | 121 | 42 | 22 |
| L1 / contextual v2, HIGH | 73 | **2** | **1** |
| L1 / MEDIUM | 134 | 49 | 33 |
| L1+L2 / HIGH | 214 | 127 | 109 |
| L1+L2+L3 / HIGH | 274 | 177 | 151 |
| L1+L2+L3 / MEDIUM | 424 | 313 | 273 |

The single task that no annotator has ever flagged and that L1 v2 flags hard is `GitHub--40`
("Select Sign up on the GitHub homepage to see if email 'test123@gmail.com' already exists"),
graded D. Under v2 the other one outside Magnitude is `Amazon--5`.

The v1 row reproduces the "41" reported in earlier scoping notes (the difference of one is
abbreviated months now being recognised). **The gap between the v1 row and the v2 row is the whole
point of context-sensitivity**: a past date only invalidates *transactional* tasks; archival
queries age without breaking.

---

## 8. Longitudinal protocol

### Two curves, deliberately not merged

**Curve A — mortality as practitioners see it.** Cumulative tasks flagged by ≥1 of the 6 dated
annotators. Real observation, three fatal defects if read as a rate: (1) **left censoring** — the
first audit is 9.5 months after publication and flags 121 tasks at once, with no death date; (2)
**observation effort varies** — each point is a different annotator with a different threshold, so
a step may be a wave of decay or a more zealous reader; (3) **intent is not observation** —
Magnitude re-dates pre-emptively, Skyvern refreshes in bulk.

**Curve B — mortality as a constant instrument sees it.** The L1 detector replayed month by month
on the *frozen* corpus. The task text does not move; only the reference date advances. Every task
therefore has an exact, computable date of death. None of the three defects above applies — but it
sees exactly one mode of decay (T1) and nothing that happens on the site.

The two curves **bound** the phenomenon: B is an exact measure of a subset of causes, A a noisy
measure of all causes. Their gap is itself a result.

**Curve B′** applies the same instrument to the corpus *repaired* by Magnitude, from the date of
repair — which is how "do repairs last?" becomes a measurement rather than an opinion.

Resolution caveat: curve B's death dates are known **to the month** (31 grid points) and are dates
of **textual expiry**, not of execution failure. Day-level bisection was feasible and would add
nothing to a 30-month curve.

### Annual rate estimator

Constant-hazard model over the observation window Δt (months):

```
λ            = −ln(1 − k/n) / Δt
annual rate  = 1 − e^(−12λ)
CI 95 %      = Wilson interval on k/n, propagated through the same transform
```

| Estimator | k / n | Δt | Annual rate | 95 % CI | Status |
|---|---|---:|---:|---|---|
| A1 raw practitioner cumulative | 169/643 | 26.05 | 13.1 % | [11.4 ; 15.0] | left-censored → **overestimates** |
| **A2 post-first-audit increments** | 48/522 | 16.59 | **6.7 %** | [5.1 ; 8.8] | **recommended headline** |
| B constant instrument, frozen corpus | 28/598 | 29.44 | 1.9 % | [1.3 ; 2.8] | strict lower bound (T1 only) |
| B′ constant instrument, repaired corpus | 60/588 | 13.31 | 9.2 % | [7.2 ; 11.7] | |
| C patch rot | 65/65 | 13.31 | 100 % | [92.6 ; 100] | chosen population, **not transposable** |
| D Online-Mind2Web control | 52/300 | 13.31 | 15.8 % | [12.2 ; 20.1] | a *maintained* benchmark — upper bound of the visible |

**Defensible range, excluding patch rot: 1.9 % – 15.8 % per year.** A2 is recommended because it
drops the left-censored block and measures only increments observed after the first audit.

The Online-Mind2Web control is load-bearing: it is a benchmark that is *actively maintained*, so
its replacement log measures decay **observed under surveillance** rather than decay discovered
late. That it is the highest estimate is the expected direction — you find more when you look.

### Fork health

Each fork is measured twice with the same instrument: at its own freeze date, and at 2026-08-15.
The first number says what the fork's authors achieved; the second says how long it lasted.

---

## 9. Reproduction

```bash
# 0. dependencies (L1 needs none)
pip install -e ".[dev]" && pip install requests httpx

# 1. data, at pinned revisions
mkdir -p data/raw && curl -sSL -o data/raw/webvoyager_original.jsonl \
  https://raw.githubusercontent.com/MinorJerry/WebVoyager/091544539eba485dbd74ef3742011ddeede37336/data/WebVoyager_data.jsonl
sha256sum data/raw/webvoyager_original.jsonl   # 69b19fd8…88
python3 -m benchmark_doctor.ground_truth.fetch_sources
python3 -m benchmark_doctor.ground_truth.reconcile

# 2. the three phases
python3 run_all.py --phase audit      # needs network + OPENROUTER_API_KEY (L3)
python3 run_all.py --phase validate   # offline: replays runs/health_20260815_findings.json
python3 run_all.py --phase export

# 3. the longitudinal study (offline)
python3 analysis_longitudinal.py

# 4. the tests that lock the published figures
python3 -m pytest -q                  # 89 tests
```

| Step | Network | API key | Notes |
|---|---|---|---|
| `--phase audit` | yes (L2, L3) | yes for L3 | `--l3-backend tfidf --no-solvability` runs it free at reduced quality |
| `--phase validate` | **no** | **no** | replays the raw findings log — this is what makes the validation checkable by a reader |
| `--phase export` | no | no | |
| `analysis_longitudinal.py` | no | no | |

`runs/health_20260815_findings.json` (~1.9 MB) is the raw findings log. It is kept precisely so the
validation can be re-run without network, key, or budget.

Outputs: `runs/health_20260815.{json,html}`, `runs/validation_ablation_20260815.json`,
`runs/longitudinal_20260815.json`, `runs/longitudinal_curves_20260815.csv` (108 rows, ready to
plot), `exports/webvoyager_verified_v0.1.jsonl` + `.stats.json`.

---

## 10. Open conventions and known divergences

Declared rather than smoothed over:

1. **Curve A includes only the six independent annotators.** An earlier internal count included
   the Skyvern 01/2025 snapshot and Emergence, giving 147 rather than 133 at the Magnitude
   milestone. Both are defensible; the six-annotator convention is used throughout so that
   agreement statistics and the curve rest on the same population.
2. **Online-Mind2Web: 52 distinct tasks, not 55.** The last wave reuses suffixed identifiers
   (`…_051526`): 58 replacement events over 55 raw identifiers over **52 distinct tasks**, because
   5 tasks had to be replaced more than once (four twice, one three times). 52 is used, consistently
   with the published λ = 0.0143/month; an earlier internal count of 55 did not normalise the
   suffixes.
3. **The canonical patch in the export is chosen by recency**, not by vote: all 87 tasks with
   divergent patches receive textually different rewrites, and no voting rule reconciles different
   dates. Defensible but arbitrary — and 20 of the 116 retained patches are themselves already
   expired at the measurement date.
4. **`access_decay_per_month = 0`** is a declared absence of measurement, not a measured zero.

---

## 11. Checklist before quoting a number from this repository

- [ ] State the **reference date** — every figure is dated.
- [ ] State the **access channel** for anything involving L2. "Blocked from a datacenter IP" is
      not "dead".
- [ ] State the **threshold** (HIGH or MEDIUM) and the **ground-truth definition** for any
      precision/recall figure. The same detector scores 0.986 and 0.164 depending on the latter.
- [ ] State whether the score includes the **practitioner prior**.
- [ ] For a decay rate, state the **estimator** (A1/A2/B/B′/C/D) — they range from 1.9 % to 100 %
      and answer different questions.
- [ ] Do not present the full stack as a verdict: measured precision is below 0.45.
