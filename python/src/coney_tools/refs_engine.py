# SPDX-License-Identifier: GPL-3.0-or-later
"""Read the engine reference lists from the player's own executable and scripts: camera types and switches, screen
effects and AI goal types (`coney-tools refs extract`).

Camera types are checked against each class's own type function (vtable slot `+0x1e8`) and named by the class tag
the game allocates them with; screen effects come from the queue's jump table, the effect-layer tags and the
`CfgScrFx` calls of the scripts; goal types are found by scanning the executable's data for goal vtables, each of
which names itself (slot `+0x14`) and gives its type id (slot `+0x0c`), and are tied to the `Goal*` bindings that
make them through the binding list in research/bindings/. Only names, ids and numbers are kept.

Each `topic_*` function returns the entries of one list, in page order; the pure functions under them take a word
reader and the walked scripts, so the tests can feed them synthetic memory and calls.

Research: docs/research/camera.md#types, docs/research/graphics.md#screen-effects, docs/research/ai.md#goals.
"""

from __future__ import annotations

import collections
import re
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from coney_tools import lua4
from coney_tools.refs import Field, Topic

if TYPE_CHECKING:
    from pathlib import Path

    from coney_tools.refs_extract import DiscFacts

F = Field
#: A word of the executable at a virtual address, or None outside its sections.
Word = Callable[[int], int | None]
#: A NUL-terminated string of the executable at a virtual address, or None outside its sections.
Text = Callable[[int], str | None]

# --- MIPS: the few instruction shapes the readers recognise -------------------------------------------------------

JR_RA = 0x03E00008
_TEXT = (0x00100000, 0x004F6578)  # .text of SLUS_212.15
_LONGEST = 2000  # instructions read from one function before giving up on finding its `jr ra`


def _signed(value: int) -> int:
    """A 16-bit immediate as a signed number."""
    return value - 0x10000 if value & 0x8000 else value


def return_constant(word: Word, function: int) -> int | None:
    """The number a two-instruction function returns (`jr ra` with `li v0, n` before it or in its delay slot), or
    None when the function is not that shape."""
    first, second = word(function), word(function + 4)
    if first is None or second is None:
        return None
    for candidate, other in ((first, second), (second, first)):
        if other != JR_RA:
            continue
        if candidate >> 16 == 0x2402:  # addiu v0, zero, n
            return _signed(candidate & 0xFFFF)
        if candidate in (0x0000102D, 0x00001021, 0x00001025):  # move v0, zero
            return 0
    return None


def return_address(word: Word, function: int) -> int | None:
    """The address a three-instruction function returns (`lui v0, hi; jr ra; addiu v0, v0, lo`), or None."""
    words = [word(function + 4 * i) for i in range(3)]
    if None in words:
        return None
    high, ret, low = words  # type: ignore[misc]
    if high >> 16 != 0x3C02 or ret != JR_RA or low >> 16 != 0x2442:  # type: ignore[operator]
        return None
    return ((high & 0xFFFF) << 16) + _signed(low & 0xFFFF)  # type: ignore[operator]


def _scan(word: Word, function: int) -> tuple[set[int], set[int]]:
    """The addresses one function builds with `lui` + `addiu` (or `ori`), and the functions it calls with `jal`, up to
    its `jr ra` and the delay slot after it."""
    high: dict[int, int] = {}
    built, called = set(), set()
    address, last = function, False
    for _ in range(_LONGEST):
        x = word(address)
        if x is None:
            break
        op, rs, rt, imm = x >> 26, (x >> 21) & 31, (x >> 16) & 31, x & 0xFFFF
        if op == 0x0F:  # lui
            high[rt] = imm << 16
        elif op in (0x09, 0x19) and rs in high:  # addiu / daddiu off a lui
            built.add((high[rs] + _signed(imm)) & 0xFFFFFFFF)
        elif op == 0x0D and rs in high:  # ori
            built.add(high[rs] | imm)
        elif op == 0x03:  # jal
            called.add((x & 0x3FFFFFF) << 2)
        if last:
            break
        last = x == JR_RA
        address += 4
    return built, called


def referenced(word: Word, function: int, wanted: set[int], depth: int = 3) -> set[int]:
    """The `wanted` addresses a function builds; when it builds none, those its callees build, `depth` calls deep.

    A binding's C function either builds the goal itself or calls the helper that does, so the first level with a
    hit is the goal it makes; looking deeper would also find the goals those helpers fall back to.
    """
    built, called = _scan(word, function)
    hits = built & wanted
    if hits or depth == 0:
        return hits
    found: set[int] = set()
    for callee in sorted(called):
        if _TEXT[0] <= callee < _TEXT[1] and callee != function:
            found |= referenced(word, callee, wanted, depth - 1)
    return found


