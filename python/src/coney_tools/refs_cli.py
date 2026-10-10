# SPDX-License-Identifier: GPL-3.0-or-later
"""The `coney-tools refs ...` commands: render the game reference pages, and refresh their lists from the disc.

`refs render` reads `research/references/*.yaml`, checks each against its schema and writes `docs/references/`;
with `--check` it changes nothing and fails when a page is out of date (CI runs it). `refs extract` reads the
player's disc, merges what it finds into the YAML (keeping every hand-written field) and renders.
`refs compress-images` turns the rendered thumbnails into small palette PNGs before they are committed.

Research: docs/guides/research-workflow.md#reference-lists
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import yaml

from coney_tools import refs, refs_engine, refs_env, refs_play, refs_render
from coney_tools.config import ConfigError, find_repo_root
from coney_tools.refs import Topic
from coney_tools.refs_topics import TOPICS, topic
from coney_tools.wad_cli import open_disc

REFS_DIR = Path("research/references")
DOCS_DIR = Path("docs/references")
IMAGES_DIR = DOCS_DIR / "images"
BINDINGS_INDEX = DOCS_DIR / "bindings/index.md"
ENTITIES_PAGE = DOCS_DIR / "entities.md"  # hand-written; the index links it when it exists
GAPS_FILE = REFS_DIR / "still-to-list.yaml"  # the families with no list yet, shown on the index


def _yaml_path(root: Path, item: Topic) -> Path:
    """Where a topic's list lives."""
    return root / REFS_DIR / f"{item.key}.yaml"


def load_all(root: Path) -> list[refs.RefList]:
    """Every topic's list, in index order. Raises ConfigError naming each missing or invalid file."""
    lists, problems = [], []
    for item in TOPICS:
        path = _yaml_path(root, item)
        if not path.is_file():
            problems.append(f"{path.relative_to(root)}: missing (run `coney-tools refs extract`)")
            continue
        try:
            lists.append(refs.load(path, item))
        except refs.RefsError as error:
            problems.append(str(error))
    if problems:
        raise ConfigError("\n".join(problems))
    return lists


def load_gaps(root: Path) -> refs.Gaps | None:
    """The families still to list, or None when the checkout has no still-to-list file."""
    path = root / GAPS_FILE
    return refs.load_gaps(path) if path.is_file() else None


def pages(root: Path, lists: list[refs.RefList]) -> dict[Path, str]:
    """Every generated page by path: the index and one page per topic."""
    index = refs_render.index(
        lists,
        (root / BINDINGS_INDEX).is_file(),
        entities_page=(root / ENTITIES_PAGE).is_file(),
        gaps=load_gaps(root),
    )
    out = {root / DOCS_DIR / "index.md": index}
    out.update({root / DOCS_DIR / f"{reflist.topic.key}.md": refs_render.page(reflist) for reflist in lists})
    for reflist in lists:
        if reflist.topic.split:
            out.update({root / DOCS_DIR / path: text for path, text in refs_render.group_pages(reflist).items()})
    return out


def leftover_pages(root: Path, wanted: dict[Path, str]) -> list[Path]:
    """Pages in a split list's folder that no group produces any more (a group that left the list)."""
    found = []
    for item in TOPICS:
        folder = root / DOCS_DIR / item.key
        if item.split and folder.is_dir():
            found += [path for path in sorted(folder.glob("*.md")) if path not in wanted]
    return found


def run_render(check: bool) -> int:
    """Write the pages, or with `check` report the stale ones and return 1."""
    root = find_repo_root(Path.cwd())
    stale = []
    wanted = pages(root, load_all(root))
    for path in leftover_pages(root, wanted):
        stale.append(path.relative_to(root).as_posix())
        if not check:
            path.unlink()
    for path, text in wanted.items():
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == text:
            continue
        stale.append(path.relative_to(root).as_posix())
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    if check and stale:
        print("coney-tools: out of date with research/references/ (run `coney-tools refs render`):", file=sys.stderr)
        for name in stale:
            print(f"  {name}", file=sys.stderr)
        return 1
    print(f"{len(stale)} page(s) {'stale' if check else 'written'}; {len(TOPICS)} lists")
    return 0


