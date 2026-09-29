# GameVault extension system — how it actually works

Written against GameVault v1.3.1, from reading the source and from building the
ZOOM Platform extension the hard way. Everything here was verified in the code
or in logs on a real device; nothing is assumed.

---

## 1. What an extension is

An extension is a set of files under `defaults/`. It never touches `src/`.

```
defaults/scripts/<store>.py                       the client: auth, library, download
defaults/scripts/<store>-config.py                CLI wrapper (argparse) around it
defaults/scripts/Extensions/<Store>/static.json   action sets + the store tab
defaults/scripts/Extensions/<Store>/store.sh      bash functions the dispatcher calls
defaults/scripts/Extensions/<Store>/settings.sh   env: paths, DBFILE, INSTALL_DIR
defaults/scripts/Extensions/<Store>/<store>-launcher.sh
defaults/scripts/Extensions/<Store>/get-<store>-args.sh
defaults/scripts/Extensions/<Store>/install_deps.sh
defaults/conf_schemas/<store>tabconfig.json       tab settings schema
```

Each store owns a SQLite DB (`<store>.db`) in `DECKY_PLUGIN_RUNTIME_DIR`,
created from the shared schema in `GameSet.create_tables()`.

---

## 2. How the pieces find each other

### static.json merging

`defaults/scripts/get-json.py` walks **two** directories —
`./scripts/Extensions` (shipped) and `../../data/GameVault/scripts/Extensions`
(installed at runtime) — and merges every `static.json` it finds. Its `update()`
**concatenates lists**, which is how each store contributes one entry to the
shared `gamevault-tabs.Content.Tabs` array. The store tab bar is that union.

Invoked as `get-json.py <key>`, it prints the merged fragment for that key.

### Action resolution

`main.py`:

- `Helper.get_action(actionSet, actionName)` looks in `Helper.action_cache`,
  then falls back to `<actionSet>.json` on disk.
- An ActionSet is cached when any action returns `{"Type": "ActionSet", ...}` —
  that is what `Type: "Init"` commands are for.
- `execute_action` then runs `action["Command"]` with the args appended,
  shell-quoted.

**Trap:** if the action does not exist, `get_action` returns `None` and
`action["Command"]` raises — the UI shows
**`'NoneType' object is not subscriptable`**. Removing an action the frontend
calls unconditionally produces exactly this. (Hit on 2026-09-28 by dropping
`LoginLaunchOptions`.)

### Dispatch into bash

`defaults/scripts/gamevault.sh <Platform> <action> [args...]`

- sources every `Extensions/*/store.sh`
- each `store.sh` appends its name to `PLATFORMS` and any extra verbs to
  `ACTIONS`
- calls the bash function `<Platform>_<action>`

`ACTIONS` is a fixed allow-list in `gamevault.sh` plus whatever a store adds.
A verb not in `ACTIONS` prints `Invalid action: <verb>` and exits 1 — the UI
then sees no output and reports a failure.

If `<Platform>_<action>` is not defined but the verb is allowed, the dispatcher
falls back to calling a bare `<action>` — a shared function from `shared.sh`.
That is how stores inherit `launchoptions`, `loginlaunchoptions`,
`get_steam_env` and similar without redefining them.

Arguments arrive positionally: `$1` is normally the shortname.

---

## 3. The type contract

Every script prints one JSON object. `Type` decides how the UI reads it.

