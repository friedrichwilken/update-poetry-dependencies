# AGENTS.md

For agents. Terse on purpose. `CLAUDE.md` -> symlink to this file.

## Repo

Composite GitHub Action: updates Python deps (Poetry|uv) one package at a time, runs project tests after each, keeps passes, drops failures, opens one PR with report.

- `action.yml`: thin wrapper (installs uv, runs `python -m updater` on pinned Python). Source of truth: inputs, outputs, defaults.
- `updater/`: all logic.
- `tests/unit/`: fast, fakes in `fakes.py`. `tests/fixture/*`: real projects for e2e jobs.
- `docs/manual/`: reference. `docs/tutorials/`: step-by-step.

## Commands

```bash
uv sync --locked
uv run pytest tests/unit
uv run ruff check . && uv run ruff format --check .
actionlint                                  # workflows
python3 .github/scripts/lint_docs_workflows.py   # docs examples incl. Poetry rendition; needs actionlint; NOT covered by pytest
```

## Code rules

- `updater/` stdlib only. Why: runs via `uv run --no-project`, nothing to install from.
- All subprocesses via injected runner (`runner.py`), arg lists. Only shell command: user's `test-command`. Why: unit-testable, injection-free.
- No `${{ }}` inside `run:` (action.yml, workflows); pass via `env:`. Test-enforced for action.yml.
- Outputs + `report-json` additive: new fields only when set; feature off => byte-identical output. Test per feature.
- Verify CLI behaviour with the real tool in a scratch dir (`uv ...`, `uv tool run --from poetry==<default in action.yml> poetry ...`), never from memory. Why: several bugs came from assumed CLI behaviour.
- Fixtures lock old versions on purpose (incl. CVEs) so e2e has something to update. Never bump. Dependabot ignores `tests/fixture/*`.
- New mode/backend => own e2e fixture case + stable CI job name (job names = required status checks).

## Workflow

Issue first (`bug:`/`feature:` prefix) -> one PR per issue/small group -> independent review that tries to break it with real tools -> fix findings -> squash-merge on green CI. Never skip review: every round found real bugs CI missed.

---

## Docs method (reusable in any project)

### Problem

Readers evaluate a tool in seconds. Wall of text => "complicated" => they leave before learning it is simple. README jobs, only these: what it is, why care, prove it is easy, point to the rest.

### Structure (Diátaxis, reduced)

| Where | Answers | Style |
|---|---|---|
| `README.md` | what is it, usable in 60s? | one screen, code before prose |
| `docs/tutorials/` | walk me through it | learn by doing, one capability per step |
| `docs/manual/` | what exactly does X do? | reference, one question per page |

Never mix kinds. Tutorial listing every option loses the learner; reference telling a story is slow to scan.

### README

1. Hard length limit, test-enforced (here 70 lines). Only a limit that can fail holds.
2. Order: one sentence what -> Why -> one complete copy-paste quick start -> small sample of the result -> feature one-liners linking into manual -> links.
3. Why before how: reader's problem in reader's words, then payoff, two short paragraphs. Describing what a tool does is not a reason to care.
4. Quick start: zero optional settings. Never explain a default.
5. Prerequisites that make the first run fail go next to the quick start, as a short list.
6. No option tables, internals, history, caveats -> manual. Caveat needed for the quick start => quick start is wrong.
7. Show real output. Sample must be test-compared with what the code renders (invented samples drift).
8. Competitor comparison: separate manual page, only claims verifiable in their official docs, say when the competitor is the better choice. Not in README body.

### Tutorial

1. One tutorial builds one artefact; each step adds exactly one capability.
2. Every step shows the complete file so far; any step is copy-paste runnable (model: FastAPI tutorial).
3. New/changed lines carry a trailing comment saying what the line does: `dry-run: 'true'   # <- does everything except push and open the PR`. Not `# new` (marks, teaches nothing). Redundant with prose on purpose: impatient readers skim only the code. Arrow only in the step introducing the line; final recap has none. Test-enforced by diffing consecutive steps.
4. Explain cryptic syntax inline where it appears: `cron: '0 6 * * 1'   # <- every Monday at 06:00 UTC`. Nobody reads cron.
5. Intro = two sentences + few bullets (what we build, conventions). Never explain the tutorial's method in paragraphs. Per step: 3-4 short sentences, code, then "What you should see" as 2-3 bullets.
6. One tutorial for variants, not one per variant. Write for the default; mark differing lines inline: `test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'`. Never commented-out alternative blocks (copy-pasted, rot). Parallel tutorials = 95% duplication, drift. Variant rendition is generated mechanically from the markers and validated in CI.
7. Details -> manual; link, do not repeat.

### Manual

1. One question per page; filename = topic (`token-and-permissions.md`).
2. Page opens with the answer (1-2 sentences) + code block; details after.
3. Facts that mirror a source of truth (inputs, defaults, schemas) live in exactly one place, test-checked against the source.
4. Index page, one line per page. Relative cross-links.
5. Page needs a table of contents => split it.

### Docs are tested like code (most projects skip this)

- every input/output documented; documented defaults == `action.yml`
- every YAML example uses only existing inputs; complete example workflows linted in CI against the local action
- variant markers applied mechanically, result validated too
- tutorial steps diffed: arrows on exactly the new/changed lines
- README output sample == real rendering
- every relative link + anchor resolves
- README length limit

Behaviour change => failing docs test names the page to update. Claim no test can check => verify against code before writing.

### Style

- Wall of text can appear anywhere (tutorial intro, "what you should see", a note after a code block). Prose explaining the document instead of the subject => cut. Run-on sentence with 2+ facts => list.
- Plain words, short sentences, second person in tutorials. Common case first. What before why. 5-line example over a paragraph.
- Jargon only with its meaning attached once ("dogfooding": using your own product), else plain words.

### Checklist (docs change)

- README within limit; quick start still copy-paste runnable?
- each new fact in exactly one place?
- tutorial step: complete file, new lines explained with `# <-`, one capability?
- manual page: answer first, one question?
- `uv run pytest tests/unit` + `lint_docs_workflows.py` green?