# --- script usage -------------------------------------------------------------------------------------------------


def _whole(value: Any) -> int | None:
    """A whole number argument as an int, else None."""
    return int(value) if isinstance(value, float) and value.is_integer() else None


def literal_uses(scripts: dict[str, lua4.ChunkFacts], callee: str, argument: int = 0) -> dict[int, list[str]]:
    """Per whole-number literal of one argument of `callee`: the script of each call."""
    found: dict[int, list[str]] = collections.defaultdict(list)
    for script, chunk in scripts.items():
        for call in chunk.calls:
            if call.callee == callee and len(call.args) > argument:
                number = _whole(call.args[argument])
                if number is not None:
                    found[number].append(script)
    return found


def callers(scripts: dict[str, lua4.ChunkFacts], callees: Iterable[str]) -> list[str]:
    """The script of every call to any of `callees`."""
    names = set(callees)
    return [script for script, chunk in scripts.items() for call in chunk.calls if call.callee in names]


def _scripts(calls: list[str]) -> list[str] | None:
    """At most six distinct scripts, in name order."""
    return sorted(set(calls))[:6] or None


# --- camera types and switches ------------------------------------------------------------------------------------

#: The camera factory and the type function every camera class has (vtable function word `+0x1ec`).
CAMERA_FACTORY = 0x0011E1B0
CAMERA_TYPE_SLOT = 0x1EC
#: Each camera class: type -> (vtable, class tag string, how the game makes it, object size, bindings that make it).
#: Confirmed (code) at the factory and the getters `0x0011f9e0`-`0x00120188` (docs/research/camera.md#types).
CAMERA_CLASSES: dict[int, tuple[int, int, str, int, tuple[str, ...]]] = {
    0: (0x00535A90, 0x00548590, "factory, constructor `0x00123ea0`", 0x210, ("CameraCreateFixed",)),
    1: (0x005362D0, 0x00548580, "factory, constructor `0x001352f0`", 0x220, ("CameraCreateLocked",)),
    2: (0x00535D50, 0x005486A0, "one per player, `0x0011f9e0` (array `0x005d9158`)", 0x480, ("CamSetupFollow",)),
    3: (0x00537350, 0x00548708, "one, `0x00120038` (`0x0050b16c`)", 0x350, ("CamSetupPoizo",)),
    4: (0x00537090, 0x00548540, "factory, constructor `0x001421b8`", 0x1F0, ()),
    5: (0x00537610, 0x005486B0, "one per player, `0x0011fac8` (array `0x005d9180`)", 0x240, ("CameraMakeActive",)),
    6: (0x00536B10, 0x005486D0, "one per player, `0x0011fc98` (array `0x005d9188`)", 0x340, ()),
    7: (0x00536850, 0x005486E0, "one per player, `0x0011fd80` (array `0x005d9170`)", 0x250, ()),
    8: (0x00536590, 0x005486E8, "one per player, `0x0011fe68` (array `0x005d9178`)", 0x260, ()),
    9: (0x00536DD0, 0x005486C0, "one per player, `0x0011fbb0` (array `0x005d9160`)", 0x3F0, ("CamSetupRail",)),
    11: (0x00536010, 0x005486F8, "one per player, `0x0011ff50` (array `0x005d9168`)", 0x220, ("CamSetupHood",)),
    12: (0x005357D0, 0x00548718, "one, `0x001200e0` (`0x0050b170`)", 0x200, ("CamUseDeathCamera",)),
    13: (0x005378D0, 0x00548728, "one, `0x00120188` (`0x0050b174`)", 0x200, ("CameraCreateWin",)),
    16: (0x00535250, 0x005485A0, "factory, constructor `0x001204f0`", 0x230, ("CameraCreateThird",)),
}
#: `CamEnable`'s switches (`0x0011de58`): switch -> (what it sets, scope, value after a level's reset `0x00122b80`,
#: the code that reads it). Confirmed (code) at those addresses (docs/research/camera.md#switches).
CAMERA_SWITCHES: dict[int, tuple[str, str, int, str]] = {
    0: ("`0x0050b1b8[player]`", "per player", 1, "`0x00129050` (right stick and zoom), `0x001af010`"),
    1: ("`0x0050b1cc`", "global", 0, "`0x00130990` (follow camera collision)"),
    2: ("rail camera `+0x3e6`", "per player", 0, "the rail camera"),
    3: ("`0x0050b1c0`", "global", 1, "`0x00121888`, `0x00122ed0` (views), `0x001282a0`, `0x0013b7b8` (targets)"),
    4: ("`0x0050b1c8`", "global", 1, "`0x001282a0`, `0x00126c40`, `0x0013c710` (targets)"),
    5: ("follow camera `+0x468`", "per player", 1, "`0x00126a30` (sprint zoom)"),
    6: ("`0x0050b1d0`", "global", 1, "`0x00121298` (camera shake)"),
    7: ("`0x0050b2ac`", "global", 1, "`0x0013e708` (rail camera)"),
    8: ("`0x0050b2b0`", "global", 1, "`0x0013b7b8`, `0x0013d6b0` (rail camera targets)"),
    9: ("`0x0050b1d4`", "global", 1, "`0x00101dd8` (power camera)"),
    10: ("`0x0050b248`, `0x0050b249`", "both pads", 1, "`0x00129c78` (auto-follow)"),
    11: ("`0x0050b23c`", "global", 1, "`0x0012ae58` (`0x0012b4b4`, the look-behind argument of `0x00129050`)"),
    12: ("`0x0050b2b4`", "global", 1, "`0x0013b7b8` (rail camera targets)"),
    13: ("`0x0050b1e0`", "global", 0, "`0x00121888` (views)"),
}

