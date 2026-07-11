#!/usr/bin/env bash
# Steam invokes this as:  rpgmaker-launcher.sh <game_id> <engine>
# It runs the game NATIVELY: NW.js for MV/MZ, mkxp-z for VX Ace/XP/VX. No Wine/Proton.
export DECKY_PLUGIN_RUNTIME_DIR="${DECKY_PLUGIN_RUNTIME_DIR:-${HOME}/homebrew/data/GameVault}"
export DECKY_PLUGIN_DIR="${DECKY_PLUGIN_DIR:-${HOME}/homebrew/plugins/GameVault}"
export DECKY_PLUGIN_LOG_DIR="${DECKY_PLUGIN_LOG_DIR:-${HOME}/homebrew/logs/GameVault}"
export Extensions="${Extensions:-Extensions}"

# Steam Game Mode launches with LC_ALL=C (POSIX). Under a non-UTF-8 locale Chromium
# can't encode multibyte paths (e.g. "Kirumi 決定版") into a file:// URL, so NW.js fails
# to load index.html -> "Your file couldn't be accessed". Check the EFFECTIVE locale
# (LC_ALL overrides LC_CTYPE overrides LANG) and force UTF-8 if it isn't already. Game
# Mode sets LC_ALL=C *and* LANG=en_US.UTF-8, so we must look at LC_ALL, not just LANG.
eff_locale="${LC_ALL:-${LC_CTYPE:-${LANG:-}}}"
case "$eff_locale" in
  *[Uu][Tt][Ff]*) : ;;
  *) export LANG=C.UTF-8 LC_ALL=C.UTF-8 ;;
esac

source "${DECKY_PLUGIN_DIR}/scripts/Extensions/RPGMaker/settings.sh"

ID="$1"
ENGINE="$2"
mkdir -p "$DECKY_PLUGIN_LOG_DIR"
LOG="${DECKY_PLUGIN_LOG_DIR}/rpgmaker-run.log"

GAME_DIR=$($RPGMAKERCONF --get-game-dir "$ID" --dbfile "$DBFILE")
if [ -z "$ENGINE" ]; then
    ENGINE=$($RPGMAKERCONF --get-args "$ID" --dbfile "$DBFILE")
fi
# Entrypoint relative to the game folder (Linux binary / Electron index). Only the
# native-launcher engines route through here; scummvm/dos/windows launch directly.
APP_REL=$($RPGMAKERCONF --get-app-path "$ID" --dbfile "$DBFILE")

RT="$RPGMAKER_RUNTIME"
NW="$RT/nwjs/nw"
# RPG Maker MV/MZ render through pixi.js WebGL inside NW.js's Chromium. Getting a GL
# context under Steam Game Mode (gamescope) on RADV is finicky and games disagree:
#   - --enable-webgl + --ignore-gpu-blocklist: undo Chromium's WebGL blocklist.
#   - SwiftShader software GL SEGFAULTS under gamescope's Vulkan WSI -> never use it.
#   - Out-of-process GPU + Vulkan: some games render, but others crash the GPU process
#     ("CreateCommandBuffer", exit_code=512).
#   - In-process GPU + Vulkan: "Vulkan not supported with in process gpu" -> EGL_BAD_CONFIG.
#   => The combo with no fatal signature for any game tested: IN-process GPU + the GL
#      (radeonsi) ANGLE backend. --in-process-gpu removes the crashing GPU-IPC boundary;
#      --use-angle=gl avoids the vulkan-in-process conflict. Still hardware (radeonsi).
# Override per-game via RPGMAKER_NW_FLAGS in the Steam launch options if one misbehaves.
# --enable-logging=stderr surfaces the page's console (WebGL/plugin errors) into the run
# log — kept in as a diagnostic. A game folder may also carry gv_nwflags.txt to fully
# replace these flags for just that game (see run_nw).
NW_FLAGS="${RPGMAKER_NW_FLAGS:---ignore-gpu-blocklist --enable-webgl --in-process-gpu --use-gl=angle --use-angle=gl --enable-logging=stderr --log-level=0}"

run_nw(){
    # Linux is case-sensitive but RPG Maker data often references assets with
    # Windows casing -> "Failed to load: img/....png". Inject a shim that remaps
    # missing-case loads to the real file. We inject a <script> as the first tag
    # in the game's index.html (NW.js inject_js_start proved unreliable / lacked
    # a `require` in its context) so it runs in the page with Node integration,
    # before any asset loads. index.html lives in www/ for MV, at root for MZ.
    local casefix_src="${DECKY_PLUGIN_DIR}/scripts/Extensions/RPGMaker/casefix.js"
    local html_dir=""
    if [ -f "$GAME_DIR/www/index.html" ]; then html_dir="$GAME_DIR/www"
    elif [ -f "$GAME_DIR/index.html" ]; then html_dir="$GAME_DIR"; fi
    if [ -f "$casefix_src" ] && [ -n "$html_dir" ]; then
        cp -f "$casefix_src" "$html_dir/casefix.js" 2>/dev/null
        python3 - "$html_dir/index.html" <<'PY' 2>/dev/null
import sys, os, re
p = sys.argv[1]
try:
    html = open(p, encoding='utf-8', errors='ignore').read()
except Exception:
    sys.exit(0)
if 'casefix.js' in html:
    sys.exit(0)
if not os.path.exists(p + '.gvbak'):
    try: open(p + '.gvbak', 'w', encoding='utf-8').write(html)
    except Exception: pass
tag = '<script type="text/javascript" src="casefix.js"></script>'
# insert right after <head ...> so it runs before every other script
m = re.search(r'<head[^>]*>', html, re.I)
if m:
    out = html[:m.end()] + '\n' + tag + html[m.end():]
else:
    out = tag + '\n' + html   # no <head>: prepend
try: open(p, 'w', encoding='utf-8').write(out)
except Exception: pass
PY
    fi
    # Per-game override: a gv_nwflags.txt in the game folder fully replaces NW_FLAGS
    # for just this game (some games need a different GL/GPU path than the default).
    local flags="$NW_FLAGS"
    if [ -f "$GAME_DIR/gv_nwflags.txt" ]; then
        flags="$(tr '\r\n' '  ' < "$GAME_DIR/gv_nwflags.txt")"
        echo "per-game NW flags: $flags" >> "$LOG"
    fi
    # shellcheck disable=SC2086  # flags must word-split into separate args
    exec "$NW" $flags "$GAME_DIR" >> "$LOG" 2>&1
}
# mkxp-z: run the extracted binary directly (the AppImage's AppRun hardcodes usr/bin/mkxp-z
# but the binary sits at the AppDir root). Replicate AppRun's env: bundled libs + SRCDIR=cwd.
MKXPZ_BIN="$RT/mkxp-z/mkxp-z"
MKXPZ_LIBS="$RT/mkxp-z/usr/lib"

