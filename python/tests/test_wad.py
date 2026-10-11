# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the wad commands and the ISO reader, on tiny synthetic archives with made-up names and contents."""

import struct
import zlib
from pathlib import Path

import pytest

from coney_tools import wad, wad_cli
from coney_tools.cli import main
from coney_tools.config import ConfigError
from coney_tools.disc import SECTOR, Disc

# The made-up archive: three named files, then an unnamed fourth (hash 0xDEADBEEF) whose bytes mention gamma.txt.
FILES = {"alpha.lua": b"\x1bLua-made-up-alpha", "beta.dat": b"\x01\x00\x00\x00beta", "gamma.txt": b"gamma text"}
HIDDEN = b"\x02\x00\x00\x00 refers to gamma.txt"


def h(name: str) -> int:
    """The name hash of a bare file name, written out independently of `wad.name_hash`."""
    return zlib.crc32(("./ee_files/" + name).encode())


def build_archive() -> tuple[bytes, bytes, list[tuple[str, int]]]:
    """Return (dir bytes, wad bytes, [(label, hash)]) for the made-up archive; entries are 2048-aligned."""
    items = [(h(name), data) for name, data in FILES.items()] + [(0xDEADBEEF, HIDDEN)]
    wad_bytes = b""
    entries = b""
    for hashed, data in items:
        entries += struct.pack("<III", len(wad_bytes), len(data), hashed)
        wad_bytes += data + b"\0" * (-len(data) % SECTOR)
    return struct.pack("<I12x", len(items)) + entries, wad_bytes, [(n, h(n)) for n in FILES]


def make_folder(root: Path) -> Path:
    """A disc folder holding the made-up archive and executable."""
    directory, wad_bytes, _ = build_archive()
    root.mkdir()
    (root / "WARRIORS.DIR").write_bytes(directory)
    (root / "WARRIORS.WAD").write_bytes(wad_bytes)
    # A made-up executable that mentions two of the names (and one that is not in the archive).
    (root / "SLUS_212.15").write_bytes(b"\0\0load alpha.lua\0\0data\\beta.dat\0noise\0missing.xyz\0")
    return root


def dir_record(name: bytes, extent: int, size: int, flags: int = 0) -> bytes:
    """One ECMA-119 directory record, padded to an even length, with both-endian extent and size."""
    length = 33 + len(name) + (len(name) + 1) % 2
    record = bytearray(length)
    record[0] = length
    struct.pack_into("<I", record, 2, extent)
    struct.pack_into(">I", record, 6, extent)
    struct.pack_into("<I", record, 10, size)
    struct.pack_into(">I", record, 14, size)
    record[25] = flags
    record[32] = len(name)
    record[33 : 33 + len(name)] = name
    return bytes(record)


