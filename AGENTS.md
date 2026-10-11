# AGENTS.md -- Coney

Coney is an open-source, functional reimplementation of *The Warriors* (Rockstar Toronto, PS2, 2005) in C++23,
running natively on Windows, Linux and macOS from a disc the player owns. Anyone should be able to hand-write a
subsystem from our docs and comments alone. Legal rules in full: `LEGAL.md`.

## Layout

`src/core/` platform-neutral engine code; `src/platform/` the only place for OS, SDL3 or librw code; `tests/`
Catch2; `python/` the `coney-tools` CLI (uv); `docs/research/` what we know about the original; `docs/guides/` how
we work; `assets/` Coney's own assets (sandbox layouts, CC0 textures; never game data); `cmake/deps.cmake` pinned
dependencies. Worktrees go in `../../worktrees/coney/<branch>/`, scratch output
in `../../scratch/`; game files, emulators and tool installs live beside the repo, never in it.

## How we work

Read `docs/guides/how-we-work.md` before starting: the pipeline, the analyst and implementer roles, the coordinator,
sharing one machine and merging. Whoever starts agents follows `docs/guides/agents.md` (fork or fresh, which model,
briefs, long commands and the prompt cache). Nobody waits for a person to play their work: the automated tests
are the gate, so every piece of work proves itself as `docs/guides/testing.md` defines ("done" per kind of work, the
player's path, gamepad input, playthrough tests, the checks to run before reporting).

## Build and test

- Engine: `cmake --preset dev && cmake --build --preset dev && ctest --preset dev` (Windows: from a shell with the
  MSVC environment, `vcvars64.bat`). Presets `dev`, `release`, `ci` (warnings as errors), `asan` (Linux/macOS).
- Python: `uv run --project python pytest python/tests`; `uvx pre-commit run --all-files` before committing.
- Docs: `.venv/Scripts/python -m mkdocs build --strict`. Build details: `docs/guides/building.md`.

## Rules (never broken)

- **No game data** anywhere in the repo, issues, fixtures or CI: no executables, BIOS, assets, extracted files or
  dumps. Tests use synthetic fixtures; disc-backed checks print counts and hashes only. Exception: curated
  reference lists (names, ids, values, our own short descriptions) and small reference screenshots of models;
  never asset files, game text or script source, per `LEGAL.md`.
- **Clean room:** only analysts read decompiler output or disassembly, and they write `docs/research/` pages that
  cite addresses and short snippets. Engine code is written fresh from those pages, never transcribed.
- **Research claims** carry an evidence level: confirmed (code) at a cited address, confirmed (runtime), inferred,
  or speculative. Addresses are like `0x001490b8` in NTSC-U `SLUS_212.15`. How: `docs/guides/research-workflow.md`.
- **Reverse-engineering work** (Ghidra, disassembly, PCSX2, research claims) runs on Opus 5.5.
- **Faithful first:** gameplay matches the original exactly until the game is complete. Coney's own mechanics and
  enhancements wait (designs may be written now); debug tooling is not a mechanic and is fine.
- **Never exclude a file from the 512 KB large-file check** in `.pre-commit-config.yaml`: it catches game data
  committed by mistake. Split big generated data and pages instead.
- Making the repo public, tagging releases, force-pushing and legal or licence questions are maintainer decisions.

## Code

- C++23 within MSVC 19.38+, GCC 13+, Clang 17+, Xcode 16+; clang-format (`.clang-format`) decides layout; no
  exceptions: recoverable errors return `std::expected<T, coney::Error>`, broken invariants `CONEY_ASSERT`.
- Reimplemented code cites the original: `@orig 0x<addr> <Name> (<File>.cpp)`, plus a link to its research page.
- A doc comment on every public type and function, and a short comment above every other function (helpers,
  private members, long lambdas) and before each step of a long one; comments explain *why*, briefly. Keep the
  engine's test mode possible (fixed timestep, seeded randomness, scripted input): never assume real time, a display
  or a human.
- Tests for everything testable without the game, written first: `docs/guides/testing.md`. Style and the rest:
  `docs/guides/conventions.md`.

## Documentation

Document as you work: a change that alters behaviour, a command or what we know updates its living doc in the same
commit. One document per subject, updated in place: findings in `docs/research/`, how-tos in `docs/guides/`, the
why in code comments. Mission work updates `research/missions.yaml` (status, checkpoints) in the same commit and
reruns `coney-tools missions render`. CI refuses a pull request that changes `src/` or `python/src/` without
changing `docs/` or `research/`, unless its description has a line `Docs: none`. `HANDOFF.md` holds only the current
state of the work (local, never committed).

## Commits and GitHub

- Title `area: Verb the rest`, at most 72 characters, present tense, no trailing period. Verbs: Add, Fix, Update,
  Remove, Rebuild, Rework, Improve, Document. Areas: `build`, `ci`, `core`, `fileio`, `graphics`, `audio`,
  `platform`, `tools`, `research`, `agents`, `tests`, `legal`, `docs` (list and meanings:
  `.github/commit-conventions.json`, which CI checks PR titles against).
- A body says what changed for a user or developer and why. An agent ends the message with
  `Co-Authored-By: <model name> <its noreply address>` (Claude: `Claude Opus 5.5 <noreply@anthropic.com>`) and no
  other trailer; no other email address appears in a message.
- No file, code comment or commit message contains the repository's or the docs site's address; only the README
  does. Docs link files outside `docs/` as `repo:<path>`.
- Work happens on branches; before a push the branch is squashed into feature-sized commits. Only `main` and
  release branches are pushed.
- Ask the user you are working for before you push any other branch or open a pull request, and say why (for
  example, CI only runs on pushes to `main` and on pull requests). A pull request or issue you write carries no
  tool-attribution line.