CAMERAS = Topic(
    "cameras",
    "id",
    "cam",
    (
        F(
            "id",
            "str",
            "Our stable id: `type-<n>` for a camera type, `switch-<n>` for a `CamEnable` switch.",
            required=True,
        ),
        F("kind", "str", "`type` or `switch`.", "Kind"),
        F("number", "int", "The type (what the class's type function returns) or the switch number.", "Number"),
        F("class", "str", "Type: the class tag the game allocates it with, read from the executable.", "Class"),
        F("vtable", "hex", "Type: the class's vtable."),
        F("size", "hex", "Type: the object's size in bytes."),
        F(
            "made",
            "str",
            "Type: how the game makes one: the factory `0x0011e1b0`, or a getter that keeps it.",
            prose=True,
        ),
        F("made_by", "list", "Type: the bindings that make or set it up.", "Made by"),
        F("sets", "str", "Switch: the flag `CamEnable` writes.", "Sets", prose=True),
        F("scope", "str", "Switch: one flag for all, one per player, or one per camera.", "Scope"),
        F("default", "int", "Switch: its value after a level's camera reset (`0x00122b80`).", "Default"),
        F("read_by", "str", "Switch: the code that reads it.", prose=True),
        F("calls", "int", "Script calls: of the bindings that make the type, or `CamEnable` with the switch.", "Calls"),
        F("scripts", "list", "The scripts that make those calls (at most six).", "Scripts"),
        F("meaning", "str", "What it is or does, in our words.", "What", curated=True),
    ),
    group_by="kind",
    nav="Camera types and switches",
)


def camera_types(word: Word, text: Text, scripts: dict[str, lua4.ChunkFacts]) -> list[dict[str, Any]]:
    """Every camera class, its type read from the class's own type function. Raises ValueError when a vtable does
    not give the type the table says (a different executable)."""
    entries = []
    for number, (vtable, tag, made, size, made_by) in CAMERA_CLASSES.items():
        function = word(vtable + CAMERA_TYPE_SLOT)
        read = return_constant(word, function) if function is not None else None
        if read != number:
            raise ValueError(f"camera vtable 0x{vtable:08x} gives type {read}, not {number}")
        uses = callers(scripts, made_by)
        entries.append(
            {
                "id": f"type-{number}",
                "kind": "type",
                "number": number,
                "class": text(tag),
                "vtable": vtable,
                "size": size,
                "made": made,
                "made_by": list(made_by) or None,
                "calls": len(uses) or None,
                "scripts": _scripts(uses),
            }
        )
    return entries


def camera_switches(scripts: dict[str, lua4.ChunkFacts]) -> list[dict[str, Any]]:
    """Every `CamEnable` switch, with the scripts that pass it."""
    used = literal_uses(scripts, "CamEnable")
    return [
        {
            "id": f"switch-{number}",
            "kind": "switch",
            "number": number,
            "sets": sets,
            "scope": scope,
            "default": default,
            "read_by": read_by,
            "calls": len(used.get(number, [])) or None,
            "scripts": _scripts(used.get(number, [])),
        }
        for number, (sets, scope, default, read_by) in CAMERA_SWITCHES.items()
    ]


