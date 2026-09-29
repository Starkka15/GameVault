# Building a GameVault store extension, start to end

A build order, not a reference. Follow it top to bottom and each step is
verifiable in the UI before the next one depends on it. The companion file
`EXTENSION-SYSTEM.md` explains *how the machinery works*; this one tells you
*what to write and in what order*.

Written against GameVault v1.2.5.

---

## Step 0 — Decide what kind of store you have

This decides most of the work, so answer it before writing anything. Sizes are
the real ones from the seven shipped extensions.

| Kind | Examples | `store.sh` / `.py` | What you write |
|---|---|---|---|
| **Local scanner, no auth** | RPGMaker ("My Added Games") | 129 / 539 | The smallest possible extension. 17 actions, no login at all. |
| **CLI-backed** | GOG (`gogdl`), Epic (`legendary`), Amazon (`nile`), EA + Ubisoft (`maxima-cli`, `optima-cli`) | 254–451 / 449–501 | A thin adapter. The CLI owns auth, library, download, resume, progress. |
| **Documented API + token** | itch.io (API key) | 260 / 1266 | A client. Auth is a stateless key in a file, but you write download and extraction yourself. |
| **Session / web-only** | ZOOM Platform | ~140 / ~900 | Everything: form login, CSRF, cookies, 2FA, expiring URLs, multipart, resume, progress, extraction. |

Note the shape: **CLI-backed stores have small Python files** (449–501 lines)
because the CLI does the work. The two without a CLI — itch.io and ZOOM — are
two to three times larger. If a maintained CLI exists, **use it**.

### The action inventory

Counted across all seven. Implement the core; add the rest only if your store
has the feature.

**Universal — all seven implement these (17 actions):**
`init`, `refresh`, `getgames`, `getgamedetails`, `getgamesize`, `getjsonimages`,
`download`, `install`, `uninstall`, `cancelinstall`, `getprogress`,
`getlaunchoptions`, `loginstatus`, `getsetting`, `savesetting`, `gettabconfig`,
`savetabconfig`

**Six of seven** (all but RPGMaker, which has no auth):
`login`, `login-launch-options`, `logout`, `get-exe-list`, `run-exe`,
`getplatformconfig`, `saveplatformconfig`, `update-umu-id`

**Store-specific — do not cargo-cult these:**
`apply-protonfixes`/`lookup-protonfixes` (4), `checkupdate` (3),
`verify`/`repair` (3), `download-saves`/`upload-saves`/`toggle-autosync` (2),
`detect-installed` (**GOG only**), DLC actions (GOG), EOS overlay (Epic),
collections (itch.io), `move`/`import`/`protontricks` (Epic),
`getprofile`/`renew`/`settings` (Optima)

Then answer three more:

