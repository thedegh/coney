# SPDX-License-Identifier: GPL-3.0-or-later
"""Read the facts of the game reference lists from the player's own disc (`coney-tools refs extract`).

Everything here reads the disc and keeps only names, ids and numbers: the configuration calls of the compiled
scripts (`CfgChar`, `CfgGang`, `CfgObj` ...), the Character List of `warriors.glr`, the animation descriptors, two
tables of the executable and the names recovered for the WAD's entries. Nothing is copied out of the disc; the
lists hold what a modder needs to name a thing.

Each `topic_*` function returns the entries of one list, in the order the page shows them. Hand-written fields are
never produced here; `refs.merge` keeps them from the YAML.

Research: docs/guides/research-workflow.md#reference-lists, docs/research/characters.md,
docs/research/formats/animation.md, docs/research/gui.md#markup, docs/research/frontend.md#input.
"""

from __future__ import annotations

import collections
import contextlib
import hashlib
import math
import re
import struct
import sys
import zlib
from collections.abc import Callable, Iterable
from functools import cached_property
from itertools import pairwise
from pathlib import Path
from typing import Any

from coney_tools import lua4, refs_engine, refs_env, refs_play, refs_scripts, refs_world, wad
from coney_tools.chunks import looks_like_container, parse_container
from coney_tools.disc import Disc
from coney_tools.elf import Elf, read_elf

# --- addresses and layouts (NTSC-U SLUS_212.15) -------------------------------------------------------------------

#: The 35 default anim slots a human starts with (docs/research/characters.md#anim-slots).
ANIM_SLOT_TABLE = 0x005105D8
ANIM_SLOTS = 35
#: The markup tag table: 66 strings of 61 bytes (docs/research/gui.md#markup).
TAG_TABLE = 0x0050D718
TAG_COUNT = 66
TAG_SIZE = 61
#: Anim ids per character data (the Character Data chunk's slot count).
ANIM_IDS = 722
#: Chunk types inside a character data resource and the Character List (docs/research/formats/wad-contents.md).
CHUNK_KEYFRAMES, CHUNK_DESCRIPTOR, CHUNK_CHARACTER_DATA, CHUNK_CHARACTER_LIST = 0x00, 0x02, 0x08, 0x44
#: The slots that hold walk, jog, run and sprint (docs/research/characters.md#speed-classes).
GAIT_SLOTS = {"walk": 4, "jog": 5, "run": 6, "sprint": 7}
#: Clips play at 30 frames a second.
FPS = 30
#: Character data resource names: `<prefix>_header`; the generic one fills every slot a character leaves unset.
GENERIC_DATA = "generic_header"
UNSET = 0xFFFFFFFF
#: The speech command table: 207 records `{u32 id, char *name}` (docs/research/sound.md#speech).
SPEECH_TABLE = 0x0050AAA8
SPEECH_COMMANDS = 207
#: The sound list chunk of `warriors.glr` (docs/research/formats/wad-contents.md).
CHUNK_STATIC_SOUNDS = 0x29

#: Our reading of the model name prefixes (the first underscore-separated part of a model name).
FACTIONS = {
    "warr": "Warriors",
    "bopp": "Boppers",
    "dest": "Destroyers",
    "fury": "Furies",
    "hiha": "Hi-Hats",
    "hurr": "Hurricanes",
    "hun": "Huns",
    "huns": "Huns",
    "jsbs": "Jones Street Boys",
    "lizz": "Lizzies",
    "moon": "Moonrunners",
    "orph": "Orphans",
    "punk": "Punks",
    "riff": "Riffs",
    "rogu": "Rogues",
    "samo": "Saracens",
    "sara": "Saracens",
    "sava": "Savage Huns",
    "turn": "Turnbull ACs",
    "civl": "civilians",
    "cops": "police",
    "cop": "police",
    "bum": "bums",
    "boss": "bosses",
}

#: The pad's button word, bit by bit (docs/research/frontend.md#input), with the glyph tag that draws each button.
BUTTONS = (
    (0x0001, "L2", "<L2>"),
    (0x0002, "R2", "<R2>"),
    (0x0004, "L1", "<L1>"),
    (0x0008, "R1", "<R1>"),
    (0x0010, "triangle", "<T>"),
    (0x0020, "circle", "<O>"),
    (0x0040, "cross", "<X>"),
    (0x0080, "square", "<S>"),
    (0x0100, "SELECT", "<SELECT>"),
    (0x0200, "L3", "<L3>"),
    (0x0400, "R3", "<R3>"),
    (0x0800, "START", "<START>"),
    (0x1000, "d-pad up", "<DU>"),
    (0x2000, "d-pad right", "<DR>"),
    (0x4000, "d-pad down", "<DD>"),
    (0x8000, "d-pad left", "<DL>"),
)

#: Script files whose global constants make up the enums list, and globals that are not constants.
ENUM_SCRIPTS = (
    "enum_preload.lua",
    "config_preload.lua",
    "config_preload2.lua",
    "config_preload3.lua",
    "global.lua",
    "rumble_preload.lua",
)
_CONSTANT = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$|^[A-Z]{2,}[0-9]*$")
_LEVEL_SCRIPT = re.compile(r"^level(\d+)")
_FILE_NAME = re.compile(r"^[\w./-]+\.[A-Za-z][A-Za-z0-9_]*$")


