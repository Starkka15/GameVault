# Decky GameVault

> **A community fork of [Junk-Store](https://github.com/ebenbruyns/junkstore) — an open, extensible multi-store game launcher for the Steam Deck and other Decky-compatible handhelds (ROG Ally, Legion Go, …).**

## About

GameVault lets you browse, install, and launch non-Steam games directly from Game Mode — no Desktop Mode required. Games are added to your Steam library as shortcuts with the right compatibility tool (Proton, or **native** for engines that don't need it), artwork, and per-game launch settings.

Built on the Junk-Store framework, this fork adds seven store/library integrations and a large set of quality-of-life features on top of the original Epic Games support.

**Current release: v1.2.1** — see [Releases](https://github.com/Starkka15/GameVault/releases).

## Store & Library Integrations

| Source | Backend | Runs via | Notes |
|--------|---------|----------|-------|
| **Epic Games** | Legendary | Proton | Original upstream integration |
| **GOG** | gogdl | Proton | Community extension — login, install, DLC manager, cloud saves |
| **Amazon Games** | Nile | Proton | Community extension |
| **itch.io** | itch.io API | Proton / native | Owned games **and** your Collections |
| **RPG Maker** | NW.js / mkxp-z | **Native** (no Proton) | Drop-folder scanner for MV/MZ/VX Ace/XP/VX |
| **EA Play** *(beta)* | maxima-cli | Proton | EA back-catalog titles |
| **Ubisoft (Optima)** *(beta)* | optima-cli | Proton | Owned Ubisoft games via built-in Uplay R1 / Orbit R2 loaders — no Ubisoft Connect |

### A Note on GOG

The official Junk-Store project offers its own GOG integration via [Patreon](https://www.patreon.com/junkstore) or [Ko-fi](https://ko-fi.com/junkstore). The GOG extension in this fork is a **separate, independently-built** implementation. If you want the officially supported GOG experience, please consider supporting the original project.

### Setup Notes

- **Epic Games** — Works out of the box. Log in from the plugin.
- **GOG** — Install dependencies from the About menu first. Login uses a browser redirect (needs a keyboard to paste the redirect URL once).
- **Amazon Games** — Install dependencies from the About menu first. Browser-redirect login, same as GOG.
- **itch.io** — Log in with your itch.io API key to access purchased and claimed games. See **itch.io Collections** below.
- **RPG Maker** — Install dependencies (this fetches the native NW.js + mkxp-z runtimes), then drop game folders into the RPG Maker install location. See **RPG Maker (Native)** below.
- **EA Play** *(beta)* — Requires the `maxima-cli` EA client. Install dependencies from the About menu, then log in with your EA account.
- **Ubisoft (Optima)** *(beta)* — Install dependencies from the About menu (fetches the `optima-cli` runtime), then log in with your Ubisoft account in the browser. Games run through GameVault's own DRM loaders — no Ubisoft Connect install needed. See **Ubisoft (Optima)** below.

## Features

### Original (from Junk-Store)

Part of the upstream framework GameVault is built on:

- **Epic Games Store** — Full integration via Legendary (install, update, verify, repair)
- **EOS Overlay Management** — Install, update, and remove the Epic Online Services overlay
- **Per-Game Launch Configuration** — Proton version, environment variables, FPS limiting, FSR, ESYNC/FSYNC toggles from the QAM
- **Platform Config Editor** — Edit game INI/config files directly from Game Mode
- **Executable Runner** — Run executables (EXE, BAT, MSI) from a game's install folder
- **Protontricks Integration** — Launch the Protontricks GUI for manual Proton fixes
- **UMU ID Management** — Update UMU IDs for compatibility tracking
- **Registry Fix** — Apply Windows registry fixes via Proton (Epic)
- **Dependency Installer** — One-click install for Proton EasyAntiCheat and BattlEye runtimes
- **Import/Move Games** — Manage game storage locations
- **Custom Backend Support** — Extensible architecture for community store scripts
- **Developer Mode** — Toggle developer tools and the log viewer

### Community Additions (GameVault Fork)

Added by this fork:

- **GOG Extension** — Full game management, browser-based login, cloud save sync
- **GOG DLC Manager** — Per-game gear menu to install/remove individual DLCs, with a base-game-only toggle
- **Amazon Games Extension** — Full game management via the Nile backend
- **itch.io Extension** — Owned games via API key
- **itch.io Collections** — Your itch.io Collections imported as a library source: an **Owned** tab plus one nested sub-tab per Collection. Toggle Collection import on/off in the tab config
- **RPG Maker (Native) Extension** — Run RPG Maker games with no Proton (see below)
- **EA Play Extension** *(beta)* — Launch EA back-catalog titles through `maxima-cli`
- **Ubisoft (Optima) Extension** *(beta)* — Install and launch owned Ubisoft games through built-in Uplay R1 / Orbit R2 loaders, no Ubisoft Connect required (see below)
- **My Added Games** — A tab for games you add manually, kept alongside the store libraries
- **SteamGridDB Artwork Fallback** — Automatically fills missing artwork from SteamGridDB. Set your API key in any store's tab config (gear icon); results are cached per game
- **Artwork Scan** — Sweep a library and backfill missing cover/hero/logo art
- **Cloud Save Sync (Epic & GOG)** — Upload/download saves, with a per-game auto-sync toggle
- **GE-Proton Installer** — One-click download and install of the latest GE-Proton from the Dependencies tab
- **Proton Fixes Lookup** — Look up known fixes for any installed game from the [umu-protonfixes](https://github.com/Open-Wine-Components/umu-protonfixes) database; falls back to Steam fixes via UMU ID
- **Auto-Apply Proton Fixes** — One-click apply of known environment-variable fixes to a game's launch config
- **Storage Management** — Total disk usage across all stores, per-store breakdown, free space, and installed games sorted by size, from the About page's Storage tab
- **Batch Install Queue** — Select multiple games from a store grid and queue them for sequential download and install
- **Game Update Detection** — Checks for updates when viewing an installed game (Epic, GOG, Amazon) and flags an "Update Available" indicator on the play button
- **Improved GOG Uninstall** — Cleans up gogdl manifest state so games can be reinstalled without manual intervention

### RPG Maker (Native)

Runs RPG Maker games **natively** — no Wine or Proton — so they're light on a handheld:

- **MV / MZ** launch under a bundled native Linux **NW.js**.
- **VX Ace / XP / VX** (RGSS) launch under **mkxp-z**, a native C++ reimplementation of the RGSS runtime.

There's no store to log into — it's a **drop-folder scanner**. Copy a game's folder into the RPG Maker install location; the extension detects the engine, lists it, and "Add" creates a **native** Steam shortcut (compatibility tool cleared). The NW.js and mkxp-z runtimes are fetched by **About → Install Dependencies**.

### Ubisoft (Optima) *(beta)*

Installs and launches games you **own** on Ubisoft, backed by a standalone `optima-cli` client — no Ubisoft Connect install required. Ownership is verified against your Ubisoft account, and games run through GameVault's own **Uplay R1** / **Orbit R2** DRM loaders under Proton.

Optima **self-heals** on every launch — it re-writes the game's registry keys and DRM config, makes sure the local save folder exists (your saves are never touched), and re-verifies the loader. So if a game fails once, **try launching a second time** before assuming it's broken.

Some limitations to be aware of (it's a beta):

- **Single-player only.** Online/multiplayer is untested and generally won't work — the loaders emulate *local* ownership and can't provide a real online session (e.g. free-to-play titles like Brawlhalla that auth against Ubisoft's servers will bail).
- **Uplay R1 / Orbit R2 titles only.** Games protected by **Denuvo** or any other DRM can't be emulated and won't launch. For those, use Ubisoft Connect via Heroic.
- Tested working on the ROG Ally so far: **Assassin's Creed III**, **Assassin's Creed IV: Black Flag**, **Assassin's Creed Unity**, **Beyond Good & Evil**, **Tom Clancy's Splinter Cell**, and **Watch_Dogs**.

If a game won't launch, retry once, then open a GitHub issue with the **"[Optima] game won't launch"** template — include the game title, product id, and the logs from `~/homebrew/logs/GameVault/`.

The `optima-cli` runtime is fetched by **About → Install Dependencies**.

## Installing

1. Download **`GameVault.zip`** from the [Releases](https://github.com/Starkka15/GameVault/releases) page.
2. Transfer it to your device.
3. Extract to `~/homebrew/plugins/GameVault/`.
4. Restart Decky Loader.
5. Open the plugin, go to **About → Install Dependencies** to pull the runtimes needed by GOG, Amazon, EA Play, Ubisoft (Optima), and RPG Maker.

### Adding a single extension to an existing install

Two extensions ship standalone installers you can run on-device to add them without reinstalling the whole plugin:

- `install-itchio-extension.sh`
- `install-rpgmaker-extension.sh`

## Building from source

```bash
pnpm install
pnpm run build
```

The frontend is TypeScript (React); most store extensions are shell + Python under `defaults/scripts/Extensions/<Store>/`. `dist/` is git-ignored and produced by the build.

## Contributing / Backend CLIs

The **Ubisoft (Optima)** and **EA Play (Maxima)** extensions are thin GameVault wrappers around standalone command-line clients. Those clients live in their own repos, are the place where the real login / install / launch logic lives, and **run standalone on the desktop** (no Decky or Steam required) — which makes them easy to hack on and test outside the plugin:

- **Optima** (Ubisoft Connect client, Rust `optima-cli`) — [github.com/Starkka15/Optima](https://github.com/Starkka15/Optima)
- **Maxima** (EA Desktop replacement, `maxima-cli`) — [github.com/Starkka15/Maxima](https://github.com/Starkka15/Maxima)

If you'd like to help develop or flesh these out — more supported games, better DRM handling, online/auth work — contributions to those repos are welcome. GameVault picks up the improvements automatically the next time it fetches the runtime via **About → Install Dependencies**. Extension-side glue (tabs, install/launch scripts) lives here under `defaults/scripts/Extensions/{Optima,EA}/`.

## Credits

### Original Project
- [Junk-Store](https://github.com/ebenbruyns/junkstore) by Eben Bruyns
- Eben Bruyns (junkrunner) — Software Sorcerer
- Annie Ryan (mrs junkrunner) — Order Oracle
- Jesse Bofill — Visual Virtuoso
- Tech — Glitch Gladiator
- Logan (Beebles) — UI Developer

### Community Fork
- **Starkka15** — GOG, Amazon, itch.io, RPG Maker (native), EA Play, and Ubisoft (Optima) extensions; `optima-cli` (the Ubisoft Connect client itself); itch.io Collections; GOG DLC manager; My Added Games; cloud save sync; SteamGridDB integration + artwork scan; GE-Proton installer; protonfixes lookup/apply; storage management; batch install queue; update detection

### Backends & Third-Party Tools

Most of the fork's store extensions are wrappers that drive excellent third-party tools. Full credit to their authors — GameVault just integrates them into Game Mode. In several cases we maintain **forked branches** with GameVault-specific changes: upstream didn't always work as-is under GameVault's Proton/SteamOS handheld flow, so we've patched things to make them reliable there. Those forks track upstream and exist only to bridge the gap — all credit stays with the original authors.

- **[gogdl](https://github.com/Heroic-Games-Launcher/heroic-gogdl)** — the GOG downloader behind the GOG extension, from the **Heroic Games Launcher** project (Paweł Lidwin / imLinguin and contributors). GameVault installs the upstream `heroic-gogdl` flatpak.
- **[Nile](https://github.com/imLinguin/nile)** — the Amazon Games downloader behind the Amazon extension, by **Paweł Lidwin (imLinguin)**.
- **[Maxima](https://github.com/ArmchairDevelopers/Maxima)** (`maxima-cli`) — the open-source EA Desktop replacement powering the EA Play extension, by the **Maxima project (ArmchairDevelopers)** and contributors. We run a [forked branch](https://github.com/Starkka15/Maxima) that adds the non-interactive install/launch CLI plus GameVault-specific fixes (e.g. live download-progress reporting, install resume, registry self-heal).
- **RPG Maker runtimes** — [**NW.js**](https://nwjs.io) (runs MV/MZ) by the NW.js project; [**mkxp-z**](https://github.com/mkxp-z/mkxp-z) (runs VX Ace/XP/VX), a continuation of [**mkxp**](https://github.com/Ancurio/mkxp) by Jonas Kulla (Ancurio). GameVault only repackages the mkxp-z AppImage; the runtime is theirs.
- **Ubisoft (Optima) DRM loaders** — [`optima-cli`](https://github.com/Starkka15/Optima) is ours, but the emulation shims it deploys are **not**: the [Uplay R1 loader](https://github.com/Re0xCat/uplay-r1-loader) and [Orbit R2 loader](https://github.com/Re0xCat/ubiorbitapi-r2-loader) by **Re0xCat**, Ubisoft demux/manifest/install-protocol reversing by [**YoobieRE**](https://github.com/YoobieRE), and Proton launching via [**umu-launcher**](https://github.com/Open-Wine-Components/umu-launcher). We vendor and patch the loaders (e.g. the Orbit R2 shim is fixed up in `optima-cli`'s tree) so they work under our Proton launch flow — original authorship is unchanged.
- **[Legendary](https://github.com/derrod/legendary)** — the Epic Games downloader behind the Epic integration, by **Rui Pinheiro (derrod)** (used via the upstream Junk-Store Epic integration).
- **[GE-Proton](https://github.com/GloriousEggroll/proton-ge-custom)** — the custom Proton build fetched by the GE-Proton installer, by **Thomas Crider (GloriousEggroll)**.
- **[umu-protonfixes](https://github.com/Open-Wine-Components/umu-protonfixes)** — the Proton-fixes database behind the protonfixes lookup/apply feature (and [umu-launcher](https://github.com/Open-Wine-Components/umu-launcher), also used by Optima), by **Open-Wine-Components**.
- **[SteamGridDB](https://www.steamgriddb.com)** — the community artwork source powering the artwork fallback and library artwork scan.
- **[DOSBox Staging](https://dosbox-staging.github.io)** — runs DOS-era GOG titles; installed as a flatpak on demand.

### Platform

GameVault is a plugin for **[Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)** and is built with [`decky-frontend-lib`](https://github.com/SteamDeckHomebrew/decky-frontend-lib) — both by the **SteamDeck Homebrew** project. None of this exists without their plugin platform.

## Links

- Original project: [github.com/ebenbruyns/junkstore](https://github.com/ebenbruyns/junkstore)
- Official Junk-Store Discord: [![Chat](https://img.shields.io/badge/chat-on%20discord-7289da.svg)](https://discord.gg/Dy7JUNc44A)

## License

See [LICENSE](LICENSE). GameVault inherits Junk-Store's license as a fork.

## AI Disclosure

This project is developed with AI assistance. See **[AI.md](AI.md)** for how AI is used
here, the ethical obligations behind it, and how upstream credit and licensing are handled.
