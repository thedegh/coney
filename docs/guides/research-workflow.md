# Research workflow

Research turns the original game into documents that someone can implement from **without opening Ghidra**. A
research page says what a part of the game does, what its data looks like and how sure we are of each claim; the
engine code is then written from that page. This guide covers who does what, how claims are graded, where findings
go and how to write them up.

The pages themselves live in `docs/research/`, one living page per subsystem or file format. How to lay a page out
is in [Writing these docs](writing-docs.md#subsystem-page).

## Clean room {#clean-room}

Coney is a clean-room reimplementation: the code has the same observable behaviour as the original but its own
structure, names and control flow. The rule is set in
[LEGAL.md](repo:LEGAL.md#clean-room); this section is how we work within it.

The work splits into two roles.

| | Analyst | Implementer |
| --- | --- | --- |
| Reads | Ghidra's decompiler output and disassembly of `SLUS_212.15`, the running game in PCSX2, the game's data files, plus everything the implementer reads | `docs/research/`, the research database (`research/*.yaml`), Coney's own code and tests |
| Writes | research pages in `docs/research/`, entries in `research/*.yaml` | engine code in `src/`, tools, tests |
| Never | implements a function whose original code they have read | reads decompiler output or disassembly, opens the Ghidra project or the emulator's debugger |

The split is per function, and it binds people and agents alike: **whoever has read a function's original code
(its decompiler output or its disassembly) never implements that function. Someone else implements it, from the
research page.** The reason is evidence, not trust. Code written by someone who has never seen the original can only
have come from the page, so its independence can be shown; code written by someone who has seen it cannot, however
carefully they worked. You may analyse one function and implement a different one, as long as you have never read
the original code of the one you implement.

For agents, Rekit enforces the split where the platform allows: the analyst agent and the implementer agent are
separate, and the implementer agent has no Ghidra or emulator tools at all. People keep it by discipline: before
implementing a function, check that you haven't read the original code of the functions involved, and hand
the work on if you have.

What crosses from analyst to implementer is **facts and behaviour**, never code: data layouts, constants, file
formats, algorithms needed to read the game's data (the CRC-32 name hash, for example), and prose descriptions of
what a function does. Short pseudocode is fine when it explains behaviour; a function's control flow copied line by
line is not (see [Writing up a finding](#writing-up-a-finding)).

### When a research page isn't enough

Sooner or later an implementer needs something the page doesn't say. Don't look at the original to fill the gap,
not even briefly: once you have read a function's original code, you can no longer implement that function (see
above), and the work has to go to someone else.

Instead:

1. Add the question to the page's **Open questions** section, saying what you need and why (what decision in the
   code depends on it).
2. Raise it with an analyst: as a GitHub issue, or, for an agent, in its report as a blocker.
3. Carry on with whatever doesn't depend on the answer, or stop and say so. A guess written into code without a note
   is worse than a gap, because nobody knows to come back to it.

An analyst answers by updating the page, which is how the answer reaches every later reader too.

## Evidence levels {#evidence-levels}

Every non-obvious claim on a research page says how we know it. A reader deciding whether to build on a claim needs
to know whether it was read in the code, seen happening, or worked out from clues. There are four levels.

| Level | Meaning | YAML value |
| --- | --- | --- |
| **confirmed (code)** | Read in the original's code, at a cited address | `confirmed-code` |
| **confirmed (runtime)** | Observed in the original game running under PCSX2; the claim states the PCSX2 version and the method (a breakpoint at an address, a memory watch, a frame) | `confirmed-runtime` |
| **inferred** | Follows from evidence that points one way, without being read or observed directly | `inferred` |
| **speculative** | A plausible guess, written down so it can be tested | `speculative` |

Examples (the current pages have no runtime observation yet, so that level is shown as a template):

- **Confirmed (code).** [WARRIORS.DIR](../research/formats/wad-dir.md): the index's constructor at `0x00149160`
  reads the entry count, seeks to `0x10`, allocates `count * 12` bytes and reads the entry table. The claim names
  the address where anyone with the executable can check it.
- **Confirmed (runtime).** [Memory](../research/memory.md#sizes-at-runtime): the `Sector Pool` is 17,217,536 bytes,
  read in PCSX2 2.9.94 over PINE from the pool object the page documents (`0x00760f80`, block size at `+0x0c`) on
  a retail boot, with the moments of the reads (start-up movies, main menu, a fight in `level102`). The claim says
  what was read, where, when and in which emulator version, so anyone can repeat it.
- **Inferred.** [Compiler](../research/compiler.md): the vtables use 8-byte `{delta, fn}` slots, the GCC 2.x
  layout, which points to GCC 2.95.x. The layout is confirmed; the compiler version is a conclusion drawn from it,
  and the page says the exact version is not confirmed.
- **Speculative.** [Recon](../research/overview.md#disc-layout): the custom `IOP.IRX` module is "probably" the
  audio driver. Nothing has been read or observed yet; the guess is recorded so that someone can test it.

A check against the game's own files is **corroboration**, not a level of its own: it is written next to the
claim it supports. [WARRIORS.DIR](../research/formats/wad-dir.md) does this: its layout is confirmed (code), and the
line beside it notes that the layout predicts `16 + 10701 × 12 = 128,428` bytes, the size of `WARRIORS.DIR` on the
disc. The check makes the claim more trustworthy, but it grades nothing by itself.

Write the level next to the claim it grades, for example `**Evidence:** confirmed (code) at 0x00149160.` A claim
that moves up a level (a guess confirmed in the code, say) is updated in place, and the old level goes away. Some
older pages say "Confidence: confirmed from code"; that means confirmed (code), and those pages are brought to the
new wording when they are next edited.

A page also says what it was checked against: the executable (`SLUS_212.15`, see
[Writing up a finding](#writing-up-a-finding)) and, for runtime claims, the PCSX2 version.

## The research database {#the-research-database}

Research pages are for reading; the research database is the same knowledge in a form tools can check. It is a set
of YAML files in `research/` at the repository root, in the schema Rekit defines:

- `research/symbols/<area>.yaml`: one entry per function or global, by address;
- `research/types/<area>.yaml`: one entry per struct, with its fields at their offsets.

```yaml
# research/symbols/<area>.yaml
- addr: 0x001490b8
  name: DVDWadIndex::Find
  tu: Device/ps2/fileio/DVDWadIndexPS2.cpp     # original translation unit, when known
  evidence: confirmed-code                     # confirmed-code | confirmed-runtime | inferred | speculative
  reimpl: src/fileio/wad_index.cpp             # filled in by `rekit research check --fix-reimpl`
  notes: CRC-32 of the lowercased name, then a linear scan.
```

```yaml
# research/types/<area>.yaml
- name: WadDirEntry
  size: 12
  evidence: confirmed-code
  fields:
    - { offset: 0x0, type: u32, name: wadOffset }
    - { offset: 0x4, type: u32, name: size }
    - { offset: 0x8, type: u32, name: nameHash, notes: "CRC-32 of the lowercased path" }
```

The database keeps three things in step:

- **the code:** `rekit research check` matches every `@orig` tag in the source against the symbols, in both
  directions (see [Comments and @orig](conventions.md#comments-and-orig));
- **the docs:** `rekit research tables` generates the symbol and type tables in `docs/research/tables/`, which are
  never edited by hand;
- **Ghidra:** `rekit ghidra apply` pushes names, types and comments into an analyst's local Ghidra project, and
  `rekit ghidra export` brings new names back, never overwriting an entry that has a higher evidence level.

The database **arrives with Rekit**. Until then, findings are recorded on the research pages only, and the YAML
is seeded from them when it arrives. One file is already there, because it is Coney's own: the script bindings.

### The script bindings {#bindings}

The files `research/bindings/<category>.yaml` list every function the game registers with its Lua state, one entry
per name: the masterlist of the game's script bindings (what FiveM calls natives), which is also the reference for
script mods. There is one file per category, named by the category's id (the ids are in `coney_tools/natives.py`), so
an entry has no `category` key; moving a binding to another category means moving its entry to that file.
`coney-tools natives render` checks the files and generates the reference pages in `docs/references/bindings/` from
them; the pages are never edited by hand, and CI runs `natives render --check` ([coney-tools](coney-tools.md#natives)).
An entry of `level.yaml`:

```yaml
- name: GetLevelId                 # the Lua global's name
  origin: game                     # game (default) | coney: a binding Coney adds for mods, with no wrapper or usage
  registered_by: RegisterBindings  # RegisterBindings (default) | ScriptSystem (the four Cfg* of the constructor)
  wrapper: 0x0036c568              # the tolua wrapper
  calls:                           # the functions of the game the wrapper calls, with our name when we have one
    - {addr: 0x0041d6f0}           # add `name: ...` once the function has one of ours
  args:                            # in the order the wrapper reads them (Lua argument 1, 2, ...)
    - {name: index, lua: number, ctype: unsigned, desc: "Index of a level record (0 is the front end)."}
  results:                         # what the wrapper pushes
    - {lua: number, desc: "The record's level number, as in levelNN.lua."}
  overloads:                       # only for the ten names registered twice: the first registration, same keys
    - {wrapper: 0x..., calls: [...], args: [...], results: [...], note: "when it is used"}
  description: "What the binding does, in one to four sentences."
  evidence: confirmed-code         # the level of the description and meanings; the signature is always confirmed (code)
  depth: thorough                  # thorough (the callee was traced) | brief (a shorter description)
  notes: "Caveats: ignored arguments, edge cases."
  usage: {chunks: 2, calls: 8, boot: true, mission1: false, result_used: true}
  coney: not implemented           # not implemented (default) | partial | implemented
```

- `lua` is how the wrapper reads an argument: `number`, `boolean`, `string`, `table` (with `elem: number` or `string`
  and, when fixed, `count`) or `userdata`; a number's `ctype` is what it becomes (`int`, `unsigned`, `float` or
  `double`). `default` is the value an argument left off takes, and `written_back: true` marks a table the binding
  writes into (every table argument of the game's bindings is). A result's `lua` is `number`, `boolean` (1 or nil),
  `string` or `usertype` (with `type`).
- `usage` is counted from the disc's compiled Lua chunks: how many chunks reference the binding's global name and
  how many references there are (`calls`), whether the boot-to-menu scripts or the first mission's scripts
  reference it (`mission1` also counts the `global.lua` helpers those scripts reach; `coney-tools natives mission1`
  sets it from the disc), and whether a traced call keeps its result (a lower bound). It holds counts only. The
  optional `levels: [80, 87, ...]` lists the story's later levels whose scripts can call it, in story order
  (`coney-tools natives missions` sets it from the disc).
- `coney` is never edited by hand: `coney-tools natives coney` sets it from Coney's binding table
  (`src/scripting/script_bindings.cpp`), writing the key only when it is not the default
  ([coney-tools](coney-tools.md#natives)).
- `depth: mechanical` (signature only, no description) is accepted so a new entry can land before it is described;
  the masterlist has none.

## Reference lists {#reference-lists}

The [Game references](../references/index.md) are lists of the things scripts, mods and Coney's code name:
characters, power and Warrior classes, attack kinds and tables, hat fittings, gangs, the Rumble roster, AI goal types,
objects, inventory items, cars, particle effects, glass types, doors, object tints, lights, levels and their player
starts, world flags, object zones, volume boxes, scenes and movies, camera types and switches, screen effects, clips,
anim ids, controls, commands, spawner states, crime types, unlockables, statistics, colours, radar icons, text tags,
text labels, script constants, sounds, speech, script events and WAD entry names. Each is a YAML file in
`research/references/<list>.yaml`, and its page in `docs/references/` is generated from it. They hold only names, ids,
numbers and our own short descriptions (`LEGAL.md`, "Reference lists"): never game text, script source or a file from
the disc.

A list file has a fixed shape; the fields of its entries are defined per list in
`python/src/coney_tools/refs_topics.py`, and each page ends with its list's fields:

```yaml
title: Characters (humans)
about: |                                  # Markdown, our own words: what the list is
  ...
complete: |                               # Markdown: what is complete and what is not
  ...
defaults: {source: "config_preload2.lua, CfgChar", evidence: inferred}
entries:
  - id: 32
    model: warr_re_cv
    label: Rembrandt (`_cv` model)        # hand-written
```

- In `complete:` write the number of entries as `{count}` (`{count} of 10,701 names are known`), never as a
  number: the page fills in the real count, so it cannot go stale when entries are added, and `refs render`
  refuses a text that spells the count out. Counts of a part of the list (the 9 modes among a roster's 450
  entries) stay hand-written, so check them whenever you add entries.
- Every entry has a **source** and an **evidence** level (the [levels](#evidence-levels) above, spelled
  `confirmed-code`, `confirmed-runtime`, `inferred`, `speculative`), its own or the list's `defaults`.
- Each entry has a stable **anchor**, `<list page>#<prefix>-<key>` (`characters.md#char-32`,
  `levels.md#level-29`), for links from research pages, issues and mods. A key never changes once published.
- Fields are either **read from the disc** or **hand-written** (each page's field table says which).
  `coney-tools refs extract` rewrites the first kind and keeps the second, and keeps entries it did not produce,
  so a hand-added entry or a name found another way survives a refresh.

Commands ([coney-tools](coney-tools.md#refs)):

```sh
uv run --project python coney-tools refs extract [DISC] [--only LIST ...] [--names FILE]   # refresh from your disc
uv run --project python coney-tools refs render [--check]                                 # write or check the pages
```

A list too long for one file is **split** (`split=True` on its topic; [World flags](../references/flags.md) is one):
`<list>.yaml` keeps the title, prose and defaults, `research/references/<list>/<group>.yaml` holds the entries of one
`group_by` group each, and the page `<list>.md` becomes an overview linking one page per group,
`docs/references/<list>/<group>.md`, where the entries keep their anchors. Every file stays under the repository's
512 KB file guard, and each page loads fast.

To change a list by hand, edit its YAML and run `refs render`; CI fails when a page is out of date with its YAML.

The families of ids and names that scripts use but no list covers yet are in
`research/references/still-to-list.yaml`, most useful first, each with `family`, `what`, `source`, `count`, `image`
and `needs`; `refs render` shows them on the index as [Still to list](../references/index.md#still-to-list). A family
that gets its own list leaves that file. [Entities](../references/entities.md), the map of what scripts can make and
refer to, is written by hand; the index links it.

To add a field or a list, add it in `refs_topics.py` (and its reader in `refs_extract.py` when it comes from the
disc), then run `refs extract`. **Thumbnails** go in `docs/references/images/` (`characters/<model>.png`,
`objects/<name>.png`, `cars/<type>.png`; 256 × 256, transparent, rendered by `coney --render-references` from the
player's disc, then shrunk with `coney-tools refs compress-images`); `refs extract` links each one that exists. The
character images are rendered with `--names` given every model name in `character-models.yaml`, so only the models
with no recovered name are named by hash. 2D icons (`radar/icon-<n>.png`, `particles/<name>.png`) are one sheet
rectangle each, at most 64 × 64 (`LEGAL.md`); no renderer makes them yet.

## The mission list {#missions}

[Missions](../missions/index.md) is the status checklist of the story: one page per level (the 18 story missions,
the hub, the flashbacks and the Armies of the Night stages), generated by `coney-tools missions render` from
`research/missions.yaml`. Each entry has the level, its `group` and `slot`, a `label` ("Mission 2"), a summary in our
own words (never game text) with its `summary_source` (research, disc, web or mixed; web summaries list their URLs
under `sources` and are replaced by our own walkthrough), a `status`, its `checkpoints` (`count`, which must equal the
levels list's Sections column, a `default` status and per-checkpoint `each` overrides with a note), `research` links,
`issues`, `questions` and the disc `test`. A mission's title is not kept in `missions.yaml`: it is the level's `title`
in the levels list (`GSTRING.MISSIONNAME` of the English string file, filled by `coney-tools refs extract`), shown in
the page heading and the overview. The five statuses are Not Started, In Progress, Pending Gameplay Approval, Needs
Fixes and Approved, for missions and checkpoints alike.

**Whose job:** an implementer (human or agent) updates `missions.yaml` in the same commit as mission work: In Progress
when a checkpoint is started, each checkpoint to Pending Gameplay Approval when it plays to its end, the mission to
Pending when every checkpoint does, and re-runs `missions render`. Only a maintainer moves a mission to Needs Fixes or
Approved after play-testing it against the original, listing what was off under `issues`; the commit that merges the
fix moves it back to Pending. An analyst's finding that changes what a mission needs goes on the research page, which
the entry links.

## Tools

- **Ghidra with ghidra-mcp.** Static analysis of `SLUS_212.15`, with the Emotion Engine processor extension; the
  ghidra-mcp server lets analyst agents drive it. Setup: [Ghidra + ghidra-mcp](ghidra.md). The Ghidra project holds
  the game's code, so it stays on your machine and is never committed.
- **PCSX2.** For runtime evidence: memory reads and writes on the game as it runs. `coney-tools pcsx2` makes patched
  state copies, starts PCSX2 on one and records a scripted run as a per-update trace
  ([Recording a trace](#recording-a-trace)); `coney-tools trace diff` compares it with Coney's
  ([Comparing with Coney](#comparing-with-coney)). How PCSX2 is driven underneath: [Driving PCSX2](#driving-pcsx2).
- **The Xbox executable (optional).** For string- and float-heavy code (front end, audio cues, scripting glue,
  camera maths), the same function in the Xbox build's `default.xbe` can read faster: string literals inline, the
  object argument visible, library calls named. Find the twin through a string both builds share, load the XBE in
  its own Ghidra project (never the main one), and use it only to read the logic: offsets, sizes and vtable slots
  differ, and evidence is cited at `SLUS_212.15` addresses only. Measurements and the loader used:
  [Xbox executable](../research/xbox-executable.md).
- **Save states in Ghidra (evaluated 2026-10-05, not used).** The EE extension's `PCSX2SaveStateImporter.java`
  script pours a state's RAM into a program's writable blocks and the heap above `.bss` (a `.other` block); run on a
  scratch copy of our project with `pcsx2 repack-state` first, it took 10 s, and a script labelling level99's 19 live
  brains, their goals and the 7 gangs ran in 2 s. The same walk over PINE gave the same facts in 0.03 s after a
  19 s PCSX2 launch, with names from the static project either way, and reading `eeMemory.bin` straight from the state
  file gives the same frozen moment without either. Ghidra adds nothing PINE lacks but a frozen, searchable heap; it
  costs a 170 MB project copy per state, its labels never reach the main project, and code patches and the hook cave
  below `0x00100000` do not show, so we read live data over PINE or from the state file.
- **Capture analysis.** Recording what the game sends to the graphics hardware or the sound processor and studying
  the capture. It is a later fallback, for questions that the code and the debugger answer badly (exact rendering
  state, timing). Captures contain game data: they stay in your scratch folder and never enter the repository.

### Running Coney {#running-coney}

A window that takes the keyboard focus interrupts whoever is typing, so agents and tools start Coney only in ways that
leave the focus alone:

- **Test mode, always.** Run `coney` with `--frames N` (and `--input-script`, `--screenshot` as needed) or
  `--headless`, never as a plain interactive run. In test mode Coney's window opens without taking the focus (it
  may show on top, but keystrokes stay where they were), and `--render-references` (which hides its window) never
  takes it either. Any other windowed run started by a tool adds `--no-activate`
  ([Frame rate](building.md#frame-rate)).
- **ctest needs nothing.** The disc tests inside `coney_tests` run on librw's NULL renderer and open no window; the
  `coney` smoke tests (`repo:src/platform/CMakeLists.txt`) run `--headless` or stop at the command line before a
  window opens; the one test with a window (`coney.frame_copies_upright`) hides it and so never takes the focus. A new
  smoke test keeps to `--headless`. `coney-tools trace coney` runs Coney `--headless` too.
- **How.** librw's GL3 device makes and shows the window with SDL's defaults, which activate it. Before it does,
  `RenderEngine::start` (`repo:src/platform/render_engine.cpp`) turns off SDL's `SDL_WINDOW_ACTIVATE_WHEN_SHOWN` and
  `SDL_WINDOW_ACTIVATE_WHEN_RAISED` hints, so on Windows the window is shown with `SWP_NOACTIVATE`. Unlike PCSX2's Qt
  ([below](#driving-pcsx2)), SDL honours that, so no launcher is needed and the run's output stays on the console.

### Driving PCSX2 {#driving-pcsx2}

How the first runtime pass (2026-10-04, official portable PCSX2 2.9.94) was done; it needs nothing but PCSX2, its
PINE server and the `pcsx2` MCP server (or any PINE client).

- **Set-up.** Enable PINE in `inis/PCSX2.ini` (`[EmuCore]` `EnablePINE = true`, `PINESlot = 28011`) before launching.
  PCSX2 2.9.94 fails to open an ISO whose path holds commas and parentheses ("Requested filename ... does not
  exist"), so the launcher boots an NTFS hard link with a plain name in the scratch folder (it copies nothing).
- **PCSX2 is started only by `coney-tools pcsx2 launch` or `pcsx2 record`, never by hand** (no `pcsx2-qt.exe` from
  a shell, a script or `Start-Process`). The launcher is what keeps PCSX2 from taking the keyboard focus, which
  interrupts whoever is typing. `pcsx2 launch --agent <id> [<state.p2s>]` starts it on a state file, or with no
  state boots the disc and returns once PINE answers; it runs under your claim and leaves PCSX2 running.
- **How the launcher keeps the focus off** (`repo:python/src/coney_tools/pcsx2_proc.py`, whose docstring says why it
  must stay this way). A no-activate show command alone (`SW_SHOWNOACTIVATE` in `STARTUPINFO`) was not enough: Qt
  ignores it for its first window, and Windows lets a process activate its window when the foreground process
  started it, which every agent's process tree (under the user's terminal) is. So the launcher has WMI start PCSX2
  (`Win32_Process.Create`): its parent is WMI's provider host, outside that tree, with no foreground rights to hand
  down. As a backstop, while `pcsx2 record` runs a guard polls every 50 ms and, if a PCSX2 window is in the
  foreground, hands it back to the window that had it (no input sent, PCSX2 never minimised, so screenshots keep
  working). Checked 2026-10-07: the foreground owner logged every 50 ms over a state launch and over a cold boot
  (about 900 polls each) was never PCSX2.
- **Several at once.** A portable PCSX2 keeps its settings, states and memory cards in its own folder, so each copy of
  the folder (`pcsx2`, `pcsx2-b`, ..., each with its own `PINESlot` 28011, 28012, ...) is an independent instance, and
  `coney-tools pcsx2` reads the port from that copy's `PCSX2.ini`. Every PCSX2 use starts with
  `coney-tools pcsx2 claim --agent <your id>` (it prints the copy's folder and port; `--json` for scripts) and ends
  with `pcsx2 release --agent <your id>`, which also closes your PCSX2. `pcsx2 status` shows who holds what, built
  from the live claims and processes; a claim whose process is gone is stale and the next `claim` takes it over.
  `pcsx2 launch` and `pcsx2 record` take `--agent` and run under your claim (making one if you hold none). Input to the
  game is over PINE only (scripted
  pad input, the stick table below); no tool takes the keyboard focus. When a hotkey is unavoidable (Space to
  pause), `pcsx2 keys --agent <id> --copy <name> space` posts the key to that copy's window by handle, and
  `pcsx2 screenshot --copy <name> --out <png>` reads the window by handle (not F8); both are Windows-only and leave
  the focus alone. PCSX2 never takes the focus (the launcher, above), and every copy has `[InputSources] SDL = false` so
  the
  user's gamepad cannot drive it; a maintainer turns SDL on in a copy only to test by hand, and `claim` and `status`
  warn when it is on. Claims live in `pcsx2-claims/` of the shared scratch folder (`pcsx2_root` and `pcsx2_claims_dir`
  in `coney.local.toml` move the copies and the claims).
- **What PINE gives.** Memory reads and writes, game info and save/load state slots. No breakpoints, registers,
  pause or frame capture. PCSX2 serves one PINE client at a time, so a second client (a script of your own) blocks
  while the MCP server is connected.
- **Input and hotkeys.** Keyboard messages posted to the PCSX2 window by handle (`pcsx2 keys`, `WM_KEYDOWN`) reach
  the hotkeys in `[Hotkeys]` (verified: a posted Space paused and resumed the game with the window unfocused) and the
  pad bindings in `[Pad1]` (Return = Start, K = Cross, arrows = D-pad, WASD = left stick; not yet checked with posted
  keys). The hotkeys: **Space pauses**, F8 saves a screenshot to `snaps/` (aspect-corrected, 1240 × 930 for the
  game's 640 × 448), F4 toggles the frame limiter. Hold a pad key for about 300 ms so that a 30 Hz game sees it.
  Leave the frame limiter on: with it off, real-time waits (the legal screen's 5 s) pass in a blink.
- **A chosen analog stick value.** Keyboard keys bound to a stick only give full deflection (raw byte 0
  or 255), but the gait thresholds need partial values. The game turns each raw stick byte into a float through a
  256-entry `float` table at `0x0050b8d0` (entry 0 is −1.0, entry 255 is +1.0); it is data, so a PINE write takes
  effect at once. To give the left stick a magnitude *m* straight up: write −*m* to entry 0 (`0x0050b8d0`) and +*m*
  to entry 255 (`0x0050b8d0 + 0x3fc`), then hold W; the pad record (`0x005dd810`; `+0x08` / `+0x0c` the stick as
  floats, `+0x00` / `+0x04` the same turned by the camera) shows the value the game uses. Write −1.0 / +1.0 back
  afterwards. The camera's right-stick code (`0x00129050`) reads the raw bytes, so the table does not change it.
  State the magnitude used with every runtime claim that depends on input ("stick magnitude 0.5, straight up").
- **Catching a moment.** Load a state, press Space to pause, make the memory writes, then send Space followed by a
  run of F8 presses (one a second, or faster) and look at the screenshots afterwards. Data drawn in one frame
  usually survives in memory until reused: a sprite batch's arrays keep the last frame's sprites after its count is
  reset, which is how the draw-order keys and colours were read.
- **Patching code to see something.** A code write lands before the recompiler first compiles the block if the
  function has not run yet; the legal screen's placement was measured by patching its clear colour to blue and
  halving its size factors, and the start-up movies were skipped by making their skip check (`0x0042a820`) return 1.
  Say on the page which patch a claim depends on. A write to code that has already been compiled is not picked up
  (PCSX2 logs "Impossible block clearing failure", and writing during a state load crashed it).
- **Scripted pad input** (2026-10-05, the traversal pass). When the keyboard does not reach the window, or for exact
  timing, make the pad code read buttons and the left stick from spare bytes after the `scePadRead` buffer: in the
  DualShock 2 path the `lbu` loads at `0x00149dd4`, `0x00149dd8`, `0x00149de8` and `0x00149df0` (and at `0x00149e8c`,
  `0x00149e90`, `0x00149ea8`, `0x00149eb0` in the digital path) take offsets `0x22`, `0x23`, `0x26` and `0x27`
  instead of 2, 3, 6 and 7, so `0x005de3aa` / `0x005de3ab` are the active-low button bytes and `0x005de3ae` /
  `0x005de3af` the stick's x and y. The patch must be in RAM before the block is compiled: **copy** the save state
  file (a zip of `eeMemory.bin` and the rest; Python 3.14's `zipfile` reads its zstd entries), patch `eeMemory.bin` at
  those addresses, and start it with `coney-tools pcsx2 launch --agent <id> <copy>`; restart PCSX2 the same way
  for every run. Then write the bytes over PINE (the stick table above gives the magnitude). Find the player as the human
  whose `+0x1b0` is 0: in later levels it is not human 0, and the per-player record is indexed by its `+0x92`. The
  patch is `scripted-pad` in `research/traces/patches.toml`, with each instruction word it expects and the one that
  replaces it; `coney-tools pcsx2 prepare-state` and `pcsx2 record` make the copy and restart PCSX2 for you.
- **The right stick, too** (2026-10-05, the feel pass). The right stick's loads are at `0x00149df8` / `0x00149e00`
  (DualShock 2 path) and `0x00149eb8` / `0x00149ec0` (digital path), offsets 4 and 5; making them 0x24 and 0x25
  puts the right stick's x and y at `0x005de3ac` / `0x005de3ad` (the `right-stick` patch). The stick table at
  `0x0050b8d0` is the same map as
  Coney's `pad::stickValue` (dead band 95-160, `(raw − 160) / 95`), so writing the raw bytes Coney makes from an input
  script's percentages (`160 + round(0.95 × v)`, `95 − round(0.95 × |v|)`, 128 at rest) gives both games the same
  stick, diagonals included, without touching the table.
- **A puppet human** (2026-10-05, the combat runtime pass). To make an AI human attack, grab or block the player,
  write command ids ([Combat](../research/combat.md#commands)) into its per-player record (`0x00660f50` + index ×
  `0x2c`, `+0x20`): `Player_UpdateActions` runs for every human whose per-player `+0x1e` is 0, AI humans included,
  and acts on that command. For a human with no pad, `0x00146000` clears `+0x20` every update, so put a `nop` over its
  `sw zero,0x20(a0)` at `0x00146030` in the state copy (with the pad patch above; the `puppet` patch), then write the
  command for one
  update and 0 the next (a cross tap is `0x12`, then `0x10`, then 0). A grab needs a target: write the player's handle
  (human `+0x90`) to the puppet's human `+0xc8` and its brain's `+0x124` (`0x006d53f0` + index × `0x2f0`), or 70 misses.
  A held button (R1 to block) is read from a pad record, so give the puppet pad index 4 (per-player `+0x19`) and write
  the button into all eight entries of pad record 4's button history (`0x005dd950 + 0x1c`, eight `u16`) every update.
  Set `CfgAutoLockAndCombat` (`0x005104b8`) to 0 when the player must not turn to face the attacker. Pick the puppet
  by name: the nearest human changes as pedestrians walk, and an ally's hits play reactions without damage.
- **Following a script at runtime** (2026-10-07, the level99 hints pass). To log which Lua functions run and which
  bindings a script calls, with their arguments, hook the Lua 4 VM. Its interpreter entry is `0x00334478`
  (`luaV_execute`, called by `luaD_call` `0x00328b40`); its `a1` is the closure, whose prototype (`+0x00`) holds
  `lineDefined` at `+0x38` and the chunk name at `+0x3c`. The C-function call is `0x00328a30` (`callCclosure`): `a1`
  is the closure, `+0x00` the binding's address (as in a bindings dump), and `a2` its first argument. Arguments are
  16-byte TObjects: type at `+0`, value at `+8` (1 nil, 2 number as a double, 3 string with its text at `+0x10`).
  Only the first argument is reliable: the slots after the last real argument hold old values. The hooks are
  `lua-exec`, `c-call` and `c-call-args`. A script's tables are read the same way, from the globals table
  (`ScriptSystem *0x00512b04` → state `+4` → globals `+0x44`). That gives `Objects.<name>`, a spawn handle (index
  `<< 16`), which leads to the live object through the spawn record (`+0x24` low 16 bits) and the handle table
  `0x006ebd38` ([Objects](../research/objects.md#spawn-records)). A driver that plays a level's steps by what they
  show ([Scripts](../research/scripting.md#level99-hints)) must send partial sticks through Coney's byte map (below):
  a plain linear map falls inside the dead band and the player stands still.
- **One sample per update.** Batch every read of a sample into one PINE message and keep a sample only when a
  character update has run since the last one: the game counts its 60 Hz ticks at `0x005104f4` and steps the
  characters on each tick that makes the count even ([Tasks](../research/tasks.md#tick)), so the count halved numbers
  the updates. Apply the scripted input as each update is seen. `coney-tools pcsx2 record` does exactly this
  ([Recording a trace](#recording-a-trace)). (The first recorder counted updates by the game time in milliseconds,
  `*(0x0050b734) + 0x48`; its rounding skipped and repeated steps after the frame that catches a tick up, about every
  33 s.)
- **Hooks: a call log without breakpoints** (2026-10-05, the runtime-checks pass). PINE has no breakpoints, so "who
  writes this" and "which objects does this run" are answered by patching code in the state copy: a hook replaces two
  instructions with a jump to a cave in memory the game leaves empty (`0x000a0000`; zeros from `0x00095100` to the
  ELF at `0x00100000` in every state checked), which writes chosen registers and loads into a ring buffer
  (`0x000b0000`) and runs the two instructions. The recorder reads the ring every poll and writes one CSV per hook
  ([Hooks](#hooks)). A **call hook** makes the game call one of its own functions on its own thread, as a script
  binding would: that is how a fight is started on a pedestrian (`GoalFight`'s `0x002b2b90`) for the AI checks.
- **Leave the quick-save slots alone.** Load existing slots read-only (they may hold someone else's test spots), and
  keep your own states as files in your scratch folder, made as above. PINE can only save to a slot number: when a
  state must be saved from a running game, save it to an empty slot above 10 and move the file to your scratch folder
  at once. A state saved from a patched copy still holds the patches; put each patched word back to the original that
  `patches.toml` lists before using it as a scenario's `state`, or the copy is refused.
- **Hygiene.** Save states, screenshots and logs contain game data: keep them in your scratch folder (move the
  `.p2s` files out of `pcsx2/sstates/` afterwards) and close PCSX2 when done. Screenshots are measured, never
  committed; a claim quotes the numbers.

### Recording a trace {#recording-a-trace}

A parity question ("does Coney's walk start take as long as the original's?") is answered by playing **one input
script** on both games and comparing their per-update traces. The original's side is a **scenario**: a TOML file in
`research/traces/scenarios/` that names the save state, the patches, the input script beside it, how many updates to
record, and the fields to read. Scenarios, patches, field sets and input scripts are committed; the traces they record
are measurements of the game and stay in your scratch folder.

```sh
uv run --project python coney-tools pcsx2 record research/traces/scenarios/walk60.toml --out ../../scratch/walk60-original.csv
```

`record` copies the scenario's quick-save slot (read only), or the state file it names under `scratch_dir`, to
`<scratch_dir>/pcsx2/<scenario>.p2s` with the patches applied, starts PCSX2 on the copy with `-fastboot -statefile`
(through a hard link to the disc when its path has commas or parentheses), waits until the patched state runs, plays the
script and samples every update, then closes PCSX2 and warns if a file appeared in its `sstates/` folder. The folders
come from `coney.local.toml` (`pcsx2_dir`, `game_dir`, `scratch_dir`) or from `--pcsx2-dir`, `--iso` and `--scratch`;
PINE must be on in PCSX2's ini. `--state` records from another state file (or `slot:N`), `--attach` records a PCSX2 you
started yourself on a patched copy (`coney-tools pcsx2 prepare-state`, then `pcsx2 launch`), and `--keep-open` leaves it
running. It prints the number of updates, how many reads each poll made, the time per poll and the updates it missed.

**Timing.** Step 0 is the first sample, before any input. After the sample of step N the recorder writes the pad for
frame N of the script, which the update of step N + 1 reads: the numbering of Coney's `--trace`, where frame N of an
input script is step N + 1. A missed update (one the poll did not see) is listed by step; its input lands an update
late. The stick bytes are made from the script's percentages exactly as Coney makes them, so both games see the same
stick; a tap holds the button for one update. With PCSX2 2.9.94 on Windows a poll of 26 reads took about 0.05 ms, so
the tick count is seen many times per update; no update was missed in the smoke runs (130 to 230 updates). A step
counts from the tick that follows the update's own (the count turning odd), so a sample never sees an update half
done; the frame that catches up a tick (one in about 1000, [Tasks](../research/tasks.md#tick)) runs two updates and
shows as one missed step.

**Where a run's time goes** (`walk60`, 2026-10-05, two runs alike): the patched copy 0.15 s, PCSX2 from start to PINE
answering 12.1 s, the state running 0.5 s later, the 170 updates 5.7 s (real time), closing 0.2 s: 19.1 s, two thirds
of it PCSX2 starting. Started without a state it took as long (11.6-16.4 s to PINE over three launches), so the
state load itself is under a second. Loading each next state into a PCSX2 left running would save about 12 s a run;
PINE loads only numbered slots, so that needs a slot above 10 that the tool fills and empties, which is worth adding
once runs come in batches.

**The scenario file:**

```toml
description = "level99 street: the walk start and the walk, stick 60 % up for 100 updates, then the stop"
research = "docs/research/feel.md"
input = "walk60.txt"              # a Coney input script, beside the scenario
updates = 170                     # updates to record; Coney runs as many frames
fields = ["player", "camera"]     # field sets of research/traces/fields.toml

[original]
slot = 1                          # the quick-save slot to copy, never written
# state = "states/x.p2s"          # or a state file of your own, relative to scratch_dir (never committed)
patches = ["scripted-pad", "right-stick"]
let = { puppet = 'human("PoizoCiv")' }       # names resolved once, before the first update
setup = [ { address = "prec(puppet) + 0x1e", type = "u8", value = "0", frame = 0, until = 0 } ]

[coney]
level = "level99"                 # --play-level
args = []                         # more of Coney's options, such as ["--spawn", "start"]
settle = 0                        # updates Coney plays first with no input, dropped from its trace

[diff]                            # how `coney-tools trace diff --scenario` compares the two traces
start_frame = true
columns = ["x", "y", "heading", "speed", "gait", "clip"]
tolerance = { x = 0.1, speed = 0.05 }
```

`setup` writes are made after the samples of frames `frame` to `until`; the values are expressions worked out at that
moment (`f32(tf(player)) - 1.5 * sin(heading(player))` puts the puppet 1.5 m in front of the player).

`calls` (in `[original]`) make the game call one of its functions after the sample of frame `frame`, through the call
hook among the scenario's patches: `{ function = "0x002b2b90", args = ["u32(enemy + 0x90)", "u32(player + 0x90)"],
frame = 3 }` is `GoalFight(enemy, player)`. One call per frame; the arguments (up to six) are expressions worked out
then, and the recorder stops if the call before was not made.

**Patches** (`research/traces/patches.toml`) are named groups of edits to the copy's `eeMemory.bin`: a code edit gives
the address, the instruction word the state must hold there and the word that replaces it, and the copy is refused
when the state holds something else. `scripted-pad`, `right-stick` and `puppet` are the patches of
[Driving PCSX2](#driving-pcsx2).

**Fields** (`research/traces/fields.toml`) are named sets of columns. A field is read every update at an
**address expression** (`tf(player) + 0x4`, type `f32`), or worked out by a **formula** from the fields before it
(`wrap(deg(2 * atan2(qz, qw)))`); `hidden = true` keeps a helper out of the CSV, and `follow = true` works the address
out again at every sample, for a chain of pointers that changes as the game plays (the top of an animation stack).
Expressions are arithmetic over these names, and nothing else of Python:

| Name | Value |
| --- | --- |
| `player` | the human whose player number `+0x1b0` is 0, among the 60 at `0x00640c80 + i × 0x6d0` in use (`+0xd4` set) |
| `human("Name")` | the human in use with that name (`+0x80`) |
| `index(h)`, `rec(h)` | the handle index (`+0x92`); the record (`*(h + 0xd4)`) |
| `prec(h)`, `tf(h)`, `brain(h)` | `0x00660f50 + index × 0x2c`; `0x00714b00 + index × 0x20`; `0x006d53f0 + index × 0x2f0` |
| `heading(h)` | the heading in radians from the transform's rotation (0 faces +y, anticlockwise) |
| `camera`, `game_time` | `*(0x005d9158)`; `*(0x0050b734) + 0x48` |
| `u8` ... `f32` (address) | a value in memory (`u8 s8 u16 s16 u32 s32 f32`) |
| `sin cos atan2 hypot sqrt abs min max deg rad wrap pi` | math; `wrap` takes degrees to (-180, 180] |

A column that Coney's `--trace` also writes has Coney's name and unit ([Tracing](building.md#tracing)): `x`, `y`,
`z`, `heading`, `speed`, `vz`, `gait`, `clip`, `stamina`, `command`, `health`, `power` and the camera's `cam_*`,
`look_*`, `wanted_*`, `cam_distance`, `cam_pitch`, `cam_yaw`, `band_near` and `target_pitch`. `phase` (record
`+0x08`) is the original's only.

#### Hooks {#hooks}

Hooks are declared in the same file as `[hook.NAME]` and named in a scenario's `patches` like a patch. Each gives the
address, the two instruction words it displaces (checked against the state; neither may be a branch, and the first may
be a jump with its delay slot, as in a two-instruction setter) and up to seven values to `log`: a register (`a0`, `ra`,
`sp`), a float register (`"f28"` logs an `f32`; in a table without `type`, the raw word, to compare floats exactly),
`count` (the EE's cycle counter, 4,915,200 a 60 Hz tick) or a load such as `[a0 + 0x14]`, `[[a0 + 0x0] + 0x200]` or
`[0x005104f4]`, a word unless a table gives `type`. The hook's address must not be a delay slot or a branch target, and
a load must only follow pointers the hooked code itself uses: a bad load crashes the game. `pcsx2 record` writes each
hook's calls to `<trace>.<hook>.csv` (the ring's sequence number, the step, the values). The step is the update the call
was made in, the same numbering as the trace's rows, so a call logged at step N shows its effect in the sample of step
N. It comes from the tick count read in the same message: while the count is 2Q or 2Q + 1 the game is in the update a
sample labels Q + 1 (an entry of a missed update goes to the step after it; logging `[0x005104f4]` pins the tick
exactly). Recordings made before 2026-10-07 labelled entries with the step of the poll before: one step early for a call
made while the count was even (everything in `Humans_Update`), usually right for one made while it was odd (the second
tick, after the pair). `call = true` makes the call hook of `calls` above; put it at the entry of a function that takes
no floating-point arguments (`call-brains` is at `Brains_Update`, before the brains run). The hooks of the
runtime-checks pass: `tick-game` and `humans-update` (the play step and the character step), `wheel-update` (each object
the wheel updates), `state-code` (record `+0x14`'s setter), `set-command` and `get-command` (per-player `+0x20`),
`brain-think`, `brain-event`, `attack-warning`, `try-block`, `block-start`, `skid-test` (the locomotion's run-stop test)
and `call-brains`.

A logged load can also log the **text** it points to: `text = N` (at most N bytes, up to 1024) reads the string at the
value plus `text_offset`, and `text_when = "NAME=VALUE"` reads it only when another logged value has that value (a
script value's type tag, so a number is never read as a pointer). The recorder reads the texts while the game is
paused for the ring, writes them to a `<name>_text` column, and takes a text whose second byte is zero for UTF-16.
The event hooks use this: `event-call` (the script VM's call of a C binding, `0x00328a30`, its binding and first two
arguments), `event-callback` (the engine's look-up of a script function by name before it calls it, `0x00356e08`),
`event-hint` (the hint box showing a new text, `0x001cdf7c`) and `event-sound` (a sound started, `0x00111de8`, its
hash).

### Comparing with Coney {#comparing-with-coney}

`coney-tools trace coney` plays the same scenario on Coney headless (`--play-level` from its `[coney]` table,
`--frames` its updates, its input script, `--trace`), and `coney-tools trace diff` compares the two traces. A
scenario whose level opens with a script that holds the pad (level99 checkpoint 3: Vermin's fence lesson, about 9 s)
sets `settle` in `[coney]`: Coney plays that many updates first, the input script is shifted by them, and they are
dropped from the trace (renumbered from 1), so the run starts where the original's saved slot does:

```sh
uv run --project python coney-tools trace coney research/traces/scenarios/walk60.toml --out ../../scratch/walk60-coney.csv
uv run --project python coney-tools trace diff ../../scratch/walk60-original.csv ../../scratch/walk60-coney.csv --scenario research/traces/scenarios/walk60.toml
```

The diff aligns the rows by step, from the first update of input (the script's first frame + 1; `--from` and `--to`
choose others), and prints for each column the first step outside its tolerance, the largest difference and where it
is, then a short table of both traces around each divergence. It exits with 1 when a column is outside its
tolerance, so it can gate a check, and 2 when a trace cannot be read. Without a scenario it compares every numeric
column the two share; `--columns` picks some, `--tolerance COLUMN=VALUE` (or `*=VALUE`) sets tolerances (whole-number
columns are exact by default, others 0.001), `--shift N` compares the original's step s with Coney's s + N, and
headings compare round the circle.

The two games seldom start at the same spot: Coney starts a level where its script puts the player, the original where
the state was saved. `--start-frame` (or `start_frame = true`) moves each trace into its player's frame at the first
compared step, so positions are metres from where he stood, forward along +y, and headings are turns from his
heading then. The camera's points move with him, so a camera that starts at another angle shows as a heading offset.
To start both at the same spot, give Coney the state's place with `--start X,Y,Z,HEADING,DISTANCE,YAW` in the
scenario's `args`, taken from the original trace's first row (`x`, `y`, `z`, `heading`, `cam_distance`, `cam_yaw`).

The smoke scenarios reproduce claims of the research pages: `walk60` (the walk start, level99's street, slot 1),
`run_circle` (the run and the camera's auto-centre turning it into a circle, slot 1), both started at slot 1's spot
(level99 checkpoint 3 with `--start`), and `combat_cross` (`X1` then `XX2` at a puppet civilian 1.5 m away, slot 6, which
walks in to 1.36 m; on Coney the fight yard's `cross` spawn, a still target 1.05 m away that X1 steers onto alike).

### Differential playthroughs {#differential-playthroughs}

A trace diff compares two games update by update, which holds for a few seconds of walking but not for a mission: the
AI, load times and the camera move every later event, and a fixed input script falls out of step with the game it
drives. A **differential playthrough** compares a mission at the level a player notices instead, the **order of
events**, and drives both games through the same stretch with one **adaptive course**:

1. **Event logs on both sides, at the same semantic points.** Each game writes one CSV line per event (`step, kind,
   name, detail`): a script binding called, a call into the scripts by name, a hint shown, a sound started, a human
   appearing, going down or removed. Coney writes them with `--event-log`
   ([Building](building.md#event-log)); the original's come from hooks at the places that do the same thing (the
   script VM's binding call, the engine's script look-up, the hint box, the sound start), cited to their addresses on
   the research pages. A binding's call is the best hook: it is the mission script's own vocabulary, so both games
   name the event alike without interpretation.
2. **One course, two games.** The course is a small policy that looks, once an update, at what is on screen (the
   player and camera, the other humans, the world objects of interest) and at the update's events, and answers with
   the pad: walk into the marker that is shown, fight the nearest enemy when a lesson is armed, stand before a cabinet
   and press square then triangle. Both games give the same observation (Coney through `--pad-pipe`, the original from
   its tables over the emulator's memory interface), so one policy plays both, with the same partial stick
   deflections. A course plays the player's path: from the state at a checkpoint's start or a save made there, through
   the level as the Story path sets it up, never from a debug spawn the player cannot reach.
3. **Compare the order, not the frames** (`coney-tools trace events-diff`). The bindings the rules name become kinds
   (`tutorial`, `objective`, `checkpoint`, `hint`, `speech`, `spawn`, ...), long texts become hashes and arguments
   past a binding's arity are dropped. **Milestones** (tutorial steps, checkpoints, objectives, mission ends) are
   matched in order first and cut both logs into segments; every other kind is matched in order within its segment,
   so a hint is matched only between the milestones it came between. Sounds compare by set (their order follows the
   AI's timing), an event repeated within a few updates is one event, and an event seen more than `frequent` times
   compares by count. The report names the furthest milestone both games reached, the original's next one Coney never
   reached, and the missing, extra and out-of-order events with their steps; milestones whose spacing differs by more
   than a window are listed under timing.

A scenario (`research/traces/missions/*.toml`) names the course, the event that ends the run (`until`), the
original's save state and hooks, and Coney's level and checkpoint:

```sh
uv run --project python coney-tools trace mission research/traces/missions/level99_cp1.toml --side original --agent YOU --out ../../scratch/cp1-original.csv
uv run --project python coney-tools trace mission research/traces/missions/level99_cp1.toml --side coney --out ../../scratch/cp1-coney.csv
uv run --project python coney-tools trace events-diff ../../scratch/cp1-original.csv ../../scratch/cp1-coney.csv
```

Read a report from the top: where Coney stopped is the first finding, the rest are what the player meets on the way.
A missing hint or callback names a script path Coney never takes; a milestone far later on Coney than on the original
names a lesson the course could not finish, which is a Coney bug only once the same course finished it on the
original. When the two runs start at different points (a save state made inside a checkpoint, Coney at its start),
`--from "kind name"` starts both logs at the first event they share. The logs hold the game's text: they stay in
scratch, and `--labels` names the hashed texts from a string table read from your own disc.

Write a course from the player's view only: what a policy cannot see on screen it must not use (a script's internal
state, a handle number), or it will pass on one game for a reason the other does not share. When the course itself
fails on the original, fix the course before reading anything into Coney's run.

## Lessons learned {#lessons-learned}

What past sessions taught, written so that it holds for any game. Multi-agent coordination, the shared machine and
merging are in [How we work](how-we-work.md#shared-machine); the emulator's mechanics are in
[Driving PCSX2](#driving-pcsx2).

### Method

- **Runtime beats reading.** When the code is ambiguous, run it: read or write the memory of the original while a
  scripted scenario plays, and grade the result `confirmed (runtime)`. Say on the page which patch or input the claim
  depends on.
- **Drive every movement like a player would.** Give input as a gamepad with analog sticks, at realistic partial
  deflections, and state the magnitude with every claim that depends on it ("stick 0.5, straight up"). A behaviour
  found only at full deflection is usually not what the player meets.
- **Input goes through the game's memory, never the window.** Writing pad state over the remote-memory interface (the
  patches above) is exact, repeatable and leaves the user's keyboard and focus alone. Use posted window messages only
  for the rare hotkey, and never move focus.
- **One sample per update.** Compare games by the update, not by wall-clock time: count the game's own ticks, record
  one row per update, and apply scripted input as each update is seen. Rows labelled by the poll rather than the
  update are off by one, which looks like a behaviour difference and is not.
- **Test your instruments.** A recorder, hook or diff tool is code too. Pin its labelling with a test that drives a
  fake game (the hook recorder once labelled every entry one update early until a test with two-message updates
  exposed it), and say in the guide how recordings made before a fix are wrong. When a result is off by a fixed
  amount, suspect the tool before the code.
- **Compare missions by events, not frames.** Past a few seconds, two games drift apart in time for harmless reasons
  (AI timing, loads, the camera). Compare the order of the events a player notices instead, drive both with one
  adaptive policy that plays by what is on screen, and let the first milestone one game never reaches say where to
  look ([Differential playthroughs](#differential-playthroughs)).
- **Compare, then localise.** Run the same scenario on both games and diff the traces; the first differing column and
  step says where to read. A difference goes back as a question or a fix, never as a page edit that hides it.
- **Trace the cause, not the symptom.** A stuck character, a missing effect or a wrong value usually comes from a
  state that is never reset or a handler that never fires; follow who writes the value and who clears it. Write down
  what you ruled out, in one line, so nobody repeats it.
- **Test through the path the player uses.** A reimplementation grows shortcuts for testing (start a level directly,
  skip the menus), and each shortcut that sets the game up its own way hides bugs the player meets: a pause that only
  the real path has, a hand-over between checkpoints that a direct start never plays, a debug service wired to one
  path only. Keep one set-up that every start goes through, differing only in where it starts, and run playthrough
  tests through it. When a play-tester sees a bug that a test does not, first ask which path each one took.
- **Find a second source for the same function.** Another build of the game (named library calls, inline strings) can
  read faster; cite evidence only at the primary executable's addresses.
- **Ask the data.** Tables, lists and counts can be read from the disc by tool and printed as counts and hashes;
  that is evidence anyone can rerun, and it puts no game data in the repository.

### Conduct

- **Claim before use, release after.** Anything shared and scarce (an emulator copy, a lock) has one user at a time:
  claim it with the tool, release it when done, and close what you started.
- **Keep other people's slots read-only.** Quick-save slots, settings and files someone else made are never overwritten;
  save your own states to files in scratch, and put patched words back before reusing a saved state.
- **Add names, never undo them.** The shared Ghidra project is written by many analysts: rename and annotate freely,
  but do not revert another analyst's names; a disagreement goes on the page as an open question.
- **Do not guess in code.** A gap in a page becomes an open question on the page and a marked stand-in in code, never
  a silent guess ([When a research page isn't enough](#when-a-research-page-isnt-enough)).
- **Research is done when a reader can implement from it:** a name and plate comment in Ghidra, and a page that cites
  the address with an evidence level and says what the function does ([The Understood measure](#understood)).
- **Weak evidence stays labelled.** A screenshot is a source of measurements, not a claim; a claim quotes numbers, the
  scenario that produced them and the build or state they came from.

## Writing up a finding

A finding is done when someone else can use it without asking you. For each one:

1. **Update the living page.** Find the page for the subsystem or format and change it in place; create a page only
   when none covers the subject. Don't start a dated notes page: one page per subject means the reader never has to
   reconcile two versions.
2. **Grade every claim** with an [evidence level](#evidence-levels).
3. **Add or update the YAML entries** for the functions, globals and types the finding touches (once the database exists),
   with the same evidence level as the page.
4. **Cite addresses** as `0x001490b8`: eight hex digits, in the NTSC-U executable `SLUS_212.15` (SHA1
   `e9cb2cc49aa046b9e494313dce2f5038ed17b2f4`). Every address in the project refers to that one file, so a reader
   with the same disc can check any claim.
5. **Describe, don't reproduce.** Explain behaviour in prose, with short pseudocode or a short snippet where it
   makes the point clearer. Never paste a whole function, decompiled or disassembled, and never paste a long
   stretch of one: it puts the original's code in the repository and hands the implementer something to copy. See
   [LEGAL.md](repo:LEGAL.md#research-limits).
6. **No game data.** Tables of offsets, constants and counts are facts and belong on the page; the bytes of a game
   file, a dump or an extracted asset never do.
7. **Build the docs** with `mkdocs build --strict` (see [Writing these docs](writing-docs.md)), which catches broken
   links and pages missing from the navigation.
8. **Ship the docs with the code.** CI refuses a pull request that changes `src/` or `python/src/` without changing
   anything under `docs/` or `research/`. A change that needs no documentation (a refactor, a rename) says so with a
   line `Docs: none` in the pull request description; editing the description re-runs the check. Check it yourself with
   `git diff --name-only main... | uv run --project python coney-tools repo check-docs`. Counts quoted in a page by
   hand are held to the data by tests and by `{count}` in the reference lists ([above](#reference-lists)).

## The Understood measure {#understood}

A function is researched in full ("understood" on the [progress page](../progress/index.md)) when it has a
meaningful name and a plate comment in the shared Ghidra project, and a research page cites its address in a table
row or paragraph that states an evidence level and says what it does. A function nobody needs (dead code, a debug
stub) is cited with `not needed: <reason>` instead. The bar checks the name and the citation; the plate comment is
listed in the backlog. Citations on the [source map](../research/source-map.md) do not count; a script binding's
wrapper counts through its `evidence` in `research/bindings`.

The names, sizes and plate flags come from `docs/progress/ghidra-functions.tsv`, exported from Ghidra; the
citations are read from the pages on every `progress update`. After renaming functions in Ghidra, refresh both
(ghidra-mcp on `:8090` must be running; the export only reads):

```sh
uv run --project python coney-tools progress ghidra    # re-export the listing (--check: exit 1 when stale)
uv run --project python coney-tools progress update    # regenerate the bars; CI runs it with --check
uv run --project python coney-tools progress backlog "<scratch>/research-backlog"   # per-subsystem to-do lists
```

The backlog writes one Markdown file per subsystem, outside the repository: every function not yet understood,
largest first, with what it lacks (`name`, `cite` or `evidence`), whether it has a plate comment, and the name a page
already gives it. A row that lacks only `name` is documented already; renaming it in Ghidra is the cheapest step.