def _int(value: Any) -> Any:
    """A whole float as an int; anything else as it is."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _global(value: Any, prefix: str = "") -> str | None:
    """The name of a global argument (`PHYS.OBB` -> `OBB` with prefix `PHYS.`), or a plain string, or None."""
    if isinstance(value, lua4.Global):
        name = value.name
        return name[len(prefix) :] if prefix and name.startswith(prefix) else name
    if isinstance(value, str) and value != "none":
        return value
    return None


def _number(value: Any) -> int | float | None:
    """A numeric argument, or None when the walk could not know it."""
    return _int(value) if isinstance(value, float) else None


def _numbers(value: Any) -> list[Any] | None:
    """A table of numbers as a list, rounded to 6 decimals, or None."""
    if not isinstance(value, lua4.Table):
        return None
    items = [_int(round(v, 6)) if isinstance(v, float) else None for v in value.as_list()]
    return items if items and all(v is not None for v in items) else None


def _crc(name: str) -> int:
    """CRC-32 of a name, as the Character List and the resource names use it (lower case)."""
    return zlib.crc32(name.lower().encode("latin-1"))


def _note(message: str) -> None:
    """A progress line on stderr."""
    print(f"coney-tools: {message}", file=sys.stderr)


#: The font's metrics file, which no string names: its bitmap twin `cn12.bmp` is named in the executable and the
#: pair shares a stem (docs/research/gui.md#the-metrics1-file). Kept only if it hashes to an entry.
FONT_FILES = ("cn12.met",)


class DiscFacts:
    """The disc, read once and kept: the WAD's entries and names, the compiled scripts and the resources."""

    def __init__(self, disc: Disc, known_names: Iterable[str] = ()) -> None:
        """Open the disc; `known_names` are names found earlier (the WAD names list, a names file), each kept only
        when it hashes to an entry of this disc."""
        self.disc = disc
        self.entries = wad.load_entries(disc)
        self._handle = disc.open(wad.WAD_FILE)
        self._known = [*known_names, *refs_scripts.candidate_script_names(), *FONT_FILES]

    def read(self, entry: wad.WadEntry) -> bytes:
        """One entry's bytes."""
        self._handle.seek(entry.offset)
        return self._handle.read(entry.size)

    @cached_property
    def names(self) -> dict[int, str]:
        """Entry hash -> file name (without `./ee_files/`): the known names that match, then those recovered."""
        _note("recovering the WAD's entry names (a full pass over the disc)")
        hashes = {entry.hash for entry in self.entries}
        found = {key: name for key, name in wad.hash_names(self._known).items() if key in hashes}
        for key, name in wad.recover_names(self.disc, self.entries).items():
            found.setdefault(key, wad.display_name(name))
        # A CRC-32 match on a string such as "-61.622" is chance: keep names with a word-like extension only.
        named = {key: name for key, name in found.items() if _FILE_NAME.match(name)}
        # The streamed worlds' names are not strings on the disc: the loader builds them from format strings.
        # (A world's own files are not stems: `level9s_ms34` would only find chance matches.)
        stems = {name.rsplit(".", 1)[0] for name in named.values() if not wad.WORLD_FILE.search(name)}
        sorted_block = (entry.hash for entry in self.entries if entry.index >= wad.SORTED_BLOCK_START)
        for key, name in wad.streamed_world_names(stems, sorted_block).items():
            named.setdefault(key, name)
        return named

    def by_name(self, name: str) -> wad.WadEntry | None:
        """The entry a file name hashes to, if any."""
        key = wad.name_hash(wad.NAME_PREFIX + name)
        return next((entry for entry in self.entries if entry.hash == key), None)

    @cached_property
    def scripts(self) -> dict[str, lua4.ChunkFacts]:
        """Every compiled script's facts, by file name (or the hash in hex when its name is not recovered)."""
        result: dict[str, lua4.ChunkFacts] = {}
        for entry in self.entries:
            self._handle.seek(entry.offset)
            if self._handle.read(4) != lua4.HEADER[:4]:
                continue
            name = self.names.get(entry.hash, f"{entry.hash:08x}")
            try:
                result[name] = lua4.walk_chunk(lua4.parse_chunk(self.read(entry)))
            except lua4.LuaError as error:
                _note(f"skipped {name}: {error}")
        return result

    def calls(self, callee: str, script: str | None = None) -> Iterable[tuple[str, lua4.Call]]:
        """Every call of `callee` (in one script or in all), with the script's name."""
        for name, facts in self.scripts.items():
            if script is None or name == script:
                yield from ((name, call) for call in facts.calls if call.callee == callee)

    def table(self, script: str, name: str) -> lua4.Table | None:
        """The last table a script gave a global."""
        facts = self.scripts.get(script)
        return facts.tables.get(name) if facts else None

    @cached_property
    def elf(self) -> Elf:
        """The executable."""
        with self.disc.open(wad.ELF_FILE) as handle:
            return read_elf(handle.read())

    def elf_bytes(self, address: int, size: int) -> bytes:
        """`size` bytes of the executable at a virtual address."""
        for section in self.elf.sections.values():
            if section.address <= address < section.address + section.size:
                start = section.offset + address - section.address
                return self.elf.data[start : start + size]
        raise ValueError(f"0x{address:08x} is in no section")

    @cached_property
    def strings(self) -> set[str]:
        """Candidate names: every string of every script, and every recovered file name without its extension."""
        found: set[str] = set()
        for entry in self.entries:
            self._handle.seek(entry.offset)
            if self._handle.read(4) == lua4.HEADER[:4]:
                with contextlib.suppress(lua4.LuaError):  # a chunk the reader cannot parse adds no candidates
                    found.update(s for s in lua4.all_strings(lua4.parse_chunk(self.read(entry))) if s)
        found.update(name.rsplit(".", 1)[0] for name in self.names.values())
        return found

    @cached_property
    def character_list(self) -> list[tuple[int, ...]]:
        """The Character List: 32-byte records of eight words (docs/research/characters.md#files)."""
        entry = self.by_name("warriors.glr")
        if entry is None:
            raise ValueError("warriors.glr is not on the disc")
        data = self.read(entry)
        container = parse_container(data)
        if container is None:
            raise ValueError("warriors.glr is not a chunk container")
        for resource in container.resources:
            for chunk in resource.chunks:
                if chunk.type == CHUNK_CHARACTER_LIST:
                    count = struct.unpack_from("<I", data, chunk.offset)[0]
                    return [struct.unpack_from("<8I", data, chunk.offset + 16 + i * 32) for i in range(count)]
        raise ValueError("warriors.glr has no Character List")

    @cached_property
    def _animation_scan(self) -> tuple[list[Clip], dict[int, tuple[list[Clip], tuple[int, ...]]]]:
        """One streaming pass over every chunk container: the distinct clips, and each character data's clips (in
        load order) with its 722 anim slots. Only these facts are kept, never an entry's bytes."""
        _note("reading every animation (a full pass over the disc)")
        by_digest: dict[str, Clip] = {}
        character_data: dict[int, tuple[list[Clip], tuple[int, ...]]] = {}
        for entry in self.entries:
            self._handle.seek(entry.offset)
            if not looks_like_container(self._handle.read(16), entry.size):
                continue
            data = self.read(entry)
            container = parse_container(data)
            for resource in container.resources if container else []:
                table = next((c for c in resource.chunks if c.type == CHUNK_CHARACTER_DATA), None)
                loaded = []
                for first, second in pairwise(resource.chunks):
                    if first.type != CHUNK_KEYFRAMES or second.type != CHUNK_DESCRIPTOR:
                        continue
                    clip = Clip.read(data, first.offset, first.size, second.offset)
                    clip = by_digest.setdefault(clip.digest, clip)
                    clip.packs.add(entry.index)
                    (clip.data_resources if table else clip.files).add(resource.hash)
                    loaded.append(clip)
                if table is not None and resource.hash not in character_data:
                    slots = struct.unpack_from(f"<{ANIM_IDS}I", data, table.offset + 8)
                    character_data[resource.hash] = (loaded, slots)
        return sorted(by_digest.values(), key=lambda clip: (clip.name, clip.digest)), character_data

    @property
    def clips(self) -> list[Clip]:
        """Every distinct animation clip on the disc, with where it is found."""
        return self._animation_scan[0]

    @property
    def character_data(self) -> dict[int, tuple[list[Clip], tuple[int, ...]]]:
        """Character data resource hash -> its clips in load order and its 722 anim slots."""
        return self._animation_scan[1]

    def clip_for(self, data_hash: int, anim_id: int) -> Clip | None:
        """The clip a character data plays for an anim id: its own slot, else the generic one.

        Slot value n names the n-th clip counted from the last one loaded (the chunk system pops them last-in
        first-out; docs/research/formats/animation.md, "Where clips are found").
        """
        for key in (data_hash, _crc(GENERIC_DATA)):
            if key not in self.character_data:
                continue
            loaded, slots = self.character_data[key]
            slot = slots[anim_id]
            if slot != UNSET and slot < len(loaded):
                return loaded[len(loaded) - 1 - slot]
        return None

    @cached_property
    def static_sounds(self) -> set[int]:
        """The name hashes of the sound list in `warriors.glr` (chunk `0x29`: a count, then 16-byte records; the CRC-32
        of a sound's name is the last word of each 16 bytes counted from the chunk's start; docs/research/sound.md)."""
        entry = self.by_name("warriors.glr")
        data = self.read(entry) if entry else b""
        container = parse_container(data) if data else None
        for resource in container.resources if container else []:
            for chunk in resource.chunks:
                if chunk.type == CHUNK_STATIC_SOUNDS:
                    words = struct.unpack_from(f"<{chunk.size // 4}I", data, chunk.offset)
                    return set(words[3::4])
        return set()

    @cached_property
    def speech_command_names(self) -> list[str]:
        """The 207 speech command names of the executable's table (`{u32 id, char *name}`; docs/research/sound.md)."""
        names = []
        for index in range(SPEECH_COMMANDS):
            number, pointer = struct.unpack("<2I", self.elf_bytes(SPEECH_TABLE + 8 * index, 8))
            text = self.elf_bytes(pointer, 64).split(b"\0")[0].decode("latin-1")
            names.append(text if number == index else "")
        return names

    def resource_name(self, key: int) -> str | None:
        """A resource's name, recovered by hashing candidate strings (`<x>_header`, `<model>_geo` ...)."""
        return self._resource_names.get(key)

    @cached_property
    def _resource_names(self) -> dict[int, str]:
        """Hash -> name for the candidate strings and their resource forms."""
        found: dict[int, str] = {}
        for text in self.strings:
            if len(text) > 64 or not re.match(r"^[\w/.-]+$", text):
                continue
            base = text.lower()
            stems = {base}
            parts = base.split("_")
            stems.update("_".join(parts[:k]) for k in range(1, len(parts)))
            for stem in stems:
                for name in (stem, f"{stem}_header", f"{stem}_geo", f"{stem}_tex", f"{stem}_a"):
                    found.setdefault(_crc(name), name)
        return found


class Clip:
    """One distinct clip: its descriptor's facts and where it is found."""

    def __init__(self, name: str, duration: float, dx: float, dy: float, events: int, digest: str) -> None:
        self.name = name
        self.duration = duration
        self.distance = (dx * dx + dy * dy) ** 0.5
        self.events = events
        self.digest = digest
        self.packs: set[int] = set()
        self.data_resources: set[int] = set()
        self.files: set[int] = set()

    @classmethod
    def read(cls, data: bytes, keys_at: int, keys_size: int, descriptor_at: int) -> Clip:
        """A clip from its keyframe chunk and its 80-byte descriptor (docs/research/formats/animation.md)."""
        descriptor = data[descriptor_at : descriptor_at + 80]
        dx, dy, duration = struct.unpack_from("<3f", descriptor, 4)
        events = struct.unpack_from("<H", descriptor, 0x1A)[0]
        name = descriptor[0x25:0x43].split(b"\0")[0].decode("latin-1")
        # Identity: the keys and the descriptor, without the descriptor's load-time pointers.
        digest = hashlib.sha1(data[keys_at : keys_at + keys_size] + descriptor[4:0x1C] + descriptor[0x20:]).hexdigest()
        return cls(name, duration, dx, dy, events, digest)

    def speed(self) -> float:
        """Horizontal root displacement over playing time, m/s (0 for a clip of no length)."""
        return self.distance / self.duration if self.duration > 0 else 0.0