def known_names(root: Path, names_file: Path | None) -> list[str]:
    """Names found before: the WAD names list, and a names file (one name per line) when given."""
    names: list[str] = []
    path = _yaml_path(root, topic("wad-names"))
    if path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        names += [str(entry["name"]) for entry in data.get("entries") or [] if entry.get("name")]
    if names_file is not None:
        try:
            text = names_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ConfigError(f"{names_file}: cannot be read ({error})") from error
        names += [line.split()[-1] for line in text.splitlines() if line.strip() and not line.startswith("#")]
    return names


def run_extract(disc_arg: str | None, only: list[str] | None, names_file: Path | None) -> int:
    """Read the disc, merge each topic's facts into its YAML (keeping hand-written fields) and render."""
    from coney_tools import refs_extract  # the disc readers are only needed here

    root = find_repo_root(Path.cwd())
    wanted = [topic(key) for key in only] if only else list(TOPICS)
    facts = refs_extract.DiscFacts(open_disc(disc_arg), known_names(root, names_file))
    for item in wanted:
        fresh = refs_extract.EXTRACTORS[item.key](facts, root / IMAGES_DIR)
        path = _yaml_path(root, item)
        existing = refs.load(path, item) if path.is_file() else new_list(item)
        merged = refs.merge(existing, fresh)
        refs.write(path, merged)
        print(f"{item.key}: {len(fresh)} extracted, {len(merged.entries)} in the list")
    # Re-render only when every list exists (a first `--only` run leaves the others to come).
    if all(_yaml_path(root, item).is_file() for item in TOPICS):
        return run_render(check=False)
    return 0


def compress_image(path: Path) -> tuple[int, int]:
    """Rewrite one PNG as a 256-colour palette image with alpha; returns its sizes before and after.

    `coney --render-references` writes full-colour PNGs of about 26 KB each. The docs keep about 550 of them, so
    they are stored with a palette instead: under a quarter of the size, and indistinguishable at 256 pixels.
    Pillow's octree quantizer is deterministic, so the same render always gives the same bytes. A file the palette
    would not make smaller (a radar icon of a few hundred pixels, where the palette itself outweighs the pixels) is
    left as it is.
    """
    from PIL import Image  # only this command needs Pillow

    before = path.stat().st_size
    with Image.open(path) as image:
        palette = image.convert("RGBA").quantize(256, method=Image.Quantize.FASTOCTREE)
    packed = io.BytesIO()
    palette.save(packed, "PNG", optimize=True)
    if packed.tell() < before:
        path.write_bytes(packed.getvalue())
    return before, path.stat().st_size


def run_compress_images(folder: Path | None) -> int:
    """Compress every PNG below docs/references/images/ (or `folder`) in place."""
    root = find_repo_root(Path.cwd())
    base = folder if folder is not None else root / IMAGES_DIR
    files = sorted(base.rglob("*.png"))
    before = after = 0
    for path in files:
        old, new = compress_image(path)
        before, after = before + old, after + new
    print(f"{len(files)} image(s): {before // 1024} KB -> {after // 1024} KB")
    return 0


def new_list(item: Topic) -> refs.RefList:
    """An empty list with its starting prose and defaults, for a topic that has no YAML yet."""
    start = STARTERS.get(item.key, {})
    return refs.RefList(
        item,
        start.get("title", item.nav or item.key),
        start.get("about", ""),
        start.get("complete", ""),
        {"source": start.get("source", "the scripts on the disc"), "evidence": start.get("evidence", "inferred")},
    )


def topic_keys() -> list[str]:
    """The file stems `--only` accepts."""
    return [item.key for item in TOPICS]


