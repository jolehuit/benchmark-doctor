# Contributing

Thanks for looking. This is research code released with a master's thesis. Contributions that
make it *less* honest (a number without the script that produced it, a verdict without its
access channel) will be turned down however good the code is.

Start with [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md). Almost every design decision that looks
odd is explained there.

## Where help is worth the most

Roughly ordered by how much they would improve the measured results, not by how fun they are.

- **Detectors for the uninstrumented categories.** T4 (UI/environment instability), T6 (multiple
  valid solutions) and T8 (timing dependencies) have **no detector at all**. The tool currently
  flags T8 tasks for unrelated reasons, which is worse than not flagging them. This is the largest
  hole in the project.
- **Better granularity for L2.** Access verdicts are currently host-level: WebVoyager gives one
  start URL per task, so a block on `allrecipes.com` propagates to all 45 Allrecipes tasks. That is
  the main source of false positives (108 of 151). A detector that probes a *task-specific*
  resource, such as a search result or a product page derived from the statement, would attack the
  problem at its root.
- **Parsers for other benchmarks.** Only WebVoyager is instrumented end to end. `PARSERS` in
  `benchmark_doctor/cli.py` has exactly one entry. Online-Mind2Web, WebArena, AssistantBench and
  Mind2Web are all natural targets, and each new corpus tests whether the taxonomy generalises.
- **Channel implementations.** `PlaywrightChannel` exists but was never exercised in the reference
  campaign. A working local-browser channel, or a residential-proxy channel, would let anyone check
  which of our access findings are real and which are our own network being filtered. That directly
  tightens the κ = 0.40 credibility constant, which currently rests on three observations.
- **Ground-truth sources.** New dated patch-sets, or a manual arbitration of the 71 contested
  tasks in `exports/webvoyager_verified_v0.1.jsonl`. Arbitration is the brick still missing from a
  genuine "WebVoyager-Verified", and it cannot be automated: it requires opening the sites.
- **Figures.** `runs/longitudinal_curves_20260815.csv` (108 rows) is ready to plot and nothing
  plots it.

## Invariants a contribution must not break

These are not style preferences. Each of them exists because violating it produced a wrong number
at some point during this project.

**Every finding carries its access channel.** `Finding.channel` is mandatory. A verdict that
does not say where it was observed from confuses "the task is dead" with "our infrastructure
cannot see it". We measured a URL returning 402 from a datacenter IP and 200 from a browser 47
seconds later. Purely static detectors use `Channel.STATIC`, which is a claim too, namely that no
request was made.

**No binary verdict is ever stored.** A detector emits findings; whether a task counts as
flagged is computed later, at a threshold the caller chooses. If you find yourself writing
`task.is_broken = True`, stop: you are baking a decision policy into a measurement, and you make
the ablation in `run_all.py --phase validate` impossible.

**Severity and confidence are different axes.** *Severity* = how bad this is **if the finding is
true**. *Confidence* = how sure the detector is that it is true. Collapsing them into one number
loses the distinction between "certainly a minor problem" and "possibly a fatal one".

**No finding without quotable evidence and a date.** `evidence` must contain the excerpt of the
statement, or of the site's response, that justifies the finding. `observed_at` must be set. A
report about an object whose whole thesis is that it changes over time cannot contain undated
observations.

## Adding a detector

The contract is one function, task in, findings out:

```python
# benchmark_doctor/detectors/l1_yourthing.py
"""L1 : <what it detects, and what it refuses to claim>."""

import datetime as _dt

from ..models import Category, Channel, Finding, Severity, Task


def detect_your_thing(task: Task, *, today: _dt.date | None = None) -> list[Finding]:
    """Détecte <…>.

    Args:
        task: la tâche à analyser.
        today: date de référence, jamais `date.today()` en dur dans la logique.
    """
    day = today or _dt.date.today()
    findings: list[Finding] = []
    if ...:
        findings.append(Finding(
            category=Category.UI_INSTABILITY,   # T1..T8
            severity=Severity.MEDIUM,           # if true, how bad
            confidence=0.7,                     # how sure we are
            evidence=matched_text,              # quotable, always
            detector="l1_yourthing",            # prefix sets the layer: l1_/l2_/l3_
            channel=Channel.STATIC,             # mandatory
            signal="specific_pattern_name",     # the granularity ablation tables use
            task_id=task.task_id,
            observed_at=day,
        ))
    return findings
```

Then: export it from `benchmark_doctor/detectors/__init__.py` **only if it is an L1 detector**,
because that module is imported by environments with no network dependencies at all, and must stay
importable with the standard library alone. L2 and L3 detectors are imported explicitly by their
own modules. Wire it into `_run_layers` in `cli.py`.

