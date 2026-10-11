# WAD contents

Verified against: `SLUS_212.15` (NTSC-U, SHA1 `e9cb2cc49aa046b9e494313dce2f5038ed17b2f4`) and the `WARRIORS.WAD` /
`WARRIORS.DIR` on the same disc. No runtime claims. Survey date 2026-10-04.

## Purpose

What the 10,701 entries of `WARRIORS.WAD` are, how the common container around most of them is laid out, and how
many of their names can be recovered. It is the map for the per-format pages that follow: each content kind below
gets its own page when it is decoded. How entries are found by name is on [WARRIORS.DIR / .WAD](wad-dir.md).

Unless a claim says otherwise, it comes from reading the game's data, not its code: its level is **inferred**, and
the corroboration is a count over the whole archive. All values are little-endian.

## Original structure

The container is the game's **chunk system** (`c:/Warriors/Source/Core/ChunkSystem.cpp`, from the executable's
assertion strings). The executable holds a table naming every chunk type, which is where the type names below come
from:

| Address | What | Evidence |
| --- | --- | --- |
| `0x0050b2e0` | Chunk-type table: 84 records of 12 bytes, `{const char* name, u32 a, u32 b}`, for types `0x00`–`0x53`, ended by a record of three `0xffffffff` | read from the executable's data; that a chunk's type indexes it is inferred (below) |