# --- screen effects -----------------------------------------------------------------------------------------------

#: `ScreenQueueEffect`'s jump table (`0x0018d450`): six code addresses, one per effect.
QUEUE_TABLE = 0x00552F70
QUEUE_EFFECTS = 6
#: The effect layers a manager keeps at `+0x154 + 0x10 * layer`: layer -> (class tag, bindings that start and end it).
#: Confirmed (code) at `0x0018bae0` / `0x0018bd48`.
LAYERS: dict[int, tuple[int, tuple[str, ...]]] = {
    0: (0x00552F28, ("StartRain", "EndRain")),
    1: (0x00552F30, ("StartFog", "EndFog")),
    2: (0x00552F38, ("StartFilmGrain", "EndFilmGrain")),
    3: (0x00552F48, ("StartRoomSmoke", "EndRoomSmoke")),
}
#: The thirteen looks (colour and motion-blur states, 0x18-byte slots at manager `+0x10`) and who switches to each,
#: where traced (docs/research/graphics.md#looks).
LOOK_COUNT = 13
LOOK_USERS: dict[int, str] = {
    0: "`0x00284280`",
    2: "`0x00236d28` (sets human flag `0x80000`); ended by `0x00236fb8` and `ScreenQueueEffect(1)`",
    3: "after look 2 ends (`0x0018b950`)",
    4: "after look 0 ends (`0x0018b950`)",
    5: "`ScreenQueueEffect` 4 and 5",
    7: "`EnableHeat`",
    8: "its out time ends look 3 (`0x0018b950`)",
    9: "`SetLevelColour`; `ExitStore` returns to it",
    10: "`EnterStore`",
}
CONFIG_SCRIPT = "config_preload2.lua"

SCREEN_EFFECTS = Topic(
    "screen-effects",
    "id",
    "fx",
    (
        F(
            "id",
            "str",
            "Our stable id: `queue-<n>` (a `ScreenQueueEffect` type), `look-<n>` (a `CfgScrFx` slot) or "
            "`layer-<n>` (an effect layer).",
            required=True,
        ),
        F("kind", "str", "`queue`, `look` or `layer`.", "Kind"),
        F("number", "int", "The number the binding takes: effect type, slot or layer.", "Number"),
        F("handler", "hex", "Queue: the code the effect's jump-table entry runs, read from the executable.", "Code"),
        F("class", "str", "Layer: the class tag its object is allocated with, read from the executable.", "Class"),
        F("colour", "list", "Look: `{r, g, b, a}` (0-255) `CfgScrFx` gives it (colour form).", "Colour"),
        F("in_ms", "int", "Look: milliseconds to blend in (slot `+0x10`, kept in seconds).", "In (ms)"),
        F("out_ms", "int", "Look: milliseconds to blend out (slot `+0x14`).", "Out (ms)"),
        F("value", "int", "Look: the colour form's fifth number (slot `+0x18`, the motion-blur alpha).", "Blur"),
        F("hold_ms", "int", "Look: milliseconds kept as 60 Hz frames (slot `+0x20`; look 5: the pulse's hold)."),
        F("value2", "int", "Look: the colour form's seventh number (slot `+0x1c`)."),
        F("strength", "int", "Look 5: the pulse's strength (manager `+0x148`)."),
        F("factors", "list", "Look 5: the two floats of the numeric form (manager `+0x14c`, `+0x150`)."),
        F("set_by", "str", "Who switches to it or makes it.", "Set by", prose=True),
        F("bindings", "list", "Layer: the bindings that start and end it.", "Bindings"),
        F("calls", "int", "Script calls: `ScreenQueueEffect` with the type, or the layer's bindings.", "Calls"),
        F("scripts", "list", "The scripts that make those calls (at most six).", "Scripts"),
        F("meaning", "str", "What it shows, in our words.", "What", curated=True),
    ),
    group_by="kind",
    nav="Screen effects",
)


