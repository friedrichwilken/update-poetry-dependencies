# AGENTS.md

Guidance for AI agents (and humans) working in this repo. `CLAUDE.md` is a symlink to this file.

## What this is

A composite GitHub Action that updates Python dependencies (Poetry or uv) one package at a time, runs the
project's tests after each update, keeps what passes, drops what fails, and opens one pull request with a report.

- `action.yml` — thin wrapper: installs uv, then runs `python -m updater` on a pinned Python. Source of truth for inputs, outputs and defaults.
- `updater/` — all logic. Stdlib only.
- `tests/unit/` — fast tests with fakes (`fakes.py`). `tests/fixture/*` — real projects for the e2e jobs.
- `docs/manual/` — reference. `docs/tutorials/` — step-by-step. See "How we write docs" below.

## Commands

```bash
uv sync --locked                 # dev environment
uv run pytest tests/unit         # unit tests
uv run ruff check . && uv run ruff format --check .
actionlint                       # workflows (brew install actionlint)
```

## Rules for code

- **Stdlib only** in `updater/`. The action runs with `uv run --no-project`; there is nowhere to install dependencies from.
- **Every subprocess goes through the injected runner** (`runner.py`) with an argument list. The only shell command is the user's `test-command`. This is what makes the logic unit-testable and injection-free.
- **No `${{ }}` inside `run:` blocks** in `action.yml` or workflows — pass values via `env:`. A unit test enforces this for `action.yml`.
- **Outputs and `report-json` are additive.** New fields appear only when set; with a feature off, output must stay byte-identical. Each feature has a test for that.
- **Verify tool behaviour with the real tool**, not from memory: `uv ...` and `uv tool run --from poetry==<default in action.yml> poetry ...` in a scratch directory. Several bugs here came from assumed CLI behaviour.
- **Fixtures lock old versions on purpose** (even ones with CVEs) so the e2e jobs have something to update. Never bump them; Dependabot is configured to ignore `tests/fixture/*`.
- A new mode or backend brings its own e2e fixture case and a stable CI job name (job names are required status checks).

## How we work

Issue first (`bug:` / `feature:` prefix) → one PR per issue or small group → an independent review of the PR that
tries to break it with the real tools → fix findings → merge on green CI (squash). Reviews have found real bugs
that CI missed in every round; do not skip them.

---

## How we write the README and docs — and why

This section is written to be reusable: point an agent at it from any other project.

### The problem we are solving

People evaluate a tool in seconds. A wall of text reads as "this is complicated" and they leave — before
learning that the tool is simple. So the README's only jobs are: say what this is, prove it is easy, and show
where the rest lives. Everything else is somewhere else.

### The structure

| Where | Answers | Style |
|---|---|---|
| `README.md` | "What is this, and can I use it in 60 seconds?" | One screen. Code before prose. |
| `docs/tutorials/` | "Walk me through it." | Learning by doing, one capability per step. |
| `docs/manual/` | "What exactly does X do?" | Reference. One question per page. |

This is the [Diátaxis](https://diataxis.fr) split, reduced to what a small project needs. Do not mix the kinds:
a tutorial that stops to list every option loses the learner; a reference page that tells a story is slow to scan.

### README rules

1. **Hard length limit** (here: 70 lines, enforced by a test). A limit you can fail is the only kind that holds.
2. Order: one sentence on what it is → **Why** → **one complete, copy-pasteable quick start** → a small sample of the result → feature one-liners, each linking into the manual → links to tutorials.
   - **Why** comes before how. State the reader's problem in their words (here: "a red bulk-bump PR tells you something broke, not what"), then the payoff, in two short paragraphs. A description of what a tool does is not a reason to care.
3. The quick start uses **zero optional settings**. Never explain a default in the README.
4. **No option tables, no internals, no history, no caveats.** They go in the manual. If a caveat matters for the quick start, the quick start is wrong.
5. Show the output (here: a few lines of the PR report). People want to see what they get.

### Tutorial rules

1. One tutorial that **builds one artefact step by step**; each step adds exactly one capability.
2. **Every step shows the complete file so far.** The reader can stop at any step with something that works. (FastAPI's tutorial is the model.)
3. **New lines carry a trailing comment that says what they do**: `dry-run: 'true'   # <- does everything except push and open the PR`. Not `# new` — that marks the line but teaches nothing. Yes, it repeats the prose; impatient readers only skim the code, so the code must explain itself. A line keeps its arrow only in the step that introduces it; the final recap has none. A test enforces this.
4. **Explain cryptic syntax inline**, where it appears: `cron: '0 6 * * 1'   # <- every Monday at 06:00 UTC`. Nobody reads cron.
5. **The intro is two sentences and a few bullets**: what we build, then the conventions. Do not explain the tutorial's method in paragraphs — start. 3–4 short sentences per step, then "what you should see".
6. **One tutorial for variants, not one per variant.** When two setups differ in a few lines, write for the default and mark the differing lines inline: `test-command: 'uv run pytest'   # Poetry: 'poetry run pytest'`. Never use commented-out alternative blocks — they get copy-pasted and rot. Parallel tutorials are 95% duplication and drift apart.
7. Details belong in the manual; link to it, do not repeat it.

### Manual rules

1. **One question per page**; the filename is the question's topic (`token-and-permissions.md`).
2. Each page opens with the answer in 1–2 sentences and a code block. Details follow for those who need them.
3. Generated-looking facts (inputs, defaults, output schemas) live in exactly one place and are checked against the source of truth by a test.
4. An index page with one line per page. Cross-link with relative links.

### Keeping docs true (the part most projects skip)

Docs rot silently, so they are tested like code:

- every input/output in `action.yml` is documented, and documented defaults match;
- every YAML example only uses inputs that exist; complete example workflows are linted in CI against the local action;
- variant comments (`# Poetry: ...`) are applied mechanically and the result is validated too;
- tutorial steps are diffed: every new or changed line must carry its `# <-` comment, and nothing else may;
- samples of output shown in the README are compared with what the code really renders;
- every relative link and anchor resolves;
- the README length limit.

When you change behaviour, the failing docs test tells you which page to update. If you add a doc claim that
no test can check, verify it against the code before writing it.

### Writing style

A wall of text can appear anywhere, not only in the README — a three-paragraph tutorial intro is one. If a block of prose explains the document instead of the subject, cut it.

Plain words, short sentences, second person in tutorials. Lead with the common case. Say what something does
before why. Prefer a 5-line example over a paragraph. If a page needs a table of contents, split it.

### Checklist for a docs change

- [ ] Does the README still fit the limit, and does the quick start still work by copy-paste?
- [ ] Is each new fact in exactly one place?
- [ ] Tutorial step: complete file shown, new lines explained with `# <-`, one capability?
- [ ] Manual page: answer first, one question?
- [ ] `uv run pytest tests/unit` (docs tests) green?