def make_iso(path: Path, files: dict[str, bytes], pad_directory: bool = False) -> Path:
    """Write a minimal ISO 9660 image: system area, a volume descriptor at sector 16, a root directory, then files."""
    root_extent = 18
    extents: dict[str, int] = {}
    root_sectors = 2 if pad_directory else 1
    cursor = root_extent + root_sectors
    for name, data in files.items():
        extents[name] = cursor
        cursor += -(-len(data) // SECTOR)
    root_size = root_sectors * SECTOR
    records = dir_record(b"\x00", root_extent, root_size, 2) + dir_record(b"\x01", root_extent, root_size, 2)
    records += dir_record(b"SUBDIR", 99, SECTOR, 2)
    if pad_directory:
        records = records.ljust(SECTOR, b"\0")  # a record never spans sectors, so the sector is padded out
    for name, data in files.items():
        records += dir_record(f"{name};1".encode(), extents[name], len(data))
    root_sector = records.ljust(root_size, b"\0")
    pvd = bytearray(SECTOR)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    struct.pack_into("<H", pvd, 128, SECTOR)
    pvd[156:190] = dir_record(b"\x00", root_extent, root_size, 2)[:34]
    image = bytearray(SECTOR * 16) + pvd + bytearray(SECTOR) + root_sector
    for data in files.values():
        image += data + b"\0" * (-len(data) % SECTOR)
    path.write_bytes(bytes(image))
    return path


def make_iso_disc(path: Path) -> Path:
    """An ISO image holding the made-up archive and executable."""
    directory, wad_bytes, _ = build_archive()
    return make_iso(
        path,
        {
            "WARRIORS.DIR": directory,
            "WARRIORS.WAD": wad_bytes,
            "SLUS_212.15": b"\0\0load alpha.lua\0\0data\\beta.dat\0noise\0missing.xyz\0",
        },
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake checkout (with a game_dir configured) as the working directory."""
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "coney.local.example.toml").write_text("", encoding="utf-8")
    (root / "coney.local.toml").write_text(f'game_dir = "{(tmp_path / "disc").as_posix()}"\n', encoding="utf-8")
    monkeypatch.chdir(root)
    return root


# --- parsing and hashing ---


def test_name_hash_lowercases() -> None:
    assert wad.name_hash("./ee_files/Global.LUA") == zlib.crc32(b"./ee_files/global.lua")


def test_parse_dir() -> None:
    """Entries come out in file order with their hashes, offsets and sizes."""
    directory, wad_bytes, _ = build_archive()
    entries = wad.parse_dir(directory, len(wad_bytes))
    assert [e.hash for e in entries][:3] == [h(n) for n in FILES]
    assert entries[1].offset == SECTOR and entries[1].size == len(FILES["beta.dat"])


def test_parse_dir_truncated_header() -> None:
    with pytest.raises(ConfigError, match="truncated"):
        wad.parse_dir(b"\x01\x00")


def test_parse_dir_count_mismatch() -> None:
    directory, _, _ = build_archive()
    with pytest.raises(ConfigError, match="header says 4 entries"):
        wad.parse_dir(directory[:-5])


def test_parse_dir_entry_past_end_of_wad() -> None:
    directory, wad_bytes, _ = build_archive()
    with pytest.raises(ConfigError, match=r"entry 3 .*past the end"):
        wad.parse_dir(directory, len(wad_bytes) - SECTOR - 1)


def test_hash_names_adds_the_prefix_and_ignores_it() -> None:
    table = wad.hash_names(["alpha.lua", "./ee_files/beta.dat", "café.txt"])
    assert table[h("alpha.lua")] == "alpha.lua"
    assert table[h("beta.dat")] == "beta.dat"
    assert len(table) == 3


def test_load_names_skips_comments(tmp_path: Path) -> None:
    names = tmp_path / "names.txt"
    names.write_text("# comment\n\nalpha.lua\n", encoding="utf-8")
    assert wad.load_names(names) == wad.hash_names(["alpha.lua"])
    with pytest.raises(ConfigError, match="cannot be read"):
        wad.load_names(tmp_path / "missing.txt")


def test_harvest_matches_across_a_chunk_edge() -> None:
    found: dict[int, str] = {}
    wad.harvest([b"xx\0alp", b"ha.lua\0yy"], {h("alpha.lua"): ""}, found)
    assert found == {h("alpha.lua"): "alpha.lua"}


# --- the ISO reader ---


def test_iso_reader_reads_root_files(tmp_path: Path) -> None:
    disc = Disc(make_iso(tmp_path / "t.iso", {"HELLO.TXT": b"hello", "BIG.BIN": b"x" * 5000}, pad_directory=True))
    assert disc.has("hello.txt") and disc.has("HELLO.TXT;1") and not disc.has("SUBDIR")
    assert disc.size("BIG.BIN") == 5000
    with disc.open("HELLO.TXT") as handle:
        assert handle.read() == b"hello"
    with disc.open("BIG.BIN") as handle:
        handle.seek(4990)
        assert handle.read(100) == b"x" * 10


def test_iso_reader_rejects_other_files(tmp_path: Path) -> None:
    junk = tmp_path / "junk.iso"
    junk.write_bytes(b"\0" * (SECTOR * 20))
    with pytest.raises(ConfigError, match="not an ISO 9660"):
        Disc(junk)
    with pytest.raises(ConfigError, match="not a folder or an ISO"):
        Disc(tmp_path / "nothing")


def test_disc_missing_file(tmp_path: Path) -> None:
    """Opening a file the disc root lacks raises a ConfigError naming it."""
    disc = Disc(make_iso(tmp_path / "t.iso", {"A.BIN": b"a"}))
    with pytest.raises(ConfigError, match=r"no WARRIORS\.DIR"):
        disc.open("WARRIORS.DIR")


# --- commands ---


@pytest.mark.parametrize("kind", ["folder", "iso"])
def test_info_and_list(kind: str, tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`wad info` and `wad list` give the same results from a folder and from an ISO image."""
    disc = make_folder(tmp_path / "d") if kind == "folder" else make_iso_disc(tmp_path / "d.iso")
    names = tmp_path / "names.txt"
    names.write_text("alpha.lua\n", encoding="utf-8")
    assert main(["wad", "info", str(disc), "--names", str(names)]) == 0
    out = capsys.readouterr().out
    assert "entries: 4" in out and "'\\x1bLua'" not in out
    assert "names known: 1 of 4" in out
    assert main(["wad", "list", str(disc), "--names", str(names)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["0", "0", str(len(FILES["alpha.lua"])), f"{h('alpha.lua'):08x}", "alpha.lua"]
    assert lines[3].split()[-1] == "deadbeef"


class _ClosedStdout:
    """A stdout whose reader has gone, failing the way a closed pipe does on Windows (EINVAL, not EPIPE)."""

    def write(self, text: str) -> int:
        raise OSError(22, "Invalid argument")

    def flush(self) -> None:
        pass


def test_list_into_a_closed_pipe_stops_quietly(tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    disc = make_folder(tmp_path / "d")
    monkeypatch.setattr("sys.stdout", _ClosedStdout())
    with pytest.raises(wad_cli.OutputClosedError):
        wad_cli.run_list(str(disc), None)


def test_info_uses_game_dir_default(tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_folder(tmp_path / "disc")
    assert main(["wad", "info"]) == 0
    assert "entries: 4" in capsys.readouterr().out


def test_info_without_game_dir_is_exit_2(tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "coney.local.toml").write_text('game_dir = ""\n', encoding="utf-8")
    assert main(["wad", "info"]) == 2
    assert "game_dir" in capsys.readouterr().err


def test_malformed_dir_is_exit_2(tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    disc = make_folder(tmp_path / "d")
    (disc / "WARRIORS.DIR").write_bytes(b"\x05\x00\x00\x00")
    assert main(["wad", "list", str(disc)]) == 2
    err = capsys.readouterr().err
    assert "truncated" in err and "Traceback" not in err and err.count("\n") == 1


def test_extract_names_and_only(tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Extracted files take a known name or `<hash>.bin`; `--only` takes hashes and names."""
    disc = make_folder(tmp_path / "d")
    names = tmp_path / "names.txt"
    names.write_text("alpha.lua\n", encoding="utf-8")
    out = tmp_path / "out"
    assert main(["wad", "extract", str(disc), str(out), "--names", str(names)]) == 0
    assert (out / "alpha.lua").read_bytes() == FILES["alpha.lua"]
    assert (out / f"{h('beta.dat'):08x}.bin").read_bytes() == FILES["beta.dat"]
    assert (out / "deadbeef.bin").read_bytes() == HIDDEN
    assert "extracted 4 entries" in capsys.readouterr().out

    only = tmp_path / "only"
    assert main(["wad", "extract", str(disc), str(only), "--only", f"{h('beta.dat'):08x}", "gamma.txt"]) == 0
    assert sorted(p.name for p in only.iterdir()) == sorted([f"{h('beta.dat'):08x}.bin", f"{h('gamma.txt'):08x}.bin"])


def test_extract_unknown_only_is_exit_2(tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    disc = make_folder(tmp_path / "d")
    assert main(["wad", "extract", str(disc), str(tmp_path / "out"), "--only", "nope.bin"]) == 2
    assert "no entry" in capsys.readouterr().err


def test_extract_refuses_a_folder_inside_the_repository(
    tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    disc = make_folder(tmp_path / "d")
    assert main(["wad", "extract", str(disc), str(repo / "out")]) == 2
    assert "inside the repository" in capsys.readouterr().err
    assert not (repo / "out").exists()
    assert main(["wad", "extract", str(disc), "relative-out"]) == 2  # relative to the checkout cwd


def test_names_recovers_from_elf_and_wad(tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    disc = make_folder(tmp_path / "d")
    out = tmp_path / "found.txt"
    assert main(["wad", "names", str(disc), str(out)]) == 0
    assert "recovered 3 of 4 names" in capsys.readouterr().out
    assert out.read_text(encoding="utf-8").splitlines() == ["alpha.lua", "beta.dat", "gamma.txt"]


def test_names_refuses_an_output_file_inside_the_repository(
    tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    disc = make_folder(tmp_path / "d")
    assert main(["wad", "names", str(disc), str(repo / "names.txt")]) == 2
    assert "inside the repository" in capsys.readouterr().err


def test_names_finds_names_inside_wad_entries_without_an_elf(tmp_path: Path, repo: Path) -> None:
    disc = make_folder(tmp_path / "d")
    (disc / "SLUS_212.15").unlink()
    entries = wad.load_entries(Disc(disc))
    assert wad.recover_names(Disc(disc), entries) == {h("gamma.txt"): "gamma.txt"}


def test_too_many_paths_is_exit_2(tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["wad", "names", "a", "b", "c"]) == 2
    assert "too many arguments" in capsys.readouterr().err


def test_streamed_world_names_apply_the_loader_formats_to_level_stems() -> None:
    names = ["level7s_sec.wld", "level7s_sec.mem", "level7s_ms3.sec", "level12d_ms0.sec"]
    found = wad.streamed_world_names([], [wad.name_hash(wad.NAME_PREFIX + name) for name in names])
    assert sorted(found.values()) == sorted(names)


def test_streamed_world_names_try_the_given_stems_and_ignore_other_hashes() -> None:
    hashes = [wad.name_hash(wad.NAME_PREFIX + "arena_sec.wld"), 0x12345678]
    assert wad.streamed_world_names(["arena"], hashes) == {hashes[0]: "arena_sec.wld"}
    assert wad.streamed_world_names([], hashes) == {}


def test_world_file_pattern_matches_only_a_worlds_own_files() -> None:
    assert all(wad.WORLD_FILE.search(name) for name in ("a_ms12.sec", "a_sec.wld", "A_SEC.MEM"))
    assert not any(wad.WORLD_FILE.search(name) for name in ("a.scn", "a_sec.lua", "ms12.sec"))
