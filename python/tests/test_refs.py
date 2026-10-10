# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the game reference lists: the Lua 4 reader, the YAML schema, the merge, the pages and the commands.

Everything is synthetic: a hand-assembled Lua 4.0 chunk, a made-up topic and made-up entries.
"""

import struct
from pathlib import Path

import pytest

from coney_tools import lua4, refs, refs_cli, refs_render
from coney_tools.cli import main
from coney_tools.refs import Field, RefList, RefsError, Topic
from coney_tools.refs_topics import TOPICS

# --- a hand-assembled Lua 4.0 chunk ------------------------------------------------------------------------------

_MAXARG_S = ((1 << 26) - 1) >> 1


def _op(name: str, u: int = 0, a: int | None = None, b: int = 0) -> int:
    """One instruction: the opcode in the low 6 bits, then U (or A and B)."""
    code = lua4.OPCODES.index(name)
    if a is not None:
        return code | (b << 6) | (a << 15)
    return code | (u << 6)


def _string(text: str | None) -> bytes:
    """A Lua 4.0 string: a length counting the trailing NUL, 0 for none."""
    if text is None:
        return struct.pack("<I", 0)
    raw = text.encode("latin-1") + b"\0"
    return struct.pack("<I", len(raw)) + raw


def _chunk(strings: list[str], code: list[int]) -> bytes:
    """A whole chunk holding one main function with no parameters, locals, numbers or children."""
    body = _string(None) + struct.pack("<iiBi", 0, 0, 0, 8)
    body += struct.pack("<ii", 0, 0)  # no locals, no line info
    body += struct.pack("<i", len(strings)) + b"".join(_string(s) for s in strings)
    body += struct.pack("<ii", 0, 0)  # no numbers, no child functions
    body += struct.pack("<i", len(code)) + b"".join(struct.pack("<I", word) for word in code)
    return lua4.HEADER + struct.pack("<d", 3.14159265358979e8) + body


# CfgChar(32, "warr_re_cv"); LEVEL = 7
CHUNK = _chunk(
    ["CfgChar", "warr_re_cv", "LEVEL"],
    [
        _op("GETGLOBAL", 0),
        _op("PUSHINT", 32 + _MAXARG_S),
        _op("PUSHSTRING", 1),
        _op("CALL", a=0, b=0),
        _op("PUSHINT", 7 + _MAXARG_S),
        _op("SETGLOBAL", 2),
        _op("END"),
    ],
)


def test_lua4_reads_calls_and_assignments() -> None:
    facts = lua4.walk_chunk(lua4.parse_chunk(CHUNK))
    assert [(call.callee, [lua4.plain(arg) for arg in call.args]) for call in facts.calls] == [
        ("CfgChar", [32, "warr_re_cv"])
    ]
    assert [(item.name, lua4.plain(item.value)) for item in facts.assignments] == [("LEVEL", 7)]
    assert lua4.all_strings(lua4.parse_chunk(CHUNK)) == ["CfgChar", "warr_re_cv", "LEVEL"]


def _proto(strings: list[str], code: list[int], children: list[bytes] | None = None) -> bytes:
    """One function prototype (no parameters, locals or numbers) with the given child prototypes."""
    kids = children or []
    body = _string(None) + struct.pack("<iiBi", 0, 0, 0, 8)
    body += struct.pack("<ii", 0, 0)
    body += struct.pack("<i", len(strings)) + b"".join(_string(s) for s in strings)
    body += struct.pack("<ii", 0, len(kids)) + b"".join(kids)
    return body + struct.pack("<i", len(code)) + b"".join(struct.pack("<I", word) for word in code)


def _int(value: int) -> int:
    """`PUSHINT value`."""
    return _op("PUSHINT", value + _MAXARG_S)


def _facts(main: bytes) -> lua4.ChunkFacts:
    """Walk a chunk whose main function is `main`."""
    return lua4.walk_chunk(lua4.parse_chunk(lua4.HEADER + struct.pack("<d", 3.14159265358979e8) + main))


# function AddWarriors1() HuCreate("Ajax", 11, {1, 2, 0}, 90, nil, 1, g) end; PlayerGang = {AddWarriors1}
STORY_LEVEL = _proto(
    ["AddWarriors1", "PlayerGang"],
    [
        _op("CLOSURE", a=0, b=0),
        _op("SETGLOBAL", 0),
        _op("CREATETABLE", 1),
        _op("GETGLOBAL", 0),
        _op("SETLIST", a=0, b=1),
        _op("SETGLOBAL", 1),
        _op("END"),
    ],
    [
        _proto(
            ["HuCreate", "Ajax", "g"],
            [
                _op("GETGLOBAL", 0),
                _op("PUSHSTRING", 1),
                _int(11),
                _op("CREATETABLE", 3),
                _int(1),
                _int(2),
                _int(0),
                _op("SETLIST", a=0, b=3),
                _int(90),
                _op("PUSHNIL", 1),
                _int(1),
                _op("GETGLOBAL", 2),
                _op("CALL", a=0, b=0),
                _op("END"),
            ],
        )
    ],
)

# fP1 = {AddFlag("fP1_1", {3, 4, 0}, 45, 0, 0)}
RUMBLE_FLAGS = _proto(
    ["AddFlag", "fP1_1", "fP1"],
    [
        _op("CREATETABLE", 1),
        _op("GETGLOBAL", 0),
        _op("PUSHSTRING", 1),
        _op("CREATETABLE", 3),
        _int(3),
        _int(4),
        _int(0),
        _op("SETLIST", a=0, b=3),
        _int(45),
        _int(0),
        _int(0),
        _op("CALL", a=1, b=1),
        _op("SETLIST", a=0, b=1),
        _op("SETGLOBAL", 2),
        _op("END"),
    ],
)


def test_lua4_names_functions_and_keeps_call_arguments() -> None:
    story = _facts(STORY_LEVEL)
    assert story.functions() == {"AddWarriors1": "main/0"}
    assert [table for path, table in story.constructed if path == "main"] == [story.tables["PlayerGang"]]
    flags = _facts(RUMBLE_FLAGS).tables["fP1"].items[1]
    assert isinstance(flags, lua4.CallResult) and flags.callee == "AddFlag"
    assert [lua4.plain(arg) for arg in flags.args] == ["fP1_1", [3, 4, 0], 45, 0, 0]
    assert flags == lua4.CallResult("AddFlag")  # the arguments do not take part in comparisons


def test_level_starts_read_story_checkpoints_and_rumble_flags() -> None:
    from coney_tools.refs_extract import level_starts

    starts = level_starts({"level7.lua": _facts(STORY_LEVEL), "level101_brawl_init.lua": _facts(RUMBLE_FLAGS)})
    assert starts == [
        {
            "id": "level7-1",
            "level": "level7",
            "checkpoint": 1,
            "character": "Ajax",
            "type": 11,
            "pos": [1, 2, 0],
            "heading": 90,
            "via": "HuCreate in AddWarriors1",
            "script": None,
        },
        {
            "id": "level101-brawl",
            "level": "level101",
            "mode": "brawl",
            "pos": [3, 4, 0],
            "heading": 45,
            "via": "flag fP1_1",
            "script": "level101_brawl_init",
        },
    ]


def test_lua4_refuses_other_data() -> None:
    with pytest.raises(lua4.LuaError, match="header"):
        lua4.parse_chunk(b"\x1bLua\x50" + bytes(40))
    with pytest.raises(lua4.LuaError, match="cut short"):
        lua4.parse_chunk(CHUNK[:-6])
    with pytest.raises(lua4.LuaError, match="left after"):
        lua4.parse_chunk(CHUNK + b"\0")


# --- schema, YAML and merge --------------------------------------------------------------------------------------

THINGS = Topic(
    "things",
    "id",
    "thing",
    (
        Field("id", "int", "The id.", "Id", required=True),
        Field("name", "str", "A name.", "Name"),
        Field("hash", "hex", "A hash.", "Hash"),
        Field("size", "float", "A size.", "Size"),
        Field("tags", "list", "Tags.", "Tags"),
        Field("speeds", "dict", "Speeds.", "Speeds"),
        Field("label", "str", "Who it is.", "Who", curated=True),
        Field("friends", "list", "Other things.", "Friends", link="things.md#thing"),
    ),
)


def _things(entries: list[dict[str, object]]) -> RefList:
    """A list of the made-up topic with the given entries."""
    return RefList(
        THINGS, "Things", "About *things*.", "All of them.", {"source": "made up", "evidence": "inferred"}, entries
    )


def test_validate_reports_each_problem() -> None:
    reflist = _things(
        [
            {"id": 1, "name": 5},
            {"id": 1, "colour": "red"},
            {"name": "no id"},
            {"id": 3, "evidence": "probably"},
        ]
    )
    problems = "\n".join(refs.validate(reflist, "things.yaml"))
    assert "name should be str" in problems
    assert "unknown field 'colour'" in problems
    assert "id 1 appears twice" in problems
    assert "no id" in problems
    assert "evidence 'probably' is not one of" in problems
    bare = _things([{"id": 9}])
    bare.defaults = {}
    assert "no source" in "\n".join(refs.validate(bare, "things.yaml"))


def test_dump_and_load_round_trip(tmp_path: Path) -> None:
    entries = [
        {"id": 1, "name": "yes", "hash": 0xDEADBEEF, "size": 1.0, "tags": ["a b", 2], "speeds": {"walk": 1.5}},
        {"id": 2, "name": "0x12", "hash": 0x40, "label": "Has: a colon | and a pipe", "friends": [1]},
        {"id": 3, "name": "plain_name/path.ext", "size": -0.25},
    ]
    path = tmp_path / "things.yaml"
    refs.write(path, _things(entries))
    text = path.read_text(encoding="utf-8")
    assert "hash: 0xdeadbeef" in text and "hash: 0x0040" in text
    assert 'name: "yes"' in text  # a YAML word stays a string
    loaded = refs.load(path, THINGS)
    assert loaded.entries == entries
    assert loaded.about == "About *things*." and loaded.complete == "All of them."
    assert refs.dump(loaded) == text  # canonical: a second write changes nothing


def test_load_refuses_bad_files(tmp_path: Path) -> None:
    path = tmp_path / "things.yaml"
    path.write_text("title: x\nentries: [{id: 1}]\nextra: 1\n", encoding="utf-8")
    with pytest.raises(RefsError, match="unknown top-level keys extra"):
        refs.load(path, THINGS)
    path.write_text("entries: [{id: 1, source: s, evidence: guessed}]\n", encoding="utf-8")
    with pytest.raises(RefsError, match="evidence 'guessed'"):
        refs.load(path, THINGS)
    path.write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(RefsError, match="not a mapping"):
        refs.load(path, THINGS)


_GAP = "  - {family: Cars, what: Parked cars., source: CarSpawn, count: '6', image: none, needs: RE}\n"


def test_load_gaps_reads_families_in_order_and_names_each_problem(tmp_path: Path) -> None:
    path = tmp_path / "still-to-list.yaml"
    path.write_text("families:\n" + _GAP + _GAP.replace("Cars", "Flags") + "excluded: Credits.\n", encoding="utf-8")
    gaps = refs.load_gaps(path)
    assert [family["family"] for family in gaps.families] == ["Cars", "Flags"]
    assert gaps.families[0]["count"] == "6" and gaps.excluded == "Credits."
    path.write_text("families:\n  - {family: Cars, colour: red}\nmore: 1\n", encoding="utf-8")
    with pytest.raises(RefsError) as error:
        refs.load_gaps(path)
    assert "unknown top-level keys more" in str(error.value)
    assert "family Cars: missing what, source, count, image, needs" in str(error.value)
    assert "unknown fields colour" in str(error.value)
    path.write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(RefsError, match="list of families"):
        refs.load_gaps(path)


def test_index_links_entities_and_lists_the_gaps() -> None:
    gaps = refs.Gaps(({name: f"{name} | x" for name in refs.GAP_FIELDS},), "Not these.")
    text = refs_render.index([], bindings_page=True, entities_page=True, gaps=gaps)
    assert "[Entities](entities.md)" in text and "## Still to list {#still-to-list}" in text
    assert "| family \\| x | what \\| x |" in text and "Not these." in text
    plain = refs_render.index([], bindings_page=True)
    assert "entities.md" not in plain and "Still to list" not in plain


def test_index_says_so_when_nothing_is_left_to_list() -> None:
    text = refs_render.index([], bindings_page=True, gaps=refs.Gaps((), ""))
    assert "Every family the scripts use has a list now." in text and "| Family |" not in text


def test_merge_keeps_hand_written_fields_and_entries() -> None:
    old = _things(
        [
            {"id": 1, "name": "old", "size": 2.0, "label": "The first", "evidence": "confirmed-runtime"},
            {"id": 2, "name": "gone from the disc", "label": "Kept"},
        ]
    )
    merged = refs.merge(old, [{"id": 1, "name": "new", "hash": 7}, {"id": 5, "name": "fresh"}])
    assert merged.entries == [
        {"id": 1, "name": "new", "hash": 7, "label": "The first", "evidence": "confirmed-runtime"},
        {"id": 5, "name": "fresh"},
        {"id": 2, "name": "gone from the disc", "label": "Kept"},
    ]
    assert merged.about == old.about


def test_complete_text_counts_the_entries_itself() -> None:
    reflist = _things([{"id": n} for n in range(1500)])
    reflist.complete = "{count} of 10,701 are known."
    assert reflist.complete_text() == "1,500 of 10,701 are known."
    assert "1,500 of 10,701 are known." in refs_render.page(reflist)
    assert refs.validate(reflist, "things.yaml") == []


def test_validate_refuses_a_typed_in_entry_count() -> None:
    reflist = _things([{"id": n} for n in range(1500)])
    for typed in ("All 1,500 are listed.", "All 1500 are listed.", "Every thing (1,500)."):
        reflist.complete = typed
        assert "spells out the entry count (1,500)" in "\n".join(refs.validate(reflist, "things.yaml"))
    for fine in ("All {count} are listed.", "1,500.5 is not a count; 11,500 and 1,5000 are other numbers."):
        reflist.complete = fine
        assert refs.validate(reflist, "things.yaml") == []


def test_validate_leaves_small_counts_alone() -> None:
    reflist = _things([{"id": n} for n in range(5)])
    reflist.complete = "5 of them have a model."
    assert refs.validate(reflist, "things.yaml") == []


# --- pages -------------------------------------------------------------------------------------------------------


def test_page_has_anchors_links_and_schema() -> None:
    page = refs_render.page(_things([{"id": 70000, "name": "a", "label": "Prose *here*", "friends": [1]}]))
    assert page.startswith("# Things\n")
    assert "Do not edit." in page and "About *things*." in page and '!!! info "What is complete"' in page
    assert '<span id="thing-00011170"></span>70000' in page  # large keys anchor as hex
    assert "| `a` |" in page and "| Prose *here* |" in page  # names as code, hand-written text as Markdown
    assert "[1](things.md#thing-1)" in page
    assert "| `label` | str | yes | Who it is. |" in page
    assert "| Hash |" not in page.split("## Sources")[0]  # a column no entry fills is left out


def test_slug_and_cells() -> None:
    assert refs_render.slug("pad-d-pad up") == "pad-d-pad-up"
    assert refs_render.slug(32) == "32"
    assert refs_render.cell(THINGS.field_map()["size"], 1.23456789) == "1.2346"
    assert refs_render.cell(THINGS.field_map()["speeds"], {"walk": 1.5}) == "walk 1.5"
    assert refs_render.cell(THINGS.field_map()["name"], "a|b") == "`a\\|b`"


def test_every_real_topic_has_a_unique_key_and_anchor() -> None:
    assert len({t.key for t in TOPICS}) == len(TOPICS) == len({t.anchor for t in TOPICS})
    for item in TOPICS:
        fields = item.field_map()
        assert item.key_field in fields and fields[item.key_field].required
        assert item.group_by is None or item.group_by in fields
        assert item.key in refs_cli.STARTERS


# --- commands ----------------------------------------------------------------------------------------------------


def _checkout(tmp_path: Path) -> Path:
    """A made-up checkout with an empty list for every real topic."""
    (tmp_path / "coney.local.example.toml").write_text("", encoding="utf-8")
    for item in TOPICS:
        refs.write(tmp_path / refs_cli.REFS_DIR / f"{item.key}.yaml", refs_cli.new_list(item))
    return tmp_path


def test_render_writes_then_check_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(_checkout(tmp_path))
    assert main(["refs", "render", "--check"]) == 1  # no pages yet
    assert main(["refs", "render"]) == 0
    assert main(["refs", "render", "--check"]) == 0
    index = (tmp_path / "docs" / "references" / "index.md").read_text(encoding="utf-8")
    assert "[Characters](characters.md)" in index and "Script bindings" in index
    assert "Still to list" not in index  # this checkout has no still-to-list file
    (tmp_path / refs_cli.GAPS_FILE).write_text("families:\n" + _GAP, encoding="utf-8")
    assert main(["refs", "render", "--check"]) == 1  # the index now lacks the family
    assert main(["refs", "render"]) == 0
    assert "| Cars |" in (tmp_path / "docs" / "references" / "index.md").read_text(encoding="utf-8")
    page = tmp_path / "docs" / "references" / "levels.md"
    page.write_text(page.read_text(encoding="utf-8") + "edited\n", encoding="utf-8")
    assert main(["refs", "render", "--check"]) == 1


def test_render_reports_a_bad_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(_checkout(tmp_path))
    (tmp_path / refs_cli.REFS_DIR / "gangs.yaml").write_text("entries: [{id: x}]\n", encoding="utf-8")
    (tmp_path / refs_cli.REFS_DIR / "levels.yaml").unlink()
    assert main(["refs", "render"]) == 2
    error = capsys.readouterr().err
    assert "id should be int" in error and "levels.yaml: missing" in error


def test_image_cells_point_below_the_images_folder() -> None:
    characters = next(item for item in TOPICS if item.key == "characters")
    cell = refs_render.cell(characters.field_map()["image"], "characters/warr_re_cv.png", "characters")
    assert cell == '![characters/warr_re_cv.png](images/characters/warr_re_cv.png){ width="96" }'


def test_an_object_gets_its_thumbnail_only_when_the_file_exists(tmp_path: Path) -> None:
    from coney_tools.refs_extract import _image

    (tmp_path / "objects").mkdir()
    (tmp_path / "objects" / "dyn_bat.png").write_bytes(b"png")
    assert _image(tmp_path, "objects", "dyn_bat") == "objects/dyn_bat.png"
    assert _image(tmp_path, "objects", "dyn_door") is None
    assert _image(None, "objects", "dyn_bat") is None
    objects = next(item for item in TOPICS if item.key == "objects")
    assert "image" in objects.field_map()


def test_compress_image_keeps_size_and_alpha_and_is_deterministic(tmp_path: Path) -> None:
    """A thumbnail becomes a palette PNG of the same size, keeps its transparency and compresses the same twice."""
    from PIL import Image

    from coney_tools.refs_cli import compress_image

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for x in range(16, 48):
        for y in range(8, 56):
            image.putpixel((x, y), (x * 5, y * 4, 120, 255))
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    image.save(first, compress_level=0)  # stored, as large as a render is for its size
    image.save(second, compress_level=0)
    compress_image(first)
    compress_image(second)
    assert first.read_bytes() == second.read_bytes()
    with Image.open(first) as result:
        assert result.mode == "P"
        assert result.size == (64, 64)
        rgba = result.convert("RGBA")
        assert rgba.getpixel((0, 0)) == (0, 0, 0, 0)
        pixel = rgba.getpixel((32, 32))
        assert isinstance(pixel, tuple)
        assert pixel[3] == 255


def test_compress_image_leaves_a_file_the_palette_would_not_shrink(tmp_path: Path) -> None:
    """A tiny icon stays as it was: a 256-colour palette would outweigh its few pixels."""
    from PIL import Image

    from coney_tools.refs_cli import compress_image

    icon = tmp_path / "icon-69.png"
    Image.new("RGBA", (4, 4), (200, 30, 30, 255)).save(icon, optimize=True)
    original = icon.read_bytes()
    before, after = compress_image(icon)
    assert before == after == len(original)
    assert icon.read_bytes() == original


def test_texture_size_reads_the_first_native_texture() -> None:
    """A made-up PS2 native texture: platform, name and mask strings, then the raster's struct with its size."""
    from coney_tools.refs_extract import _texture_size

    # One RenderWare section: type, size, version stamp, body.
    def section(kind: int, body: bytes) -> bytes:
        return struct.pack("<3I", kind, len(body), 0x1C02000A) + body

    raster = section(1, section(1, struct.pack("<3I", 512, 256, 8)))
    data = b"junk" + b"PS2\0" + struct.pack("<I", 0x1106) + section(2, b"sheet\0\0\0") + section(2, b"\0" * 4) + raster
    assert _texture_size(data, 0, len(data)) == (512, 256)
    assert _texture_size(b"no texture here", 0, 15) is None
