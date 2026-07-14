---
name: Optima game won't launch / won't install
about: A Ubisoft (Optima) game fails to launch or install
title: '[Optima] <Game Title> - '
labels: optima
assignees: ''

---

**Before filing:** Optima has self-healing built in. On every launch it re-writes
the game's registry keys and `Uplay.toml`, makes sure the local `Saves/` folder
exists (your saves are never touched), and re-verifies the R1/R2 loader. So a
one-off failure often fixes itself on the next launch — try launching a second
time first.

If it still fails, it's almost always one of:
- **Unsupported DRM** — Denuvo, or any DRM other than Uplay R1 / Orbit R2. These
  can't be emulated and won't launch. (Uplay-R1/R2-only titles are the supported set.)
- **A real bug** — which is what this report is for.

---

**Game title**
(exact name, e.g. "Assassin's Creed Unity")

**Product ID** (if known)
(the numeric id, e.g. 720)

**What happens**
Launches / installs and then... (splash then quits, black screen, error dialog,
install stalls at X%, etc.)

**Optima logs** (required — attach or paste)
On the handheld these live in `~/homebrew/logs/GameVault/`:
- `run-exe.log` — game launch stdout/stderr (the important one for launch failures)
- `<ProductID>.log` and `<ProductID>.progress` — install output
- `debug.log`

Grab them over SSH or from Decky's plugin log folder. Paste the relevant tail, or
attach the files.

**Handheld device**
 - Device: [e.g. Steam Deck, ROG Ally, Legion Go]
 - OS: [e.g. SteamOS, Bazzite]
 - GameVault version: [e.g. 1.1.7]

**Additional context**
Anything else — does it work through Ubisoft Connect/Heroic? Did it install fully?