def look_configs(scripts: dict[str, lua4.ChunkFacts]) -> dict[int, dict[str, Any]]:
    """Each slot's `CfgScrFx` configuration (the last call wins): the colour form `(slot, {r, g, b, a}, in, out,
    value, hold, value2)` or the numeric form `(slot, in, out, hold, strength, f1, f2)` that only slot 5 uses."""
    found: dict[int, dict[str, Any]] = {}
    for chunk in scripts.values():
        for call in chunk.calls:
            if call.callee != "CfgScrFx" or len(call.args) < 7:
                continue
            slot = _whole(call.args[0])
            if slot is None:
                continue
            args = call.args
            if isinstance(args[1], lua4.Table):
                colour = [_whole(v) for v in args[1].as_list()]
                found[slot] = {
                    "colour": colour if len(colour) == 4 and None not in colour else None,
                    "in_ms": _whole(args[2]),
                    "out_ms": _whole(args[3]),
                    "value": _whole(args[4]),
                    "hold_ms": _whole(args[5]),
                    "value2": _whole(args[6]),
                }
            else:
                factors = [round(v, 6) if isinstance(v, float) else None for v in args[5:7]]
                found[slot] = {
                    "in_ms": _whole(args[1]),
                    "out_ms": _whole(args[2]),
                    "hold_ms": _whole(args[3]),
                    "strength": _whole(args[4]),
                    "factors": factors if None not in factors else None,
                }
    return found


def screen_effects(word: Word, text: Text, scripts: dict[str, lua4.ChunkFacts]) -> list[dict[str, Any]]:
    """The queue's six effects, the thirteen looks and the four effect layers."""
    queued = literal_uses(scripts, "ScreenQueueEffect")
    entries: list[dict[str, Any]] = []
    for number in range(QUEUE_EFFECTS):
        entries.append(
            {
                "id": f"queue-{number}",
                "kind": "queue",
                "number": number,
                "handler": word(QUEUE_TABLE + 4 * number),
                "calls": len(queued.get(number, [])) or None,
                "scripts": _scripts(queued.get(number, [])),
            }
        )
    configs = look_configs(scripts)
    for number in range(LOOK_COUNT):
        entries.append(
            {
                "id": f"look-{number}",
                "kind": "look",
                "number": number,
                **configs.get(number, {}),
                "set_by": LOOK_USERS.get(number),
            }
        )
    for number, (tag, bindings) in LAYERS.items():
        uses = callers(scripts, bindings)
        entries.append(
            {
                "id": f"layer-{number}",
                "kind": "layer",
                "number": number,
                "class": text(tag),
                "bindings": list(bindings),
                "calls": len(uses) or None,
                "scripts": _scripts(uses),
            }
        )
    return entries


# --- AI goal types ------------------------------------------------------------------------------------------------

#: Goal vtable function words: the type id, the class name, Process and the event handler; and the default handler.
GOAL_TYPE_SLOT, GOAL_NAME_SLOT, GOAL_PROCESS_SLOT, GOAL_EVENT_SLOT = 0x0C, 0x14, 0x44, 0x4C
GOAL_DEFAULT_EVENT = 0x0029EF80
_GOAL_NAME = re.compile(r"^[A-Z][A-Za-z0-9_]*$")

GOAL_TYPES = Topic(
    "goal-types",
    "id",
    "goal",
    (
        F(
            "id",
            "int",
            "The goal type: what the class's type function returns (vtable `+0x0c`).",
            "Type",
            required=True,
        ),
        F("name", "str", "The class's own name (the string vtable `+0x14` returns).", "Goal"),
        F("vtable", "hex", "The class's vtable.", "Vtable"),
        F("process", "hex", "Its Process function (vtable `+0x44`), run each brain update."),
        F("event", "hex", "Its own event handler (vtable `+0x4c`), when it has one."),
        F("bindings", "list", "The script bindings that make it (found by following their code).", "Bindings"),
        F("calls", "int", "Script calls of those bindings.", "Calls"),
        F("scripts", "list", "The scripts that make those calls (at most six)."),
        F("meaning", "str", "What the goal does, in our words.", "What", curated=True),
    ),
    compact=True,
    nav="AI goal types",
)