echo "[$(date)] launch id=$ID engine=$ENGINE dir=$GAME_DIR" >> "$LOG" 2>&1

if [ ! -d "$GAME_DIR" ]; then
    echo "Game folder not found: $GAME_DIR" >> "$LOG" 2>&1
    exit 1
fi

run_mkxpz(){
    cd "$GAME_DIR" || exit 1
    # Preload a Win32API shim so Windows-only DLL calls (gdiplus screenshots,
    # user32 window resizing, etc.) degrade to no-ops instead of crashing mkxp-z
    # at script-load. Copy it into the game dir so mkxp-z's filesystem finds it.
    local shim_src="${DECKY_PLUGIN_DIR}/scripts/Extensions/RPGMaker/win32api_shim.rb"
    local shim_name="gamevault_win32_shim.rb"
    [ -f "$shim_src" ] && cp -f "$shim_src" "$GAME_DIR/$shim_name" 2>/dev/null
    # Point mkxp-z at the bundled RTP so RTP-dependent games find stock assets.
    local rtp_name=""
    case "$ENGINE" in
      vxace) rtp_name="RPGVXAce" ;;
      xp)    rtp_name="RPGXP" ;;
      vx)    rtp_name="RPGVX" ;;
    esac
    local rtp_dir="$RT/rtp/$rtp_name"
    # Write our mkxp.json (RTP + preload shim) only if the game has none of its own.
    if [ ! -e "$GAME_DIR/mkxp.json" ]; then
        local rtp_json=""
        [ -n "$rtp_name" ] && [ -d "$rtp_dir" ] && rtp_json="\"RTP\": [ \"$rtp_dir\" ], "
        printf '{ %s"preloadScript": [ "%s" ] }\n' "$rtp_json" "$shim_name" > "$GAME_DIR/mkxp.json" 2>/dev/null \
            && echo "wrote mkxp.json (RTP=${rtp_dir:-none}, preload=$shim_name)" >> "$LOG"
    fi
    exec env LD_LIBRARY_PATH="${MKXPZ_LIBS}:${LD_LIBRARY_PATH}" SRCDIR="$GAME_DIR" "$MKXPZ_BIN" >> "$LOG" 2>&1
}

run_linux(){
    cd "$GAME_DIR" || exit 1
    local app="$APP_REL"
    if [ -z "$app" ]; then
        # Fallback sniff: prefer a Unity .x86_64, else a .sh launcher.
        app=$(basename "$(ls -1 "$GAME_DIR"/*.x86_64 2>/dev/null | head -1)" 2>/dev/null)
        [ -z "$app" ] && app=$(basename "$(ls -1 "$GAME_DIR"/*.sh 2>/dev/null | head -1)" 2>/dev/null)
    fi
    local exe="$GAME_DIR/$app"
    if [ ! -f "$exe" ]; then
        echo "linux entrypoint not found: $exe" >> "$LOG"
        exit 1
    fi
    chmod +x "$exe" 2>/dev/null
    echo "linux exec: $exe" >> "$LOG"
    exec "$exe" >> "$LOG" 2>&1
}

run_electron(){
    # NW.js-packaged HTML games (package.nw / resources/app / index.html+package.json)
    # run under the bundled NW.js runtime, same Chromium GL flags as MV/MZ.
    echo "electron/nwjs exec on: $GAME_DIR" >> "$LOG"
    # shellcheck disable=SC2086  # NW_FLAGS must word-split
    exec "$NW" $NW_FLAGS "$GAME_DIR" >> "$LOG" 2>&1
}

case "$ENGINE" in
  mv|mz)
    run_nw
    ;;
  vxace|xp|vx)
    run_mkxpz
    ;;
  linux)
    run_linux
    ;;
  electron)
    run_electron
    ;;
  *)
    # Fallback: sniff the folder if the engine tag is missing. scummvm/dos/windows
    # never reach here (they launch via flatpak / Proton directly).
    if [ -f "$GAME_DIR/package.json" ] || [ -f "$GAME_DIR/www/index.html" ]; then
        run_nw
    else
        run_mkxpz
    fi
    ;;
esac
