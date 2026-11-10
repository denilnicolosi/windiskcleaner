# Contributing

Thanks for helping. DiskDiet deletes files on other people's computers, so the bar for
"safe" is high and the code is kept small on purpose.

## Setup

```
uv sync
uv run pytest
uv run ruff check
uv run python -m diskdiet
```

## What is welcome

- **New cleanup rules** — the easiest and most useful contribution. See
  [docs/RULES.md](docs/RULES.md).
- Fixes for wrong advice, with the program and version where you saw it.
- Translations of existing strings (`src/diskdiet/strings.py`, `rules.py`).

Please open an issue before larger changes (new tabs, new kinds of action).

## Ground rules

- Read the invariants in [CLAUDE.md](CLAUDE.md). They apply to humans too.
- Every rule and heuristic comes with a test. Tests run on temporary folders only and must
  not write large files.
- Never test a cleanup on real data you care about.
- One logical change per pull request; add a line under *Unreleased* in `CHANGELOG.md`.

## Pull request checklist

- [ ] `uv run pytest` and `uv run ruff check` pass
- [ ] Both languages provided for new user-visible text
- [ ] `CHANGELOG.md` updated
