# SPDX-License-Identifier: GPL-3.0-or-later
"""Hand-written counts in the research pages must equal the reference lists they are counted from.

The generated pages cannot drift from their YAML (`coney-tools refs render --check` fails CI), but a research page
that quotes a count by hand can. These tests read the repository's own pages and lists, never game data.
"""

import collections
import re
from pathlib import Path

import yaml

from coney_tools.config import find_repo_root

ROOT = find_repo_root(Path(__file__).parent)
WAD_CONTENTS = ROOT / "docs" / "research" / "formats" / "wad-contents.md"
WAD_DIR = ROOT / "docs" / "research" / "formats" / "wad-dir.md"
WAD_NAMES = ROOT / "research" / "references" / "wad-names.yaml"

#: A row of the Names table of wad-contents.md: `.ext` | count | text.
_ROW = re.compile(r"^\| `\.(\w+)` \| ([\d,]+) \|", re.MULTILINE)


def _name_counts() -> collections.Counter[str]:
    """The recovered names per extension, from the reference list."""
    entries = yaml.safe_load(WAD_NAMES.read_text(encoding="utf-8"))["entries"]
    return collections.Counter(entry["kind"] for entry in entries)


def _names_section() -> str:
    """The text of wad-contents.md from its Names heading to the next one."""
    text = WAD_CONTENTS.read_text(encoding="utf-8")
    start = text.index("## Names {#names}")
    return text[start : text.index("\n## ", start + 1)]


def test_names_table_matches_the_list() -> None:
    """Each row of the Names table is the number of names of that extension in wad-names.yaml, and none is missing."""
    shown = {ext: int(count.replace(",", "")) for ext, count in _ROW.findall(_names_section())}
    assert shown == dict(_name_counts())


def test_names_total_matches_the_list() -> None:
    """The total in the layout table, the Names text and wad-dir.md all say how many names the list holds."""
    total = f"{sum(_name_counts().values()):,}"
    contents = WAD_CONTENTS.read_text(encoding="utf-8")
    assert f"**{total}** |" in contents  # the Total row of the layout table
    assert f"{total} of the 10,701 entry names are recovered" in _names_section()
    assert f"All {total} recovered names in this block" in contents
    assert f"**Recovered names:** {total} of 10,701" in WAD_DIR.read_text(encoding="utf-8")