Choosing severity honestly is most of the work. `HIGH` means "very probably not executable as
written". `CRITICAL` is reserved for inexecutability **confirmed by direct observation**, which a
static detector can never have. If your detector is a prioritisation signal rather than a verdict,
as `l1_reference` is, cap its severity below the hard-flag threshold on purpose and say so in the
docstring.

Every new detector must come with:

- unit tests in `tests/` covering at least one positive, one negative and one near-miss;
- a measurement of what it adds: precision, recall and **exclusive** true positives against at
  least one of the five ground-truth definitions. A detector that only re-flags what `l1_temporal`
  already flags adds cost and no information. `l2_content` is in the repository as an honest
  counter-example: precision 1.000, recall 0.006.

## Adding a parser or a ground-truth source

**Parser**: a function `(source, *, benchmark) -> list[Task]`, in `benchmark_doctor/parsers/`,
registered in `PARSERS`. Model it on `parsers/webvoyager.py`.

**Ground-truth source**: add a `SourceSpec` to `benchmark_doctor/ground_truth/sources.py`. Four
fields decide whether the numbers stay honest:

- `commit`: a **pinned revision**, never a branch. `fetch_sources.py` downloads exactly that.
- `date`: the date of the **artifact**, not of the paper announcing it.
- `annotator`: two sources by the same team share one annotator key and count once in agreement
  statistics (this is why Skyvern's two snapshots do not inflate agreement).
- `confidence` / `counted_in_agreement`: set these to `faible` / `False` when an exclusion is not
  attributable to decay (Emergence re-samples to 35 tasks per site; that is not a verdict).

## Tests, and the figures they lock

```bash
python3 -m pytest -q        # 89 tests, < 1 s
```

`tests/test_pipeline_and_cli.py` **deliberately hard-codes the published figures**. If you change a
detector, those tests fail. That is the feature: the failure is the signal that every table in the
README, in `docs/METHODOLOGY.md` and in the thesis has to be recomputed. Update the expected
values in the same commit as the detector change, and say in the PR description which published
numbers moved and why.

## Rules for numbers

- **Any figure in a PR must come with the script that produced it.** No hand-computed numbers, in
  code, in docs, or in a commit message.
- **State the threshold and the ground-truth definition.** The same L1 detector scores precision
  0.986 against "flagged by ≥1 annotator" and 0.164 against "deleted by ≥1 annotator". A bare
  precision figure is not a claim, it is a mood.
- **Ablate by filtering, never by re-running.** The campaign runs once and layer subsets are
  obtained by filtering findings. Re-running would measure a change in the web while pretending to
  measure a change in method.
- **Negative results are welcome.** This repository publishes the fact that adding L3 degrades its
  own ranking (AUC 0.831 → 0.775). Contributions that measure and report a failure are worth more
  than contributions that quietly avoid measuring.

## Data, secrets and cost

- **`data/raw/` is not versioned.** Third-party corpora keep their own licences and are not
  redistributed here. Bootstrap with the commands in the README; every revision is pinned.
- **Never commit a key.** `.env` is git-ignored and stays that way. L3 reads
  `OPENROUTER_API_KEY` from the environment (falling back to an untracked `.env`). No key ever
  appears in a versioned file, a log, or a test fixture.
- **Do not burn other people's budget.** L3 calls are cached on disk under `runs/l3_cache/`
  (git-ignored); a re-run costs \$0. If a PR needs L3 evidence, ship the recorded findings rather
  than asking a reviewer to pay to reproduce them. The whole reference campaign cost \$0.26; keep
  it that cheap.
- **Be polite to the sites being probed.** L2 memoises observations per host and throttles to one
  request per second. Do not remove either. A benchmark health checker that gets its users
  rate-limited has defeated its own purpose.

## Reporting a decayed task (no code required)

This is a genuinely useful contribution. Open an issue with:

1. the **task id** and the benchmark (e.g. `Booking--12`, WebVoyager);
2. the **date** you observed it;
3. the **access channel** you used: browser, plain HTTP, which country/network. This is not
   bureaucracy, it is the difference between "this task is dead" and "this task is invisible from
   your network";
4. what you saw, quoted or screenshotted;
5. which taxonomy category you think it is (T1–T8), if you have a view.

Please do **not** open an issue that only says "the tool flagged task X and I disagree". That is
expected: the full stack has precision below 0.45 by design. Say what you saw when you opened the
site, and the report becomes ground truth.

## Language

Identifiers, CLI flags, file names, this document and `docs/` are **English**. Docstrings, inline
comments, CLI output and the field names of exported reports are **French**, because they were
written for a French-language thesis. Mixed, and known to be mixed.

New code: write docstrings in whichever of the two you are comfortable with. An accurate French
docstring beats an approximate English one, and vice versa. Do not translate existing docstrings in
a PR that also changes behaviour; those two changes must be reviewable separately.

## Licence

Contributions are accepted under the [MIT licence](LICENSE), same as the rest of the project. By
opening a pull request you agree that your contribution is licensed under it.
