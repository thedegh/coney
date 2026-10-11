# SPDX-License-Identifier: GPL-3.0-or-later
"""WARRIORS.DIR / WARRIORS.WAD: parse the index, look entries up by name hash, extract, recover names.

Research: docs/research/formats/wad-dir.md (the layout) and docs/research/name-hash.md (the hash).
"""

from __future__ import annotations

import re
import struct
import sys
import zlib
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from coney_tools.config import ConfigError, find_repo_root
from coney_tools.disc import Disc

DIR_FILE = "WARRIORS.DIR"
WAD_FILE = "WARRIORS.WAD"
ELF_FILE = "SLUS_212.15"
#: The prefix the game puts before a file's name before hashing it.
NAME_PREFIX = "./ee_files/"
_HEADER = 16  # WARRIORS.DIR's header: the entry count, then 12 bytes of padding
_ENTRY = 12  # one entry: offset, size, name hash
_CHUNK = 8 << 20  # bytes per read when streaming an entry


def name_hash(path: str) -> int:
    """Return the hash WARRIORS.DIR stores for `path`: CRC-32 of the lowercased text.

    Research: docs/research/name-hash.md
    """
    return zlib.crc32(path.lower().encode("ascii"))


@dataclass(frozen=True)
class WadEntry:
    """One WARRIORS.DIR entry: where the data is in WARRIORS.WAD and the hash of its name."""

    index: int  # position in WARRIORS.DIR
    offset: int  # byte offset into WARRIORS.WAD
    size: int  # bytes
    hash: int  # name_hash of `./ee_files/<name>`


def parse_dir(data: bytes, wad_size: int | None = None) -> list[WadEntry]:
    """Parse the bytes of WARRIORS.DIR.

    Raises ConfigError when the file is truncated, its size does not match its entry count, or (when `wad_size` is
    given) an entry reaches past the end of the WAD.
    """
    if len(data) < _HEADER:
        raise ConfigError(f"{DIR_FILE}: truncated ({len(data)} bytes, the header alone is {_HEADER})")
    (count,) = struct.unpack_from("<I", data, 0)
    expected = _HEADER + count * _ENTRY
    if len(data) != expected:
        raise ConfigError(f"{DIR_FILE}: header says {count} entries ({expected} bytes) but the file has {len(data)}")
    entries = []
    for index in range(count):
        offset, size, hashed = struct.unpack_from("<III", data, _HEADER + index * _ENTRY)
        if wad_size is not None and offset + size > wad_size:
            raise ConfigError(
                f"{DIR_FILE}: entry {index} ({hashed:08x}) ends at {offset + size}, "
                f"past the end of {WAD_FILE} ({wad_size})"
            )
        entries.append(WadEntry(index, offset, size, hashed))
    return entries


def load_entries(disc: Disc) -> list[WadEntry]:
    """Read and validate the index of `disc`."""
    with disc.open(DIR_FILE) as handle:
        data = handle.read()
    return parse_dir(data, disc.size(WAD_FILE))


def display_name(name: str) -> str:
    """The name without the `./ee_files/` prefix, as shown and used for extracted files."""
    return name[len(NAME_PREFIX) :] if name.lower().startswith(NAME_PREFIX) else name


def hash_names(names: Iterable[str]) -> dict[int, str]:
    """Map hash to name for each candidate, trying the name with `./ee_files/` in front and as given.

    A name without the prefix is the usual case (`global.lua`); the game always hashes it with the prefix.
    """
    table: dict[int, str] = {}
    for name in names:
        if not name.isascii():
            continue
        table.setdefault(name_hash(NAME_PREFIX + display_name(name)), display_name(name))
        table.setdefault(name_hash(name), display_name(name))
    return table