def goal_vtables(word: Word, text: Text, start: int, end: int) -> dict[int, tuple[int, str]]:
    """Every goal vtable between `start` and `end`: vtable -> (type, name).

    A goal vtable starts with three zero words, and its function words `+0x0c` and `+0x14` are two- and
    three-instruction functions returning the type id and the name.
    """
    found: dict[int, tuple[int, str]] = {}
    for vtable in range(start, end - GOAL_EVENT_SLOT, 8):
        if word(vtable) != 0 or word(vtable + 4) != 0 or word(vtable + 8) != 0:
            continue
        type_function, name_function = word(vtable + GOAL_TYPE_SLOT), word(vtable + GOAL_NAME_SLOT)
        if not type_function or not name_function:
            continue
        number = return_constant(word, type_function)
        name_at = return_address(word, name_function)
        if number is None or name_at is None:
            continue
        name = text(name_at)
        if name and _GOAL_NAME.match(name):
            found[vtable] = (number, name)
    return found


def goal_types(
    word: Word,
    text: Text,
    data: tuple[int, int],
    bindings: dict[str, list[int]],
    scripts: dict[str, lua4.ChunkFacts],
) -> list[dict[str, Any]]:
    """Every goal class in the `data` range, by type, with the bindings (name -> their C functions) that make it."""
    vtables = goal_vtables(word, text, *data)
    makers: dict[int, set[str]] = collections.defaultdict(set)
    for name, functions in bindings.items():
        for function in functions:
            for vtable in referenced(word, function, set(vtables)):
                makers[vtable].add(name)
    entries = []
    for vtable, (number, name) in sorted(vtables.items(), key=lambda item: item[1][0]):
        made_by = sorted(makers.get(vtable, ()))
        uses = callers(scripts, made_by)
        event = word(vtable + GOAL_EVENT_SLOT)
        entries.append(
            {
                "id": number,
                "name": name,
                "vtable": vtable,
                "process": word(vtable + GOAL_PROCESS_SLOT),
                "event": event if event != GOAL_DEFAULT_EVENT else None,
                "bindings": made_by or None,
                "calls": len(uses) or None,
                "scripts": _scripts(uses),
            }
        )
    return entries


#: The title, source and evidence each list starts with (`refs_cli.STARTERS`); its prose lives in the YAML.
STARTERS: dict[str, dict[str, str]] = {
    "cameras": {
        "title": "Camera types and switches",
        "source": "SLUS_212.15, camera factory 0x0011e1b0 and CamEnable 0x0011de58",
        "evidence": "confirmed-code",
    },
    "screen-effects": {
        "title": "Screen effects",
        "source": "SLUS_212.15, ScreenEffectsManager.cpp (0x0018b168-0x0018e7c0); config_preload2.lua, CfgScrFx",
        "evidence": "confirmed-code",
    },
    "goal-types": {
        "title": "AI goal types",
        "source": "SLUS_212.15, goal vtables (type +0x0c, name +0x14) and the bindings' code",
        "evidence": "confirmed-code",
    },
}


# --- the extractors ---------------------------------------------------------------------------------------------


class _Executable:
    """Words and strings of the disc's executable by virtual address."""

    def __init__(self, facts: DiscFacts) -> None:
        self._facts = facts

    def word(self, address: int) -> int | None:
        """One little-endian word, or None outside the sections."""
        try:
            return int.from_bytes(self._facts.elf_bytes(address, 4), "little")
        except ValueError:
            return None

    def text(self, address: int) -> str | None:
        """A NUL-terminated string, or None outside the sections."""
        try:
            return self._facts.elf_bytes(address, 64).split(b"\0")[0].decode("latin-1")
        except ValueError:
            return None


def topic_cameras(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Camera types, then `CamEnable`'s switches."""
    exe = _Executable(facts)
    return camera_types(exe.word, exe.text, facts.scripts) + camera_switches(facts.scripts)


def topic_screen_effects(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """`ScreenQueueEffect`'s effects, `CfgScrFx`'s looks and the effect layers."""
    exe = _Executable(facts)
    return screen_effects(exe.word, exe.text, facts.scripts)


def _goal_bindings() -> dict[str, list[int]]:
    """Every binding of research/bindings/ with the C functions its registrations call."""
    from pathlib import Path

    from coney_tools import natives
    from coney_tools.config import find_repo_root

    found: dict[str, list[int]] = {}
    for binding in natives.load(find_repo_root(Path.cwd())).bindings:
        found[binding.name] = [call.addr for variant in (binding.main, *binding.overloads) for call in variant.calls]
    return found


def topic_goal_types(facts: DiscFacts, images: Path | None) -> list[dict[str, Any]]:
    """Every goal class of the executable's data section, by type."""
    exe = _Executable(facts)
    data = facts.elf.sections[".data"]
    return goal_types(exe.word, exe.text, (data.address, data.address + data.size), _goal_bindings(), facts.scripts)