| Type | Content | Used by |
|---|---|---|
| `ActionSet` | `SetName`, `Actions[]` | cached by name; `Init` commands |
| `StoreTabs` | `Tabs[]` of `{Title, Type, ActionId}` | the tab bar, and sub-tab containers |
| `GameGrid` | `Games[]`, `NeedsLogin` | the store grid |
| `GameDetails` | `Name`, `ApplicationPath`, `RootFolder`, `SteamClientID`, … | the game page |
| `GameSize` | `Size` (string) | game page |
| `LaunchOptions` | `Exe`, `Options`, `WorkingDir`, `Compatibility`, `CompatToolName` | shortcut setup |
| `ProgressUpdate` | `Percentage`, `Description`, `Error?` | install polling |
| `GameImages` | `Grid`, `GridH`, `Hero`, `Logo` | Steam artwork |
| `LoginStatus` | `Username`, `LoggedIn` | login panel |
| `Progress` | `Message` | **the response `Download` must return** |
| `Error` | `Message`, … | shows a modal; `executeAction` returns **null** |
| `Empty`, `Text`, `Html`, `MainMenu`, `SideBarPage` | — | other panes |

`executeAction` returning `null` matters: `ContentTabs` skips caching a null
result, and callers treat it as failure.

---

## 4. Lifecycle, start to finish

### Plugin start

`main.py Plugin._main` → `execute_action("init", "init")`. Working directory is
`DECKY_PLUGIN_RUNTIME_DIR` if `init.json` exists there, else `DECKY_PLUGIN_DIR`.
Each store's `<Platform>_init` normally syncs its library, so a store that was
logged in previously already has rows before any tab is opened.

### Tab bar

`gamevault-tabs` (merged) → one entry per store → `ContentTabs` renders a
`Content` per tab, keyed by `ActionId`.

`Content` caches results in a module-level `contentCache`, **TTL 5 minutes**,
keyed `${initActionSet}_${initAction}_${JSON.stringify(gridContentParams)}`.
Cache hits skip the backend entirely. `refreshContent()` bypasses it and
overwrites the entry.

A store tab may point either straight at a grid action set (GOG, ZOOM) or at a
`StoreTabs` container that yields sub-tabs (itch.io, for Owned + Collections).

### Grid

`GetContent` → `<Platform>_getgames <filter> <installed> <limited>` →
`--getgameswithimages <imagePrefix> <filter> <installed> <limited> <urlencode> <origin>`.

Positional index 4 is `needsLogin`, index 5 is `origin` (itch.io only).

Convention: if the result has no games, an unfiltered view calls
`<Platform>_init` once and re-queries, so a store self-heals from an empty DB.

`NeedsLogin: "true"` renders the login panel **alongside** the grid; it does not
hide games.

### Login

`LoginContent` does, in order:

1. `GetLoginActions` → the login ActionSet
2. `LoginLaunchOptions` → **must return `LaunchOptions`**
3. creates a Steam shortcut from it
4. `Login` with `{appId, gameId}` — launches that shortcut
5. on exit: navigates back and removes the shortcut

So the login script runs **as a Steam app**, which is how it gets a window and
the on-screen keyboard in Game Mode. It ends by calling
`gamevault.sh <Platform> loginstatus --flush-cache`.

`setLoggedIn("true")` fires when the shortcut *launches*, not when the login
finishes — the status poll at that moment still reads logged-out.

### Installing

`installQueue.ts` `processItem` is the authority:

1. `Download {shortname}` → **must be `Type: "Progress"`**, else
   `"Failed to start download"` immediately.
2. poll `GetProgress {shortname}` → `ProgressUpdate`.
   `Content.Error` aborts; `Percentage >= 100` ends the loop.
3. create a Steam shortcut; `GetDetails` for the name and any existing id.
4. `Install {shortname, steamClientID}` → **must be `Type: "LaunchOptions"`**.
   The store uses this call to persist the shortcut id and report how to launch.
5. `GetJsonImages` → artwork.

`GameDetailsItem` has a second, non-queue path for update/verify/repair that
polls `GetProgress` the same way and calls `Install` the same way.

**`Install` does not mean "begin installing".** In every working store it is the
finalise step and does three things:

```bash
<CONF> --detect-executable "$1"          # sets ApplicationPath
<CONF> --addsteamclientid "$1" "$2"      # persists SteamClientID
<CONF> --launchoptions "$1" "$ARGS" ""   # returns LaunchOptions
```

