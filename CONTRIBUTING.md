# Contributing

[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) explains the design decisions that look odd.

## Invariants a contribution must not break

Each one exists because breaking it produced a wrong number at some point in this project.

- `Finding.channel` defaults to `Channel.STATIC`, a claim that no request was made; a detector that
  opens a connection sets the channel used, which separates a dead task from one we cannot see.
- No binary verdict is stored. Whether a task counts as flagged is computed later, at a threshold
  the caller chooses; `task.is_broken = True` bakes a decision policy into a measurement and makes
  the ablation of `run_all.py --phase validate` impossible.
- Severity is how bad the finding is if it is true, confidence is how sure the detector is that it
  is true. One number cannot carry both.
- `evidence` holds the excerpt that justifies the finding, and `observed_at` defaults to the day of
  construction, so a detector replaying a recorded observation sets it to that observation's date.

## Adding a detector

The contract is one function, `(task, *, today) -> list[Finding]`, with `today` injected by the
caller and never read from the clock inside; `detectors/l1_sideeffect.py` is the model. Beyond the
fields above, a finding names a `category` among T1 to T8, a `detector` whose prefix sets the layer
(`l1_`, `l2_`, `l3_`) and a `signal`, the granularity the ablation tables read.

Export it from `benchmark_doctor/detectors/__init__.py` only if it is an L1 detector: that module
stays importable with the standard library alone. L2 and L3 detectors are imported by their own
modules, and `_run_layers` in `cli.py` wires them in.

Choosing the severity is most of the work. `HIGH` means "very probably not executable as written",
and `CRITICAL` is reserved for inexecutability confirmed by direct observation, which a static
detector never has. A detector meant as a prioritisation signal, as `l1_reference` is, caps its
severity below the hard-flag threshold and says so in its docstring.

It ships with unit tests covering a positive, a negative and a near-miss, plus its precision,
recall and exclusive true positives against at least one of the five ground-truth definitions.
`tests/test_pipeline_and_cli.py` hard-codes the published figures, so a detector change makes it
fail, and that failure is the signal that every table in the README, in `docs/METHODOLOGY.md` and
in the thesis has to be recomputed in the same commit.

## Adding a parser or a ground-truth source

A parser is a function `(source, *, benchmark) -> list[Task]` in `benchmark_doctor/parsers/`,
registered in `PARSERS`; `parsers/webvoyager.py` is the model. A ground-truth source is a
`SourceSpec` in `benchmark_doctor/ground_truth/sources.py`, where four fields keep the numbers
honest: `commit` is a pinned revision, never a branch; `date` is the artifact's own date, as its
repository gives it, not the paper's; `annotator` is shared by two sources from the same team, so
they count once in the agreement statistics; `confidence` and `counted_in_agreement` fall to
`faible` and `False` when an exclusion is not attributable to decay, as when Emergence re-samples
to 35 tasks per site.

## Data, secrets and network manners

`data/raw/` keeps third-party corpora at the revisions pinned in `ground_truth/sources.py`. `.env`
is git-ignored and stays that way: L3 reads `OPENROUTER_API_KEY` from the environment, and no key
belongs in a versioned file, a log or a test fixture. L3 calls are cached under `runs/l3_cache/`,
git-ignored too, so a pull request needing L3 evidence ships the recorded findings rather than
asking a reviewer to pay for a re-run. `DirectHTTPChannel` memoises observations per host and
throttles to one request per second (`min_interval`); both stay.

## Reporting a decayed task

No code required. An issue gives the task id and its benchmark (`Booking--12`, WebVoyager), the
date, the channel used and the country and network it came from, and what was seen, quoted or
screenshotted. The full stack has a measured precision below 0.45, so a flag a reader disagrees
with is expected; the usable part of a report is what the site showed on the day.

## Language

`README.md`, `CONTRIBUTING.md` and `docs/METHODOLOGY.md` are in English, as are identifiers, CLI
flags and file names. Docstrings, comments, CLI output, exported field names and the source
documents of `docs/` and `exports/` are in French, because they were written for a French-language
thesis, and a new docstring may be in either language.

## Licence

Contributions are accepted under the [MIT licence](LICENSE), like the rest of the project. Opening
a pull request means the contribution is licensed under it.
