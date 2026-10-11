# Building and testing

This page takes you from a fresh clone to a built, tested Coney on Windows, Linux or macOS, and covers the Python
tools, the documentation and the checks CI runs on every pull request. The rules the code itself follows are in
[Conventions](conventions.md); where to put your game files and tools is in [Local workspace](workspace.md).

Nothing here needs the game. The build and every test run on synthetic data, so you can build and test Coney
before you have a disc image at all.

## What you need

| | Windows | Linux | macOS |
| --- | --- | --- | --- |
| Compiler | MSVC 19.38+ (Visual Studio 2022 17.8 or Build Tools 2022) | GCC 13+ or Clang 19+ | Xcode 16+ |
| CMake 3.28+ and Ninja | bundled with Visual Studio | distribution packages | Homebrew |
| Git | yes | yes | yes |
| [uv](https://docs.astral.sh/uv/) | for the Python tools and pre-commit | same | same |

The C++ dependencies (SDL3, librw, Dear ImGui, Catch2, FFmpeg) are not installed by hand: CMake downloads them on the
first configure,
at the exact commits pinned in `cmake/deps.cmake`. That first configure needs network access and takes a few
minutes; later builds reuse the copies under `build/<preset>/_deps/`.

librw is built for its OpenGL 3 platform with SDL3 creating the window and the context, so the build also needs the
OpenGL headers and libraries: part of the system on Windows and macOS, `libgl1-mesa-dev` on Linux (in the package
list below). CMake hands librw the SDL3 it fetched rather than one installed on the machine; how, and why librw's own
asserts are off, is explained in `cmake/deps.cmake`.

Clang 17 and 18 are supported by the language rules but not on Linux with libstdc++: libstdc++ only declares
`std::expected` when the compiler reports full C++20 concepts support, which Clang first does in version 19. Use
Clang 19 or newer there.

### FFmpeg {#ffmpeg}

The game's movies are Bink 1 files ([Movies](../research/movies.md)); Coney decodes them with FFmpeg's Bink demuxer,
Bink video decoder and Bink audio (DCT) decoder. `cmake/deps.cmake` fetches the FFmpeg 9.0.2 release tarball and
checks its SHA-256, and `cmake/ffmpeg/CMakeLists.txt` compiles only what those three components need (about 90 of
FFmpeg's C files) into one static library, `ffmpeg_bink`, linked by `src/platform/` alone. The build is
LGPL-2.1-or-later:
no GPL, version-3 or nonfree part, no network, no programs, no assembly ([Licences](repo:LEGAL.md)).

**Why not FFmpeg's own build.** FFmpeg builds with a `configure` script and `make`, which need a POSIX shell (MSYS2 on
Windows, with MSVC as the compiler) and refuse a source or build folder whose path has a space in it, as many Windows
checkouts do. Prebuilt LGPL archives are full builds of everything, and the usual ones are not kept at fixed versions.
So CMake builds the trimmed library itself, the same way on Windows (MSVC), Linux (GCC, Clang) and macOS (Apple
Clang), with nothing to install. It writes the files `configure` would generate (`config.h` and the component lists),
setting every `CONFIG_`, `HAVE_` and `ARCH_` name the sources use to 0 except the few the file lists; FFmpeg's plain
C code runs (no assembly), which decodes a 640 × 448 movie many times faster than it plays. FFmpeg is always built
optimised, whatever the preset, because its code relies on the compiler removing disabled branches. It adds about a
minute to a clean build; its sources are cached with the other dependencies under `build/<preset>/_deps/`.

**To update FFmpeg**, change the version, URL and SHA-256 in `cmake/deps.cmake`. If the new release links with
missing symbols, the source list in `cmake/ffmpeg/CMakeLists.txt` needs the files that define them: on Linux, configure
the release with the options in that file's header, build its three libraries, link a small program that opens and
decodes a Bink file with `-Wl,-Map`, and take the objects the map lists.

**To use a different or modified FFmpeg** (the LGPL's relinking right), point CMake at its sources and rebuild:
`cmake --preset dev -DFETCHCONTENT_SOURCE_DIR_FFMPEG=/path/to/ffmpeg`. Coney's own code sees FFmpeg only through
`src/platform/`, so any FFmpeg with the Bink components works.

### Windows

Install Visual Studio 2022 or the Build Tools for Visual Studio 2022 with the **Desktop development with C++**
workload. It brings MSVC, CMake and Ninja; you do not need to install them separately.

The compiler and those tools are on `PATH` only inside a shell with the MSVC environment loaded. Either open the
**x64 Native Tools Command Prompt for VS 2022** from the Start menu, or run `vcvars64.bat` in an existing
`cmd` shell:

```bat
"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
```

For a Visual Studio install, replace `BuildTools` with your edition (`Community`, `Professional` or `Enterprise`)
and `Program Files (x86)` with `Program Files`. Every `cmake` and `ctest` command below runs from that shell.

### Linux

On Ubuntu 24.04 (other distributions have the same packages under similar names):

```sh
sudo apt-get install cmake ninja-build g++-13 \
  libx11-dev libxext-dev libxrandr-dev libxcursor-dev libxfixes-dev libxi-dev libxss-dev libxtst-dev \
  libwayland-dev libxkbcommon-dev libegl1-mesa-dev libgl1-mesa-dev libdbus-1-dev libudev-dev \
  libasound2-dev libpulse-dev libpipewire-0.3-dev
```

The second and third lines are what SDL3 needs to build its X11 and Wayland video drivers, the fourth its ALSA,
PulseAudio and PipeWire sound output; `libgl1-mesa-dev` is
also what librw's OpenGL renderer links against. For Clang, install
`clang-19 clang-tools-19` in place of `g++-13`; `clang-tools-19` brings `clang-scan-deps`, which CMake runs on C++23
sources when the compiler is Clang. Pick the compiler with `CC` and `CXX` before the first configure:

```sh
export CC=clang-19 CXX=clang++-19
```

A build directory remembers its compiler, so to switch compilers later, delete `build/<preset>/` first.

### macOS

Install Xcode 16 or newer (or its command line tools with `xcode-select --install`), then:

```sh
brew install cmake ninja
```

## Build and test

Everything goes through the presets in `CMakePresets.json`. The everyday loop is:

```sh
cmake --preset dev
cmake --build --preset dev
ctest --preset dev
```

The first line only needs running again when a `CMakeLists.txt` or `cmake/deps.cmake` changes in a way the build
does not pick up by itself. Each preset builds into its own `build/<preset>/` folder, so presets never disturb each
other.

| Preset | Build type | What it is for |
| --- | --- | --- |
| `dev` | Debug | day-to-day work |
| `release` | RelWithDebInfo | an optimised build that can still be debugged |
| `ci` | Debug, warnings as errors | what CI builds; run it before a pull request |
| `asan` | Debug, warnings as errors, AddressSanitizer and UBSan | memory and undefined-behaviour bugs; Linux and macOS only |

`ctest` runs the Catch2 unit tests (`coney_tests`) and seventeen smoke tests of the `coney` executable itself: it starts
and stops headless, prints its help, refuses a bad argument, refuses `--load`, `--view-txd`, `--view-sheet`,
`--view-text`, `--view-world`, `--view-character`, `--play-level` or `--render-references` without `--disc`, refuses a
disc that does not exist, refuses `--fps-cap` in test mode, plays a synthetic input script
(`tests/support/menu_input.txt`) and refuses one that does not exist, opens [the debug menu](debug-menu.md) with the pad
chord and walks it to a native call (`coney.debug_menu_by_pad`, `tests/support/debug_menu.txt`), and refuses a tunables
file that is not one. With `CONEY_DISC` set when CMake configures, more run `coney --disc`: the start-up movies, `LOGO`
played out and the others skipped by a scripted pad (`coney.plays_movies`, `tests/support/movie_skip.txt`), to the main
menu (`coney.reaches_main_menu`), Rembrandt's clips in the character viewer under a scripted orbit
(`coney.views_character`, `tests/support/character_orbit.txt`), and level99 played headless under a scripted pad
(`coney.plays_level`, `tests/support/play_walk.txt`). The unit tests build their disc images, archives, RenderWare
texture dictionaries, streamed worlds, PS2 geometry and collision meshes byte by byte; none needs the game or a GPU (the
librw tests run librw on its NULL device). Fifteen tests check your own disc: every texture dictionary; every sprite
sheet, font and the sheet table; every streamed world with the atomics of its parts (`[world]`, about a second); every
level's worlds streamed under a scripted camera path, with the streaming's invariants checked every frame
(`[world_streaming]`, about 30 seconds); the UI strings of all five languages, run through the game's own Lua scripts
(`[strings]`); the two text fonts with every English UI string laid out in them (`[text]`); the front end's scripts (the
preloads, `global.lua`, `level100.lua` and the menu callbacks) run in the script system with no error and no missing
binding (`[scripts]`); the start-up path from the legal screen to the main menu, through quick rumble and story to the
level request and back, driven by a scripted pad (`[frontend]`); STORY through the mission-complete mode to Rembrandt
standing at level99's start under the pad, QUICK RUMBLE through the Rumble menu's four screens to a Baseball Fury on the
Fight Pen's flag under the pad, the level scripts' player starts and models for a few checkpoints, the hub's and two
arenas' flag starts, the hub's chat events run for 20 seconds without a script error, and the game's random table read
from the executable (`[story]`); a QUICK RUMBLE Brawl left to the computer's Orphan, which beats the Fury, through the
win sequence to the result screen naming the Orphans, a WAR PARTY's hand-over, and King of the hill held by the player
to its result screen, Battle royal won by ringing the other side out (`[rumble]`, the set-up changed after the menus as
an unlocked profile would choose it); every animation clip in the WAD, parsed and sampled (`[anim]`, about 7 seconds);
every Character List record with its model, textures, character data and clips, skinned (`[characters]`); every Object
List record with its model and texture dictionary, the models of one atomic read (`[object_list]`); Rembrandt's Anim
Range List with a damage for every attack and the grab and tackle ranges, and Rembrandt in the sandbox's fight yard
doing a combo, a grab with a strike, spins and a throw, a tackle and a mugging on a passive target (`[combat]`); and
Rembrandt at level99's start, walked, run, turned, stopped and run into the scenery by scripted partial stick
deflections, with his speeds and clips checked against the research (`[player]`), and played again through the main loop
at five frame rates and with irregular frames, bit for bit the same as in test mode (`[frame_rate]`); and `LOGO` decoded
through FFmpeg to its 115 frames and its sound, and `L99_IN`'s six captions found (`[movies]`). They run only when the
environment variable `CONEY_DISC` names the disc, are reported as skipped otherwise, and print counts only:

```sh
CONEY_DISC=/path/to/warriors.iso build/dev/tests/coney_tests "[disc]"
```

The level99 intro's sound check (`[disc][story][audio]`) also writes everything it mixed as a 48 kHz stereo WAV file
when `CONEY_AUDIO_WAV` names one, to listen to; keep it out of the repository.

## Run Coney {#run-coney}

The executable is `build/<preset>/src/platform/coney` (`coney.exe` on Windows). Run with no arguments, it opens a
960 × 720 window and runs until you close it (or press Escape). Underneath, the game-mode stack runs on a fixed
1/30 s step with an idle mode at its bottom, which clears the screen to a dark slate and presents it every frame.
The game runs at the same speed at any frame rate ([Frame rate](#frame-rate)).

Everything is drawn into the original's 640 × 448 screen, shown at a television's 4:3 shape as large as the window
allows and centred; a window of another shape gets black bars at the sides or at the top and bottom.

```text
coney [--disc PATH] [--load ENTRY]... [--view-txd ENTRY] [--view-sheet SHEET] [--frames N] [--screenshot PATH]
      [--headless] [--help] [--input-script FILE] [--view-text FONT TEXT] [--language CODE]
      [--view-world NAME] [--view-character [NAME]] [--anim CLIP]
      [--play-level NAME [--spawn NAME | --checkpoint N] [--start X,Y,Z,H[,D,YAW]] [--trace FILE]
                   [--script-trace FILE] [--scene NAME] [--camera X,Y,Z,QX,QY,QZ,QW[,FOV]] [--freeze-world]]
      [--render-size WxH]
      [--sandbox [NAME]] [--assets DIR] [--render-references DIR [--kind KIND] [--only NAME]... [--names FILE]]
      [--fps-cap N] [--vsync on|off] [--line-blend on|off] [--show-fps] [--tunables FILE]
      [--no-audio | --audio-test]
      [--skip-movies] [--rumble TYPE [--arena N] [--gang-size N]]
      [--profiles DIR] [--dev-overlay N] [--no-activate] [--event-log FILE] [--pad-pipe]
```

Coney draws with librw's OpenGL 3 renderer (an OpenGL 3.3 core context through SDL3; librw falls back to 2.1 or OpenGL
ES). Where the driver offers less than OpenGL 3.3 (Windows' own OpenGL 1.1 renderer on a machine with no graphics
driver, such as CI's), Coney stops at start-up with an error that names the version it was offered, since SDL would
otherwise hand librw the old context and librw would crash. `--frames N` stops after N frames (each one fixed step and
one render, see [Frame rate](#frame-rate)), which is how tests and scripts run it. `--headless` runs with no window
and librw's NULL renderer, so it needs neither a display nor a GPU; this is how CI runs it:

```sh
build/dev/src/platform/coney --headless --frames 3
```

Without `--headless`, a machine with no display or no OpenGL fails at start-up with SDL's reason and exit code 1.

`--screenshot PATH` saves the last frame (the one `--frames N` stops at) as a PNG and prints how many of its pixels
differ from the background and a hash of the frame, so a script can check that something was drawn without keeping
the image. Keep screenshots of game data out of the repository (`../../scratch/` is the place).

The STORY profiles are saved as one file each (`profile-1.sav` to `profile-6.sav`) in `profiles` in your data folder
(`%APPDATA%\Coney\Coney\` on Windows, `~/.local/share/Coney/Coney/` on Linux, `~/Library/Application
Support/Coney/Coney/` on macOS); `--profiles DIR` names another folder. A test-mode run without `--profiles` keeps
its profiles in memory, so tests never touch yours ([Profiles and saving](../research/save.md#coney)).

### Frame rate {#frame-rate}

The game always advances in the original's fixed steps of 1/30 s, 30 a second, whatever the display does; drawing is
apart from the step and runs as fast as the display or the cap allows, each frame blended between the last two steps,
so motion is smooth above 30 frames a second and the game's speed never changes
([Update and render](conventions.md#update-and-render)).

| Option | Does |
| --- | --- |
| `--fps-cap N` | at most N frames a second; 0, the default, is no cap. 30 is the original's rhythm: one step and one frame, nothing blended |
| `--vsync on\|off` | wait for the display's vertical blank when presenting (on, the default) or not (frames may tear) |
| `--line-blend on\|off` | an optional PS2 look: soften the picture as the PS2's video output does, each shown line the mean of two neighbouring lines of the original's 448 (on; [Rendering](../research/rendering.md#output)), or show the frame as drawn (off, the default); reference renders are never blended |
| `--show-fps` | print the frame and step rates once a second, and the totals when Coney stops |

The default, no cap with vsync on, draws one frame per refresh of the display. With vsync off and no cap Coney draws
as fast as it can, which keeps a processor core busy; give a cap to save power. Below 7.5 frames a second (or after a
stall such as dragging the window) the game slows down rather than catching up in a rush, as the original slows down
when a frame runs long. A blended frame shows the world up to one step (33 ms) behind the newest simulated state, and
the pads are read once per step, as in the original.

Test mode is lockstep: with `--frames`, `--headless`, `--input-script` or `--screenshot` every frame is one step and
one render, with no clock, so a run gives the same result every time on any machine. `--fps-cap` and `--show-fps`
are refused there.

A test-mode run's window opens without taking the keyboard focus, so a scripted run never interrupts someone typing;
`--no-activate` does the same for any other run, and `--render-references` never takes it. Agents start Coney only
this way ([Running Coney](research-workflow.md#running-coney)).

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --show-fps
build/dev/src/platform/coney --disc /path/to/warriors.iso --view-character --fps-cap 144 --vsync off --show-fps
```

### Sound {#sound}

Coney plays through the system's default playback device at 48 kHz stereo and prints the device's name at start-up;
when no device opens, it says why and runs silent. When the default output changes, or a headset is plugged in or
out, the sound moves to the new default device and carries on; if SDL gives the device up altogether, Coney opens the
default device again, trying once a second until one opens. `--no-audio` opens no device. In test mode no device opens either:
the sound is mixed offline, 1,600 frames (1/30 s) per frame, so a run mixes the same samples every time.
`--audio-test` plays a synthesised tone sweep (220 to 880 Hz and back, looping) and prints at the end what was mixed;
offline that is the frame count, the peak and a hash. The debug menus' Audio page sets the volumes and plays the same
tone ([The debug menus](debug-menu.md#pages)).

```sh
build/dev/src/platform/coney --audio-test
build/dev/src/platform/coney --headless --frames 60 --audio-test
```

### Loading entries from your disc

`--disc PATH` names your own copy of the game: a mounted disc (`H:\` on Windows, `/mnt/disc` on Linux), a folder
holding `WARRIORS.DIR` and `WARRIORS.WAD`, or an ISO 9660 image of the disc (the same forms `coney-tools wad`
takes, see [The coney-tools command line](coney-tools.md#naming-the-disc)). Coney reads `WARRIORS.DIR`, checks it
against `WARRIORS.WAD`, and prints how many entries it lists.

With `--disc` and no viewer or `--load`, Coney runs the game's start-up as far as it goes. First the start-up movies
play with their sound (`LOGO`, `PLOGO`, then the intro `L1_IN`; [Movies](../research/movies.md#coneys-implementation)):
any pad button skips one, except `LOGO`, which always plays its 3.8 s. `--skip-movies` skips every movie at once; the
frame numbers below count from the legal screen, as they do with it. Then the legal screen for five seconds (150
frames; no button skips it, as in the original), the memory-card check's "checking" message for three seconds (90
frames), then the menus' first screen over `level100`'s world, the game's logo and a blinking "press START" (from frame
242). START leads to the main menu (story, extras, quick rumble); the d-pad or the left stick moves, cross chooses and
triangle or circle goes back. Coney prints a line for each movie, music and sound it plays or skips, and one for each
screen it reaches
([Front end](../research/frontend.md#coneys-implementation)). `--language CODE` picks the strings and the legal
screen.

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --frames 3 --screenshot ../../scratch/legal.png
build/dev/src/platform/coney --disc /path/to/warriors.iso --headless --frames 530 --skip-movies --input-script tests/support/start_menu.txt
```

The second line runs to the main menu without a window: its last line is `profile manager: PM_Mode`. The front end
loads behind the memory-card loading screen (its two pictures and the red spinner, 7.2 s), so the menus are up from
frame 458.

**STORY** starts a new game as the original does, through the profile screens: (with two pads, how many players),
the profile manager (CREATE NEW PROFILE when there is none), the name keyboard (cross types the key under the cursor,
OK accepts), the difficulty, the brightness (left and right) and the subtitles. Profiles last for the run only (Coney
has no saves yet). The menus fade out and the game's own scripts take it from there (`Menu.startGame`,
`runNextMission(1)`, the mission-complete mode, `UnlockAndLoad`), to `level99` at checkpoint 1. Its level script
creates Rembrandt, and Coney loads the level with him where the script put him, under your control
([Playing a level](#playing-a-level)), after the level's loading screen (its pictures, the timed bar and the fades, for
about 3.2 s: [Level loading](../research/level-loading.md#coneys-implementation)), and its intro movie `L99_IN` plays
over it (skipped with `--skip-movies`). There is no intro scene, tutorial or other character yet. The log shows the
way: `profile manager: PM_Create` and the other screens, `profile manager: profile "A" created in slot 0`, `script:
Menu.startGame()`, `mission complete: kind 4`, `level flow: starting level99`, `loading screen: level99 (3 pictures:
...)`, `gameplay: level99 checkpoint 1: player 1 Rembrandt ...`, then `movie: L99_IN`. The scripted way
(`tests/support/story_new_profile_session.txt`: a one-letter name, the defaults, the cursor moved with the left stick
at 70 %; the test harnesses without the memory-card screen play the same presses 220 frames earlier,
`tests/support/story_new_profile.txt`):

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --headless --frames 790 --skip-movies --input-script tests/support/story_new_profile_session.txt
```

The loading screen shows from about frame 672 and level99 plays from frame 768.

**QUICK RUMBLE** follows the original's path too: the menu's scripts call `ShowRumbleModeInterface`, which opens the
Rumble menu (mode 0x11) and its four screens, as a fresh boot offers them: **Game Mode** (1 ON 1 or WAR PARTY),
**Game Type** (one player against the computer, or versus or co-op with a second pad), **Choose Gangs** (the BASEBALL
FURIES against the ORPHANS, the gangs a fresh profile has) and **Choose Area** (the Fight Pen, `level102`). The lists
come from the disc's own Rumble scripts, so the text is the game's. Up and down (d-pad or left stick) pick an entry,
cross confirms it and moves on, triangle or circle goes back a screen (out of the menu from the first). On Choose
Gangs each side picks in turn: up and down choose the gang, left and right rotate its roster to choose the warchief,
cross locks the side (twice in all), and back unlocks it; each change of screen is logged (`rumble menu: Game Type`).
The layout is Coney's: the screen's
name and its entries in white and grey on black. Confirming the arena calls the scripts' `Menu.startRumbleMode`, whose
level request loads the arena; the arena's script reads the set-up (`GetRumbleModeData`, `GetRumbleModeGangName`), and
its start callback creates player 1, the Furies' first fighter, and teleports him to his gang's first flag, where you
control him. A Brawl then plays to its end ([Rumble mode](../research/rumble.md#coney)): the intro names the two
gangs over the arena, and cross on its prompt starts the countdown; the Orphan confronts you and fights. Knock him
out and the win camera circles the winner, then the result screen offers **Replay** (the match again) and, after
**more**, **Rumble menu** (back to Game Mode) and **Quit** (the main menu). In a script, from boot (cross skips the
two logo movies, the stick up most of the way wraps the main menu round to QUICK RUMBLE, then cross on each screen,
twice on Choose Gangs, then on the intro's prompt):

```text
120 tap cross
135 tap cross
430 tap start
442 stick left 0 70
444 stick left 0 0
455 tap cross
510 tap cross
520 tap cross
530 tap cross
535 tap cross
540 tap cross
860 tap cross
900 tap cross
940 tap cross
980 tap cross
1020 tap cross
```

Left at that, the Orphan beats the Fury, cheers on the win camera, and the result screen names the Orphans (about frame
6100). With the stick down most of the way on Game Mode (`500 stick left 0 -70`, `502 stick left 0 0`) the match is a
WAR PARTY, five a side; when the player goes down with team-mates standing, the pad passes to one of them (`player: the
pad passes from human ... to human ...`). Add `tap square` every 12 frames from 1100 to 2000 and the Orphan goes down
instead; the result screen takes input from about frame 2400 (`2400 tap cross` replays). The run logs each step (`rumble
intro: done, calling FinishCountdown`, `rumble result: winner ...`, `rumble result: choice 0`).

#### Rumble from the command line {#rumble-from-the-command-line}

A fresh profile's Rumble menu offers only **1 ON 1** and **WAR PARTY** (Game Mode), the Furies and the Orphans and
the Fight Pen; King of the hill, Battle royal, Survival and Wheelchair, and the other arenas, are unlocked through the
story ([Rumble](../research/rumble.md)). For play-testing the others there is `--rumble TYPE [--arena N] [--gang-size
N]` (`--disc` needed): Coney boots as usual and goes through QUICK RUMBLE's menus, and when the arena is confirmed the
mode, the arena and the gang size are written over the menu's choice, so the arena's scripts run as the menu would have
set them. Go through the menu by hand (or with a script, as above); whatever you choose there, the match is the one you
named, and the log says `rumble menu: --rumble sets game type ...`.

| `TYPE` | Mode | Game type | Default arena | Default gang size |
| --- | --- | --- | --- | --- |
| `brawl` | Brawl (1 ON 1) | 12 | 102 | 1 |
| `warparty` | Brawl (WAR PARTY) | 14 | 102 | 5 |
| `kinghill` | King of the hill | 2 | 101 | 3 |
| `royal` | Battle royal | 3 | 131 | 3 |
| `survival` | Survival | 9 | 134 | 1 |
| `wchair` | Wheelchair | 24 | 104 | 1 |

`TYPE` may also be the game type's number (a listed number takes that mode's defaults; any other 1 to 99 plays in arena
102 with one a side, which its arena script may not support). `--arena` takes an arena's level number (101 to 137) and
`--gang-size` 1 to 9. A bad `TYPE` prints the valid names and exits with 2. Test mode works as for any run: add
`--headless --frames N --input-script FILE`.

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --skip-movies --rumble kinghill
build/dev/src/platform/coney --disc /path/to/warriors.iso --rumble royal --arena 131 --gang-size 3
```

`--load ENTRY` loads one WAD entry through the reimplemented chunk system and prints a summary of it. `ENTRY` is a
file name such as `level1.lev` (any letter case) or a name hash written `0x` and up to 8 hex digits, such as
`0x7e23a6f2`, for entries whose name is not known. Give `--load` as often as you like; with any `--load`, Coney
opens no window, loads one entry per frame of its fixed timestep and exits when all are done.

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --load level1.lev --load global.pak
```

```text
/path/to/warriors.iso: WARRIORS.DIR lists 10701 entries
level1.lev: entry 6864, hash 0x393f70e2, 46992 bytes
  flat container: 18 chunks, 46688 bytes of chunk data (header says 46688)
    type 0x03 Collision Mesh: 1 chunk, 160 bytes
    ...
  left on the stacks: 18 chunks, 0 objects; 0 trailing bytes
```

The summary gives the container's shape (flat, or grouped for a pack of resources), the number of chunks and their
bytes per [chunk type](../research/chunk-system.md#chunk-type-table), and what the chunk handlers left on the
loader's stacks. It prints counts and sizes only, never the data. An entry that is not a chunk container (Lua
bytecode, text, sound banks) is reported as such. Coney exits with 0 when every entry loaded, 1 when any could not
be found or parsed, and 2 for a bad command line. With `--load`, the two RenderWare texture dictionary chunk types
(`0x0B` and `0x2A`) are read by their stream handlers through librw, on its NULL renderer.

### Viewing texture dictionaries

`--view-txd ENTRY` opens the window and shows every texture of a WAD entry's texture dictionaries, laid out in a grid
that fills the window, each scaled to its cell without changing its shape and drawn with its transparency over a
grey background. `ENTRY` is named as for `--load`. The entry may be a chunk container holding texture dictionary
chunks (a standalone resource, a pack or a level), or a world sector atomics file, whose stream starts with a
(usually empty) dictionary. Coney prints how many dictionaries and textures it found, with each texture's size and
format, then runs until the window closes or `--frames N` is reached.

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --view-txd 863681355 --frames 3 --screenshot ../../scratch/legal.png
```

That entry is the legal screen, the first image the game shows ([Graphics](../research/graphics.md#first-screen)).
The textures are the PS2's palettised formats, converted by librw: palettes are expanded and the PS2's alpha range
(128 is opaque) is scaled to 0-255.

### Viewing sprite sheets

`--view-sheet SHEET` opens the window and shows every rectangle of a sprite sheet
([GUI](../research/gui.md#particle-page)) as a sprite, laid out in a grid over the logical screen, each at its own
shape, over a grey background. The sprites go through the same sprite batch and 2D pass as the game's
([GUI](../research/gui.md#coneys-implementation)), so this is also a check of that path. `SHEET` is a sheet's
resource name, such as `menu_system`, `big_font` or `legal_screen` (Coney looks for the WAD file named by the decimal
CRC-32 of the name), or failing that a WAD entry named as for `--load`. Coney prints the number of rectangles, the
sheet's first glyph (-1 for a sheet that is not a font) and the texture's size.

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --view-sheet menu_system --frames 2 --screenshot ../../scratch/menu.png
```

### Viewing text

`--view-text FONT TEXT` opens the window and lays out and draws one text, as a text widget would
([GUI](../research/gui.md#coneys-implementation)): markup tags such as `<COLOR AA2B2BFF>`, `<SIZE 1.5>`, `<CR>`,
`<CENTER>`, `<BIGFONT>` and the button glyphs `<X>`, `<T>`, `<DU>` all work. `FONT` is the sheet the text starts in:
`part_page0`, the font Coney's text starts in and the one with the button pictures, or `big_font`, which `<BIGFONT>`
always uses. `TEXT` is the text itself (quote it for the shell), or `@` and the id of one of the game's UI strings,
decimal or `0x` hex (`@0x1f` is the menus' usage line). For `@ID` Coney runs the game's string scripts for the
language `--language CODE` gives (`en`, `es`, `fr`, `it` or `de`; English by default) and prints the number of strings
and the length of the one shown, never its text. The text's game time runs with the frames, so `<PULSE>` and
`<DISPLAYTIME>` animate.

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --view-text part_page0 @0x1f --frames 3 --screenshot ../../scratch/usage.png
build/dev/src/platform/coney --disc /path/to/warriors.iso --view-text part_page0 "<BIGFONT>Title</BIGFONT><CR>Press <X>" --frames 3
```

### The world viewer {#the-world-viewer}

`--view-world NAME` loads a level's streamed scenery and lets you fly through it
([The streamed world](../research/world.md#coneys-implementation)). `NAME` is a level, such as `level2`, which loads
both of its worlds (`level2s` and `level2d`), a single world such as `level2s`, or `objarena`. The worlds' layouts and
textures load first, then the parts around the camera before the first frame (the original's preload), and from then
on one part is read or freed per frame as you move. New scenery fades in over a second; the view's far end follows
the nearest scenery not yet loaded, up to the player camera's far clip of 115, with fog in the background colour,
white until a level script sets one. The camera looks through the player camera's lens (65°, near clip 0.1). For a
level, its level file (`<name>.lev`) loads too. Its night sky, turning clouds and skyline are drawn behind the scenery,
and its light glows (the halos round lamps) are drawn over it. Fog still fades the nearest scenery to white, and the
white shows below the horizon once you leave the streets. There are no objects or script yet. Coney prints one line
for each part read or freed and a summary when it stops (counts only).

The camera starts above the middle of the first part and is driven by pad 1. These controls are Coney's own; the
original's cameras follow the player:

| Pad | Keyboard | Does |
| --- | --- | --- |
| left stick | W A S D | fly forward and back along the view, and sideways |
| right stick, d-pad | arrow keys | turn left and right, look up and down |
| R1 / L1 | E / Q | rise / sink straight up and down |
| cross (held) | K or Space | five times as fast |

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --view-world level2
build/dev/src/platform/coney --disc /path/to/warriors.iso --view-world level2 --frames 60 --input-script fly.txt --screenshot ../../scratch/level2.png
build/dev/src/platform/coney --disc /path/to/warriors.iso --view-world level51 --headless --frames 300 --input-script fly.txt
```

With `--headless` the streaming, visibility and draw distance run exactly as in a window and nothing is drawn, which
is how a test drives it. Game time runs on the fixed 1/30 s step, so a script gives the same parts in the same frames
every time.

### The character viewer {#the-character-viewer}

`--view-character [NAME]` loads a character by its model name, as the Character List names it, and plays one of its
clips on the skinned model in place, on the fixed 1/30 s step
([Characters](../research/characters.md#coneys-implementation)). Without a name it shows Rembrandt (`warr_re_cv`).
`--anim CLIP` picks the clip by anim id (a number, such as `408`, Rembrandt's walk) or by name (such as `gen_walk`);
without it the viewer plays id 408, or the character's first clip when 408 is not set. Clips loop. There is no level,
movement or follow camera; the character stands in a slate-blue void, and Coney prints a summary when it stops (counts
only).

The orbit camera looks at the character's middle and is driven by pad 1. These controls are Coney's own; analog
sticks move in proportion to how far they are pushed:

| Pad | Keyboard | Does |
| --- | --- | --- |
| right stick, d-pad | arrow keys | orbit left and right, look from higher or lower |
| left stick (up / down) | W / S | move in and out |
| R1 / L1 | E / Q | move in / out |
| circle | L | play the next clip |
| square | J | play the previous clip |

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --view-character
build/dev/src/platform/coney --disc /path/to/warriors.iso --view-character warr_ty_cv --anim gen_walk
build/dev/src/platform/coney --disc /path/to/warriors.iso --view-character --frames 90 --input-script tests/support/character_orbit.txt --screenshot ../../scratch/rembrandt.png
```

A script drives it like a player, with partial deflections: `stick right 60 0` orbits at 60 % of the full rate,
`stick left 0 35` moves in at 35 %.

### The sandbox {#the-sandbox}

`--sandbox [NAME]` flies a free camera round one of Coney's own test worlds of textured shapes (slopes, stairs,
ledges, fences, gaps), with no disc needed. It is Coney's feature, not the original's; the layouts, their format and
how to add one are in [The sandbox](sandbox.md).

```sh
build/dev/src/platform/coney --sandbox parkour
```

### Playing a level {#playing-a-level}

`--play-level NAME` puts you in a level (`level2`, `level99`: any of the 79 with a streamed world, listed on the debug
menu's [Levels page](debug-menu.md), which also switches between them) as player 1, driven with a gamepad's analog
sticks, with the follow camera behind him ([Characters](../research/characters.md#coneys-implementation),
[Camera](../research/camera.md#coneys-implementation)). The level's worlds and level file load and stream as in [the
world viewer](#the-world-viewer); he stands where the level's own script creates player 1, as when the story reaches the
level: Coney runs the scripts the original runs before it (the preloads, then a fresh Lua state with `SetCheckPoint`),
then `global.lua` and the level's script, and takes the position and heading of its `HuCreate` for player 1, and prints
them (`gameplay: level2 checkpoint 3: player 1 Cleon (type 1, model warr_cl) at ...`). `--checkpoint N` picks the
checkpoint (1 by
default), so `--play-level level2 --checkpoint 3` starts where level2's third checkpoint does. He is drawn as the
character the script's type names (Cleon at `level2 --checkpoint 3`, Snow at `level3 --checkpoint 4`), through the
type's `CfgChar` model ([Characters](../research/characters.md#type-to-model)); a type with no model falls back to
Rembrandt with a log line. The scripts' world flags are kept, so a script that teleports player 1 to a flag puts him
there with the flag's heading, without snapping him to the ground, as the original: the hub, `level95`, starts the
Warchief at one of its doors, chosen with the game's own random numbers (read from your disc's executable; door 5 while
the tutorial is locked, which it always is for now), and an arena run alone (`--play-level level102`) uses the Rumble
menu's default set-up ([Flags](../research/flags.md#coneys-implementation)). The scripts keep running in play, one
script frame per step: their scheduled calls, their volume-box triggers and their message handlers, and every other
human they create is an AI human with its own model, driven by the scripts' goals and gangs
([AI](../research/ai.md#coney)); bindings Coney lacks are skipped with a log line. A level whose script creates no
player 1 puts him above
the middle of its first world's part 1, Coney's stand-in. He walks, runs, sprints, turns and leans into turns, stops,
steps onto kerbs under 25 cm, slides along walls, jumps, climbs fences and walls, and falls off ledges on the level's
collision mesh, with the original's speeds, turn rates and clips: the walk or run start, a blend across walk, jog, run
and sprint, the idle, the run stop, the jump and its landing, and the climbs
([Characters](../research/characters.md#sprint)). He fights as the original's player does
([Combat](../research/combat.md#coneys-implementation)): the square and cross chains, the snaps, the run attack, the
charge and the dive, the block, rage, the grab with its strikes, spins, throws and the mugging, and the tackle, with the
original's commands, timing and clips; the sandbox's fight yard
(`--play-level sandbox:combat`) has passive targets that take the hits. With a target (the one he attacked, or the one
L1 picks) he locks onto it, as the original's default settings do: he faces it and the stick walks him at one speed in
any direction with the combat walk until it is more than 2.5 m away or down. There are no objects yet, and scenes end at
once; a fall out of the world puts him back at the start. Coney prints
a line whenever the clip changes and a summary when it stops (the player's position, speed, gait, clip, traversal state,
stamina, the camera's distance and counts only).

| Pad | Keyboard | Does |
| --- | --- | --- |
| left stick | W A S D (full deflection) | move, relative to the camera: a walk below 95 % of the stick's travel, a run above |
| L2 held | 1 | sprint, with the stick past 95 %, while stamina lasts (135, 6.75 s); let go to refill it |
| triangle | I | climb the fence or wall ahead (within reach, stick pushed); otherwise jump from a run or sprint; in a grab, mug |
| square | J | attack (`S1`; pressed again in the chain window `SS2`, then `SSS3`; with the stick pushed past 95 % to a side or back, a snap; at a run, the run attack); in a grab, strike |
| cross | K or Space | attack on the release (`X1`, then `XX2` or `XS2`); in a grab, strike |
| circle | L | tapped, grab the target in reach; held, tackle; in a grab, throw towards the stick (pushed past 25 %) |
| R1 held | E | block: the stick turns him in place and he does not move; in a grab, R1 pressed spins the hold |
| L1 held | Q | pick the target in front (within 2.5 m): he faces it and the stick walks him round it |
| L1 + R1 | Q + E | start rage, with a full rage meter |
| L2 held, then cross or square | 1, then K or J | the charge or the dive, at a run or sprint |
| right stick | none | turn the camera round him, look up and down |

The stick's direction is turned by the camera's heading, so up always moves away from the camera. The game's own
dead zone (12 %) applies; the walk speed does not depend on how far the stick is pushed, only whether it is pushed
past 95 %. Let go at a walk and he stops at once and settles into the idle; let go (or pull the stick back) at a run
or a sprint and he skids through the run stop. The camera swings round behind him while he walks, runs or sprints
(the original's auto-centre rule), except just after a wall hid him from it, so a stick held to the side runs him in a
circle; it pulls in to 3 m and lowers to 7° over half a second of a sprint and goes back a quarter of a second after
it, and it swings away from a wall beside it.
The jump needs a run (faster than 3.3 m/s) and is refused within 5.5 m of a climbable face, where triangle climbs
or does nothing. In a script: `press l2`, `stick left 0 100`, `tap triangle`. The fights: `tap square` every 6 frames
for the square chain, `tap circle` to grab and `press circle` with a `release circle` 7 or more frames later to
tackle, `press r1` to block (the fight scripts: `tests/support/combat_*.txt`).

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --play-level level99
build/dev/src/platform/coney --disc /path/to/warriors.iso --play-level level99 --frames 200 --input-script tests/support/play_walk.txt --screenshot ../../scratch/walk.png
build/dev/src/platform/coney --disc /path/to/warriors.iso --play-level level99 --headless --frames 300 --input-script tests/support/play_wall.txt
```

The simulation runs on the fixed 1/30 s step and reads only the pads and game time, so a script gives the same path,
clips and camera every time, in a window or headless. Drawing blends the snapshots of the last two steps (Rembrandt's
feet, heading and pose, the camera's eye and target), so play runs at the same speed and moves smoothly at any frame
rate ([Frame rate](#frame-rate)). Scripts drive it with partial deflections, as a player would: `stick left 0 30` walks
forward at 30 %, `stick left 50 87` runs along an arc to the right, `stick right 60 0` turns the camera at 60 % of its
full rate.

`--play-level sandbox` (or `sandbox:NAME` for another layout) plays a [sandbox](sandbox.md) test world in place of a
level: the same player, follow camera and character, on the sandbox's collision mesh. Only the scenery differs.
Rembrandt starts at the layout's first spawn point, or at the one `--spawn NAME` names. Nothing streams; the far clip
is the layout's fog end. The disc is still needed, for the character.

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --play-level sandbox:parkour --spawn lane
build/dev/src/platform/coney --disc /path/to/warriors.iso --play-level sandbox --spawn stairs --frames 120 --input-script tests/support/sandbox_walk_short.txt --screenshot ../../scratch/stairs.png
build/dev/src/platform/coney --disc /path/to/warriors.iso --play-level sandbox:combat --frames 30 --input-script tests/support/combat_combo.txt --screenshot ../../scratch/combo.png
```

A layout's `target` lines put passive humans to fight there ([Sandbox](sandbox.md#the-layout-format)); the summary
then adds the fight's counts (hits, damage, power, rage, and the targets' health, reactions, stuns and knockdowns).

#### Tracing {#tracing}

`--trace FILE` (with `--play-level`) writes the player's and the follow camera's state after every step to `FILE`,
one CSV line per step, so a feel or combat comparison with the original ([Feel comparison](../research/feel.md)) can
be repeated with Coney alone. Drive it with an input script in test mode, so the run is the same every time:

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --play-level sandbox:parkour --spawn lane --headless --frames 300 --input-script ../../scratch/run_turn.txt --trace ../../scratch/run_turn.csv
```

The columns, positions in metres (game axes, z up), angles in degrees, speeds in m/s:

| Columns | What |
| --- | --- |
| `step` | the step, from 1 (frame N of an input script is step N + 1) |
| `x`, `y`, `z`, `heading` | the feet and the facing (0 faces +y, anticlockwise) |
| `speed`, `vz` | the speed across the ground and the vertical speed |
| `gait`, `clip`, `traversal` | the stored gait (0 standing to 5 sprint), the anim id playing, and `none`, `jumping`, `landing`, `run stop`, ... |
| `stamina`, `sprinting` | the stamina meter and whether a sprint is asked for |
| `cam_x` ... `wanted_z` | the camera's position, its look-at point and its wanted position |
| `cam_distance`, `cam_pitch`, `cam_yaw` | the camera's distance from its look-at point, its pitch above it and the heading its view faces |
| `band_near`, `target_pitch`, `auto_turn` | the leash band's near edge (the sprint zoom moves it), the target pitch, and the auto-centre rule's turn this step |
| `command`, `health`, `power` | the command matched this step (0 for none; [Combat](../research/combat.md#commands)), the health and the power meter |
| `aim_x`, `aim_y`, `aim_z`, `aim_lag` | the aim point the view faces ([Camera](../research/camera.md#aim-point)) and its lag |

`--script-trace FILE` (with `--play-level` and a level) writes what the level's scripts do to `FILE`, one line per
call: every script binding they call, with its arguments and what it returned (`HUDSetObjective(0, "...", 0, nil)`,
`HuCreate(...) -> 396`), and every call the engine makes into them by name, marked `>` (`> P1.EnterRiot(74, 398)`, a
box's message, a scene's end). Short lists of numbers (a position) are shown whole, other tables as `{table}`. It is
how a mission's run shows where its scripts wait. The file holds the game's own text (objectives, speech names): keep
it out of the repository.

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --play-level level34 --checkpoint 1 --headless --frames 1800 --script-trace ../../scratch/level34.trace
```

`--start X,Y,Z,HEADING[,DISTANCE,YAW]` (with `--play-level`) moves player 1, after the level's own start, to those
feet (dropped onto the ground below) and heading in degrees, and with the last two puts the follow camera DISTANCE
metres from him with its view facing YAW degrees. It is a test aid: a trace scenario starts Coney where the
original's save state stands, as `walk60` and `run_circle` do from slot 1's first trace row.

`--scene NAME` (with `--play-level`) plays the in-engine scene NAME at once, after any `--start`, as a level99
cinematic: player 1 takes the role named `warrrecv` and the other roles are played by stand-ins drawn from the role's
model, letterboxed and skippable with cross or START ([Scenes](../research/scenes.md)). It plays on the level's own
scene system, beside the scenes the level's scripts play themselves (level99's intro, `l99_c1`, at checkpoint 1). It
is a test aid:

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --play-level level99 --scene l99_c5 --frames 560 --screenshot ../../scratch/l99_c5.png
```

The original's trace, recorded in PCSX2 by `coney-tools pcsx2 record`, uses the same names and units for the columns
both have, and `coney-tools trace coney` runs a scenario's script on Coney with `--trace`; `coney-tools trace diff`
compares the two, column by column ([Comparing with Coney](research-workflow.md#comparing-with-coney)).

**The story's own set-up.** A level played with `--play-level` is the story's level, started there directly: it runs in
the same game session as the story from the main menu and the debug menus' jumps (`src/platform/game_session.h`,
[Test through the player's path](testing.md#test-through-the-players-path)), and differs only in skipping the
start-up movies, the legal screen, the memory-card check and the menus. So it has the loading screen and the level's
intro movie (`--skip-movies` skips the movie), the pause (START) and the mission screens, the game's sound with the
level's own bank, and the debug menus' Lua console and Cheats page work on its scripts. An `--input-script` starts on
the first frame after the loading screen and the movie (with no movie, the level's first step runs in the screen's last
frame, with the pad at rest), and `--frames` and `--screenshot` count from there too, however long the loading screen
and the movie take (a level that never starts playing ends the run after 10 minutes of frames, with a message).

**Going on to the next level.** A level played with `--play-level` (or from the debug menus) goes on to the next one the
way the story does, because it is the story's: when a mission ends (`HUDLaunchMissionComplete`), the mission-complete
mode runs the scripts' `UnlockAndLoad` (the unlocks, then `runNextMission(1)`, [Story
order](../research/scripting.md#run-next-mission)), and the level flow loads the level and checkpoint it chose; a level
a script starts with `MenuLoadLevel` (the hub's missions) is played the same way. The unlocks, bank and saved script
numbers carry from one level to the next, so the story's order holds: 99, 80, 87, the hub (`level95`), 34 and on.
`--frames` still ends the run.

#### Event logs {#event-log}

`--event-log FILE` writes what a player would notice to `FILE`, one CSV line per event (`step,kind,name,detail`;
`step` is the update, from 1): every script binding called (`call`, with its arguments as `--script-trace` shows
them), every call into the scripts by name (`callback`), each hint the hint box shows (`hint`, its text), each sound
started (`sound`, its hash), and the level's humans other than player 1 appearing, running out of health and being
removed (`human_in`, `human_out`, `human_gone`). It works in any mode, from the front end on; with `--play-level`
it starts when the level's Lua state is made, before its scripts run, with the step counted from there, so the
loading screen's events stay out. The file is flushed every update, so a run that is killed keeps its events. It is
the Coney side of a [differential playthrough](research-workflow.md#differential-playthroughs). Like
`--script-trace` it holds the game's own text: keep it out of the repository.

#### The pad pipe {#pad-pipe}

`--pad-pipe` lets a driver program play player 1 by what it sees, in lock step: before each update Coney
writes one line `@obs {json}` to standard output (the update before's observation: `play`, then while a level is in
play the player's feet and heading, the camera's eye and target, the other humans as `[x, y, alive, standing,
enemy]` and the observed world objects as `[type, x, y, shown]`, with car stereos among them), then reads lines from
standard input until a pad: `observe PREFIX...` chooses the world object types observed from then on, and `pad
BUTTONS RX RY LX LY` (the buttons in hexadecimal, as an input script's masks, then the four stick bytes, 0x80
centred) is the pad of the update. With `--play-level` the first observation is of the level's first update of
play: until then the session loads the level as the story does and the pad rests. With `--event-log` each event is
also written as `@ev <csv line>`; other lines on standard output are Coney's own messages. At the end of standard
input the pad is released. It is test mode (one step per update) and cannot be combined with `--input-script`.
`coney-tools trace mission` drives it.

#### Matched views {#matched-views}

Three options make a frame that can be laid beside a screenshot of the original from the same place:

- `--camera X,Y,Z,QX,QY,QZ,QW[,FOV]` (with `--play-level`) pins player 1's view for the whole run, over the follow,
  scene and free cameras. X,Y,Z is the eye in the game's axes (metres, z up) and QX..QW the orientation quaternion,
  both exactly as the original's camera object holds them at `+0x10` and `+0x20`; FOV is the field of view used, in
  degrees (`+0x48`, 60 when not given). The quaternion turns the camera's +y (the view direction) and +z (up) into the
  world ([The base camera object](../research/camera.md#the-base-camera-object)). The near and far clips are the
  current camera's, as usual, and the scenery streams round the pinned eye.
- `--render-size WxH` draws frames of W × H pixels (`640x448` is the original's frame buffer). The 2D screen fills the
  whole frame and the 3D view keeps the 4:3 shape of a television across it, so a 640 × 448 screenshot lines up pixel
  for pixel with the original's frame buffer. It needs a window.
- `--freeze-world` (with `--play-level`) stops the world after the first step of play: the scripts, people, cars,
  particles and animation stand still, while the fixed step runs on and the scenery still streams in (and fades in)
  round the camera, so every later frame shows the same picture.

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --play-level level99 --checkpoint 1 --skip-movies --freeze-world --camera 75.2,41.1,1.8,0,0,0.7071068,0.7071068,65 --render-size 640x448 --frames 300 --screenshot ../../scratch/l99_view.png
```

`--screenshot` needs a window, so these runs are not `--headless`.

### Shutdown order {#shutdown-order}

`main` destroys things in reverse order of declaration, so whatever points at the sound output must be declared
after it or reset before it. The game session (`session`) is reset explicitly right after the run summaries, before the
sound output goes: its scripts' binding context and play mode hold the game sound, and tearing them down afterwards
read freed state and segfaulted `--play-level level95` at exit. Any new
object that keeps a pointer into the sound output, the scene or the renderer follows the same rule. A ctest with
`PASS_REGULAR_EXPRESSION` ignores the exit code, so `coney.exits_cleanly_level95` and `_level99` (with `CONEY_DISC`
set) check the exit code alone.

### The debug menus {#the-debug-menus}

Every run has Coney's debug menu, a trainer-style menu of its own (the original has none): press L3 and R3 together
(F4 on the keyboard) to open it over whatever is running. It pauses and single-steps the game, edits tunable values
live, calls any script binding with arguments you choose, runs Lua in the game's script state and shows the pad's live
state. `--tunables FILE` names the file its tunable overrides are loaded from at start-up and saved to; without it a
windowed run uses `coney-tunables.ini` in your config folder and a headless run none. [The debug menus](debug-menu.md)
has the pages, the controls and how to add to it.

In a window, F1 shows the same menus as a developer overlay drawn with Dear ImGui, for the mouse and keyboard: a
window per page, filter boxes, plots and a real text box for the Lua console. `--dev-overlay N` shows it for the first
N frames and then hides it, a test aid: with `--screenshot`, the last frame must be byte-identical to a run without
the option, which shows the overlay leaves the frame as it found it.

```sh
build/dev/src/platform/coney --tunables ../../scratch/tunables.ini
build/dev/src/platform/coney --headless --frames 30 --input-script tests/support/debug_menu.txt
build/dev/src/platform/coney --frames 60 --dev-overlay 30 --screenshot ../../scratch/overlay-hidden.png
```

### Reference images {#reference-images}

`--render-references DIR` writes the reference images [the references' images](../references/index.md#images) show
and exits, one folder per list below `DIR` (made if missing): the small reference screenshots of models and the 2D
icons of at most 64 x 64 that `LEGAL.md` allows for the docs.

- **Characters** (`characters/`, 256x256): every Character List record once, standing as the character viewer's first
  frame shows it (its default clip, id 408 or else its first clip, at time 0), textured
  ([Characters](../research/characters.md#coneys-implementation)).
- **Objects** (`objects/`, 256x256): every Object List record once, its model read as the level file's models are,
  stood up and turned to face the camera ([The Object List](../research/level-loading.md#the-object-list)).
- **Cars** (`cars/`, 256x256): the six car types, each its Object List record's 47-atomic model with only the first 26
  atomics drawn, the undamaged car ([Cars](../research/cars.md#model)).
- **Radar icons** (`radar/icon-<n>.png`): rectangle `n` of `part_page0` for every icon id the scripts and the code use,
  at its own size ([GUI: radar](../research/gui.md#radar-icons)).
- **Particle effects** (`particles/`): the first sprite of each of the 58 traced types, scaled to fit 64x64
  ([Particles](../research/particles.md#sprite-words)).

The models are drawn under the character viewer's fixed lights, from the same fixed three-quarter front camera framed
on the model, on a transparent background. The sprites are cut from their sheet's texture, every texel a rectangle's
corners fall in ([Sprite sheet](../research/gui.md#particle-page)), and scaled by area averaging, which repeats each
texel when a 16-texel sprite becomes 64 pixels. Models are drawn offscreen with OpenGL, so it needs a display and a
GPU, but the window stays hidden; `--headless` is refused.

- `--kind KIND` renders only one list: `characters`, `objects`, `cars`, `radar` or `particles`; `all`, the default,
  renders every one.
- `--only NAME` renders just that entry: a model, object, car or particle type name, `icon-<n>` for a radar icon, or a
  `0x` name hash; repeatable.
- `--names FILE` names the character and object images: a text file of model and object type names, one per line (`#`
  starts a comment). An image is named after its name when that name is in the file or given to `--only`, otherwise
  after its name hash (`cbe1bfc3.png`).

```sh
build/dev/src/platform/coney --disc /path/to/warriors.iso --render-references ../../scratch/refs
build/dev/src/platform/coney --disc /path/to/warriors.iso --render-references ../../scratch/refs --only warr_re_cv --only dyn_bat
build/dev/src/platform/coney --disc /path/to/warriors.iso --render-references ../../scratch/refs --kind objects --names ../../scratch/names.txt
build/dev/src/platform/coney --disc /path/to/warriors.iso --render-references ../../scratch/refs --kind radar --only icon-28
```

To refresh the docs' thumbnails, render with a names file holding the `name` of every entry of
`research/references/character-models.yaml` and `objects.yaml`, copy the named images (and the characters' hash-named
ones, which the character models list uses) and the `cars`, `radar` and `particles` folders into
`docs/references/images/`, run `coney-tools refs compress-images` and then `coney-tools refs extract`
([coney-tools](coney-tools.md#refs)), which links every image that exists, in the hats and inventory lists too.

The images are deterministic: no clock or randomness, a fixed camera and 4x4 supersampling averaged with integer
arithmetic, and sprites scaled with integer arithmetic, so a re-render on the same machine and driver gives
byte-identical files (a different GPU driver may differ by a few model pixel values). Coney prints one line per image
(hashes, file names and sizes only). On the US disc it renders 541 character, 1,399 object, 6 car, 21 radar icon and
58 particle images in one to two minutes. The Character List has 543 records, and one name hash appears three times;
the Object List has 1,406, and one name hash appears twice; the first record's image is kept and the repeats are
reported. The six car models are not objects' models: the objects pass reports them as models of several atomics and
counts them, and the cars pass draws them. Any other record that fails is reported and counted, the batch goes on, and
the exit status is 1.

### Controls {#controls}

In a window, Coney reads the keyboard and any gamepad SDL3 recognises, and turns them into the PS2 pad the game
expects ([Front end](../research/frontend.md#coneys-implementation)). The legal screen ignores input, as in the
original; the menus, [the world viewer](#the-world-viewer), [the character viewer](#the-character-viewer) and
[a played level](#playing-a-level) and [the sandbox](sandbox.md) read port 1.

| PS2 pad | Gamepad (SDL3 names) | Keyboard (port 1) |
| --- | --- | --- |
| d-pad | d-pad | arrow keys |
| left stick | left stick | W A S D (full deflection) |
| right stick | right stick | none |
| cross | south (A on Xbox, cross on PlayStation) | K or Space |
| circle | east | L |
| square | west | J |
| triangle | north | I |
| START | start | Enter |
| SELECT | back | Backspace |
| L1, R1 | left and right shoulder | Q, E |
| L2, R2 | left and right trigger (held from a quarter of the travel) | 1, 3 |
| L3, R3 | stick presses | F, H |
| L3 and R3 together (the debug menu) | both stick presses | F4, or F and H together |
| none (the developer overlay) | none | F1 |

Gamepads can be connected and pulled out at any time. A gamepad that connects takes the first free port, port 1
first, and the log says so (`gamepad: NAME on port 1`); one pulled out frees its port and the other port keeps its
gamepad; a third waits for a free port. The keyboard always plays on port 1, alongside port 1's gamepad, and keeps
playing when it goes. Coney does not pause or show the original's controller-removed screen. On Windows, SDL's
DirectInput support is off: its device scan, which SDL repeats whenever any USB or Bluetooth device comes or goes,
can freeze the window for seconds. Xbox (XInput) gamepads and those SDL drives directly (PlayStation, Switch and
more) do not need it; for an older DirectInput-only gamepad, set the environment variable
`SDL_JOYSTICK_DIRECTINPUT=1` before starting Coney.

Escape quits, unless the developer overlay has the keyboard (a text box in it is being typed in); while it has the
keyboard, the keyboard does not play on port 1. A headless run reads no devices. L3 and R3 pressed together open and
close [the debug menu](debug-menu.md); the game never sees that chord. F1 shows and hides
[the developer overlay](debug-menu.md#the-developer-overlay).

A gamepad's sticks are squared off like a DualShock 2's: a modern stick reports a circle, about 0.71 on each axis at a
full diagonal, which the game's per-axis dead zone turns into a walk; the DualShock 2 reaches both extremes there, so
Coney stretches each stick's circle onto the square and a full diagonal runs as it does on a PS2
([Pad record](../research/frontend.md#pad-record)). Straight pushes and W A S D are unchanged.

### Input scripts {#input-scripts}

`--input-script FILE` replaces the keyboard and gamepads with a script, so a test or a headless run gets the same
input every time without a human. Each line is `FRAME [p1|p2] ACTION ARGS`, where `FRAME` counts from 0 (the frame
the line takes effect on; a script puts Coney in test mode, where a frame is one fixed step); `#` starts
 a comment and blank lines are skipped. Frames must not go down from one line to
the next.

| Action | Meaning |
| --- | --- |
| `press BUTTON...` | hold the buttons from this frame on |
| `release BUTTON...` | let them go from this frame on |
| `tap BUTTON...` | hold them for this frame only: pressed on it, released on the next |
| `stick left X Y`, `stick right X Y` | move a stick; X and Y are whole numbers from -100 to 100, right and up positive |
| `steer [PERCENT] X,Y...` | push the left stick, at PERCENT (1 to 100, default 100) of its reach, toward each world point (metres) in turn as seen from player 1's feet and the camera's heading, recomputed every frame; a point counts as reached within 1 m, and the stick centres at the last one or at the next `stick left` line |
| `connect`, `disconnect` | plug the pad in or pull it out |

Buttons are `cross`, `circle`, `triangle`, `square`, `l1`, `r1`, `l2`, `r2`, `l3`, `r3`, `start`, `select`, `up`,
`down`, `left` and `right`. The port defaults to `p1`; port 1 starts connected and port 2 does not. A held button
reports full pressure. For example:

```text
# Press START on frame 150, then move down the menu and accept.
150 tap start
160 tap down
170 tap cross
200 p2 connect
```

```sh
build/dev/src/platform/coney --headless --frames 300 --input-script ../../scratch/menu.txt
```

A script that cannot be read or has a bad line stops Coney at start-up with exit code 1 and the line's number.

## Sanitizers

The `asan` preset builds with AddressSanitizer and UndefinedBehaviorSanitizer and runs the tests under them. Any
report fails the test that caused it.

```sh
cmake --preset asan
cmake --build --preset asan
ctest --preset asan
```

LeakSanitizer reads its suppressions from `tests/lsan.supp`, which hides one known leak inside librw and nothing in
Coney's own code. Suppressions match function names, so the sanitizer must be able to name the frames in a report.
GCC's and Apple Clang's runtimes do that on their own. Clang on Linux needs `llvm-symbolizer`: install the `llvm-19`
package and point the runtime at it, or librw's leak goes unrecognised and the tests fail.

```sh
export ASAN_SYMBOLIZER_PATH=/usr/lib/llvm-19/bin/llvm-symbolizer
```

The preset is not offered on Windows: MSVC's AddressSanitizer has no UBSan and no LeakSanitizer, so it would check
much less than the Linux and macOS runs that CI does anyway.

## clang-tidy

CI runs clang-tidy 19 over Coney's own sources (`src/` and `tests/`, never the fetched dependencies), using the
`compile_commands.json` that every preset writes. To run the same check locally on Linux, after a `ci` build with
Clang 19:

```sh
run-clang-tidy-19 -p build/ci -quiet '^(?!.*_deps).*/(src|tests)/'
```

A full pass takes over an hour, so a pull request checks only the files it changes: each changed `.cpp`, plus every
`.cpp` that includes a changed header, directly or through other headers (`.github/scripts/tidy-files.sh <base>`
prints the list for a change, or `ALL`). A change to the build setup (`CMakeLists.txt`, `cmake/`, `CMakePresets.json`,
`.clang-tidy`, the build workflow) and every push to `main`, nightly run and manual run check everything, so a header
included some unusual way is still caught within a day.

## Python tools

`python/` is the `coney-tools` package (see [Conventions](conventions.md#python)). [uv](https://docs.astral.sh/uv/)
installs the right Python and the locked dependencies into `python/.venv` the first time you run something:

```sh
uv run --project python coney-tools --help
uv run --project python pytest python/tests
uv run --project python ruff check python
uv run --project python mypy python/src python/tests
```

`coney-tools config show` prints the paths your `coney.local.toml` sets (start from `coney.local.example.toml`;
[Local workspace](workspace.md) explains each one). `coney-tools repo check-title` checks a commit or pull request
title against the commit rules in [CONTRIBUTING.md](repo:CONTRIBUTING.md#commits), and `coney-tools repo check-docs`
that a change to the code also changes the docs ([Research workflow](research-workflow.md#writing-up-a-finding)).
`coney-tools wad` reads the archive on your own disc (`info`, `list`, `extract`, `names`), `coney-tools pcsx2` and
`coney-tools trace` record the original's per-update traces in PCSX2 and compare them with Coney's; [The coney-tools
command line](coney-tools.md) shows how to run each command.

## Formatting and pre-commit

clang-format decides the layout of C and C++ code, ruff that of the Python package, and a few hooks catch trailing
whitespace, broken YAML or TOML, merge-conflict markers and files over 512 KB (usually game data added by mistake).
All of them run through [pre-commit](https://pre-commit.com/), configured in `.pre-commit-config.yaml`:

```sh
uvx pre-commit run --all-files
```

Run that before every commit, or install the hooks once with `uvx pre-commit install` so that `git commit` runs them
for you. The hooks fix what they can; stage their changes and commit again. The install also adds a `commit-msg` hook
that refuses a commit whose title breaks the rules in [AGENTS.md](repo:AGENTS.md) (`area: Verb the rest`, at most 72
characters); CI checks every commit title of a pull request again, because a clone without the hook cannot be trusted.
Install it once in each clone; the worktrees of a clone share it.

## Documentation

This site is built with MkDocs from `docs/`. In a virtual environment at the repository root:

```sh
py -m venv .venv
.venv/Scripts/pip install -r requirements-docs.txt
.venv/Scripts/python -m mkdocs build --strict
```

On Linux and macOS use `python3 -m venv .venv` and `.venv/bin/` in place of `.venv/Scripts/`.
`mkdocs serve --dev-addr 127.0.0.1:8000` previews the site and reloads it as you edit. `--strict` turns broken links
and pages missing from the navigation into errors, as CI does. How to write the pages is in
[Writing these docs](writing-docs.md). The Changelog page is generated from `git log` at build time, so it needs the
full history (no shallow clone) and is never committed.

## What CI runs

Every pull request, and every push to `main` or a `release/` branch, runs these GitHub Actions workflows. The `build`
workflow also runs every night on `main` and on demand: open the repository's Actions tab, choose `build`, press
"Run workflow" and pick a branch that is already on GitHub (or `gh workflow run build.yml --ref <branch>`). A manual
run checks every file with clang-tidy. On Linux and macOS the jobs compile through ccache and keep its cache between
runs, so a job recompiles only what changed; each job prints its hit rate at the end.

| Workflow | Jobs |
| --- | --- |
| `build` | `ci` preset build and tests on Windows (MSVC), Linux (GCC 13 and Clang 19) and macOS (Apple Clang); `asan` preset on Linux Clang 19 and macOS; clang-tidy (a pull request: changed files only); pre-commit over every file |
| `python` | ruff, mypy, pytest and `coney-tools repo check` on Windows, Linux and macOS |
| `docs` | `mkdocs build --strict`, markdownlint over every Markdown file, actionlint over the workflows |
| `pr` | the pull request title and every commit title of it against the commit title rules (pull requests only) |

If a job fails, the commands above reproduce it locally. The workflow files under `.github/workflows/` are short and
list every step.
