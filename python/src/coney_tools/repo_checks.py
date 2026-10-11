# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks on the repository itself, run by `coney-tools repo check`, `check-title`, `check-docs` and CI."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from coney_tools.config import ConfigError

#: Agent entry files that must hold only a pointer to AGENTS.md, the single instruction file.
POINTER_FILES: tuple[str, ...] = ("CLAUDE.md", "GEMINI.md")
#: A pointer file holding more than this has grown instructions of its own, which would drift from AGENTS.md.
MAX_POINTER_BYTES = 400
IMPORT_LINE = "@AGENTS.md"


def check_pointer_files(root: Path) -> list[str]:
    """Check that each of POINTER_FILES exists, has a line that is exactly `@AGENTS.md` and is small.

    Returns one message per problem; an empty list means clean.
    """
    problems: list[str] = []
    for name in POINTER_FILES:
        path = root / name
        if not path.is_file():
            problems.append(f"{name}: missing")
            continue
        data = path.read_bytes()
        if len(data) > MAX_POINTER_BYTES:
            problems.append(f"{name}: {len(data)} bytes, over the {MAX_POINTER_BYTES} allowed for a pointer file")
        if IMPORT_LINE not in data.decode("utf-8", errors="replace").splitlines():
            problems.append(f"{name}: no line that is exactly {IMPORT_LINE}")
    return problems


# --- commit and pull request titles ------------------------------------------------------------------------------

#: The areas and verbs; AGENTS.md's "Commits and GitHub" section states the same rules in prose.
TITLE_RULES_FILE = ".github/commit-conventions.json"
TITLE_MAX = 72
BREAKING = "(BREAKING)"

#: `area: Verb` and at least one more word; the area and verb are then checked against the rules file.
_TITLE_FORM = re.compile(r"^(?P<area>[^\s:]+): (?P<verb>\S+) \S")


class TitleRulesError(ConfigError):
    """The commit conventions file is missing or does not hold usable title rules."""


@dataclass(frozen=True)
class TitleRules:
    """The title rules from the commit conventions file: the known areas and the allowed verbs."""

    areas: frozenset[str]
    verbs: tuple[str, ...]


def load_title_rules(root: Path) -> TitleRules:
    """Read the areas and verbs from `root / TITLE_RULES_FILE`; raises TitleRulesError when they are unusable."""
    path = root / TITLE_RULES_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise TitleRulesError(f"{TITLE_RULES_FILE}: cannot be read ({error.strerror or error})") from error
    except json.JSONDecodeError as error:
        raise TitleRulesError(f"{TITLE_RULES_FILE}: not valid JSON (line {error.lineno}: {error.msg})") from error
    if not isinstance(data, dict):
        raise TitleRulesError(f"{TITLE_RULES_FILE}: expected a JSON object")
    areas = data.get("areas")
    if not isinstance(areas, dict) or not areas or not all(isinstance(key, str) and key for key in areas):
        raise TitleRulesError(f"{TITLE_RULES_FILE}: 'areas' must be a non-empty object of area names")
    verbs = data.get("verbs")
    if not isinstance(verbs, list) or not verbs or not all(isinstance(verb, str) and verb for verb in verbs):
        raise TitleRulesError(f"{TITLE_RULES_FILE}: 'verbs' must be a non-empty list of words")
    return TitleRules(areas=frozenset(areas), verbs=tuple(verbs))


def check_title(title: str, rules: TitleRules) -> list[str]:
    """Check a title against the commit title rules: `area: Verb the rest`, a known area, an allowed verb, 72 characters
    at most, no trailing period or whitespace, and `(BREAKING)` only at the end.

    Returns one reason per broken rule; an empty list means the title passes. A title not in the form at all stops
    at that one reason, since it has no area or verb to check.
    """
    form = _TITLE_FORM.match(title)
    if not form:
        return ["not in the form 'area: Verb the rest'"]
    area, verb = form.group("area"), form.group("verb")
    problems: list[str] = []
    if area not in rules.areas:
        problems.append(f"unknown area '{area}'")
    if verb not in rules.verbs:
        problems.append(f"'{verb}' is not one of the verbs ({', '.join(rules.verbs)})")
    if len(title) > TITLE_MAX:
        problems.append(f"{len(title)} characters; {TITLE_MAX} at most")
    bare = title.rstrip()
    if bare != title:
        problems.append("ends with whitespace")
    if bare.endswith("."):
        problems.append("ends with a period")
    if BREAKING in bare and not bare.endswith(" " + BREAKING):
        problems.append(f"{BREAKING} must end the title, after a space")
    return problems


def first_line(message: str) -> str:
    """The title of a commit message: its first line that is neither blank nor a `#` comment ("" if none)."""
    for line in message.splitlines():
        if line.strip() and not line.startswith("#"):
            return line
    return ""


#: Paths whose change alters what the project does or how its tools behave, so the docs must follow.
CODE_PREFIXES: tuple[str, ...] = ("src/", "python/src/")
#: Paths that hold the documentation: the site's pages, and the reference lists and bindings behind its generated pages.
DOC_PREFIXES: tuple[str, ...] = ("docs/", "research/")
#: The line a pull request body carries when its code change needs no documentation (a refactor, a fix of a typo).
DOCS_NONE = re.compile(r"^\s*Docs:\s*none\b", re.IGNORECASE | re.MULTILINE)


def check_docs(changed: list[str], body: str) -> list[str]:
    """Check that a pull request changing code changes the docs too, or says `Docs: none` in its body.

    `changed` holds the repository-relative paths the pull request touches (forward slashes). Only `src/` and
    `python/src/` count as code, so a change to tests, CI or build files asks for nothing. Returns the reasons the
    pull request is refused; an empty list means it passes.
    """
    code = [path for path in changed if path.startswith(CODE_PREFIXES)]
    if not code or any(path.startswith(DOC_PREFIXES) for path in changed) or DOCS_NONE.search(body):
        return []
    shown = ", ".join(code[:3]) + (f" and {len(code) - 3} more" if len(code) > 3 else "")
    return [
        f"changes code ({shown}) but nothing under {' or '.join(DOC_PREFIXES)}; "
        "update the living doc in the same pull request, or put a line `Docs: none` in its description"
    ]