Fields `a` and `b` are addresses in `.text` (or zero). `b` is set only on the types that carry RenderWare streams
(`0x09`, `0x25`, `0x47` share one value, `0x0b`, `0x15` and `0x2a` have their own), so `b` is probably the stream
reader and `a` some other per-type handler. The code has since confirmed this: `b` (`+8`) reads the chunk from the
stream itself and `a` (`+4`) is an "on loaded" handler; see [Chunk system](../chunk-system.md#chunk-type-table).

## Data

### Kinds of entry

Every entry falls into exactly one of these kinds. "Named" counts entries whose name is recovered (see
[Names](#names)).

| Kind | Entries | Bytes | Named | What it is |
| --- | ---: | ---: | ---: | --- |
| Pack (`.pak`) | 881 | 671,648,576 | 236 | A list of resources, see [Packs](#packs) |
| Resource: models and textures | 3,615 | 157,810,784 | 0 | One [resource](#common-resource-shapes): a texture dictionary, a model or a character (entries 0–3,614) |
| Resource: animation (`.anm`) | 564 | 2,600,960 | 563 | Animation keyframes plus a descriptor (chunk types `0x00` + `0x02`) |
| Resource: level (`.lev`) | 64 | 31,902,768 | 64 | Level header, world, collision, paths and level props; see [Level files](#level-files) |
| Resource: global (`.glr`) | 2 | 1,677,296 | 1 | Game-wide lists: sounds, music, characters, objects, particles, anims, dependencies |
| Resource: scene list (`.cnk`) | 1 | 66,400 | 1 | One chunk of type `0x43` "Scene List" |
| Scene record (`.scn`) | 2,765 | 197,667,392 | 2,760 | Scripted scenes and cutscenes, see [Scene records](#scene-records) |
| Sector atomics (`_ms<i>.sec`) | 1,911 | 310,714,060 | 1,910 | One part of a streamed world: RenderWare atomics for its sectors, see [Level files](#level-files) |
| World stream (`_sec.wld`) | 159 | 70,177,584 | 158 | `u32 n` + RenderWare texture dictionary + RenderWare world |
| Stream manifest (`_sec.mem`) | 159 | 14,420 | 158 | Sizes of one world stream and its parts |
| Lua 4.0 bytecode (`.lua`) | 467 | 10,379,282 | 356 | Game scripts, see [Lua](#lua) |
| Object list (`_objs.txt`) | 63 | 1,111,944 | 63 | Text: a count, then one `{name {x, y, z ...}}` line per dynamic object or particle emitter; 26 hold only a zero count |
| Sound bank (`.msb`) | 21 | 27,360,592 | 20 | PS2 ADPCM (VAG) data, no header ([Audio data](audio.md#banks)) |
| Sound bank index (`.msd`) | 21 | 21,568 | 20 | `{u32 hash, u32 offset}` pairs into the matching `.msb`, ended by a zero pair |
| Older RenderWare streams | 5 | 1,395,507 | 0 | RenderWare streams stamped `0x1803FFFF` (3.6.0.3) instead of the usual `0x1C02000A` |
| Font metrics (`.met`) | 1 | 2,625 | 1 | `cn12.met`: text beginning `METRICS1`, pixel rectangles of the characters 32-126 in `cn12.bmp`; unused by the PS2 code ([GUI](../gui.md#the-metrics1-file)) |
| Memory card icon (`.ico`) | 1 | 79,128 | 1 | PS2 icon, magic `00 00 01 00` |
| Bitmap (`.bmp`) | 1 | 98,358 | 1 | `cn12.bmp`: a 256 × 128, 24-bit Windows bitmap (`BM`), the glyphs of `cn12.met`; first counted as a sound bank |
| **Total** | **10,701** | **1,484,729,244** | **6,313** | The rest of the 1,495,371,776-byte WAD is padding |

**Evidence:** inferred. Every entry is assigned by a structural test that must consume the whole entry (the
container parse below, an exact RenderWare section walk, the Lua header, the `.msd` pair layout); none falls through.

### Layout of the WAD

Every entry starts on a 2,048-byte boundary and the gap to the next entry is less than 2,048 bytes of padding.
The entries form two blocks:

- **Entries 0–3,614**: 3,615 resources (1,509 texture dictionaries, 1,324 models, 576 texture dictionaries with a
  `0x4c` chunk, 153 models with bone offsets and 53 characters). Their WAD names are **decimal numbers**: the
  CRC-32 of the resource's name, printed with `%u` (the code that loads the legal screen builds its file name this
  way, `0x00159c08`; see [Graphics](../graphics.md#first-screen)). For 3,599 of the 3,615 the number is the resource
  header's `nameHash`; the other 16 are texture dictionaries whose name hash differs. Digits sort before letters, so
  this block is just the start of the one name order below: the 3,599 decimal names are in ascending ASCII order.
- **Entries 3,615–10,700**: everything else, **sorted by name** in ASCII order of the upper-cased name (so `_`
  sorts after letters). All 6,313 recovered names in this block are in that order with no exception, which makes
  the order a strong filter against false matches when recovering names.

**Evidence:** inferred.

### Chunk container {#chunk-container}

5,127 entries (881 packs and 4,246 standalone resources) use 16-byte headers of one shape, `{u32, u32, u32 zero,
u32 hash}`, at three levels.

```c
struct ChunkHeader {         // 16 bytes; data follows immediately
    uint32_t type;           // index into the chunk-type table at 0x0050b2e0
    uint32_t size;           // bytes of data after this header; always a multiple of 16
    uint32_t zero;           // 0 in every chunk
    uint32_t hash;           // see "Hashes" below
};

struct ResourceHeader {      // 16 bytes, then `count` chunks back to back
    uint32_t count;          // number of chunks, 1 to 1,190 seen
    uint32_t dataSize;       // sum of the chunks' `size` fields: the 16-byte chunk headers are NOT counted
    uint32_t zero;
    uint32_t nameHash;       // CRC-32 of the resource's name, see below
};

struct PackHeader {          // 16 bytes, then `count` resources back to back
    uint32_t count;          // number of resources, 2 to 351 seen
    uint32_t size;           // entry size - 16: here the nested headers ARE counted
    uint32_t zero;
    uint32_t marker;         // 0xDE686795 = crc32("package")
};
```

- A **pack** is told apart by its marker. Its `count` is a resource count, not a type.
- A **resource** has `count` chunks; its `dataSize` is the payload it will occupy once the headers are stripped,
  which suggests the loader allocates `dataSize` and copies each chunk's data in.
- Chunks do not nest: a chunk's data is raw bytes or a RenderWare stream, never another chunk header.
- There is no padding between chunks or resources (every chunk `size` is already a multiple of 16).

**Evidence:** inferred. All 881 packs and all 4,246 standalone resources parse to exactly their entry size with
these rules; every pack's `size` equals entry size minus 16; every resource's `dataSize` equals the sum of its
chunks' sizes; all 109,094 chunks have `zero == 0` and a size that is a multiple of 16. That `0xDE686795` is
`crc32("package")` is a computed fact; that the game checks it is not yet read in the code.

### Hashes

All hashes are standard CRC-32 ([Name hashing](../name-hash.md)), but unlike the WAD index they are **not
lowercased** and carry no `./ee_files/` prefix:

- A resource's `nameHash` is the CRC-32 of its name as the tools spelled it: animation resources hash
  `<anim>.anm` (442 of 564 match the lowercase WAD name exactly; the rest differ only in letter case), level
  resources hash `level<N>` (30 matched), texture dictionaries a bare name with no extension (about 580 matched).
  Models hash `<name>_geo` (`car_osedan_geo`, `dyn_bat_geo`), named by the [Object List](#object-list).
- Chunk type `0x00` (animation keyframes) hashes `<anim>.anm.b.cnk` (1,132 matched), the name of the tool's
  intermediate file. The descriptor (`0x02`) still holds a truncated copy of that file name after its own name.
- In models and texture dictionaries the chunk hash usually equals the resource hash (`0x47`: 18,894 of 21,456;
  `0x2a`: 17,988 of 18,244). In the level and global resources each chunk has its own hash.

About 1,170 of the 4,211 distinct resource hashes are matched to a name so far.

**Evidence:** inferred, from the matches counted above.

### Chunk types

All types seen, with the name the executable's table gives each index. Counts are over every resource in every
pack and standalone entry (43,143 resources, 109,094 chunks); a model shared by several packs is counted each time.

| Type | Table name | Chunks | Data bytes | Size | Seen in |
| --- | --- | ---: | ---: | --- | --- |
| `0x00` | Anim Rot Keyframes | 31,274 | 135,986,000 | 32–70,672 | Animations: the keyframe data |
| `0x02` | Anim Data | 31,274 | 2,501,920 | always 80 | Animations: descriptor holding the anim's name |
| `0x03` | Collision Mesh | 64 | 10,240 | always 160 | Levels |
| `0x04` | Collision Triangles | 64 | 1,506,080 | varies | Levels |
| `0x05` | Collision Grid | 64 | 1,144,560 | varies | Levels |
| `0x06` | Collision Strings | 64 | 847,408 | varies | Levels |
| `0x07` | Collision Vertex Buffer | 64 | 1,508,704 | varies | Levels |
| `0x08` | Character Data | 1,209 | 3,520,608 | always 2,912 | Characters, with `0x45` |
| `0x15` | Sector BSP Data | 64 | 645,104 | varies | Levels: a RenderWare world (section `0x0B`) |
| `0x17` | Level Header | 64 | 3,072 | always 48 | Levels |
| `0x28` | Chunk Bone Offsets | 2,370 | 1,289,280 | always 544 | After a `0x47` model that has a skeleton |
| `0x29` | Static Sounds | 2 | 1,218,992 | | Global resources |
| `0x2a` | Renderware Texture Dic | 18,244 | 330,158,928 | 560–263,584 | RenderWare texture dictionary (section `0x16`) |
| `0x31` | Music | 2 | 71,776 | | Global resources |
| `0x40` | PathData | 64 | 5,482,576 | varies | Levels |
| `0x43` | Scene List | 1 | 66,368 | | `scene_list.cnk` |
| `0x44` | Character List | 2 | 34,784 | | Global resources |
| `0x45` | Anim Range List | 1,209 | 13,985,712 | always 11,568 | Characters, with `0x08` |
| `0x46` | Object List | 2 | 101,280 | | Global resources |
| `0x47` | Preinstance Object | 21,456 | 362,373,184 | 960–339,840 | RenderWare clump (section `0x10`): a model |
| `0x48` | Sound Command Data | 2 | 2,464 | | Global resources |
| `0x49` | Sound Material Data | 2 | 7,968 | | Global resources |
| `0x4c` | Particle Page | 1,335 | 135,600 | 48–5,968 | After a `0x2a` texture dictionary |
| `0x4d` | Particle Page Header | 2 | 9,248 | | Global resources |
| `0x4e` | Anim List | 2 | 9,056 | | Global resources |
| `0x4f` | Dependency List | 2 | 221,408 | | Global resources |
| `0x51` | Subtitles | 64 | 386,784 | varies | Levels |
| `0x52` | Collision Checked | 64 | 19,376 | varies | Levels |
| `0x53` | Occluders | 64 | 8,416 | varies | Levels |

The other 55 types in the table (string tables, particles, game objects, path grids, image palettes, subway map,
fonts, scene animation and more) do not occur as chunks in this WAD.

Several fixed-size chunks begin with a word that is an address inside `.text`, the same in every instance of the
type: `0x0045de40` (`0x02`), `0x00436b10` (`0x08`), `0x00421620` (`0x03`), `0x00409070` (`0x17`), `0x00421798`
(`0x4c`). They look like pointers written into the data when it was built, overwritten or ignored on load.

**Evidence:** inferred. That a chunk's `type` indexes the table at `0x0050b2e0` is supported by every type whose
content is recognisable: `0x15` holds a RenderWare world, `0x2a` a texture dictionary, `0x47` a clump, `0x28` a
fixed-size block beside skinned clumps, `0x00`/`0x02` animations, and the types in the global resource are its
sound, music and list types. The loaders at `0x00144180` and `0x00144398` index the table by `type`: confirmed
(code), see [Chunk system](../chunk-system.md#container-layout).

### Common resource shapes

| Chunks | Resources | Where |
| --- | ---: | --- |
| `0x47` (model) | 17,570 in packs, 1,324 standalone | Props and objects |
| `0x2a` (textures) | 15,144 in packs, 1,509 standalone | Texture dictionaries |
| `0x00` + `0x02` (animation) | 2,051 in packs, 564 standalone | Animations |
| `0x47` + `0x28` (skinned model) | 2,217 in packs, 153 standalone | Characters' bodies |
| `0x2a` + `0x4c` | 759 in packs, 576 standalone | Texture dictionaries with a particle page; includes the loading screens and screenshots |
| `0x00`, `0x02` ... `0x08`, `0x45` (character) | 1,156 in packs, 53 standalone | A character: its animations, data and anim ranges |
| 18 chunks, `0x53`, `0x2a`, `0x47` ... | 64 | Levels (`.lev`) |

### Object List (chunk `0x46`) {#object-list}

One chunk in `warriors.glr`, kept by `0x00181170` at resource manager `+0x8c` (count `+0x90`, records `+0x94`;
confirmed (code)): a 16-byte header whose first word is the count (1,406; the other three are 0), then 36-byte
records of nine words, found by `+0x00` (`0x001811b0`) and loaded as an object's model
([Objects: the model](../objects.md#models); confirmed (code) at `0x00180f58`, `0x001809c0`, `0x003a4d10`). Disc
counts (2026-10-06):

| Offset | Meaning | Evidence (disc) |
| --- | --- | --- |
| `+0x00` | CRC-32 of the object type's name, lower case (`car_osedan`, `dyn_bat`) | 1,293 of the 1,371 `CfgObj` types and the six car types have a record |
| `+0x04` | 0, or another record's name hash: the **next model** a damaged object swaps to (`0x003a4d10`, called by `DoorSwing_Hit` and six others) | 129 of the 136 non-zero values are a record's `+0x00`; none is a WAD entry |
| `+0x08` | the model resource's hash: CRC-32 of `<name>_geo` | all 1,406 are WAD entries holding one `0x47` model |
| `+0x0c` | the texture dictionary's hash (`car_osedan_tex`; shared between objects) | all 1,406 are WAD entries holding one `0x2a` chunk |
| `+0x10` | 0, or a **second texture dictionary** (loaded and instanced as `+0x0c` is) | all 33 non-zero values are WAD entries |
| `+0x14`, `+0x1c` | the sizes of the model and the dictionary resources, 32 bytes more than their chunks | |
| `+0x18` | a second size of the model, passed with `+0x14` to the memory sizer (`0x00187960`) | larger on all 1,406 |
| `+0x20` | the size of the `+0x10` resource | non-zero exactly when `+0x10` is |

1,400 models are clumps of one atomic; the six cars' have 47 ([Cars](../cars.md#model)). How the models stand and
take their textures: [Level loading](../level-loading.md#the-object-list).

### Packs

881 packs hold 2 to 351 resources each, 38,897 resources in all. The most common mixes are
characters and their props (318 packs with models, textures, animations and character data), models with their
textures and bone offsets (244), and scene packs of animations, models and textures. Named packs follow
`<scene>.pak` (the scripted scenes and cutscenes of [Scene records](#scene-records)), `level<N>_<k>.pak` (props of a
level) and `global.pak`.

### Level files

The name order (above) shows each level as a group of neighbouring entries: `level<N>.lev` (the level resource),
`level<N>.lua`, sometimes `level<N>main.lua` and `level<N>_strings.lua`, `level<N>_<k>.pak`, `level<N>_objs.txt`,
and between them the unnamed **streamed world**:

- **Sector atomics** (1,911 entries, `<world>_ms<i>.sec`): `{u32 1, u32 0, u32 0, u32 crc32(file name)}`, a
  RenderWare texture dictionary (empty in 411 of the 1,564 parts the game loads), `u32 n`, then `n` times
  `{u32 sectorIndex, RenderWare atomic (section 0x14)}`.
- **World stream** (159 entries, `<world>_sec.wld`): `u32 n`, a RenderWare texture dictionary, a RenderWare world
  (section `0x0B`).
- **Stream manifest** (159 entries, `<world>_sec.mem`): `{u32 worldSize, u32 worldHeap, u32 n}` then `n` pairs
  `{u32 partSize, u32 partHeap}`; the second values are the heap sizes the loader creates.

Every level has two worlds, `<level>s` and `<level>d`; `objarena` has one. The formats, how the game streams the
parts and the per-level counts are on [The streamed world](../world.md). **Evidence:** confirmed (code) for the
formats; names and counts from the disc.

### Scene records {#scene-records}

2,765 entries (`.scn`) are not chunked: 1,240 scene headers and 1,525 segments of long scenes, which the game
streams while the scene plays. Both start with `u32 size` (the entry's size). Their layout (roles, objects, camera,
lights, clip and keyed tracks, events), confirmed (code), is on [Scenes](../scenes.md#data).

### Lua

All 467 Lua entries start with the same Lua 4.0 header `1B 4C 75 61 40 01 04 04 04 20 06 09 08`: version 4.0,
little-endian, 4-byte `int`, `size_t` and instruction, 32-bit instructions with 6-bit opcode and 9-bit B field,
and an 8-byte (`double`) number type. Chunk names are stripped to `=(none)`. **Evidence:** inferred (header layout
from the Lua 4.0 `lundump.c` format).

### RenderWare

All RenderWare streams in the WAD carry the library stamp `0x1C02000A` (RenderWare 3.7.0.2, build `0x000a`),
except the 5 older streams stamped `0x1803FFFF` (3.6.0.3, build `0xffff`). Top-level sections seen: `0x16` texture
dictionary (PS2 native textures, platform `6`), `0x10` clump, `0x0B` world, `0x14` atomic. librw reads all four.

## Names {#names}

6,313 of the 10,701 entry names are recovered (2026-10-10), up from 412. The names are listed, with their hashes
and entry numbers, on [WAD entry names](../../references/wad-names.md); `coney-tools refs extract` recovers them again from
your own disc. A test keeps the counts in this table equal to that list.

| Extension | Names | Kind |
| --- | ---: | --- |
| `.scn` | 2,760 | Scene records |
| `.anm` | 563 | Animation resources |
| `.lua` | 356 | Lua bytecode |
| `.pak` | 236 | Packs |
| `.lev` | 64 | Level resources |
| `.sec` | 1,910 | Streamed worlds: the parts (`_ms<i>.sec`) |
| `.wld` | 158 | Streamed worlds: the world streams (`_sec.wld`) |
| `.mem` | 158 | Streamed worlds: the manifests (`_sec.mem`) |
| `.txt` | 63 | Object lists (`_objs.txt`) |
| `.msb` | 20 | Sound banks (`load_00`-`load_06` from the load screen's `%s_%2.2d`) |
| `.msd` | 20 | Sound bank indexes |
| `.cnk` | 1 | Scene list |
| `.glr` | 1 | Global resource |
| `.ico` | 1 | Memory card icon |
| `.met` | 1 | Font metrics |
| `.bmp` | 1 | The font's bitmap |

How:

1. **Harvest strings.** Every run of name-like characters in all 10,701 entries and in `SLUS_212.15` (about 1.09
   million distinct strings, 676,000 distinct stems after stripping paths and extensions). Lua bytecode, animation
   descriptors, scene records, RenderWare texture and frame names and the object lists all contribute.
2. **Try stems with extensions.** Each stem with each of about 80 extensions, hashed as
   `crc32("./ee_files/" + lowercase(name))` and looked up in the DIR.
3. **Use the record's own name.** A scene record's name plus `.scn`, and level numbers as `level<N>.lev`,
   `level<N>_<k>.pak`, `level<N>_objs.txt` and `level<N><word>.lua` for the words in Lua bytecode.
4. **Reject chance matches.** With about 50 million guesses against 10,701 hashes, roughly a hundred random matches
   are expected, so a name is kept only if its extension fits the entry's content kind (`.scn` on a scene record,
   `.pak` on a pack, and so on) and, in the sorted block, it falls between its named neighbours in name order.
   Rare extensions on unrelated content (several dozen one-off hits such as `.sec` on scene records) were rejected
   this way, as were two hits in entries 0–3,614 (where there is no order to check) whose extension did not
   fit.
5. **Streamed worlds from the code.** The world loader builds its names from the level record's world name
   (`<world>s` / `<world>d`, [Level loading](../level-loading.md#worldmanager-loadlevel)) and the format strings
   `%s_sec.wld`, `%s_sec.mem` and `%s_ms%i.sec`. Trying `level<N>s`, `level<N>d` and every other stem with them
   names 2,226 of the 2,229 streamed-world entries; together with the earlier names they keep the sorted block in order
   with no exception. The other three (entries 9,809–9,811: a part, a manifest and a world stream, which sort between
   `nudge_point.anm` and `old_cheer_idle1.anm`) take a world name no string on the disc spells.

Entries 0–3,614 are named by number ([above](#layout-of-the-wad)), which the table does not count: 3,599 of them
have their WAD name, and a readable resource name wherever the resource hash is matched (about 1,170 resource hashes
in the archive are). What stays unnamed: 16 texture dictionaries of entries 0–3,614, 645 packs, 111 Lua scripts, the three
world entries above, five scene records, five older RenderWare streams, two resources and one sound bank (`.msb` and
`.msd`, entries 9,803 and 9,804).

Brute force over short suffixes runs into CRC-32's linearity: for names of equal length, the XOR of two hashes
depends only on the XOR of the names, so a wrong guess that happens to match one entry produces matching variants
for its same-length neighbours. Several such "families" of matches turned up for the streamed-world entries; they
show those entries' true names have equal lengths and differ in a few characters, but they are not the names (the
real names, found from the code, bear this out: `level51s_ms12.sec` and `level51s_ms13.sec` differ in one character).

## Coney's implementation

`coney-tools extract` classifies every entry with the structural tests above
([python/src/coney_tools/wad_kinds.py](repo:python/src/coney_tools/wad_kinds.py)), parses the
[chunk container](#chunk-container) and hands each distinct resource to the decoder of its shape; what each kind
becomes is on [Asset inventory](inventory.md).

## Open questions

These need the code (Ghidra); the data alone cannot settle them.

1. **The chunk loader** is now on [Chunk system](../chunk-system.md): a standalone resource is its flat container
   and a pack its grouped container, and the loaders read only the counts, chunk types and sizes. The two pages'
   counts are reconciled by one classifier on [Chunk system](../chunk-system.md#container-layout): the extra flat
   and grouped parses there are world files and chance matches, and this page's kinds stand (answered).
2. **The chunk-type table's handlers** are documented on [Chunk system](../chunk-system.md#chunk-type-table);
   what remains is which code reads the unused header words (the third and fourth fields).
3. **The leading `.text` addresses** in fixed-size chunks (`0x0045de40` etc.): vtable or handler pointers from the
   build, fixed up on load, or unused?
4. **Chunk `0x4c` "Particle Page"** (answered): a sprite sheet, a count and `count` texture rectangles into the
   single texture of the dictionary before it; the full layout, checked on all 1,335 pages, is on
   [GUI](../gui.md#particle-page).
5. **The streamed world** (answered): `%s` is `level<N>s` or `level<N>d` (or `objarena`), the manifest's second
   values are heap sizes and the atomics header holds the CRC-32 of the file's name; see
   [The streamed world](../world.md).
6. **Entries 0–3,614.** Named by the decimal CRC-32 of the resource name (answered above). Open: the 16 texture
   dictionaries whose header hash does not give their WAD name.
7. **Scene records.** The full layout of headers and segments, and which code streams them (the chunk types
   `0x38`–`0x3d` named "Scene ..." do not occur in the WAD, so scene data may use its own reader).
8. **Sound banks** (answered): the `.msd` hashes are the sound list's name hashes and the IOP plays the `.msb` from
   sound RAM; see [Audio data](audio.md#banks).
