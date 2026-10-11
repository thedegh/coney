# Contributing to Coney

Thank you for helping. People and AI agents follow the same rules here, and no AI tooling is required to
contribute. If you only read one other file first, read [LEGAL.md](LEGAL.md).

## Before you start

- Read [LEGAL.md](LEGAL.md). The short version: no game data anywhere in the project, and the clean room is
  never broken.
- The clean room splits the work in two. Analysts may read decompiler output and disassembly of the original game,
  and write what they learn into `docs/research/`. Anyone writing engine code works from `docs/research/` only and
  never copies or paraphrases decompiler output. See [LEGAL.md](LEGAL.md#clean-room).
- Research lives in `docs/research/`. If the page you need does not exist or is wrong, fixing the research is a
  contribution in its own right. Each claim carries an evidence level and, where it applies, an address.

## Setting up

Clone the repository. To build and test the engine, follow [docs/guides/building.md](docs/guides/building.md).

CI checks every pull request's title against the rules under [Commits](#commits); to check a commit title yourself,
with [uv](https://docs.astral.sh/uv/) installed:

```sh
git log -1 --format=%s | uv run --project python coney-tools repo check-title -
```

CI also refuses a pull request that changes `src/` or `python/src/` without changing `docs/` or `research/`; put a
line `Docs: none` in the description when the change needs no documentation. To check it yourself:

```sh
git diff --name-only main... | uv run --project python coney-tools repo check-docs
```

To build the documentation:

```sh
py -m venv .venv
.venv/Scripts/pip install -r requirements-docs.txt
.venv/Scripts/python -m mkdocs build --strict
```

On Linux and macOS use `python3 -m venv .venv` and `.venv/bin/` in place of `.venv/Scripts/`. The build must pass
with `--strict`, which rejects broken links and pages missing from the navigation.

Game files, emulators and tool installs live outside the repository, as siblings of the checkout. The layout is
described in [docs/guides/workspace.md](docs/guides/workspace.md).

## Commits

A commit title is:

```text
area: Verb the rest
```

It is at most 72 characters, has no trailing period, and uses the present tense. The areas and verbs, with what
each area covers, are in [.github/commit-conventions.json](.github/commit-conventions.json); AGENTS.md's "Commits
and GitHub" section states the same rules. Make one commit per logical change: a test goes in the same commit as
the code that makes it pass.

The body has an opening paragraph saying what changes and why, then `Changes:` with one bullet per part when there
are several, then `Verified:` with the commands you ran and what they printed. For example:

```text
docs: Add the contributor documents

README, contributing guide, the Contributor Covenant, the security
policy and the pull request template.

Verified: mkdocs build --strict passes
```

```text
legal: Update the provenance rule for commits written by agents

A commit an agent writes names the model in a Co-Authored-By line,
so the history shows which work an agent did.

Changes:
- LEGAL.md: describe the agent trailer
- AGENTS.md: point at the rule

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

## Agents' commits

A commit an AI agent wrote names the agent in a trailer: the model's name and the vendor's noreply address, and no
other email address:

```text
Co-Authored-By: <model name> <its noreply address>
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

The person who submits or merges the work answers for it. The full rule is in [LEGAL.md](LEGAL.md#provenance).

## Pull requests

- A pull request with one feature is squash-merged, and the pull request title becomes the commit title, so it
  follows the same `area: Verb the rest` format.
- A pull request with several features is shaped into one commit per feature before review, and is rebase-merged.
- CI must pass.
- Fill in the pull request template: what and why, the checklist, and which AI tools helped, if any.
- Keep a pull request to one subject. Unrelated changes belong in separate pull requests.

## Agents

AI agents read [AGENTS.md](AGENTS.md) first; it is the single instruction file for every agent in this repository.