# --- topics ------------------------------------------------------------------------------------------------------


def _cfg_chars(facts: DiscFacts) -> list[list[Any]]:
    """The arguments of every `CfgChar` call, in order."""
    return [call.args for _, call in facts.calls("CfgChar", "config_preload2.lua")]


def _model_records(facts: DiscFacts) -> dict[int, tuple[int, ...]]:
    """Character List records by model-name CRC."""
    return {record[0]: record for record in facts.character_list}


def _hu_creates(facts: DiscFacts) -> tuple[dict[int, collections.Counter[str]], dict[int, set[int]]]:
    """Per character type: the names scripts give its humans, and the level numbers that create one."""
    names: dict[int, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    levels: dict[int, set[int]] = collections.defaultdict(set)
    for script, call in facts.calls("HuCreate"):
        if len(call.args) < 2 or not isinstance(call.args[1], float):
            continue
        kind = int(call.args[1])
        if isinstance(call.args[0], str):
            names[kind][call.args[0]] += 1
        match = _LEVEL_SCRIPT.match(script)
        if match:
            levels[kind].add(int(match.group(1)))
    return names, levels


def _image(images: Path | None, folder: str, *names: str | None) -> str | None:
    """`<folder>/<name>.png` for the first name whose thumbnail exists below images/, else None."""
    for name in names:
        if images is not None and name and (images / folder / f"{name}.png").is_file():
            return f"{folder}/{name}.png"
    return None


def topic_characters(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Character types, from `CfgChar`, the Character List, the clips and every `HuCreate`."""
    records = _model_records(facts)
    created, levels = _hu_creates(facts)
    entries = []
    for args in _cfg_chars(facts):
        kind = int(args[0])
        model = args[9] if isinstance(args[9], str) else None
        record = records.get(_crc(model)) if model else None
        speeds = None
        if record is not None:
            clips = {gait: facts.clip_for(record[1], _anim_slots(facts)[slot]) for gait, slot in GAIT_SLOTS.items()}
            speeds = {gait: round(clip.speed(), 3) for gait, clip in clips.items() if clip is not None} or None
        entries.append(
            {
                "id": kind,
                "model": model,
                "armies_model": f"{model}_a" if model and _crc(f"{model}_a") in records else None,
                "faction": FACTIONS.get(model.split("_")[0]) if model else None,
                "behaviour": _number(args[1]),
                "category": _number(args[2]),
                "speed_class": _number(args[3]),
                "v11d": _number(args[4]),
                "health": _number(args[5]),
                "damage_table": _global(args[6]),
                "attack_table": _global(args[7]),
                "damage_scale": _number(args[8]),
                "hat": _global(args[10]),
                "voice": _number(args[11]),
                "flag_14b": _number(args[12]),
                "range_table": _global(args[13]),
                "drop_group": _global(args[14]),
                "drop_chance": _number(args[15]),
                "weapon": _global(args[16]),
                "speeds": speeds,
                "script_names": [name for name, _ in created[kind].most_common(8)] or None,
                "levels": sorted(levels[kind]) or None,
                "image": _image(images, "characters", model),
            }
        )
    return sorted(entries, key=lambda entry: entry["id"])


def _anim_slots(facts: DiscFacts) -> tuple[int, ...]:
    """The 35 default anim slots from the executable."""
    return struct.unpack(f"<{ANIM_SLOTS}I", facts.elf_bytes(ANIM_SLOT_TABLE, 4 * ANIM_SLOTS))


def topic_character_models(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Every Character List record, with the names recovered for it and the types that use it."""
    types: dict[int, list[int]] = collections.defaultdict(list)
    candidates: dict[int, str] = {}
    for args in _cfg_chars(facts):
        if isinstance(args[9], str):
            types[_crc(args[9])].append(int(args[0]))
            candidates[_crc(args[9])] = args[9].lower()
            candidates[_crc(args[9] + "_a")] = args[9].lower() + "_a"
    entries = []
    for index, record in enumerate(facts.character_list):
        name = candidates.get(record[0]) or facts.resource_name(record[0])
        entries.append(
            {
                "index": index,
                "crc": record[0],
                "name": name,
                "data": facts.resource_name(record[1]),
                "data_crc": record[1],
                "geo_crc": record[2],
                "tex_crc": record[3],
                "data_size": record[4],
                "geo_size": record[5],
                "tex_size": record[7],
                "types": sorted(types.get(record[0], [])) or None,
                # The renderer names an image after the model, or after its hash when it has no name.
                "image": _image(images, "characters", name, f"{record[0]:08x}"),
            }
        )
    return sorted(entries, key=lambda entry: (entry["name"] is None, entry["name"] or "", entry["index"]))


def topic_gangs(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Gang types, from `CfgGang`, the strategy tables, `CfgGangMusic` and every `GangCreate`."""
    music = {
        int(call.args[0]): [t for t in call.args[1].as_list() if isinstance(t, str)]
        for _, call in facts.calls("CfgGangMusic")
        if call.args and isinstance(call.args[0], float) and isinstance(call.args[1], lua4.Table)
    }
    names: dict[int, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for _, call in facts.calls("GangCreate"):
        if len(call.args) > 1 and isinstance(call.args[0], float) and isinstance(call.args[1], str):
            names[int(call.args[0])][call.args[1]] += 1
    entries = []
    for _, call in facts.calls("CfgGang", "config_preload2.lua"):
        args = call.args
        if not isinstance(args[0], float):
            continue
        kind = int(args[0])
        strategy = _global(args[5])
        table = facts.table("config_preload2.lua", strategy) if strategy else None
        entries.append(
            {
                "id": kind,
                "strategy": strategy,
                "strategy_values": _numbers(table),
                # CfgGang(id, v2, v3, v4, v5, strategy, v7, v8, v9): the arguments by position.
                "v2": _number(args[1]),
                "v3": _number(args[2]),
                "v4": _number(args[3]),
                "v5": _number(args[4]),
                "v7": _number(args[6]),
                "v8": _number(args[7]),
                "v9": _number(args[8]),
                "music": music.get(kind),
                "script_names": [name for name, _ in names[kind].most_common(8)] or None,
            }
        )
    return sorted(entries, key=lambda entry: entry["id"])


def topic_speed_classes(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Speed classes, from `CfgSpeedClass`, and how many character types name each."""
    counts = collections.Counter(int(args[3]) for args in _cfg_chars(facts) if isinstance(args[3], float))
    entries = []
    for _, call in facts.calls("CfgSpeedClass", "config_preload2.lua"):
        values = _numbers(call.args[1]) or []
        values += [None] * (6 - len(values))
        if not isinstance(call.args[0], float):
            continue
        kind = int(call.args[0])
        entries.append(
            dict(zip(("id", "base", "v04", "walk", "jog", "run", "sprint"), [kind, *values[:6]], strict=True))
            | {"types": counts.get(kind)}
        )
    return sorted(entries, key=lambda entry: entry["id"])


#: How object classes are grouped on the page, by class name; anything else is "other".
OBJECT_CATEGORIES = (
    ("weapons", ("melee_weapon", "overhead_weapon", "thrown_weapon")),
    ("hats and masks", ("hat_object", "dyn_masks")),
    ("pick-ups and power-ups", ("pickup_item", "powerup_item", "dyn_pile", "dyn_icon", "dyn_objective")),
    ("doors", ("dyn_door_swinging", "dyn_door_sliding", "sub_swinging_door", "sub_sliding_door")),
    ("props", ("simple_object", "fade_object", "rotating_object", "dyn_table", "dyn_blocker", "dyn_lizzies")),
)


def topic_objects(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Object types, from every `CfgObj` (22 arguments)."""
    category = {cls: group for group, classes in OBJECT_CATEGORIES for cls in classes}
    seen: dict[str, dict[str, Any]] = {}
    for script, call in facts.calls("CfgObj"):
        args = call.args
        if len(args) < 20 or not isinstance(args[0], str) or args[0] in seen:
            continue
        object_type = _global(args[18], "OBJECT.")
        seen[args[0]] = {
            "name": args[0],
            "category": category.get(str(args[1]), "other"),
            "class": _global(args[1]),
            "type": object_type,
            "shape": _global(args[8], "PHYS."),
            "axis": _global(args[9], "AXIS."),
            "size": _numbers(args[7]),
            "mass": _number(args[10]),
            "material": _global(args[12], "MATERIAL."),
            "pickup_anim": _global(args[13], "ANIM."),
            "anim_set": _global(args[19], "ANIM."),
            "script": script,
            "image": _image(images, "objects", args[0]),
        }
    order = [group for group, _ in OBJECT_CATEGORIES] + ["other"]
    return sorted(seen.values(), key=lambda entry: (order.index(entry["category"]), entry["name"]))


def topic_object_groups(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Object groups: the names `CfgChar` gives as a drop group, and any `CfgObjectGroup` definitions."""
    defined = {call.args[0] for _, call in facts.calls("CfgObjectGroup") if call.args and isinstance(call.args[0], str)}
    users: dict[str, list[int]] = collections.defaultdict(list)
    for args in _cfg_chars(facts):
        group = _global(args[14])
        if group:
            users[group].append(int(args[0]))
    return [
        {"name": name, "defined": name in defined, "referenced_by": sorted(users.get(name, [])) or None}
        for name in sorted(set(users) | defined)
    ]


def _mission_titles(facts: DiscFacts) -> dict[str, str]:
    """Level script name -> mission title, from `GSTRING.MISSIONNAME` of the English string file.

    Only the title strings are read (names that identify a level, `LEGAL.md`'s reference-list exception); a level
    whose entry is empty (the hub) has none.
    """
    table = facts.table("config_strings_en.lua", "GSTRING")
    names = table.fields.get("MISSIONNAME") if table else None
    if not isinstance(names, lua4.Table):
        return {}
    return {str(k): v for k, v in names.fields.items() if isinstance(v, str) and v.strip()}


def topic_levels(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Level records, from `config_preload3.lua`'s `levelNames`, with what the disc holds for each."""
    table = facts.table("config_preload3.lua", "levelNames")
    rows = table.as_list() if table else []
    titles = _mission_titles(facts)
    files = set(facts.names.values())
    entries = []
    for index, row in enumerate(rows):
        if not isinstance(row, lua4.Table):
            continue
        values = row.as_list()
        name = values[0] if isinstance(values[0], str) else None
        packs = sum(1 for f in files if name and re.fullmatch(rf"{re.escape(name)}_\d+\.pak", f))
        entries.append(
            {
                "index": index,
                "name": name,
                "world": values[1] if isinstance(values[1], str) else None,
                "number": _number(values[2]),
                "title": titles.get(name or ""),
                "sections": _number(values[3]),
                "order": _number(values[4]),
                "flag1": _global(values[5]),
                "intro": _global(values[6]),
                "outro": _global(values[7]),
                "lock": _global(values[8]),
                "map": [_int(round(v, 4)) for v in values[9:12] if isinstance(v, float)] or None,
                "v78": _number(values[12]),
                "subway": _global(values[13]),
                "v80": _number(values[14]),
                "has_lev": bool(name and f"{name}.lev" in files),
                "packs": packs,
            }
        )
    return entries


#: A story level's main script, and a Rumble arena's per-mode flag script (`level<N>_<mode>_init.lua`).
_LEVEL_MAIN = re.compile(r"^level(\d+)\.lua$")
_RUMBLE_INIT = re.compile(r"^level(\d+)_([a-z0-9]+)_init\.lua$", re.IGNORECASE)
#: Tables a level script keeps its per-checkpoint scripts in: `tMission[k][3]` or `Mission[k]` / `Chapter[k]`.
_CHAPTER_TABLES = ("Mission", "Chapter", "tChapters")
#: The flag list a Rumble arena puts player 1 on the first of (`fP1[1]`, docs/research/characters.md#level-starts).
RUMBLE_PLAYER_FLAGS = "fP1"


def _player_creates(facts: lua4.ChunkFacts) -> dict[str, lua4.Call]:
    """Function path -> its first `HuCreate` for player 1 (sixth argument 1) at a literal position."""
    found: dict[str, lua4.Call] = {}
    for call in facts.calls:
        if call.callee != "HuCreate" or len(call.args) < 6 or call.args[5] != 1.0:
            continue
        pos = call.args[2]
        if isinstance(pos, lua4.Table) and len(_numbers(pos) or []) == 3 and isinstance(call.args[3], float):
            found.setdefault(call.path, call)
    return found


def _checkpoint_creators(facts: lua4.ChunkFacts, creators: set[str]) -> dict[int, str]:
    """Checkpoint -> the function that creates the Warriors for it.

    A level script indexes a list by `GetCheckPoint()` and calls the entry: either the function itself
    (`PlayerGang = {AddWarriors1, ...}`) or a row whose first item is it (`tMission = {{AddWarriors2,
    "Checkpoint1", "level99_combat"}, ...}`). The list is the one, global or local, naming the most creators.
    """
    best: dict[int, str] = {}
    for table in [*facts.tables.values(), *(table for _, table in facts.constructed)]:
        found = {}
        for key, item in table.items.items():
            head = item.items.get(1) if isinstance(item, lua4.Table) else item
            if isinstance(head, lua4.Global) and head.name in creators:
                found[key] = head.name
        if len(found) > len(best):
            best = found
    return best


def _chapter_scripts(facts: lua4.ChunkFacts) -> dict[int, str]:
    """Checkpoint -> the script it loads (`preLoadFile`), from `tMission[k][3]` or a `Mission` / `Chapter` list."""
    scripts: dict[int, str] = {}
    mission = facts.tables.get("tMission")
    if mission is not None:
        for key, row in mission.items.items():
            if isinstance(row, lua4.Table) and isinstance(row.items.get(3), str):
                scripts[key] = str(row.items[3])
    for name in _CHAPTER_TABLES:
        table = facts.tables.get(name)
        if table is not None:
            for key, item in table.items.items():
                if isinstance(item, str):
                    scripts.setdefault(key, item)
    return scripts


def level_starts(scripts: dict[str, lua4.ChunkFacts]) -> list[dict[str, Any]]:
    """Where each level puts player 1: per checkpoint of a story level, and per mode of a Rumble arena."""
    entries: list[dict[str, Any]] = []
    for script, facts in scripts.items():
        match = _LEVEL_MAIN.match(script)
        if not match:
            continue
        level = f"level{match.group(1)}"
        functions = facts.functions()
        creates = _player_creates(facts)
        creators = {name for name, path in functions.items() if path in creates}
        chapters = _chapter_scripts(facts)
        for checkpoint, creator in sorted(_checkpoint_creators(facts, creators).items()):
            call = creates[functions[creator]]
            entries.append(
                {
                    "id": f"{level}-{checkpoint}",
                    "level": level,
                    "checkpoint": checkpoint,
                    "character": call.args[0] if isinstance(call.args[0], str) else None,
                    "type": _int(call.args[1]) if isinstance(call.args[1], float) else None,
                    "pos": [_int(round(v, 4)) for v in _numbers(call.args[2]) or []],
                    "heading": _int(call.args[3]),
                    "via": f"HuCreate in {creator}",
                    "script": chapters.get(checkpoint),
                }
            )
    for script, facts in scripts.items():
        match = _RUMBLE_INIT.match(script)
        flags = facts.tables.get(RUMBLE_PLAYER_FLAGS)
        if match is None or flags is None:
            continue
        flag = flags.items.get(1)
        if not isinstance(flag, lua4.CallResult) or flag.callee != "AddFlag" or len(flag.args) < 3:
            continue
        entries.append(
            {
                "id": f"level{match.group(1)}-{match.group(2).lower()}",
                "level": f"level{match.group(1)}",
                "mode": match.group(2).lower(),
                "pos": [_int(round(v, 4)) for v in _numbers(flag.args[1]) or []],
                "heading": _number(flag.args[2]),
                "via": f"flag {flag.args[0]}" if isinstance(flag.args[0], str) else "flag",
                "script": script.removesuffix(".lua"),
            }
        )
    return sorted(entries, key=lambda e: (int(e["level"][5:]), e.get("checkpoint") or 0, e.get("mode") or ""))


def topic_level_starts(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Player 1's start per level and checkpoint (story) or mode (Rumble), from the level scripts."""
    return level_starts(facts.scripts)


def topic_animations(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Every distinct clip on the disc, with its length, its displacement and where it is found."""
    seen: collections.Counter[str] = collections.Counter()
    entries = []
    for clip in facts.clips:
        seen[clip.name] += 1
        data = sorted(facts.resource_name(h) or f"{h:08x}" for h in clip.data_resources)
        files = sorted(facts.resource_name(h) or f"{h:08x}" for h in clip.files)
        entries.append(
            {
                "id": clip.name if seen[clip.name] == 1 else f"{clip.name}#{seen[clip.name]}",
                "frames": round(clip.duration * FPS),
                "duration": round(clip.duration, 4),
                "distance": round(clip.distance, 4),
                "events": clip.events,
                "characters": data[:6] + ([f"... {len(data) - 6} more"] if len(data) > 6 else []) or None,
                "files": files or None,
                "packs": len(clip.packs),
            }
        )
    return entries


def topic_anim_ids(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """The 722 anim ids: their script names, default slots and the generic and Rembrandt clips."""
    names: dict[int, str] = {}
    facts_royal = facts.scripts.get("royal.lua")
    for assignment in facts_royal.assignments if facts_royal else []:
        if assignment.name.startswith("ANIM_") and isinstance(assignment.value, float):
            names.setdefault(int(assignment.value), assignment.name)
    slots = {anim: slot for slot, anim in reversed(list(enumerate(_anim_slots(facts))))}
    rembrandt = _model_records(facts).get(_crc("warr_re_cv"))
    entries = []
    for anim in range(ANIM_IDS):
        generic = facts.clip_for(_crc(GENERIC_DATA), anim)
        own = facts.clip_for(rembrandt[1], anim) if rembrandt else None
        entries.append(
            {
                "id": anim,
                "name": names.get(anim),
                "slot": slots.get(anim) if anim else None,
                "generic": generic.name if generic else None,
                "rembrandt": own.name if own and own is not generic else None,
            }
        )
    return entries


def topic_controls(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """The pad's buttons and sticks: the button word's bits and the glyph tags that draw them."""
    entries: list[dict[str, Any]] = [
        {"id": f"pad-{name.replace(' ', '-').lower()}", "context": "pad", "input": name, "bit": bit, "glyph": glyph}
        for bit, name, glyph in BUTTONS
    ]
    entries += [
        {"id": "pad-left-stick", "context": "pad", "input": "left stick", "glyph": "<LAS>"},
        {"id": "pad-right-stick", "context": "pad", "input": "right stick", "glyph": "<RAS>"},
    ]
    return entries


def topic_hud_colours(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """The colour table `CL` and the HUD slots `CfgHUDColor` gives its colours."""
    table = facts.table("config_preload2.lua", "CL") or facts.table("global.lua", "CL")
    slots = {
        _global(call.args[1], "CL."): int(call.args[0])
        for _, call in facts.calls("CfgHUDColor")
        if len(call.args) > 1 and isinstance(call.args[0], float)
    }
    entries = []
    for key, value in table.fields.items() if table else []:
        rgba = None
        markup = None
        if isinstance(value, str):
            match = re.search(r"<COLOR ([0-9A-Fa-f]{8})>", value)
            rgba = match.group(1).upper() if match else None
            markup = value
        elif isinstance(value, lua4.Table):
            numbers = _numbers(value)
            if numbers and len(numbers) == 4:
                rgba = "".join(f"{int(v):02X}" for v in numbers)
                markup = str(numbers)
        entries.append(
            {"id": str(key), "rgba": rgba, "swatch": rgba, "markup": markup, "hud_slot": slots.get(str(key))}
        )
    return entries


def topic_text_formatting(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """The 66 markup tags of the executable's tag table, with the glyph characters of the button tags."""
    data = facts.elf_bytes(TAG_TABLE, TAG_COUNT * TAG_SIZE)
    tags = [data[i * TAG_SIZE : (i + 1) * TAG_SIZE].split(b"\0")[0].decode("latin-1") for i in range(TAG_COUNT)]
    # The glyph characters of tags 33-49 (docs/research/gui.md#markup, read from the code).
    glyphs = (0x9F, 0x9D, 0x96, ord("n"), 0x9E, 0x97, 0x93, 0x9C, 0x94, 0x92, 0xA0, 0x95, 0x91, 0x9B, 0x99, 0x9A, 0x98)
    return [
        {"index": index, "tag": tag, "char": glyphs[index - 33] if 33 <= index < 33 + len(glyphs) else None}
        for index, tag in enumerate(tags)
    ]


def _plain_constant(value: Any) -> Any:
    """A constant's value for the list: numbers and strings as they are, anything else skipped (None)."""
    if isinstance(value, float):
        return _int(round(value, 6))
    if isinstance(value, str) and len(value) <= 40:
        return value
    return None


def topic_enums(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Constant tables (`MATERIAL.GLASS`) and loose constants (`LT_PLAY`) the preloads and global.lua define."""
    entries: dict[str, dict[str, Any]] = {}
    for script in ENUM_SCRIPTS:
        chunk = facts.scripts.get(script)
        if chunk is None:
            continue
        for name, table in chunk.tables.items():
            if not _CONSTANT.match(name) or name in ("CL", "ANIM", "GSTRING", "LABEL") or not table.fields:
                continue
            values = {str(k): _plain_constant(v) for k, v in table.fields.items()}
            if not all(isinstance(v, (int, float)) for v in values.values()):
                continue
            for key, value in sorted(values.items(), key=lambda kv: (kv[1], kv[0])):
                entries.setdefault(
                    f"{name}.{key}",
                    {"id": f"{name}.{key}", "enum": name, "name": key, "value": value, "script": script},
                )
        for assignment in chunk.assignments:
            value = _plain_constant(assignment.value)
            if not _CONSTANT.match(assignment.name) or not isinstance(value, (int, float)):
                continue
            prefix = assignment.name.split("_")[0] if "_" in assignment.name else "other"
            entries.setdefault(
                assignment.name,
                {
                    "id": assignment.name,
                    "enum": f"{prefix}_*",
                    "name": assignment.name,
                    "value": value,
                    "script": script,
                },
            )
    return sorted(
        entries.values(),
        key=lambda e: (e["enum"], e["value"] if isinstance(e["value"], (int, float)) else 0, e["name"]),
    )


def topic_sound(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Music tracks, interface sounds, sound matrices and inventory sounds the scripts configure."""
    entries: dict[str, dict[str, Any]] = {}
    played: dict[str, set[str]] = collections.defaultdict(set)
    for callee in ("SoundPlayMusicTrack", "SoundLoopMusicTrack"):
        for script, call in facts.calls(callee):
            if call.args and isinstance(call.args[0], str):
                played[call.args[0]].add(script)
    for _, call in facts.calls("SndCfgMusicInfo"):
        if call.args and isinstance(call.args[0], str):
            entries.setdefault(
                f"music:{call.args[0]}",
                {
                    "id": f"music:{call.args[0]}",
                    "kind": "music track",
                    "name": call.args[0],
                    "values": [_number(v) for v in call.args[1:]] or None,
                    "used_by": sorted(played.get(call.args[0], set()))[:8] or None,
                },
            )
    for _, call in facts.calls("SoundCfgInterfaceSound"):
        if len(call.args) > 1 and isinstance(call.args[0], float) and isinstance(call.args[1], str):
            key = f"interface:{int(call.args[0])}"
            entries.setdefault(
                key, {"id": key, "kind": "interface sound", "name": call.args[1], "number": int(call.args[0])}
            )
    for script, call in facts.calls("SndLoadMatrix"):
        if call.args and isinstance(call.args[0], str):
            key = f"matrix:{call.args[0]}"
            entries.setdefault(key, {"id": key, "kind": "sound matrix", "name": call.args[0], "used_by": []})
            entries[key]["used_by"] = sorted({*entries[key]["used_by"], script})
    for _, call in facts.calls("CfgInventoryItem"):
        args = call.args
        if len(args) > 4 and isinstance(args[1], float) and isinstance(args[3], str):
            key = f"inventory:{int(args[1])}"
            entries.setdefault(
                key,
                {
                    "id": key,
                    "kind": "inventory item",
                    "name": args[3],
                    "number": int(args[1]),
                    "values": [_number(args[2]), _number(args[4])],
                    "used_by": [args[0]] if isinstance(args[0], str) else None,
                },
            )
    order = ("music track", "interface sound", "sound matrix", "inventory item")
    configured = sorted(entries.values(), key=lambda e: (order.index(e["kind"]), e.get("number") or 0, e["name"]))
    sounds = facts.static_sounds
    named = refs_scripts.sound_names(facts.scripts, lambda name: zlib.crc32(name.encode("latin-1")) in sounds)
    return configured + [e for e in named if e["id"] not in entries]


def topic_script_events(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Message numbers `SetMsgHandler` and `GangSetMsgHandler` register callbacks for, with the commonest names."""
    handlers, clears = refs_scripts.message_handlers(facts.scripts, "SetMsgHandler")
    gang, gang_clears = refs_scripts.message_handlers(facts.scripts, "GangSetMsgHandler")
    return [
        {
            "id": message,
            "handlers": sum(handlers[message].values()),
            "clears": clears[message],
            "examples": [name for name, _ in handlers[message].most_common(5) if name != "?"] or None,
            "gang_handlers": sum(gang[message].values()) or None,
            "gang_clears": gang_clears[message] or None,
            "gang_examples": [name for name, _ in gang[message].most_common(5) if name != "?"] or None,
        }
        for message in sorted(set(handlers) | set(clears) | set(gang) | set(gang_clears))
    ]


def topic_text_labels(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """The keys of the scripts' string tables (never their text), with where each is defined and used."""
    return refs_scripts.text_labels(facts.scripts)


def topic_commands(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """`AddCommand`'s trigger kinds, the pad commands `global.lua` binds, and the Warrior commands."""
    return refs_scripts.commands(facts.scripts, BUTTONS)


def topic_speech(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """The speech commands and the voice sets, with the lines each voice set has for each command."""
    counts = [call.args[0] for _, call in facts.calls("SndAllocateCharacterVoices") if call.args]
    voices = int(counts[0]) if counts and isinstance(counts[0], float) else 0
    sounds = facts.static_sounds
    names = facts.speech_command_names
    lines = refs_scripts.voice_lines(voices, names, lambda name: zlib.crc32(name.encode("latin-1")) in sounds)
    voice_types: dict[int, list[int]] = collections.defaultdict(list)
    for args in _cfg_chars(facts):
        if isinstance(args[11], float):
            voice_types[int(args[11])].append(int(args[0]))
    return refs_scripts.speech(facts.scripts, names, lines, voice_types)


def topic_wad_names(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Every WAD entry whose name was recovered, grouped by the name's extension."""
    names = dict(facts.names)
    # The level records name their worlds; the loader derives each world's files from that name.
    table = facts.table("config_preload3.lua", "levelNames")
    rows = [row.as_list() for row in (table.as_list() if table else []) if isinstance(row, lua4.Table)]
    stems = {f"{row[1]}{kind}" for row in rows if isinstance(row[1], str) for kind in "sd"}
    sorted_block = (entry.hash for entry in facts.entries if entry.index >= wad.SORTED_BLOCK_START)
    for key, world_name in wad.streamed_world_names(stems, sorted_block).items():
        names.setdefault(key, world_name)
    entries = []
    for entry in facts.entries:
        name = names.get(entry.hash)
        if name is None:
            continue
        kind = name.rsplit(".", 1)[1].lower() if "." in name else "no extension"
        entries.append({"crc": entry.hash, "name": name, "kind": kind, "index": entry.index})
    return sorted(entries, key=lambda e: (e["kind"], e["name"]))


# --- sprite sheets, radar icons, particle types and cars ----------------------------------------------------------

#: Sprite-sheet names whose CRC-32 names a record of the sheet table (chunk 0x4D); the others show as a hash.
SHEET_NAMES = (
    "part_page0",
    "part_page1",
    "menu_system",
    "part_tv",
    "part_fire",
    "lighting",
    "hud_minigames",
    "big_font",
    "glass",
    "legal_screen",
)
#: The radar draws its blips from sheet record 0 (docs/research/gui.md#radar-icons).
RADAR_SHEET = 0
#: Icons the code itself sets (docs/research/gui.md#radar-icons): icon -> (where, forced scale, forced tint).
RADAR_CODE_ICONS: dict[int, tuple[str, float | None, str | None]] = {
    22: ("`HUD_RadarSetIcon` draws it at 0.7", 0.7, None),
    29: ("dealer type 0's blip (`0x002c7ee0`); `HUD_RadarSetIcon` tints it", 0.8, "63DB4BFF"),
    30: ("dealer type 2's blip (`0x002c7ee0`); `HUD_RadarSetIcon` tints it", 0.8, "63DB4BFF"),
    31: ("dealer type 1's blip (`0x002c7ee0`); `HUD_RadarSetIcon` tints it", 0.8, "63DB4BFF"),
    32: ("blip mode 3's ring, layer 1 (`0x001b32e0`)", 0.75, None),
    33: ("blip mode 4's ring, layer 1 (`0x001b32e0`)", 0.75, None),
    69: ("every particle blip's first icon (`hud_radar_dot`, `0x003e5bf8`)", None, None),
    352: ("blip type 6, layer 0; blip modes 1 and 2 (`0x001b2990`, `0x001b32e0`)", None, None),
    353: ("blip modes 3 and 4, layer 0 (`0x001b32e0`)", 0.8, None),
    356: ("blip type 8, both layers (`HUD_RadarAddHuman`)", None, None),
    359: ("blip type 6, layer 1 (`0x001b2990`)", None, None),
    362: ("blip type 9, a sprite widget (`0x001b2ee8`, `0x001c4d00`)", None, None),
    365: ("blip type 7 (`0x001b2ee8`)", None, None),
}
#: The blip types of the radar's add function `0x001c4d00` (docs/research/gui.md#radar-icons):
#: type -> (sprite batch, first icon, colour or None, who adds it).
RADAR_BLIP_TYPES: dict[int, tuple[str, int, str | None, str]] = {
    1: (
        "`+0x50` (32 sprites)",
        69,
        None,
        "`HUDAddSecondaryRadarMissionObjective`; `HUDAddRadarObject` with its colour",
    ),
    2: ("`+0x58` (32 sprites)", 69, None, "a dealer of type 0 (`0x002c7ee0`)"),
    3: ("`+0x54` (32 sprites)", 69, None, "a dealer of type 2 (`0x002c7ee0`)"),
    4: ("`+0x50` (32 sprites)", 69, None, "a dealer of type 1 (`0x002c7ee0`)"),
    5: ("none: `0x001b2990` adds nothing", 69, None, "`Human_Init`; `HUD_RadarAddHuman` for class 4 (civilians)"),
    6: (
        "`+0x5c` / `+0x60` by layer (96 sprites)",
        352,
        None,
        "`HUD_RadarAddHuman` for classes 2, 5, 6; the AI when a human turns on the player",
    ),
    7: ("`+0x5c` / `+0x60` by layer (96 sprites)", 365, None, "`HUD_RadarAddHuman`: class 0 or 3, not the player"),
    8: ("`+0x5c` / `+0x60` by layer (96 sprites)", 356, None, "`HUD_RadarAddHuman` for class 1 (police)"),
    9: ("a sprite widget, not a particle", 362, "787878FF", "`HUD_RadarAddHuman`: class 0 or 3, the player"),
    10: ("`+0x4c` (16 sprites)", 69, None, "`HUDAddRadarMissionObjective`"),
}
#: The script type table: 270 records of {name, init, update, message handler, flags} (docs/research/particles.md).
SCRIPT_TYPES = 0x00512F28
SCRIPT_TYPE_COUNT = 270
SCRIPT_TYPE_KINDS = ((0x400, "glass"), (0x10, "particle system"), (0x08, "object behaviour"), (0x04, "light"))
#: The sprite each traced particle type draws first: name -> (sheet record, rectangle) (docs/research/particles.md).
PARTICLE_SPRITES: dict[str, tuple[int, int]] = {
    "blo_splat": (1, 5),
    "blood_drop": (1, 52),
    "blood_spray": (1, 52),
    "bloosh": (1, 46),
    "coplights_glow": (8, 2),
    "coplights_lens_flare": (8, 2),
    "hud_radar_dot": (0, 69),
    "part_copcar_lights": (8, 2),
    "part_explosion": (1, 6),
    "part_fire": (7, 0),
    "part_fire_large": (7, 0),
    "part_fire_large_ns": (7, 0),
    "part_fire_ns": (7, 0),
    "part_fire_plume": (9, 0),
    "part_fire_tiki": (7, 0),
    "part_firebarrel": (7, 0),
    "part_firebarrel_ns": (7, 0),
    "part_firetruck_lights": (8, 2),
    "part_gun_flash": (8, 2),
    "part_narrowflame": (27, 0),
    "part_s_fire": (7, 0),
    "part_s_subway_sparks": (1, 54),
    "part_squareflame_lrg": (27, 0),
    "part_squareflame_med": (27, 0),
    "part_squareflame_sml": (27, 0),
    "part_torch_flame": (7, 0),
    "part_torch_flame_ns": (7, 0),
    "part_train_splat": (1, 6),
    "part_tv": (4, 0),
    "part_urine_stain2": (1, 6),
    "spark": (1, 41),
    "sub_anim_spark": (1, 50),
    "sub_barlamp_glow": (8, 3),
    "sub_blight_glow": (8, 3),
    "sub_blood_gout": (1, 2),
    "sub_blood_spray": (1, 6),
    "sub_car_rubble": (1, 24),
    "sub_car_sparks": (1, 45),
    "sub_embers": (1, 20),
    "sub_explode": (1, 17),
    "sub_fade_flame": (7, 0),
    "sub_fire_smoke": (1, 42),
    "sub_flame_reflect": (7, 0),
    "sub_flaming_debris": (7, 0),
    "sub_glint": (1, 41),
    "sub_muzzle_flash": (1, 35),
    "sub_objective_glow": (8, 3),
    "sub_polar_bugs": (1, 19),
    "sub_powerup_glow": (1, 29),
    "sub_shack_puff": (1, 42),
    "sub_shack_puff_aligned": (1, 42),
    "sub_splash": (1, 51),
    "sub_thrown_dust_puff": (1, 42),
    "sub_train_splat": (1, 2),
    "sub_train_splat_mist": (1, 6),
    "subway_lensflare": (409, 0),
    "subway_spark": (1, 54),
    "urine_spray": (1, 54),
}
#: Types each type's code spawns by name (inferred from its calls; docs/research/particles.md#spawning).
PARTICLE_SPAWNS: dict[str, tuple[str, ...]] = {
    "dyn_blaster": ("sub_debris", "sub_rubble", "sub_shack_puff", "sub_spark_effect", "sub_wood_splinter"),
    "dyn_breakable_light": ("sub_rubble", "sub_shack_puff", "sub_spark_effect"),
    "dyn_cbradio": ("sub_rubble", "sub_shack_puff", "sub_spark_effect"),
    "dyn_chicken": ("sub_debris", "sub_wood_splinter"),
    "dyn_ctrl_box": ("sub_rubble", "sub_shack_puff", "sub_spark_effect"),
    "dyn_door_bar_bani": ("sub_shack_puff", "sub_wood_splinter"),
    "dyn_door_bnstr": ("sub_shack_puff", "sub_wood_splinter"),
    "dyn_door_fence": ("sub_shack_puff", "sub_wood_splinter"),
    "dyn_door_fence_o": ("sub_shack_puff", "sub_wood_splinter"),
    "dyn_door_parapet": ("sub_shack_puff", "sub_wood_splinter"),
    "dyn_door_swinging": ("sub_glass", "sub_shack_puff", "sub_wood_splinter"),
    "dyn_lizzies": ("sub_shack_puff", "sub_wood_splinter"),
    "dyn_masks": ("sub_detergent", "sub_rubble", "sub_shack_puff", "sub_wood_splinter"),
    "dyn_table": ("sub_shack_puff", "sub_wood_splinter"),
    "dyn_walktalk": ("sub_shack_puff",),
    "dyn_woodbridge": ("sub_shack_puff",),
    "fade_object": ("sub_debris",),
    "fir_group": ("fir",),
    "melee_weapon": (
        "sub_coloured_glass",
        "sub_debris",
        "sub_rubble",
        "sub_shack_puff",
        "sub_wood_splinter",
        "wood_splinter_bit",
    ),
    "overhead_weapon": (
        "sub_debris",
        "sub_detergent",
        "sub_paint_splat",
        "sub_rubble",
        "sub_shack_puff",
        "sub_spark_effect",
        "sub_wood_splinter",
    ),
    "part_gun_flash": ("sub_shack_puff",),
    "part_raindrops": ("sub_ripple", "sub_splash"),
    "part_s_shack_dust_puff": ("sub_shack_puff",),
    "powerup_item": ("sub_glint", "sub_powerup_glow"),
    "rubble": ("sub_shack_puff",),
    "simple_object": ("sub_rubble",),
    "sub_anim_notes": ("glasstest", "sub_wood_splinter"),
    "sub_car_damage": ("sub_shack_puff",),
    "sub_detergent": ("sub_debris", "sub_paint_splat", "sub_shack_puff"),
    "sub_dus": ("sub_shack_puff",),
    "sub_rubble": ("rubble",),
    "sub_wood_splinter": ("wood_splinter_bit",),
    "thrown_weapon": (
        "sub_coloured_glass",
        "sub_debris",
        "sub_detergent",
        "sub_rubble",
        "sub_shack_puff",
        "sub_wood_splinter",
    ),
}
#: The car type names (`0x00512ba8`) and each type's 0x5f0-byte record (`0x0057e4c0`; docs/research/cars.md).
CAR_TYPES = 0x00512BA8
CAR_TYPE_COUNT = 6
CAR_RECORDS = 0x0057E4C0
CAR_RECORD_SIZE = 0x5F0
CAR_PARTS = 26
CAR_PART_TABLE = 0xF0  # part p's 0x30-byte record is at +0xf0 + 0x30 * p
#: `CarSetPartOpen`'s number for each part it can open (`0x0038d5b8`).
CAR_OPEN_NUMBERS = {5: 0, 4: 1, 14: 2, 16: 3, 18: 4, 20: 5}
#: Chunk types: the Object List in warriors.glr, and the sprite-sheet table, sheet and texture dictionary.
CHUNK_OBJECT_LIST, CHUNK_SHEET_TABLE, CHUNK_SHEET, CHUNK_TEXTURES = 0x46, 0x4D, 0x4C, 0x2A


def _glr_chunk(facts: DiscFacts, kind: int) -> tuple[bytes, int]:
    """warriors.glr's bytes and the offset of its first chunk of `kind`."""
    entry = facts.by_name("warriors.glr")
    if entry is None:
        raise ValueError("warriors.glr is not on the disc")
    data = facts.read(entry)
    container = parse_container(data)
    for resource in container.resources if container else ():
        for chunk in resource.chunks:
            if chunk.type == kind:
                return data, chunk.offset
    raise ValueError(f"warriors.glr has no chunk 0x{kind:02x}")


def _cstring(facts: DiscFacts, address: int) -> str:
    """A NUL-terminated string of the executable."""
    return facts.elf_bytes(address, 64).split(b"\0")[0].decode("latin-1")


def _texture_size(data: bytes, start: int, end: int) -> tuple[int, int] | None:
    """Width and height of the first PS2 native texture in a texture dictionary chunk (RenderWare sections)."""
    at = data.find(b"PS2\0", start, end)
    if at < 0:
        return None
    at += 8  # the platform and the filter word
    for _ in range(2):  # the texture's name and mask strings
        at += 12 + struct.unpack_from("<I", data, at + 4)[0]
    width, height = struct.unpack_from("<2I", data, at + 24)  # inside the raster struct's own struct
    return width, height


class Sheets:
    """The sprite-sheet table of warriors.glr and, on demand, each sheet's texture size and rectangles."""

    def __init__(self, facts: DiscFacts) -> None:
        self._facts = facts
        data, at = _glr_chunk(facts, CHUNK_SHEET_TABLE)
        count = struct.unpack_from("<I", data, at)[0]
        self.hashes = [struct.unpack_from("<2I", data, at + 4 + 8 * i)[1] for i in range(count)]
        self._names = {_crc(name): name for name in SHEET_NAMES}
        self._cache: dict[int, tuple[tuple[int, int] | None, list[tuple[float, ...]]]] = {}

    def name(self, record: int) -> str:
        """A record's sheet name, or its hash in hex."""
        key = self.hashes[record]
        return self._names.get(key, f"{key:08x}")

    def _read(self, record: int) -> tuple[tuple[int, int] | None, list[tuple[float, ...]]]:
        """A sheet's texture size and rectangles, from the WAD file named by its hash in decimal."""
        if record not in self._cache:
            size: tuple[int, int] | None = None
            rects: list[tuple[float, ...]] = []
            entry = self._facts.by_name(str(self.hashes[record]))
            data = self._facts.read(entry) if entry else b""
            container = parse_container(data) if data else None
            for resource in container.resources if container else ():
                for chunk in resource.chunks:
                    if chunk.type == CHUNK_TEXTURES and size is None:
                        size = _texture_size(data, chunk.offset, chunk.offset + chunk.size)
                    elif chunk.type == CHUNK_SHEET and not rects:
                        count = struct.unpack_from("<I", data, chunk.offset + 4)[0]
                        rects = [struct.unpack_from("<4f", data, chunk.offset + 0x14 + 16 * i) for i in range(count)]
            self._cache[record] = (size, rects)
        return self._cache[record]

    def rect_size(self, record: int, rect: int) -> list[int] | None:
        """A rectangle's size in whole texels {w, h}, or None when the sheet or rectangle is not there.

        The disc's rectangles are inset by a quarter texel (docs/research/gui.md#particle-page): the size counts every
        texel a corner falls in, as Coney's reference images cut them (`graphics::rectTexels`).
        """
        size, rects = self._read(record)
        if size is None or rect >= len(rects):
            return None
        u0, v0, u1, v1 = rects[rect]
        return [
            math.ceil(u1 * size[0] - 1e-3) - math.floor(u0 * size[0] + 1e-3),
            math.ceil(v1 * size[1] - 1e-3) - math.floor(v0 * size[1] + 1e-3),
        ]


def _uses(facts: DiscFacts, callee: str, argument: int) -> dict[Any, list[str]]:
    """Per literal value of one argument of `callee`: the scripts of each call (one item per call)."""
    found: dict[Any, list[str]] = collections.defaultdict(list)
    for script, call in facts.calls(callee):
        if len(call.args) > argument:
            value = call.args[argument]
            if isinstance(value, lua4.Global):  # a constant such as level5's HUD_WAR: its value in that script
                value = next((a.value for a in facts.scripts[script].assignments if a.name == value.name), None)
            if isinstance(value, (float, str)):
                found[_int(value)].append(script)
    return found


def _scripts(calls: list[str]) -> list[str] | None:
    """At most six distinct scripts, in name order."""
    return sorted(set(calls))[:6] or None


def topic_radar_icons(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """The radar icons the scripts and the code use, and the radar's blip types."""
    sheets = Sheets(facts)
    used = _uses(facts, "HUDSetRadarItemTexture", 1)
    numbers = sorted({n for n in used if isinstance(n, int)} | set(RADAR_CODE_ICONS))
    entries: list[dict[str, Any]] = []
    for number in numbers:
        where, scale, tint = RADAR_CODE_ICONS.get(number, (None, None, None))
        entries.append(
            {
                "id": f"icon-{number}",
                "kind": "icon",
                "number": number,
                "sheet": sheets.name(RADAR_SHEET),
                "rect": number,
                "size": sheets.rect_size(RADAR_SHEET, number),
                "set_by": where,
                "scale": scale,
                "tint": tint,
                "swatch": tint,
                "calls": len(used.get(number, [])) or None,
                "scripts": _scripts(used.get(number, [])),
                "image": _image(images, "radar", f"icon-{number}"),
            }
        )
    for number, (batch, icon, colour, who) in RADAR_BLIP_TYPES.items():
        entries.append(
            {
                "id": f"blip-{number}",
                "kind": "blip type",
                "number": number,
                "icon": icon,
                "batch": batch,
                "set_by": who,
                "tint": colour,
                "swatch": colour,
            }
        )
    return entries


def topic_particles(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """The script type table: every particle system, object behaviour, light and glass type, with its sprite."""
    sheets = Sheets(facts)
    used = _uses(facts, "SpawnParticle", 0)
    entries = []
    for index in range(SCRIPT_TYPE_COUNT):
        name_at, init, _update, _message, flags = struct.unpack("<5I", facts.elf_bytes(SCRIPT_TYPES + 20 * index, 20))
        name = _cstring(facts, name_at)
        kind = next((label for bit, label in SCRIPT_TYPE_KINDS if flags & bit), "other")
        sheet, rect = PARTICLE_SPRITES.get(name, (None, None))
        entries.append(
            {
                "name": name,
                "index": index,
                "kind": kind,
                "flags": flags,
                "init": init,
                "sheet": sheets.name(sheet) if sheet is not None else None,
                "rect": rect,
                "size": sheets.rect_size(sheet, rect) if sheet is not None and rect is not None else None,
                "spawns": list(PARTICLE_SPAWNS.get(name, ())) or None,
                "calls": len(used.get(name, [])) or None,
                "scripts": _scripts(used.get(name, [])),
                "image": _image(images, "particles", name),
            }
        )
    order = [label for _, label in SCRIPT_TYPE_KINDS] + ["other"]
    return sorted(entries, key=lambda e: (order.index(e["kind"]), e["index"]))


def _object_list(facts: DiscFacts) -> dict[int, tuple[int, ...]]:
    """The Object List of warriors.glr (chunk 0x46): 36-byte records of nine words, by name hash."""
    data, at = _glr_chunk(facts, CHUNK_OBJECT_LIST)
    count = struct.unpack_from("<I", data, at)[0]
    records = (struct.unpack_from("<9I", data, at + 16 + 36 * i) for i in range(count))
    return {record[0]: record for record in records}


def _clump_atomics(facts: DiscFacts, model_hash: int) -> int | None:
    """The atomic count of a model's clump, from the first standalone resource with that hash."""
    entry = facts.by_name(str(model_hash))
    data = facts.read(entry) if entry else b""
    container = parse_container(data) if data else None
    for resource in container.resources if container else ():
        for chunk in resource.chunks:
            if resource.hash == model_hash and chunk.type == 0x47:
                return int(struct.unpack_from("<I", data, chunk.offset + 24)[0])  # the clump struct's first word
    return None


def topic_cars(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Car types (`0x00512ba8`, their records and Object List entries), car parts and the colours scripts give."""
    objects = _object_list(facts)
    spawns = _uses(facts, "CarSpawn", 0)
    removed = _uses(facts, "CarRemovePart", 1)
    entries: list[dict[str, Any]] = []
    for number in range(CAR_TYPE_COUNT):
        name = _cstring(facts, struct.unpack("<I", facts.elf_bytes(CAR_TYPES + 4 * number, 4))[0])
        record = objects.get(_crc(name))
        model = textures = None
        if record is not None:
            model = f"{name}_geo" if record[2] == _crc(f"{name}_geo") else f"{record[2]:08x}"
            textures = next(
                (f"{other}_tex" for other in (name, "car_osedan") if record[3] == _crc(f"{other}_tex")),
                f"{record[3]:08x}",
            )
        body = struct.unpack("<3f", facts.elf_bytes(CAR_RECORDS + CAR_RECORD_SIZE * number, 12))
        entries.append(
            {
                "id": name,
                "kind": "type",
                "number": number,
                "model": model,
                "model_hash": record[2] if record else None,
                "textures": textures,
                "atomics": _clump_atomics(facts, record[2]) if record else None,
                "size": [round(v, 3) for v in body],
                "calls": len(spawns.get(name, [])) or None,
                "scripts": _scripts(spawns.get(name, [])),
                "image": _image(images, "cars", name),
            }
        )
    for part in range(CAR_PARTS):
        raw = facts.elf_bytes(CAR_RECORDS + CAR_PART_TABLE + 0x30 * part, 0x30)
        linked = raw[2]
        entries.append(
            {
                "id": f"part-{part}",
                "kind": "part",
                "number": part,
                "size": [round(v, 3) for v in struct.unpack_from("<3f", raw, 0x10)],
                "open_number": CAR_OPEN_NUMBERS.get(part),
                "linked": None if linked == 0xFF else linked,
                "sides": raw[0],
                "calls": len(removed.get(part, [])) or None,
                "scripts": _scripts(removed.get(part, [])),
            }
        )
    colours: dict[tuple[Any, ...], list[str]] = collections.defaultdict(list)
    for script, call in facts.calls("CarSetColor"):
        table = call.args[1] if len(call.args) > 1 else None
        values = tuple(_number(v) for v in table.as_list()) if isinstance(table, lua4.Table) else ()
        if len(values) == 4 and None not in values:
            colours[values].append(script)
    for number, (values, scripts) in enumerate(sorted(colours.items()), 1):
        entries.append(
            {
                "id": f"colour-{number}",
                "kind": "colour",
                "number": number,
                "rgba": list(values),
                "calls": len(scripts),
                "scripts": _scripts(scripts),
            }
        )
    return entries


#: The extractor of each topic, by file stem.
EXTRACTORS: dict[str, Callable[[DiscFacts, Path | None], list[dict[str, Any]]]] = {
    "characters": topic_characters,
    "character-models": topic_character_models,
    "gangs": topic_gangs,
    "goal-types": refs_engine.topic_goal_types,
    "speed-classes": topic_speed_classes,
    "objects": topic_objects,
    "object-groups": topic_object_groups,
    "cars": topic_cars,
    "particles": topic_particles,
    "levels": topic_levels,
    "level-starts": topic_level_starts,
    "flags": refs_world.topic_flags,
    "zones": refs_world.topic_zones,
    "boxes": refs_world.topic_boxes,
    "scenes": refs_world.topic_scenes,
    "cameras": refs_engine.topic_cameras,
    "screen-effects": refs_engine.topic_screen_effects,
    **refs_play.EXTRACTORS,
    "animations": topic_animations,
    "anim-ids": topic_anim_ids,
    "controls": topic_controls,
    "hud-colours": topic_hud_colours,
    "radar-icons": topic_radar_icons,
    "text-formatting": topic_text_formatting,
    "enums": topic_enums,
    "sound": topic_sound,
    "speech": topic_speech,
    "script-events": topic_script_events,
    "text-labels": topic_text_labels,
    "commands": topic_commands,
    "wad-names": topic_wad_names,
    **refs_env.EXTRACTORS,
}