### What "installed" means

`GameDisplay.tsx`: `const isInstalled = !!steamClientID;`

The installed filter is `WHERE SteamClientID IS NOT NULL AND SteamClientID <> ''`.
**Files on disk and a populated `InstallPath` do not make a game installed.**
Only a recorded Steam shortcut id does.

### Launching

Steam runs the shortcut: `Exe` = the store's `<store>-launcher.sh`, `Options` =
`<launcher> <shortname>%command%`. The launcher sources `settings.sh`, applies
the per-game config (esync/fsync/FSR/…), resolves `UMU_ID` when protonfixes are
enabled, and `eval`s the command. `Compatibility: true` makes the UI assign a
Proton tool; native builds must set it false.

### Uninstall

`Uninstall {shortname}` → the store removes files and clears
`InstallPath`/`SteamClientID`; the UI then calls `RemoveShortcut`.

### Settings

`settings.sh` runs `--generate-env-settings-json <schema>` and `eval`s the
result, exporting `<STORE>_<SECTION>` variables. Tab settings come from
`conf_schemas/<store>tabconfig.json`. Per-game config is stored in the DB and
edited through `GetTabConfigActions` / `GetPlatformConfigFileActions`.

---

## 5. Progress reporting

The store writes progress to **stderr**, redirected to
`$DECKY_PLUGIN_LOG_DIR/<shortname>.progress`. `GetProgress` parses the tail.

The shared format:

```
Progress: 42.50
Downloaded: 1234.00 MiB
Download\t- 12.34 MiB/s
```

Pitfalls found the hard way:

- The log is **empty for the first second** (it is truncated on start). Returning
  `Content: null` there makes the UI report a failed install while the download
  continues invisibly. Always return something, e.g. `0% / "Starting…"`.
- Steam writes `ERROR: ld.so: … gameoverlayrenderer.so … ignored.` into the same
  file before anything of ours runs. Matching a bare `error` treats that as a
  failed install. Use an explicit marker.
- A leftover log from a previous run is read as the current state — truncate on
  start.
- `Download Complete` is not `Installation complete`; extraction still follows.

---

## 6. Mistakes that cost real time

Every one of these was hit while building the ZOOM extension, and none were
visible from the command line — the CLI does not check `Type` strings, does
not render nulls, and does not care about `SteamClientID`.

| Mistake | What the user saw |
|---|---|
| `Download` returned `Type: "Download"` | "Install failed" instantly, before a byte moved |
| `Install` treated as "begin installing" | Game downloaded and extracted, but never showed as installed |
| `GetProgress` returned `Content: null` | "Install failed" on the first poll; the download continued unseen |
| Errors detected by matching the word "error" | Steam's ld.so warning read as a failed install |
| An action deleted as "unused" | `'NoneType' object is not subscriptable` |
| Init errors sent to `/dev/null` | Empty library with no explanation (it was a 401) |
| No install lock | A second click ran a rival download into the same file |
| Detection walking a Proton prefix | Picked `drive_c/windows/hh.exe` instead of the game |
| Ignoring the launcher the installer wrote | Game installed correctly but would not start |

The last two are the same lesson twice: **when an installer produces a
launcher, use it** rather than reconstructing one.

### A known open issue

After a first login on a store with an empty library, the grid can stay empty
until the view is re-queried — pressing **Toggle Installed** twice populates
it. The content cache in `ContentTabs` holds the pre-login empty result and the
login flow does not invalidate it. Not yet resolved.

## 7. Rules learned

- Extensions never modify `src/`. If it seems necessary, something is missing in
  the extension.
- Test in the UI. Every bug that mattered here was invisible from the CLI,
  because the CLI does not check `Type` strings and does not render nulls.
- Never delete an action because it looks unused; the frontend calls several
  unconditionally.
- Line endings: files transferred to the Ally arrived with CRLF and would not
  parse. Normalise with `sed -i 's/\r$//'` on deploy.