1. **How do you list what the user owns?** If there is no answer, stop — you
   cannot build a store tab. (ZOOM's answer was found by hooking `fetch` in a
   logged-in browser and watching which endpoint the site's own frontend called.)
2. **How do you get a download URL?** Is it stable or signed/expiring? Expiring
   means you must re-fetch it immediately before each download, never cache it.
3. **What shape does a game arrive in?** One archive, a multi-part installer, a
   platform-native build? This decides your install step.

---

## Step 1 — Skeleton: make a tab appear

Create the file layout. Copy an existing extension of the *same kind* as your
store and rename; do not invent the structure.

```
defaults/scripts/<store>.py
defaults/scripts/<store>-config.py
defaults/scripts/Extensions/<Store>/{static.json,store.sh,settings.sh,
    <store>-launcher.sh,get-<store>-args.sh,install_deps.sh,login.sh}
defaults/conf_schemas/<store>tabconfig.json
```

Minimum `static.json`:

```json
{
  "gamevault-actions": { "Type": "ActionSet", "Content": { "SetName": "GameVaultActions",
    "Actions": [{ "Id": "Get<Store>Actions", "Title": "...", "Type": "Init",
                  "Command": "./scripts/get-json.py <store>-actions" }] } },
  "gamevault-tabs": { "Type": "StoreTabs", "Content": { "Tabs": [
      { "Title": "<Store>", "Type": "GameGrid", "ActionId": "Get<Store>Actions" } ] } },
  "<store>-actions": { "Type": "ActionSet", "Content": { "SetName": "<Store>Actions",
    "Actions": [ ... ] } }
}
```

`store.sh` must register itself or nothing dispatches:

```bash
PLATFORMS+=("<Store>")
ACTIONS+=("any" "extra" "verbs")        # only verbs not already in gamevault.sh
if [[ "${PLATFORM}" == "<Store>" ]]; then
    source "${DECKY_PLUGIN_DIR}/scripts/${Extensions}/<Store>/settings.sh"
fi
```

**Verify in the UI:** restart Decky, open GameVault. Your tab is in the bar.
Nothing else needs to work yet.

**Traps:** a verb missing from `ACTIONS` prints `Invalid action` and exits 1.
A file with CRLF line endings will not parse — `sed -i 's/\r$//'` on deploy.

---

## Step 2 — Login (skip if your store has no auth)

**A store does not have to have a login.** RPGMaker is the proof: it defines no
`login`, `logout` or `login-launch-options` at all, and its `loginstatus`
returns a constant:

```python
def get_login_status(self, flush_cache=False):
    # No auth for a local scanner — always "logged in".
    return json.dumps({'Type': 'Status', 'Content': {'LoggedIn': True, 'Username': 'Local'}})
```

If your store scans local files, do that and skip to Step 3.

If it does have auth, you need four actions, and **all four are called
unconditionally by `LoginContent`**. Deleting one you think is unused gives
`'NoneType' object is not subscriptable`.

| Action | Returns | Implementation |
|---|---|---|
| `LoginLaunchOptions` | `LaunchOptions` | `get_steam_env; loginlaunchoptions <login.sh> "" "$LOG_DIR" "<Store> Login"` |
| `Login` | `LaunchOptions` | `get_steam_env; launchoptions <login.sh> "" "$LOG_DIR" "<Store> Login"` |
| `Logout` | `LoginStatus` | clear credentials, delete the DB, return status |
| `GetContent` | `LoginStatus` | `{Username, LoggedIn}` |

The login **runs as a Steam shortcut**, which is how it gets a window and the
on-screen keyboard in Game Mode. `login.sh` therefore must export the Decky env
itself, prompt with `kdialog`/`zenity`, do the auth, sync the library, and end
with `gamevault.sh <Store> loginstatus --flush-cache`.

Determine logged-in state from **a call that requires auth**, not from page
content or the presence of a token file. ZOOM's first version sniffed the login
page for the string `two-factor` — every page embeds the site's route table,
which names that route, so every account was told it had 2FA.

Cache the status (`add_cache`, 1 hour) and honour `--flush-cache`.

**Verify in the UI:** the login panel shows "logged out", the button opens your
dialog, and after logging in the panel shows your username. If the username
renders as `{"Type":"Setting",...}` you used `get_setting()` — that returns a
JSON envelope for the frontend, not a value.

---

## Step 3 — Library

`GetContent` on your store's action set →
`<Store>_getgames <filter> <installed> <limited>`:

```bash
TEMP=$($CONF --getgameswithimages "" "$FILTER" "$INSTALLED" "$LIMIT" "true" "" --dbfile "$DBFILE")
if echo "$TEMP" | jq -e '.Content.Games | length == 0' &>/dev/null; then
    if [[ $FILTER == "" ]] && [[ $INSTALLED == "false" ]]; then
        <Store>_init                       # sync, then re-query
        TEMP=$($CONF --getgameswithimages ... )
    fi
fi
echo "$TEMP"
```

Positional args to `--getgameswithimages` are
`imagePrefix, filter, installed, limited, urlencode, needsLogin, origin`.

Your `get_list()` writes rows into `Game`. The columns that matter:

| Column | Meaning |
|---|---|
| `ShortName` | your stable per-game id (**UNIQUE**) — use a UUID, not a slug |
| `Title`, `Notes`, `Publisher`, `Developer`, `ReleaseDate` | display |
| `InstallPath`, `RootFolder` | set at install |
| `ApplicationPath` | the executable, **relative to RootFolder** |
| `ConfigurationPath` | build kind — `windows`, `linux`, `html` |
| `SteamClientID` | set by `Install`; **this is what "installed" means** |

Cover art goes in `Images` with `Type='vertical_cover'`.

Let `<Store>_init` write its errors to a log, never `&> /dev/null`. A failed
sync and an empty library look identical otherwise — ZOOM hid a
`401 Unauthorized` that way for hours.

**Verify in the UI:** your games appear in the grid with artwork.

---

## Step 4 — Details, size, artwork

| Action | Returns | Notes |
|---|---|---|
| `GetDetails` | `GameDetails` | `--getgamedata` (inherited) |
| `GetGameSize` | `GameSize` | `"Download Size: 7.22 GB"` or `"Size on Disk: …"` |
| `GetJsonImages` | `GameImages` | `--get-base64-images` (inherited); feeds Steam artwork |

`GetGameSize` receives `installed` as a string — branch on it.

---

## Step 5 — Download and progress

Two actions, and the contract here is where most time gets lost.

```bash
function <Store>_download() {
    PROGRESS_LOG="${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    PID_FILE="${DECKY_PLUGIN_LOG_DIR}/${1}.pid"

    if [[ -f "${PID_FILE}" ]]; then                     # refuse a second copy
        OLD=$(cat "${PID_FILE}")
        if [[ -n "$OLD" ]] && kill -0 "$OLD" 2>/dev/null; then
            echo '{"Type": "Progress", "Content": {"Message": "Already installing"}}'
            return 0
        fi
        rm -f "${PID_FILE}"
    fi

    : > "${PROGRESS_LOG}"                               # start clean
    $CONF --install-game "${1}" --install-dir "${INSTALL_DIR}" --dbfile "$DBFILE" \
        2>> "$PROGRESS_LOG" > "${DECKY_PLUGIN_LOG_DIR}/${1}.output" &
    echo $! > "${PID_FILE}"
    echo '{"Type": "Progress", "Content": {"Message": "Downloading"}}'
}
```

**`Type` must be `"Progress"`.** `installQueue` checks it literally; anything
else is `"Failed to start download"` before a byte moves — and the CLI will not
catch this for you, because the CLI does not check `Type`.

Write progress to **stderr** in the shared format:

```
Progress: 42.50
Downloaded: 1234.00 MiB
```

`GetProgress` parses the tail and returns `ProgressUpdate`. Four rules:

1. **Never return `Content: null`.** The log is empty for the first second
   because you just truncated it; a null there is rendered as a failed install
   while the download runs on invisibly.
2. **Detect errors with your own marker**, e.g. `ZOOM-ERROR:`. Steam writes
   `ERROR: ld.so: … gameoverlayrenderer.so … ignored.` into your log before you
   write anything; matching a bare `error` treats that as a failure.
3. **Downloading finished ≠ installed.** If extraction follows, report ~99% with
   a description, and 100% only from an explicit completion marker.
4. **Truncate the log on start**, or the previous run's final state is read as
   this one's.

If the download is resumable, honour `Range` and handle `416` (already complete)
and `403` (a signed URL expired — re-fetch it, do not retry the same URL).

**Verify in the UI:** press Install. The bar moves, monotonically. Press Install
twice — the second press must not start a rival download.

---

## Step 6 — Install (the step everyone gets wrong)

**`Install` does not mean "begin installing".** It is called *after* the
download completes, receives the Steam shortcut id, and finalises.

The minimum, from RPGMaker — two calls and a return:

```bash
function <Store>_install() {          # $1 = shortname, $2 = steamClientID
    $CONF --addsteamclientid "${1}" "${2}" --dbfile "$DBFILE"   # THIS is "installed"
    ARGS=$($ARGS_SCRIPT "${1}")
    $CONF --launchoptions "${1}" "${ARGS}" "" --dbfile "$DBFILE" # must print LaunchOptions
    exit 0
}
```

Add to it only what your store needs — itch.io's version adds executable
detection and the umu id, and clears the progress log:

```bash
    rm -f "${DECKY_PLUGIN_LOG_DIR}/${1}.progress"
    $CONF --detect-executable "${1}" --dbfile "$DBFILE"
    $CONF --update-umu-id "${1}" <store> --dbfile "$DBFILE"
```

`--addsteamclientid`, `--update-umu-id` and `--getgamedata` are inherited from
`GenericArgs`.

### Where the executable comes from — pick the cheapest that works

This varies by store kind, and only the last case needs code you write:

| Source | Used by | How |
|---|---|---|
| Store manifest in the install dir | GOG (`goggame-<id>.info`), Amazon (`fuel.json`) | parse it after download |
| The CLI already knows | Epic, Optima, EA | read it out of the tool's metadata |
| Nothing tells you | itch.io, ZOOM | `--detect-executable`: scan heuristically |
| Known at import time | RPGMaker | set when the game is added |

Write a heuristic scanner **only** if your store publishes no manifest and has
no CLI. If it does, parse the manifest — it is shorter and it is right.

**`isInstalled` is `!!SteamClientID`.** Not `InstallPath`, not files on disk. If
`Install` does not persist the id, the game stays "uninstalled" forever no
matter how much of it is on the drive.

Your `--detect-executable` sets `ApplicationPath` **relative to `RootFolder`**,
and `ConfigurationPath` to the build kind. Pick the shallowest plausible
launcher: `start.sh` → `*.sh` → `*.x86_64`/`*.AppImage` → a bare executable.
For Windows builds, skip `unins*`, `vcredist`, `dxsetup`.

`LaunchOptions.Compatibility` must be **false for native builds** — true makes
the UI assign a Proton tool, and a native binary under Proton fails confusingly.

**Verify in the UI:** after install the button reads "Play", the game has a
Steam shortcut with artwork, and it appears under the *installed* filter.

---

## Step 7 — Launch

`GetLaunchOptions` returns `LaunchOptions` where `Exe` is your launcher script
and `Options` is `"<launcher> <shortname>%command%"`.

The launcher exports the Decky env itself, sources `settings.sh`, applies the
per-game config (esync/fsync/FSR/framerate), resolves `UMU_ID` when protonfixes
are enabled, sets `STEAM_COMPAT_INSTALL_PATH`, then `eval`s the command. Copy an
existing launcher; it is ~150 lines of environment handling you do not want to
rewrite.

**Verify in the UI:** the game launches from the GameVault entry *and* from the
Steam shortcut.

---

## Step 8 — Uninstall, update, cancel

| Action | Contract |
|---|---|
| `Uninstall` | delete files; clear `InstallPath`, `RootFolder`, `Size`, `SteamClientID`. The UI removes the shortcut. |
| `CancelInstall` | kill by **PID file**, not `pkill` on a pattern; append your error marker so polling stops |
| `CheckUpdate` | compare the store's newest version with the recorded one |

Cancelling with `pkill -f "<something>"` will match the SSH command running your
own deploy script. Use the PID file.

---

## Step 9 — Package it

Write `install-<store>-extension.sh` at the repo root modelled on
`install-itchio-extension.sh`: check the plugin dir exists, `mkdir -p` the
extension and `conf_schemas` dirs, copy each file explicitly, `chmod +x` the
shell scripts, and run `install_deps.sh`.

`install_deps.sh` fetches whatever external tool you need. On SteamOS the
filesystem is read-only, so prefer downloading a binary into
`DECKY_PLUGIN_RUNTIME_DIR` over a package manager, and validate what you
downloaded before saving it.

---

## Testing discipline

**Test in the UI at every step.** Every bug that cost real time in the ZOOM
build was invisible from the command line, because the CLI does not check `Type`
strings, does not render nulls, and does not care about `SteamClientID`. A
passing CLI call proves the backend works; it proves nothing about the feature.

Useful loop:

1. Deploy, `sed -i 's/\r$//'` the shell scripts, restart `plugin_loader`.
2. Do the thing in Game Mode.
3. Read the action sequence:
   `grep "execute_action: <Store>" ~/homebrew/logs/GameVault/<newest>.log`

That log is the ground truth for *which* actions the UI called and in what
order. Comparing a working store's sequence against yours finds contract
mismatches faster than reading either implementation.

---

## Pick your reference implementation

Do not read all seven. Copy the one closest to your store and diff against it
when something misbehaves:

| Your store | Copy | Why |
|---|---|---|
| Local files, no auth | **RPGMaker** | smallest complete extension; 17 actions |
| Wraps a CLI | **Amazon** | cleanest CLI adapter; 275/449 lines |
| CLI + saves, DLC, verify | **GOG** | the fullest implementation, but 1406 lines of Python |
| Token API, own downloader | **itch.io** | closest to a from-scratch client |
| Sub-tabs in one store | **itch.io** | the only `StoreTabs` container example |
| Session/web login | **ZOOM** | the only one, and it is the hardest path |

---

## Checklist

- [ ] Tab appears
- [ ] All four login actions exist (or none, if your store has no auth); login shows your username
- [ ] Library populates; `<Store>_init` logs its errors
- [ ] `Download` returns **`Type: "Progress"`**
- [ ] `GetProgress` never returns `Content: null`
- [ ] Errors detected by your own marker, not the word "error"
- [ ] Second Install press refused via PID file
- [ ] `Install` calls `--addsteamclientid` and returns **`LaunchOptions`**
- [ ] `--detect-executable` sets `ApplicationPath` relative to `RootFolder`
- [ ] `Compatibility: false` for native builds
- [ ] Game shows under the installed filter and launches
- [ ] Uninstall clears `SteamClientID`
- [ ] No file under `src/` was modified

---

## Time sinks, ranked

1. **Writing a download client** when no CLI exists — auth, resume, expiring
   URLs, multipart, progress. Avoid by using a CLI if one exists.
2. **Contract mismatches** — wrong `Type` strings, missing actions, null
   content. Cheap to fix, expensive to find, invisible to CLI testing.
3. **Discovering an undocumented API** — hook `fetch`/`XHR` in a logged-in
   browser session and drive the site; the network panel alone misses calls made
   during client-side navigation.
4. **Assuming the framework is wrong.** It usually is not. If an extension needs
   a change under `src/`, something is missing in the extension.