def load_names(path: Path | None) -> dict[int, str]:
    """Read a names file (one name per line; blank lines and `#` comments ignored) into a hash table."""
    if path is None:
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"{path}: cannot be read ({error})") from error
    return hash_names(line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#"))


def read_chunks(handle: BinaryIO, size: int, chunk: int = _CHUNK) -> Iterator[bytes]:
    """Yield `size` bytes from the current position of `handle` in pieces, never the whole at once."""
    left = size
    while left > 0:
        piece = handle.read(min(chunk, left))
        if not piece:
            break
        left -= len(piece)
        yield piece


def content_kind(first_four: bytes) -> str:
    """Describe the first four bytes of an entry: the ASCII text when printable, else hex."""
    if len(first_four) == 4 and all(0x20 <= b < 0x7F for b in first_four):
        return f"'{first_four.decode('ascii')}'"
    return first_four.hex() if first_four else "(empty)"


def count_kinds(wad: BinaryIO, entries: list[WadEntry]) -> Counter[str]:
    """Count entries by their first four bytes (a rough content breakdown)."""
    kinds: Counter[str] = Counter()
    for entry in entries:
        wad.seek(entry.offset)
        kinds[content_kind(wad.read(min(4, entry.size)))] += 1
    return kinds


def resolve_only(only: list[str], entries: list[WadEntry]) -> set[int]:
    """Turn `--only` arguments (8 hex digits, or a name) into entry indexes. Raises ConfigError for an unknown one."""
    by_hash: dict[int, list[int]] = {}
    for entry in entries:
        by_hash.setdefault(entry.hash, []).append(entry.index)
    wanted: set[int] = set()
    for item in only:
        text = item.lower().removeprefix("0x")
        key: int | None = None
        if re.fullmatch(r"[0-9a-f]{8}", text) and int(text, 16) in by_hash:
            key = int(text, 16)
        elif item.isascii():
            candidate = name_hash(item if item.startswith("./") else NAME_PREFIX + item)
            if candidate in by_hash:
                key = candidate
        if key is None:
            raise ConfigError(f"--only {item}: no entry with that hash or name")
        wanted.update(by_hash[key])
    return wanted


def entry_filename(entry: WadEntry, names: dict[int, str], used: set[str]) -> str:
    """The file name for an extracted entry: the recovered name's last component, else `<hash>.bin`."""
    fallback = f"{entry.hash:08x}.bin"
    name = names.get(entry.hash)
    if name:
        leaf = name.replace("\\", "/").rsplit("/", 1)[-1]
        if leaf and leaf not in (".", "..") and leaf.lower() not in used:
            used.add(leaf.lower())
            return leaf
    used.add(fallback)
    return fallback


def extract(
    disc: Disc, entries: list[WadEntry], names: dict[int, str], out_dir: Path, wanted: set[int] | None
) -> list[tuple[WadEntry, Path]]:
    """Write entries (all, or those whose index is in `wanted`) into `out_dir`, streaming each.

    Returns what was written. Raises ConfigError when a file cannot be written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    written = []
    with disc.open(WAD_FILE) as wad:
        for entry in entries:
            # Named before the `wanted` filter, so an entry gets the same file name with or without --only.
            name = entry_filename(entry, names, used)
            if wanted is not None and entry.index not in wanted:
                continue
            target = out_dir / name
            wad.seek(entry.offset)
            try:
                with target.open("wb") as out:
                    for piece in read_chunks(wad, entry.size):
                        out.write(piece)
            except OSError as error:
                raise ConfigError(f"{target}: cannot be written ({error})") from error
            written.append((entry, target))
    return written


#: A file-name-like token: path characters, then one or more `.ext` parts. Linear-time on binary data.
_TOKEN = re.compile(rb"[\w/\\-]{1,100}(?:\.[A-Za-z0-9_-]{1,32})+")


def harvest(chunks: Iterable[bytes], table: dict[int, str], found: dict[int, str]) -> None:
    """Hash every file-name-like string in `chunks`; add those that match a key of `table` to `found`.

    A string is tried by its last component with `./ee_files/` in front, which is the form the game hashes, and
    as a whole path. Chunks overlap by a few bytes so a string is not cut in half at a chunk edge.
    """
    tail = b""
    for chunk in chunks:
        data = tail + chunk
        for match in _TOKEN.finditer(data):
            token = match.group().decode("ascii")
            leaf = token.replace("\\", "/").rsplit("/", 1)[-1]
            for candidate, shown in ((NAME_PREFIX + leaf, leaf), (token, token)):
                hashed = name_hash(candidate)
                if hashed in table and hashed not in found:
                    found[hashed] = shown
        tail = data[-128:]


def recover_names(disc: Disc, entries: list[WadEntry], progress: bool = False) -> dict[int, str]:
    """Recover names for `entries` by hashing strings from the executable and from the WAD's entries.

    Returns hash to name for every entry hash a candidate matched. The executable is skipped (with a note on
    stderr) when the disc has none.
    """
    wanted = {entry.hash: "" for entry in entries}
    found: dict[int, str] = {}
    if disc.has(ELF_FILE):
        with disc.open(ELF_FILE) as elf:
            harvest(read_chunks(elf, disc.size(ELF_FILE)), wanted, found)
    else:
        print(f"coney-tools: no {ELF_FILE} on the disc; harvesting from {WAD_FILE} only", file=sys.stderr)
    with disc.open(WAD_FILE) as wad:
        for number, entry in enumerate(entries):
            wad.seek(entry.offset)
            harvest(read_chunks(wad, entry.size), wanted, found)
            if progress and number % 1000 == 999:
                print(f"  scanned {number + 1}/{len(entries)} entries, {len(found)} names", file=sys.stderr)
    return found


#: The first entry of the sorted block: from here on entries are stored in name order
#: (docs/research/formats/wad-dir.md), which rules out a chance hash match; the entries before it have no such check.
SORTED_BLOCK_START = 3615
#: The streamed world's file-name formats (the world loader's `%s_sec.wld`, `%s_sec.mem`, `%s_ms%i.sec`).
#: Research: docs/research/formats/wad-contents.md#names
WORLD_FORMATS = ("{}_sec.wld", "{}_sec.mem")
WORLD_PART_FORMAT = "{}_ms{}.sec"
#: A streamed world's file: `<world>_ms<i>.sec`, `<world>_sec.wld` or `<world>_sec.mem`.
WORLD_FILE = re.compile(r"_(?:ms\d+\.sec|sec\.(?:wld|mem))$", re.IGNORECASE)
#: The highest level number tried for a world stem `level<N>s` / `level<N>d`, and the most parts a world is tried with.
WORLD_LEVELS = 200
WORLD_PARTS = 200


def streamed_world_names(stems: Iterable[str], hashes: Iterable[int]) -> dict[int, str]:
    """Names of the streamed-world entries: the loader's format strings applied to every candidate stem.

    The world loader builds a world's names from the level record's world name (`<world>s` / `<world>d`) and three
    format strings. Each stem (the given ones, and `level<N>s` / `level<N>d` for every plausible level number) is
    tried with all of them; a name is kept when its hash is one of `hashes`. Returns hash to name.
    """
    wanted = set(hashes)
    found: dict[int, str] = {}
    candidates = {f"level{number}{kind}" for number in range(WORLD_LEVELS) for kind in "sd"}
    candidates.update(stems)
    for stem in sorted(candidates):
        for fmt in WORLD_FORMATS:
            name = fmt.format(stem)
            if name_hash(NAME_PREFIX + name) in wanted:
                found[name_hash(NAME_PREFIX + name)] = name
        for part in range(WORLD_PARTS):
            name = WORLD_PART_FORMAT.format(stem, part)
            hashed = name_hash(NAME_PREFIX + name)
            if hashed in wanted:
                found[hashed] = name
    return found


def refuse_inside_repo(path: Path) -> None:
    """Raise ConfigError when `path` lies inside a Coney checkout: game data must never land in the repository.

    Both the checkout around the working directory and the one this package was loaded from are checked.
    """
    target = path.resolve()
    for start in (Path.cwd(), Path(__file__).parent):
        try:
            root = find_repo_root(start)
        except ConfigError:
            continue
        if target.is_relative_to(root):
            raise ConfigError(
                f"{path}: is inside the repository ({root}); game data must stay outside it (see LEGAL.md). "
                "Choose a folder beside the checkout, such as ../../scratch/"
            )
