# WARRIORS.DIR / WARRIORS.WAD

The game's assets live in one archive, `WARRIORS.WAD` (1,495,371,776 bytes on the NTSC-U disc), indexed by
`WARRIORS.DIR` (128,428 bytes). Loaded by `DVDWadIndex` (`c:/Warriors/Source/Device/ps2/fileio/DVDWadIndexPS2.cpp`).

## WARRIORS.DIR

All values little-endian.

```c
struct WadDirHeader {
    uint32_t count;      // 10701 on NTSC-U
    uint8_t  pad[12];    // zero; the game seeks to 0x10 before reading entries
};

struct WadDirEntry {     // 12 bytes, `count` of them, sorted by wadOffset
    uint32_t wadOffset;  // byte offset into WARRIORS.WAD, 2048-aligned
    uint32_t size;       // byte size
    uint32_t nameHash;   // CRC32 of the lowercased path, see below
};
```

Check: `16 + 10701 × 12 = 128,428` = file size.

**Confidence:** confirmed from code. The constructor at `0x149160` reads `count`, seeks to `0x10`, allocates
`count * 12` bytes and reads the entry table.

## Name lookup

`DVDWadIndex::Find` (`0x1490b8`):

1. Lowercase the name in place (`0x143fd8`).
2. `hash = crc32(name)` (`0x143f68`). This is standard CRC-32, see [Name hashing](../name-hash.md).
3. Linear scan of the entries for `nameHash == hash`.

Names are paths of the form **`./ee_files/<basename>`**, built by `"./ee_files/" + name` at `0x148aa0` / `0x148ba8`.
The folder is flat: there are no subdirectories under `ee_files/`.

Example: `./ee_files/global.lua` → `0x7e23a6f2`.

**Recovered names:** 6,313 of 10,701 (2026-10-10), from strings in the ELF and inside WAD files, the names
scene records carry, level-number patterns and the world loader's format strings; how, and which kinds are still
unnamed, is in [WAD contents](wad-contents.md#names), and the list is
[WAD entry names](../../references/wad-names.md). Entries from index 3,615 on are stored in ASCII order of the
upper-cased name, which rules out chance matches.

## Entry contents

[WAD contents](wad-contents.md) classifies every entry and describes the chunk container most of them use (packs,
resources and typed chunks). Per-type format pages will be added as each type is decoded.

## Coney's implementation

The engine reads the index with `coney::io::WadIndex` (`src/fileio/wad_index.h`) and the archive with
`coney::io::Wad` (`src/fileio/wad.h`), from a disc folder or an ISO image (`src/fileio/disc.h`);
`coney --disc <disc> --load <entry>` uses them (see [File I/O](../file-io.md)). They make the same two checks as the
Python parser below.

`python/src/coney_tools/wad.py` parses `WARRIORS.DIR` (`parse_dir`), hashes names (`name_hash`), extracts entries
and recovers names; `disc.py` reads the files from a folder or an ISO 9660 image; `wad_cli.py` holds the
`coney-tools wad` commands. How to run them: [The coney-tools command line](../../guides/coney-tools.md).

Name recovery (`coney-tools wad names`) scans printable file-name-like strings (path characters followed by one or
more `.ext` parts) in `SLUS_212.15` and in every WAD entry, hashes each as `./ee_files/<last path component>` and
as written, and keeps those that match an entry's hash. It recovered 414 of 10,701 names on the NTSC-U disc
(2026-10-04). The parser rejects a `WARRIORS.DIR` whose size is not `16 + count x 12` and an entry that ends past
the end of the WAD; the game itself does neither check as far as these pages record.

## Open questions

- Is the whole disc one flat root (`SLUS_212.15`, `WARRIORS.DIR`, `WARRIORS.WAD` and the other files), or does the
  game read any file from a subdirectory? The ISO reader only reads the root directory.
- Do names ever hash without the `./ee_files/` prefix, for example names built by other callers of the hash? The
  recovery tries both forms, but this page only documents the prefixed one.
- Why do many entries have no name in any string on the disc? The [WAD contents](wad-contents.md#names) survey
  recovers 3,990 by also using scene records' own names, level-number patterns and the archive's name order (not
  yet in `coney-tools wad names`); the rest, notably the streamed world and entries 0-3,614, probably have names
  built at run time.