#: The prose and defaults a list starts with. After the first extract they live in the YAML and are edited there.
STARTERS: dict[str, dict[str, Any]] = {
    "characters": {
        "title": "Characters (humans)",
        "source": "config_preload2.lua, CfgChar",
        "about": "Every character type `CfgChar` configures. A level script creates a character (a *human*) with\n"
        "`HuCreate(name, type, position, heading, ...)`, and the type picks everything below: the model, health,\n"
        "damage and attack tables, voice, hat and weapon. See [Characters](../research/characters.md#classes).\n\n"
        "Speeds are what the game uses in play: each clip's root displacement over its length, for the clip the\n"
        "type's character data plays in the walk, jog, run and sprint slots (the generic clip when it has none of\n"
        "its own). The [speed class](speed-classes.md) is only a fallback.",
        "complete": "Every type `CfgChar` configures (449) is listed with every argument. The labels (who a type is)\n"
        "are hand-written and still sparse; the meaning of `v11d` and `flag_14b` is not traced.",
    },
    "character-models": {
        "title": "Character models",
        "source": "warriors.glr, Character List (chunk 0x44)",
        "evidence": "confirmed-code",
        "about": "The Character List in `warriors.glr`: one record per character model, naming its model, texture\n"
        "dictionary and character data (animations) by hash ([Characters](../research/characters.md#files)). A\n"
        "`<model>_a` record is the variant used in levels 60-64.",
        "complete": "Every record (543) is listed. Names are recovered by hashing candidate strings; a record\n"
        "without a name has none of its candidates on the disc yet.",
    },
    "gangs": {
        "title": "Gangs",
        "source": "config_preload2.lua, CfgGang",
        "about": "Gang types: `CfgGang(type, ...)` configures each, `GangCreate(type, name)` creates a gang in a\n"
        "level script and `CfgGangMusic` gives it three music tracks. Humans join a gang when they are created.",
        "complete": "Every gang type (25) is listed with its arguments; the meaning of the byte values is not traced.\n"
        "Labels are hand-written.",
    },
    "speed-classes": {
        "title": "Speed classes",
        "source": "config_preload2.lua, CfgSpeedClass",
        "about": "The fallback speed table `CfgSpeedClass` fills at `0x006b6548` (six floats per class). In play the\n"
        "game uses each human's own clip speeds instead ([Characters](../research/characters.md#speed-classes)).",
        "complete": "All five classes are listed.",
    },
    "objects": {
        "title": "Objects and weapons",
        "source": "config_preload2.lua and config_preload3.lua, CfgObj",
        "about": "Every object type `CfgObj` configures: weapons, hats and masks, pick-ups, doors and props.\n"
        "The name is also the model's name and what scripts pass to create the object.",
        "complete": "Every object type (1,371) is listed with its class, type, physics shape, size and animations.\n"
        "The category is our grouping by class. Arguments 2-5, 11 and 14-17 are not traced.",
    },
    "object-groups": {
        "title": "Object groups",
        "source": "config_preload2.lua, CfgChar",
        "about": "The item groups a character type may carry and drop (`CfgChar`'s drop group).",
        "complete": "Every group named by a character type is listed. No script on the disc calls `CfgObjectGroup`,\n"
        "so where the groups are defined is not known.",
    },
    "cars": {
        "title": "Cars",
        "source": "SLUS_212.15, car tables 0x00512ba8 and 0x0057e4c0; warriors.glr, Object List",
        "evidence": "confirmed-code",
        "about": "The six car types `CarSpawn` makes, the 26 part ids of the car bindings and the colours scripts\n"
        "give cars ([Cars](../research/cars.md)).",
        "complete": "Every type and part id is listed. What each part is, is our reading of its record (box size,\n"
        "side bits, linked part) and is inferred. Colours are the literal tables the scripts pass; 13 more calls\n"
        "pass computed values.",
    },
    "particles": {
        "title": "Particle effects",
        "source": "SLUS_212.15, script type table 0x00512f28",
        "evidence": "confirmed-code",
        "about": "Every type of the script type table: the particle systems `SpawnParticle` makes, and the object\n"
        "behaviours, lights and glass that share the table ([Particles](../research/particles.md)).",
        "complete": "All 270 types are listed. The sprite is traced for 58 of them.",
    },
    "radar-icons": {
        "title": "Radar icons and blips",
        "source": "SLUS_212.15, radar code; the scripts, HUDSetRadarItemTexture",
        "evidence": "confirmed-code",
        "about": "The icon ids `HUDSetRadarItemTexture` takes and the code sets, and the radar's blip types\n"
        "([GUI: radar](../research/gui.md#radar-icons)).",
        "complete": "Every icon a script or the code uses and every blip type the code adds are listed. The numbers\n"
        "are read from the code and the scripts; what each icon marks is inferred from who uses it. Classes are the\n"
        "character class byte `CfgChar` sets (`+0x11a`, [AI](../research/ai.md#types)).",
    },
    "levels": {
        "title": "Levels",
        "source": "config_preload3.lua, levelNames",
        "about": "The 111 level records of `levelNames` (`CfgLevelName`), in the order the game keeps them.\n"
        "A level loads from `<name>.lev` and its section packs `<name>_<k>.pak`\n"
        "([Level loading](../research/level-loading.md)).",
        "complete": "Every record is listed with every field. `.lev` and pack counts come from the WAD names list,\n"
        "so a level whose files have no recovered name shows none. Kinds are hand-written: the story order\n"
        "is `global.lua`'s `runNextMission` and the hub's `fRunMission`, the flashbacks the hub's\n"
        "`FBMission` ([Scripts](../research/scripting.md#run-next-mission)); a Rumble arena lists the modes\n"
        "whose flag scripts were found. Where each level puts the player: [Level starts](level-starts.md).",
    },
    "level-starts": {
        "title": "Level starts",
        "source": "the level scripts, HuCreate and AddFlag",
        "about": "Where each level puts player 1 when it starts: one entry per checkpoint of a story level (the\n"
        "`HuCreate` for player 1 in the function the level script calls for `GetCheckPoint()`) and one per mode of a\n"
        "Rumble arena (the first flag of the list `fP1` in `level<N>_<mode>_init.lua`, which the arena teleports\n"
        "player 1 to).\n"
        "How the game gets there: [Characters](../research/characters.md#level-starts).",
        "complete": "Every story level whose script creates player 1 at a literal position, and every Rumble flag\n"
        "script whose name is known. The hub (`level95`) places the Warchief at a flag and is hand-written.\n"
        "A checkpoint's own script may move the player again once it has loaded (see each entry's notes).",
    },
    "flags": {
        "title": "World flags",
        "source": "the level scripts, AddFlag",
        "about": "The named points with a heading that level scripts add with `AddFlag(name, {x, y, z}, heading,\n"
        "activity, group)` and use to spawn humans, send them somewhere and test against ([World\n"
        "flags](../research/flags.md)). Scripts keep the handle `AddFlag` returns; `FindFlag` finds a\n"
        "flag by name. Ambient humans pick flags by **activity**: a flag with one is a spot where a\n"
        "civilian sits, smokes, warms his hands or leaves the level.",
        "complete": "Every `AddFlag` call whose name is a literal string: 7,057 flags (4,167 names) added by 94\n"
        "scripts of 62 levels. 23 positions are computed at run time and show none; 79 flags come from\n"
        "scripts shared by several levels or whose names are not recovered (*other*). What each activity\n"
        "does is on [World flags](../research/flags.md#activities); what the group means on path-network\n"
        "flags is not traced. The two flags `InitLevel` adds itself (`CrimeScene`, `GangCall`) are not\n"
        "listed.",
    },
    "zones": {
        "title": "Object zones",
        "source": "the level scripts, ObjEnableZone and ObjSpawn",
        "about": "The zone numbers that group a level's spawned objects, so a script can switch a whole area's\n"
        "objects on or off with `ObjEnableZone(zone, enable)`. Zone 0 is on when a level starts and holds\n"
        "every object spawned without a zone; zones 1 to 254 start off\n"
        "([Tasks](../research/tasks.md#classes)). Numbers are per level: the same number names different\n"
        "objects in different levels.",
        "complete": "Every zone number a level's scripts name (`Zone<n>` globals, `<TABLE>.<NAME>_ZONE` fields),\n"
        "switch or spawn objects into: 225 zones in 62 levels. 66 of the 3,133 calls are left out because\n"
        "their zone is not a number the level defines: `global.lua`'s `BNESetup` switches its caller's\n"
        "`Zone21` to `Zone32`, and two calls of `level95` compute the zone. Objects the level file places\n"
        "in a zone are not counted (how it assigns them is not traced).",
    },
    "boxes": {
        "title": "Volume boxes",
        "source": "the level scripts, AddVolumeBox and GangAddTurfBox",
        "about": "The axis-aligned boxes level scripts add with `AddVolumeBox(name, kind, corner, size)` to test\n"
        "whether humans are inside an area, switch collision and mark a gang's turf (`GangAddTurfBox`).\n"
        "The kind picks the class: 0 a `VolumeBox`, 2 a `PlayerBox`, 3 a `TurfBox`\n"
        "([Tasks](../research/tasks.md#classes)).",
        "complete": "Every `AddVolumeBox` call whose name is a literal string: 974 boxes (547 volume, 251 player and\n"
        "176 turf boxes) in 47 levels. *Held in* and *Turf of* are filled where a script keeps the handle\n"
        "in a global: 64 of the 87 `GangAddTurfBox` calls resolve to a box. What a player box does\n"
        "differently from a volume box is not traced.",
    },
    "scenes": {
        "title": "Scenes and movies",
        "source": "scene_list.cnk, the scripts' ScenePreload, the level records",
        "evidence": "confirmed-code",
        "about": "The in-engine scenes (cutscenes and animation sets, `.scn` records) and the full-motion movies\n"
        "(`PSS/<name>.BIK`). `ScenePreload(name)` returns a scene id, the record's index in the global\n"
        "scene list `scene_list.cnk`, which the other scene bindings take; `PlayMovie(name)` plays a\n"
        "movie. How scenes play: [Scenes](../research/scenes.md); movies:\n"
        "[Movies](../research/movies.md).",
        "complete": "All 16 movies, and every scene of `scene_list.cnk` except the 1,525 segments that continue a\n"
        "longer scene: 1,240 scenes, 24 of them under names cut to 16 characters. A scene's levels and\n"
        "scripts are those that preload it by name; scenes that C++ code or a computed name loads show\n"
        "none.",
    },
    "animations": {
        "title": "Animation clips",
        "source": "character data and .anm resources, clip descriptors",
        "evidence": "confirmed-code",
        "about": "Every distinct animation clip on the disc: its name (from its descriptor), length, root\n"
        "displacement and where it is found ([Animation](../research/formats/animation.md)). Clips that share a\n"
        "name but differ are numbered `#2`, `#3` ...",
        "complete": "Every clip (1,875) is listed. Resource names are recovered by hashing; unnamed ones show as hex.",
    },
    "anim-ids": {
        "title": "Anim ids",
        "source": "royal.lua (names); character data (clips); 0x005105d8 (slots)",
        "about": "The 722 anim ids every character data maps to clips. A character's own slot wins; an unset slot\n"
        "plays the generic character data's clip ([Characters](../research/characters.md#files)). Scripts name ids\n"
        "with the `ANIM_*` constants of `royal.lua`; the locomotion slots are\n"
        "[Characters, Anim slots](../research/characters.md#anim-slots).",
        "complete": "All 722 ids are listed with the generic clip and Rembrandt's own clip where he has one. Names\n"
        "exist only for the ids `royal.lua` defines.",
    },
    "controls": {
        "title": "Controls",
        "source": "pad record and libpad layout (docs/research/frontend.md#input)",
        "about": "The pad as the game reads it: the 16-bit button word, the analog sticks, and the markup tag that\n"
        "draws each button in text. Coney drives everything as a gamepad with analog sticks; on a PC pad the face\n"
        "buttons are positional (south is cross).",
        "complete": "Every button bit and both sticks are listed. What each does on foot is still to be written;\n"
        "the front end's accept and back are known ([Front end](../research/frontend.md#input)).",
    },
    "hud-colours": {
        "title": "HUD colours",
        "source": "config_preload2.lua, CL and CfgHUDColor",
        "about": "The colour table `CL` scripts use in text (`<COLOR rrggbbaa>`) and the HUD slots `CfgHUDColor`\n"
        "assigns from it.",
        "complete": "Every key of `CL` is listed.",
    },
    "text-formatting": {
        "title": "Text formatting",
        "source": "SLUS_212.15, tag table 0x0050d718",
        "evidence": "confirmed-code",
        "about": "The markup tags text strings may carry, in the order of the executable's tag table\n"
        "([GUI, Markup tags](../research/gui.md#markup)). A tag with a trailing space (shown as ␠) takes an argument.",
        "complete": "All 66 tags are listed; the effects are written from the layout code.",
    },
    "enums": {
        "title": "Script enums",
        "source": "the preload scripts and global.lua",
        "about": "Constant tables (`MATERIAL.GLASS`) and loose constants (`LT_PLAY`) the preload scripts and\n"
        "`global.lua` define, as mods and level scripts pass them to bindings. The 722 `ANIM_*` ids are in\n"
        "[Anim ids](anim-ids.md).",
        "complete": "Every numeric constant of those scripts is listed. Meanings are hand-written and sparse.",
    },
    "sound": {
        "title": "Sound and music",
        "source": "config_preload.lua, config_preload2.lua, global.lua and the level scripts",
        "about": "The music tracks `SndCfgMusicInfo` configures, the interface sounds of `SoundCfgInterfaceSound`,\n"
        "the sound matrices scripts load, the sounds of inventory items, the ambient sounds (`AddAmbientSound`\n"
        "fills the ambient table that emitters pick from), the ambient emitters the levels place\n"
        "(`AddAmbientSoundEmitter2`) and the speech lines scripts play by name (`HuSpeak`, `HuSpeakNI`; the\n"
        '`global.lua` helper `SetVag("l11_t25_006")` stands for `vags/speeches/l11/l11_t25_006`). Names only,\n'
        "never the sounds. Gang music is in [Gangs](gangs.md); the lines humans say by kind are in\n"
        "[Speech](speech.md).",
        "complete": "Every configured sound, ambient sound, emitter and literal speech line name is listed. The two\n"
        "numbers of a music track are not traced. Speech lines whose names are built at run time are missing;\n"
        "names marked as not in the sound list may live in a level's own sound bank, or be mistakes in the\n"
        "scripts.",
    },
    "speech": {
        "title": "Speech commands and voices",
        "source": "the speech command table (0x0050aaa8), the sound list of warriors.glr, CfgChar and the scripts",
        "evidence": "confirmed-code",
        "about": "What a human can say and in which voice. A **speech command** is a kind of line (`attack`,\n"
        "`pain`, `cheer1` ...): `SoundPlayCommand(human, command)` makes a human say one, and the game says them\n"
        "itself in fights, chases and crowds. A **voice set** is a numbered folder of recorded lines; `CfgChar`\n"
        "gives each character type one ([Characters](characters.md)), and `HuSetStateRespVoiceIndex` gives a\n"
        "human another for its state responses. A voice set's lines for a command are the sounds\n"
        "`vags/character/voices/<set>/<command>_01`, `_02` ...; a voice set without lines for a command says\n"
        "nothing. How a line is picked: [Sound](../research/sound.md#speech).",
        "complete": "All 207 speech commands are listed by their names in the executable, and every voice set that\n"
        "has lines, a character type or a script user, with the lines the game finds for each. When the game\n"
        "itself says each command is not traced.",
    },
    "text-labels": {
        "title": "Text labels",
        "source": "every script: the string tables' constructors and the labels passed to bindings",
        "about": "The keys of the string tables scripts show text by: objectives (`HUDSetObjective`), tutorial hints\n"
        "(`HUDSetTutorialText`), mission-failed reasons (`HUDLaunchMissionFailed`), button prompts\n"
        "(`SetMsgHandlerEx`) and HUD labels. A script names one as `<table>.<key>`. `global.lua` builds\n"
        "`GSTRING` and `LABEL` for every level and each level script its own `LEVEL<n>`, in all five languages,\n"
        "keeping `GetLanguage`'s; Rumble arenas build `RUMBLE`; the front end's `config_strings_<lang>.lua` hold\n"
        "the numbered tables the engine reads ([GUI: strings](../research/gui.md#strings)). Only keys, never the\n"
        "text.\n"
        "\n"
        "The level tables' key prefixes, read from what the keys are passed to (inferred): `MS_C<k>_<n>` a step\n"
        "of chapter k's objective, `MP_<n>` the mission's main objective, `MB_` a bonus objective, `MF_` and\n"
        "`FAIL` a mission-failed reason, `TT_` a tutorial hint, `LBL_` a HUD bar's label, `CS_` an announcement.",
        "complete": "Every key of every string table on the disc is listed, with the scripts that name it. Keys no\n"
        "script names directly may be built at run time (`ObjectiveString`) or unused; keys with no languages are\n"
        "named by a script but defined in no table. A table of lines (`LEVEL95.ACT`) shows the ids its\n"
        "constructors give.",
    },
    "commands": {
        "title": "Commands",
        "source": "global.lua AddCommand; EnableCommand, WCEnableCommand and WCIssueCommand in the scripts",
        "about": "The commands a human acts on. A **pad command** is a number the matcher makes from a player's\n"
        "buttons each update, through the nine **trigger** kinds; `global.lua` binds them with\n"
        "`AddCommand(command, trigger, buttons, extra)` and scripts switch them per human with `EnableCommand`.\n"
        "AI humans write the same numbers. A **Warrior command** is an order the war chief gives the crew from\n"
        "the command menu (`WCIssueCommand`, `WCEnableCommand`). How buttons are matched:\n"
        "[Combat: commands](../research/combat.md#commands); the orders:\n"
        "[AI: Warrior commands](../research/ai.md#warrior-commands); the buttons: [Controls](controls.md).",
        "complete": "Every trigger kind, every pad command the scripts bind or switch and all seven Warrior commands\n"
        "are listed. What 1, 2, 9, 11, 21, 22 and 37-44 do is not traced, nor the command menu's layout; pad\n"
        "commands the code tests but no script binds are not listed.",
    },
    "script-events": {
        "title": "Script events",
        "source": "every script, SetMsgHandler and GangSetMsgHandler",
        "about": "The messages scripts subscribe to with `SetMsgHandler(object, message, callback)`, and the same\n"
        "messages for a whole gang with `GangSetMsgHandler(gang, message, callback)`: a human's event goes to its\n"
        "own handlers, then to its gang's ([AI: gang events](../research/ai.md#gang-events)). The meaning of a\n"
        "message is read from the names of the callbacks scripts give it.",
        "complete": "Every message number a script uses with either binding is listed; meanings are inferred from\n"
        "callback names.",
    },
    "wad-names": {
        "title": "WAD entry names",
        "source": "name recovery (coney-tools wad names and the WAD survey)",
        "evidence": "confirmed-code",
        "about": "The file names recovered for `WARRIORS.WAD`'s entries. The archive stores only a CRC-32 of\n"
        "`./ee_files/<name>` ([WARRIORS.DIR](../research/formats/wad-dir.md)), so a name is known once a candidate\n"
        "string hashes to an entry. Each name here was checked against its hash.",
        "complete": "{count} of 10,701 names are known; the streamed world and most early entries are still unnamed.",
    },
    **refs_env.STARTERS,
    **refs_play.STARTERS,
}
# The engine lists start from their own module's table (refs_engine.py).
STARTERS.update(refs_engine.STARTERS)
